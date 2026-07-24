"""Command-line entry point for ontologylab.

Real subcommands (a structural rewrite of drylab's flat single-run CLI):

    python -m ontologylab.main collect    --url ... | --file ...
    python -m ontologylab.main extract    --engine claude --model ...
    python -m ontologylab.main review     [--type ...] [--doc ...] [--limit N]
    python -m ontologylab.main approve    --id <id> | --filter "k=v,..."
    python -m ontologylab.main reject     --id <id>
    python -m ontologylab.main build-pack --name <name>

``approve`` / ``reject`` / ``review`` are the headless embodiment of the
human verification gate (ARCHITECTURE.md §4a): each invocation is a
discrete, human-initiated command. There is NO automated verify stage — no
pipeline stage or scheduler ever sets status='verified'.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from xml.etree.ElementTree import ParseError

from ontologylab import paths
from ontologylab.connectors.allowlist import (
    NotAllowlisted,
    check_paper_query,
    check_url,
)
from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.paper_api import (
    DEFAULT_LIMIT,
    PaperApiConnector,
    UnsupportedPaperSource,
    check_source_implemented,
)
from ontologylab.connectors.web_crawl import WebCrawlConnector
from ontologylab.engines import EngineError, engine_name_arg, get_engine
from ontologylab.expansion import expand_query
from ontologylab.extractor import (
    PROMPT_VERSION,
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
)
from ontologylab.kgstore import EndpointNotVerified, KGStore, KGStoreError
from ontologylab.packbuilder import build_pack
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps, KillSwitch


def _open_store(args: argparse.Namespace) -> KGStore:
    data_dir = Path(args.data_dir)
    return KGStore.open(paths.kg_db_path(data_dir))


def _add_data_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        default=str(paths.default_data_dir()),
        help="Working data directory (default: ROOT/data).",
    )


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------


def cmd_collect(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    job_dir = paths.new_job_dir(data_dir, "collect")
    provenance = Provenance(str(job_dir), seed=0)
    provenance.log(
        "collect.start",
        {"urls": args.url, "files": args.file, "paper_queries": args.paper_query},
    )

    if not (args.url or args.file or args.paper_query):
        print(
            "[ontologylab] nothing to collect: pass --url, --file, "
            "and/or --paper-query"
        )
        return 2

    # Mixed-run pre-validation: every gate for every input is checked BEFORE
    # any fetch, so one rejected/unsupported input can never let an earlier
    # input reach the network first (zero network I/O on failure).
    try:
        for url in args.url:
            check_url(url)
        for paper_query in args.paper_query or []:
            check_paper_query(args.paper_source, paper_query)
            check_source_implemented(args.paper_source)
    except NotAllowlisted as exc:
        provenance.log("collect.rejected", {"error": str(exc)})
        print(f"[ontologylab] REJECTED: {exc}", file=sys.stderr)
        return 2
    except UnsupportedPaperSource as exc:
        provenance.log("collect.unsupported", {"error": str(exc)})
        print(f"[ontologylab] UNSUPPORTED: {exc}", file=sys.stderr)
        return 2

    def _run_connector(connector, spec: dict) -> list[RawDocument] | None:
        """Fetch via one connector; None means logged failure (exit 2).

        NotAllowlisted / UnsupportedPaperSource are re-checked in-fetch as
        defense in depth; URLError (incl. HTTPError) and Atom ParseError are
        fetch failures — all must end as a clean CLI error, never an
        uncaught traceback.
        """
        try:
            return asyncio.run(connector.fetch(spec))
        except NotAllowlisted as exc:
            provenance.log("collect.rejected", {"error": str(exc)})
            print(f"[ontologylab] REJECTED: {exc}", file=sys.stderr)
        except UnsupportedPaperSource as exc:
            provenance.log("collect.unsupported", {"error": str(exc)})
            print(f"[ontologylab] UNSUPPORTED: {exc}", file=sys.stderr)
        except (URLError, ParseError) as exc:
            provenance.log("collect.fetch_failed", {"error": str(exc)})
            print(f"[ontologylab] FETCH FAILED: {exc}", file=sys.stderr)
        except (ValueError, OSError) as exc:
            provenance.log("collect.failed", {"error": str(exc)})
            print(f"[ontologylab] collect failed: {exc}", file=sys.stderr)
        return None

    raw_docs: list[RawDocument] = []
    if args.url:
        fetched = _run_connector(WebCrawlConnector(), {"urls": args.url})
        if fetched is None:
            return 2
        raw_docs.extend(fetched)
    for paper_query in args.paper_query or []:
        fetched = _run_connector(
            PaperApiConnector(),
            {
                "source": args.paper_source,
                "query": paper_query,
                "limit": args.limit,
            },
        )
        if fetched is None:
            return 2
        raw_docs.extend(fetched)
    for file_arg in args.file or []:
        path = Path(file_arg)
        raw_docs.append(
            RawDocument(
                source_kind="upload",
                source_uri=path.resolve().as_uri(),
                title=path.stem,
                raw_text=path.read_text(encoding="utf-8"),
            )
        )
    if not raw_docs:
        provenance.log("collect.end", {"documents": 0, "created": 0})
        print("[ontologylab] no documents matched: inputs fetched cleanly "
              "but yielded zero documents")
        return 0

    store = _open_store(args)
    try:
        created_count = 0
        for raw in raw_docs:
            doc, created = store.insert_document(
                source_kind=raw.source_kind,
                source_uri=raw.source_uri,
                title=raw.title,
                raw_text=raw.raw_text,
                content_hash=raw.content_hash,
            )
            created_count += 1 if created else 0
            provenance.log(
                "collect.doc",
                {
                    "doc_id": doc.id,
                    "source_uri": doc.source_uri,
                    "created": created,
                    "chars": len(raw.raw_text),
                },
            )
            state = "new" if created else "duplicate"
            print(f"[ontologylab] {state} document {doc.id} <- {doc.source_uri}")
        provenance.log(
            "collect.end", {"documents": len(raw_docs), "created": created_count}
        )
    finally:
        store.close()
    print(f"[ontologylab] collected {len(raw_docs)} document(s) ({created_count} new)")
    return 0


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


async def _extract_async(args: argparse.Namespace, store: KGStore) -> int:
    data_dir = Path(args.data_dir)
    job_dir = paths.new_job_dir(data_dir, "extract")
    provenance = Provenance(str(job_dir), seed=args.seed)
    caps_config = SimpleNamespace(
        iterations=0,  # no iteration cap; time/call budgets govern
        time_budget_s=args.time_budget,
        max_engine_calls=args.max_engine_calls,
    )
    caps = Caps(caps_config)
    kill_switch = KillSwitch(str(job_dir))
    kill_switch.install()

    engine = get_engine(args.engine, args.model, seed=args.seed, data_dir=data_dir)
    schema = store.get_schema()

    if args.doc_ids:
        doc_ids = args.doc_ids
    else:
        # default: every document with no extracted rows yet
        doc_ids = [
            r["id"]
            for r in store.conn.execute(
                "SELECT id FROM documents WHERE id NOT IN "
                "(SELECT DISTINCT source_doc_id FROM nodes)"
            )
        ]
    if not doc_ids:
        print("[ontologylab] no unprocessed documents to extract")
        return 0

    provenance.log(
        "extract.start",
        {"engine": args.engine, "model": args.model, "doc_ids": doc_ids},
    )
    totals = {"nodes_new": 0, "nodes_merged": 0, "edges_new": 0, "edges_merged": 0}
    stopped_reason = ""
    for doc_id in doc_ids:
        doc = store.get_document(doc_id)
        raw_text = store.document_raw_text(doc_id)
        chunks = chunk_document(raw_text)
        provenance.log(
            "extract.doc", {"doc_id": doc_id, "chunks": len(chunks)}
        )
        for chunk in chunks:
            stop, reason = caps.should_stop(
                {
                    "elapsed": provenance.elapsed_s,
                    "engine_calls": provenance.engine_calls,
                }
            )
            if stop:
                stopped_reason = reason
                break
            if kill_switch.triggered():
                stopped_reason = "kill switch triggered"
                break
            prompt = build_extraction_prompt(schema, chunk.text)
            try:
                raw_response, usage = await engine.generate(prompt, model=args.model)
            except EngineError as exc:
                provenance.log(
                    "extract.engine_error",
                    {"doc_id": doc_id, "chunk": chunk.index, "error": str(exc)},
                )
                print(
                    f"[ontologylab] engine error on {doc_id}#{chunk.index}: {exc}",
                    file=sys.stderr,
                )
                continue
            provenance.track_engine_call(
                "extract", float(usage.get("elapsed") or 0.0), usage
            )
            try:
                result = parse_and_validate_extraction(raw_response, schema, chunk)
            except EngineError as exc:
                # malformed/off-schema response: rejected + logged, never
                # inserted, never a crash (M4 acceptance criterion)
                provenance.log(
                    "extract.parse_rejected",
                    {"doc_id": doc_id, "chunk": chunk.index, "error": str(exc)},
                )
                continue
            for warning in result.warnings:
                provenance.log(
                    "extract.warning",
                    {"doc_id": doc_id, "chunk": chunk.index, "warning": warning},
                )
            stats = store.insert_proposed(
                result.entities,
                result.relations,
                source_doc_id=doc_id,
                extractor_engine=args.engine,
                extractor_model=args.model,
                prompt_version=PROMPT_VERSION,
            )
            for key in totals:
                totals[key] += stats[key]
            print(
                f"[ontologylab] {doc_id}#{chunk.index}: "
                f"+{stats['nodes_new']} nodes (+{stats['nodes_merged']} merged), "
                f"+{stats['edges_new']} edges"
            )
        if stopped_reason:
            break

    provenance.log("extract.end", {"totals": totals, "stopped": stopped_reason})
    kill_switch.uninstall()
    if stopped_reason:
        print(f"[ontologylab] extraction stopped early: {stopped_reason}")
    print(
        f"[ontologylab] extraction done: {totals['nodes_new']} new nodes, "
        f"{totals['edges_new']} new edges (proposed; run "
        f"`ontologylab review` to verify)"
    )
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    store = _open_store(args)
    try:
        return asyncio.run(_extract_async(args, store))
    finally:
        store.close()


# ---------------------------------------------------------------------------
# review / approve / reject (the human gate)
# ---------------------------------------------------------------------------


def cmd_review(args: argparse.Namespace) -> int:
    store = _open_store(args)
    try:
        rows = store.pending_review(
            kind=args.kind,
            type_name=args.type,
            source_doc_id=args.doc,
            order=args.order,
            limit=args.limit,
        )
        counts = store.counts()
    finally:
        store.close()
    if not rows:
        print("[ontologylab] review queue is empty")
    else:
        header = (
            f"{'KIND':<5} {'ID':<34} {'TYPE':<12} {'CONF':<5} {'CRITIC':<7} LABEL"
        )
        print(header)
        print("-" * len(header))
        for row in rows:
            conf = f"{row['confidence']:.2f}" if row["confidence"] is not None else "-"
            critic = (
                f"{row['critic_score']:.2f}"
                if row.get("critic_score") is not None
                else "-"
            )
            if row.get("critic_disagreement"):
                critic += "!"
            print(
                f"{row['kind']:<5} {row['id']:<34} {row['type_name']:<12} "
                f"{conf:<5} {critic:<7} {row['label']}"
            )
        if any(r.get("critic_disagreement") for r in rows):
            print(
                "\n[ontologylab] '!' = extractor/critic disagreement — "
                "worth a close look (advisory only)"
            )
    print(
        f"\n[ontologylab] proposed: {counts['nodes_proposed']} nodes / "
        f"{counts['edges_proposed']} edges | verified: "
        f"{counts['nodes_verified']} nodes / {counts['edges_verified']} edges"
    )
    return 0


def _parse_filter(raw: str) -> dict:
    """Parse 'entity_type=Component,min_confidence=0.8' into kwargs."""
    allowed = {"entity_type", "relation_type", "source_doc_id", "min_confidence"}
    out: dict = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"bad filter fragment {part!r} (expected key=value)")
        key, value = (s.strip() for s in part.split("=", 1))
        if key == "doc":
            key = "source_doc_id"
        if key not in allowed:
            raise ValueError(f"unknown filter key {key!r} (allowed: {sorted(allowed)})")
        out[key] = float(value) if key == "min_confidence" else value
    return out


def cmd_approve(args: argparse.Namespace) -> int:
    store = _open_store(args)
    try:
        if args.id:
            try:
                result = store.approve(
                    args.id, by=args.by, note=args.note, cascade=args.cascade
                )
            except EndpointNotVerified as exc:
                print(f"[ontologylab] BLOCKED: {exc}", file=sys.stderr)
                print(
                    "[ontologylab] approve the endpoint nodes first, or re-run "
                    "with --cascade to approve them together.",
                    file=sys.stderr,
                )
                return 2
            print(
                f"[ontologylab] approved {result['kind']} "
                f"{', '.join(result['approved_ids'])}"
            )
            return 0
        if args.filter:
            filters = _parse_filter(args.filter)
            report = store.bulk_approve(by=args.by, note=args.note, **filters)
            print(
                f"[ontologylab] bulk-approved {len(report['nodes_approved'])} nodes, "
                f"{len(report['edges_approved'])} edges"
            )
            if report["edges_skipped"]:
                print(
                    f"[ontologylab] skipped {len(report['edges_skipped'])} edge(s) "
                    "whose endpoints are not verified: "
                    + ", ".join(report["edges_skipped"])
                )
            return 0
        print("[ontologylab] approve requires --id or --filter", file=sys.stderr)
        return 2
    except KGStoreError as exc:
        print(f"[ontologylab] error: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()


def cmd_reject(args: argparse.Namespace) -> int:
    store = _open_store(args)
    try:
        result = store.reject(args.id, by=args.by, note=args.note)
        print(f"[ontologylab] rejected {result['kind']} {args.id}")
        return 0
    except KGStoreError as exc:
        print(f"[ontologylab] error: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()


def cmd_invalidate(args: argparse.Namespace) -> int:
    """W13: mark a verified edge as no-longer-current (kept as history)."""
    store = _open_store(args)
    try:
        store.invalidate_edge(args.id, by=args.by, reason=args.reason)
        print(
            f"[ontologylab] invalidated edge {args.id} — kept as history, "
            "no longer served as current truth; a re-extraction of the same "
            "triple will arrive as a fresh proposed edge"
        )
        return 0
    except KGStoreError as exc:
        print(f"[ontologylab] error: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()


# ---------------------------------------------------------------------------
# entity-centric review (W11: one entity's mentions + relations in one view)
# ---------------------------------------------------------------------------


def cmd_entity(args: argparse.Namespace) -> int:
    store = _open_store(args)
    try:
        entity_id = args.ref
        # Accept a name too: resolve to the best (proposed-inclusive) match.
        try:
            store._find_kind(entity_id)
        except KGStoreError:
            matches = store.entity_lookup(
                name=args.ref, include_proposed=True, limit=2
            )
            if not matches:
                print(f"[ontologylab] no entity matches {args.ref!r}",
                      file=sys.stderr)
                return 2
            if len(matches) > 1 and matches[0]["name"] != args.ref:
                print(
                    "[ontologylab] ambiguous; candidates: "
                    + ", ".join(f"{m['name']} ({m['id']})" for m in matches),
                    file=sys.stderr,
                )
                return 2
            entity_id = matches[0]["id"]
        try:
            ctx = store.entity_review_context(entity_id)
        except KGStoreError as exc:
            print(f"[ontologylab] error: {exc}", file=sys.stderr)
            return 2
    finally:
        store.close()

    ent = ctx["entity"]
    conf = f"{ent['confidence']:.2f}" if ent["confidence"] is not None else "-"
    print(f"{ent['name']}  [{ent['entity_type']}/{ent['status']}]  "
          f"conf={conf}  id={ent['id']}")
    if ent["aliases"]:
        print(f"  aliases: {', '.join(ent['aliases'])}")
    if ent["properties"]:
        print(f"  properties: {json.dumps(ent['properties'], ensure_ascii=False)}")
    if ctx["critic"]:
        critic = ctx["critic"]
        print(f"  critic: {critic['score']:.2f} ({critic['engine']}) "
              f"— {critic['rationale'] or ''}")

    print(f"\nMENTIONS ({ctx['counts']['mentions']}):")
    for mention in ctx["mentions"]:
        title = mention["doc_title"] or mention["source_doc_id"][:10]
        excerpt = (mention["excerpt"] or "(no span)").replace("\n", " ")
        print(f"  [{title}] …{excerpt}…")

    print(f"\nRELATIONS ({ctx['counts']['relations_proposed']} proposed / "
          f"{ctx['counts']['relations_verified']} verified):")
    for rel in ctx["relations"]:
        arrow = (
            f"-[{rel['relation_type']}]-> {rel['other']['name']}"
            if rel["direction"] == "out"
            else f"<-[{rel['relation_type']}]- {rel['other']['name']}"
        )
        critic_txt = (
            f" critic={rel['critic_score']:.2f}"
            if rel["critic_score"] is not None
            else ""
        )
        print(f"  [{rel['status']:<8}] {arrow} "
              f"(other: {rel['other']['status']}){critic_txt}  id={rel['id']}")

    if ctx["merge_candidates"]:
        print(f"\nMERGE CANDIDATES ({len(ctx['merge_candidates'])}):")
        for cand in ctx["merge_candidates"]:
            print(f"  ~ {cand['other']['name']} ({cand['other']['status']}) "
                  f"score={cand['score']:.2f} "
                  f"[{', '.join(cand['reasons'])}]  candidate={cand['id']}")
    print(
        "\n[ontologylab] act per item: approve/reject --id <id>, "
        "merge --target/--source"
    )
    return 0


# ---------------------------------------------------------------------------
# critic triage (W8: a second model pre-scores the queue — advisory only)
# ---------------------------------------------------------------------------


def cmd_critic(args: argparse.Namespace) -> int:
    from ontologylab.critic import critic_review, resolve_critic_model

    critic_model = resolve_critic_model(args.engine, args.model)
    engine = get_engine(args.engine, critic_model, data_dir=Path(args.data_dir))
    store = _open_store(args)
    try:
        stats = asyncio.run(
            critic_review(
                store, engine, model=critic_model,
                limit=args.limit, batch_size=args.batch_size,
            )
        )
    finally:
        store.close()
    tier = f" · {critic_model}" if critic_model else ""
    print(
        f"[ontologylab] critic ({args.engine}{tier}) scored {stats['scored']}/"
        f"{stats['candidates']} pending item(s); "
        f"{stats['disagreements']} disagreement(s) flagged"
    )
    for error in stats["errors"]:
        print(f"[ontologylab] critic batch failed open: {error}", file=sys.stderr)
    print(
        "[ontologylab] scores are advisory — triage with "
        "`ontologylab review --order critic`; approval stays yours"
    )
    return 0


# ---------------------------------------------------------------------------
# merge review (W7: scan proposes duplicate pairs, a human merges/dismisses)
# ---------------------------------------------------------------------------


def cmd_merge_scan(args: argparse.Namespace) -> int:
    from ontologylab.merge import scan_merge_candidates

    store = _open_store(args)
    try:
        stats = scan_merge_candidates(
            store, name_threshold=args.min_similarity
        )
    finally:
        store.close()
    print(
        f"[ontologylab] scanned {stats['nodes']} node(s), "
        f"{stats['pairs_checked']} pair(s): {stats['candidates_new']} new "
        f"candidate(s), {stats['candidates_existing']} already known"
    )
    if stats["candidates_new"]:
        print("[ontologylab] review them: `ontologylab merge-queue`")
    return 0


def cmd_merge_queue(args: argparse.Namespace) -> int:
    store = _open_store(args)
    try:
        items = store.merge_candidates_pending(limit=args.limit)
    finally:
        store.close()
    if not items:
        print("[ontologylab] merge queue is empty (run `ontologylab merge-scan`)")
        return 0
    for item in items:
        a, b = item["node_a"], item["node_b"]
        print(f"candidate {item['id']}  score={item['score']:.2f}  "
              f"reasons={', '.join(item['reasons'])}")
        for side, node in (("A", a), ("B", b)):
            aliases = ", ".join(node["aliases"]) or "-"
            print(
                f"  {side}: {node['name']} [{node['entity_type']}/"
                f"{node['status']}] id={node['id']} "
                f"citations={node['citation_count']} aliases={aliases}"
            )
        print(
            f"  -> merge:   ontologylab merge --target {a['id']} "
            f"--source {b['id']}"
        )
        print(f"  -> dismiss: ontologylab merge-dismiss --id {item['id']}")
    print(f"\n[ontologylab] {len(items)} pending merge candidate(s)")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    store = _open_store(args)
    try:
        report = store.merge_nodes(
            args.target, args.source, by=args.by, note=args.note
        )
    except KGStoreError as exc:
        print(f"[ontologylab] error: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()
    print(
        f"[ontologylab] merged {report['source_id']} -> {report['target_id']}: "
        f"{report['edges_repointed']} edge(s) re-pointed, "
        f"{report['edges_deduplicated']} deduplicated, "
        f"{report['edges_self_loop_rejected']} self-loop(s) dropped"
    )
    print(
        "[ontologylab] note: if this KG is embedded, re-run "
        "`ontologylab embed` to refresh the merged node's vector"
    )
    return 0


def cmd_merge_dismiss(args: argparse.Namespace) -> int:
    store = _open_store(args)
    try:
        store.dismiss_merge_candidate(args.id, by=args.by, note=args.note)
    except KGStoreError as exc:
        print(f"[ontologylab] error: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()
    print(f"[ontologylab] dismissed merge candidate {args.id} "
          "(this pair will not be re-proposed)")
    return 0


# ---------------------------------------------------------------------------
# build-pack
# ---------------------------------------------------------------------------


def cmd_build_pack(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    job_dir = paths.new_job_dir(data_dir, "build-pack")
    provenance = Provenance(str(job_dir), seed=0)
    provenance.log("build_pack.start", {"name": args.name})
    summarizer = None
    summary_method = "extractive"
    if args.summarize_engine:
        from ontologylab.communities import llm_summarizer

        summarizer = llm_summarizer(
            get_engine(
                args.summarize_engine, args.summarize_model, data_dir=data_dir
            ),
            model=args.summarize_model,
        )
        summary_method = f"llm:{args.summarize_engine}"
    manifest = build_pack(
        paths.kg_db_path(data_dir),
        args.packs_dir,
        args.name,
        source_job_id=job_dir.name,
        provenance_jsonl=provenance.jsonl_path,
        summarizer=summarizer,
        summary_method=summary_method,
    )
    provenance.log(
        "build_pack.end",
        {"pack_id": manifest.pack_id, "counts": manifest.counts},
    )
    print(f"[ontologylab] built pack {manifest.pack_id}")
    print(json.dumps(manifest.counts, indent=2))
    from ontologylab.mcp_server import serve_args

    print("[ontologylab] serve it: python "
          + " ".join(serve_args(args.packs_dir, manifest.pack_id)))
    return 0


def cmd_pack_diff(args: argparse.Namespace) -> int:
    from ontologylab.packbuilder import PackBuildError
    from ontologylab.packdiff import diff_packs

    try:
        diff = diff_packs(args.packs_dir, args.a, args.b)
    except PackBuildError as exc:
        print(f"[ontologylab] error: {exc}", file=sys.stderr)
        return 2
    print(f"[ontologylab] {args.a} -> {args.b}")
    if diff["identical"]:
        print("[ontologylab] packs are byte-identical (same content hash)")
        return 0
    for field, change in diff["manifest_changes"].items():
        print(f"  manifest {field}: {change['a']!r} -> {change['b']!r}")
    for kind in ("nodes", "edges"):
        section = diff[kind]
        for verb in ("added", "removed", "changed"):
            for item in section[verb]:
                suffix = (
                    f" ({', '.join(item['fields'])})" if verb == "changed" else ""
                )
                print(f"  {verb} {kind[:-1]}: {item['label']}{suffix}")
    summary = diff["summary"]
    print(
        f"[ontologylab] nodes +{summary['nodes_added']} "
        f"-{summary['nodes_removed']} ~{summary['nodes_changed']} | "
        f"edges +{summary['edges_added']} -{summary['edges_removed']} "
        f"~{summary['edges_changed']}"
    )
    return 0


def cmd_build_mcpb(args: argparse.Namespace) -> int:
    from ontologylab.mcpb import build_mcpb
    from ontologylab.packbuilder import PackBuildError

    try:
        bundle = build_mcpb(args.packs_dir, args.pack, out_path=args.out)
    except PackBuildError as exc:
        print(f"[ontologylab] error: {exc}", file=sys.stderr)
        return 2
    size_kb = bundle.stat().st_size / 1024
    print(f"[ontologylab] bundled {args.pack} -> {bundle} ({size_kb:.0f} KiB)")
    print(
        "[ontologylab] install: drag the .mcpb into Claude Desktop, or "
        "unzip and use manifest.json's mcp_config for any MCP client "
        "(host needs: pip install 'ontologylab[mcp]')"
    )
    return 0


# ---------------------------------------------------------------------------
# search (tier-1 lexical, optional tier-2 fail-open LLM query expansion)
# ---------------------------------------------------------------------------


def cmd_search(args: argparse.Namespace) -> int:
    try:
        store = _open_store(args)
    except KGStoreError as exc:
        print(f"[ontologylab] ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        variants: list[str] = []
        if args.expand:
            try:
                engine = get_engine(
                    args.engine, args.model, data_dir=Path(args.data_dir)
                )
                variants, usage = asyncio.run(
                    expand_query(args.query, engine, model=args.model)
                )
                if usage.get("error"):
                    print(
                        f"[ontologylab] expansion failed open: {usage['error']}",
                        file=sys.stderr,
                    )
            except EngineError as exc:
                print(
                    f"[ontologylab] expansion failed open: {exc}", file=sys.stderr
                )
                variants = []
        fts_query = " ".join([args.query, *variants]) if variants else args.query
        embedder = None
        if args.embedder:
            from ontologylab.embeddings import get_embedder

            try:
                embedder = get_embedder(args.embedder)
            except Exception as exc:  # noqa: BLE001 — 모델 다운로드/임포트 실패
                print(
                    f"[ontologylab] embedder unavailable ({exc}); "
                    "falling back to lexical",
                    file=sys.stderr,
                )
                embedder = None
            if embedder is not None and store.embedding_model() != embedder.name():
                print(
                    f"[ontologylab] no {embedder.name()!r} embeddings in this KG "
                    "(run `ontologylab embed` first); falling back to lexical",
                    file=sys.stderr,
                )
                embedder = None
        try:
            if embedder is not None:
                # 3신호 하이브리드: 벡터 신호는 원 쿼리만 임베딩하고,
                # 확장 변형은 변형들"만"으로 독립 lexical 랭킹을 만들어
                # 융합에 참여한다 (원 쿼리를 다시 섞으면 lexical 2배 가중)
                results = store.hybrid_search(
                    args.query,
                    embedder,
                    top_k=args.top_k,
                    entity_type=args.type,
                    include_proposed=args.include_proposed,
                    extra_lexical_queries=(
                        [" ".join(variants)] if variants else None
                    ),
                )
            else:
                results = store.semantic_search(
                    fts_query,
                    top_k=args.top_k,
                    entity_type=args.type,
                    include_proposed=args.include_proposed,
                )
        except KGStoreError as exc:
            print(f"[ontologylab] ERROR: {exc}", file=sys.stderr)
            return 2
        tier = "fts5"
        if embedder is not None:
            tier += "+vec-rrf"
        if variants:
            tier += "+llm-expansion"
        if variants:
            print(f"[ontologylab] tier: {tier} (terms: {', '.join(variants)})")
        else:
            print(f"[ontologylab] tier: {tier}")
        if not results:
            print(f"[ontologylab] 0 results for {args.query!r}")
        for row in results:
            print(
                f"{row['name']}  {row['entity_type']}  "
                f"score={row['match_score']:.3f}  id={row['id']}"
            )
        return 0
    finally:
        store.close()


def cmd_embed(args: argparse.Namespace) -> int:
    """Backfill embeddings (human-triggered; never runs inside extract)."""
    from ontologylab.embeddings import get_embedder

    try:
        embedder = get_embedder(args.embedder)
    except RuntimeError as exc:
        print(f"[ontologylab] ERROR: {exc}", file=sys.stderr)
        return 2
    if embedder is None:
        print("[ontologylab] no embedder selected", file=sys.stderr)
        return 2
    store = _open_store(args)
    try:
        stats = store.embed_nodes(embedder)
    finally:
        store.close()
    print(
        f"[ontologylab] embedded {stats['embedded']} node(s) with "
        f"{embedder.name()} ({stats['skipped']} already current)"
    )
    if embedder.name() == "hash-v1":
        print(
            "[ontologylab] note: hash-v1 is a lexical-overlap embedder for "
            "offline use — not semantic. Use a sentence-transformers model "
            "for real tier-2 quality."
        )
    return 0


# ---------------------------------------------------------------------------
# provider registry (configurable API model backends; keys stay in env vars)
# ---------------------------------------------------------------------------


def cmd_provider_list(args: argparse.Namespace) -> int:
    from ontologylab.providers import load_providers, resolve_api_key

    providers = load_providers(Path(args.data_dir))
    if not providers:
        print(
            "[ontologylab] no providers registered — add one with "
            "`ontologylab provider add`"
        )
        return 0
    for provider in providers:
        key_state = "set" if resolve_api_key(provider) else "MISSING"
        label = f" ({provider.label})" if provider.label else ""
        print(
            f"api:{provider.id}{label}  kind={provider.kind}  "
            f"base_url={provider.base_url}  api_key_env={provider.api_key_env}  "
            f"key:{key_state}  models={len(provider.models)}"
        )
    return 0


def cmd_provider_add(args: argparse.Namespace) -> int:
    from ontologylab.providers import Provider, ProviderError, add_provider

    models = tuple(
        m.strip() for m in (args.models or "").split(",") if m.strip()
    )
    provider = Provider(
        id=args.id,
        kind=args.kind,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        models=models,
        label=args.label or "",
    )
    try:
        add_provider(Path(args.data_dir), provider)
    except ProviderError as exc:
        print(f"[ontologylab] error: {exc}", file=sys.stderr)
        return 2
    print(
        f"[ontologylab] registered provider api:{provider.id} — select it as "
        f"`--engine api:{provider.id}`. Set the key in ${provider.api_key_env}."
    )
    return 0


def cmd_provider_remove(args: argparse.Namespace) -> int:
    from ontologylab.providers import remove_provider

    if remove_provider(Path(args.data_dir), args.id):
        print(f"[ontologylab] removed provider api:{args.id}")
        return 0
    print(f"[ontologylab] no provider with id {args.id!r}", file=sys.stderr)
    return 1


def cmd_provider_test(args: argparse.Namespace) -> int:
    """Send one tiny prompt to a provider (the only CLI path that hits the network)."""
    from ontologylab.providers import get_provider, resolve_api_key

    data_dir = Path(args.data_dir)
    provider = get_provider(data_dir, args.id)
    if provider is None:
        print(f"[ontologylab] no provider with id {args.id!r}", file=sys.stderr)
        return 1
    if not resolve_api_key(provider):
        print(
            f"[ontologylab] provider {args.id!r}: env var "
            f"{provider.api_key_env} is not set (MISSING) — export it and retry",
            file=sys.stderr,
        )
        return 1
    engine = get_engine(f"api:{provider.id}", args.model, data_dir=data_dir)
    start = time.monotonic()
    try:
        text, _usage = asyncio.run(
            engine.generate(
                "ping — reply with the single word: pong", model=args.model
            )
        )
    except EngineError as exc:
        print(f"[ontologylab] provider {args.id!r} test failed: {exc}",
              file=sys.stderr)
        return 2
    elapsed_ms = (time.monotonic() - start) * 1000
    sample = text.strip()[:40]
    print(
        f"[ontologylab] provider api:{args.id} ok · {elapsed_ms:.0f}ms · "
        f"reply: {sample!r}"
    )
    return 0


# ---------------------------------------------------------------------------
# parser wiring
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ontologylab",
        description=(
            "Local-first knowledge-graph pipeline: collect -> extract (LLM) "
            "-> verify (human) -> knowledge pack -> local MCP server."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="Fetch documents into the working KG.")
    p_collect.add_argument("--url", action="append", default=[],
                           help="URL to crawl (host must be allowlisted; repeatable).")
    p_collect.add_argument("--file", action="append", default=[],
                           help="Local text file to ingest as an upload (repeatable).")
    p_collect.add_argument("--paper-query", action="append", default=[],
                           help="Paper-API query term (must be allowlisted; "
                                "repeatable).")
    p_collect.add_argument("--paper-source", default="arxiv",
                           help="Paper API source (default: arxiv).")
    p_collect.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                           help="Max results per paper query (cap per query, "
                                "clamped to 1..25).")
    _add_data_dir(p_collect)
    p_collect.set_defaults(func=cmd_collect)

    p_extract = sub.add_parser("extract", help="LLM-extract proposed entities/relations.")
    p_extract.add_argument("--engine", default=paths.DEFAULT_ENGINE,
                           type=engine_name_arg, metavar="ENGINE",
                           help="mock|claude|codex|gemini or api:<provider-id> "
                                "(see `ontologylab provider`).")
    p_extract.add_argument("--model", default=paths.DEFAULT_MODEL)
    p_extract.add_argument("--doc-ids", nargs="*", default=None,
                           help="Documents to extract (default: all unprocessed).")
    p_extract.add_argument("--seed", type=int, default=paths.DEFAULT_SEED)
    p_extract.add_argument("--max-engine-calls", type=int,
                           default=paths.DEFAULT_MAX_ENGINE_CALLS)
    p_extract.add_argument("--time-budget", type=float,
                           default=paths.DEFAULT_TIME_BUDGET_S)
    _add_data_dir(p_extract)
    p_extract.set_defaults(func=cmd_extract)

    p_review = sub.add_parser("review", help="Print the pending review queue.")
    p_review.add_argument("--kind", choices=["node", "edge"], default=None)
    p_review.add_argument("--type", default=None,
                          help="Entity/relation type name filter.")
    p_review.add_argument("--doc", default=None, help="Source document id filter.")
    p_review.add_argument(
        "--order", default="created",
        choices=["created", "confidence", "confidence_desc", "critic"],
        help="Queue order; 'confidence' triages least-certain items first, "
             "'critic' puts the critic model's lowest scores first "
             "(run `ontologylab critic` to score).",
    )
    p_review.add_argument("--limit", type=int, default=100)
    _add_data_dir(p_review)
    p_review.set_defaults(func=cmd_review)

    p_approve = sub.add_parser(
        "approve", help="Approve proposed item(s) -> verified (human gate)."
    )
    p_approve.add_argument("--id", default=None, help="Node or edge id.")
    p_approve.add_argument(
        "--filter", default=None,
        help='Bulk filter, e.g. "entity_type=Component,min_confidence=0.8".',
    )
    p_approve.add_argument("--cascade", action="store_true",
                           help="Approve an edge together with its endpoint nodes.")
    p_approve.add_argument("--by", default=paths.DEFAULT_ACTOR)
    p_approve.add_argument("--note", default=None)
    _add_data_dir(p_approve)
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject", help="Reject a proposed item (kept for audit).")
    p_reject.add_argument("--id", required=True)
    p_reject.add_argument("--by", default=paths.DEFAULT_ACTOR)
    p_reject.add_argument("--note", default=None)
    _add_data_dir(p_reject)
    p_reject.set_defaults(func=cmd_reject)

    p_invalidate = sub.add_parser(
        "invalidate",
        help="Mark a verified edge as no-longer-current (history-preserving "
             "alternative to deletion; reject proposed edges instead).",
    )
    p_invalidate.add_argument("--id", required=True, help="Edge id.")
    p_invalidate.add_argument("--reason", default=None)
    p_invalidate.add_argument("--by", default=paths.DEFAULT_ACTOR)
    _add_data_dir(p_invalidate)
    p_invalidate.set_defaults(func=cmd_invalidate)

    p_entity = sub.add_parser(
        "entity",
        help="Entity-centric review: one entity's mentions (in source "
             "context), relations, critic score, and merge candidates.",
    )
    p_entity.add_argument("ref", help="Entity id or exact name.")
    _add_data_dir(p_entity)
    p_entity.set_defaults(func=cmd_entity)

    p_critic = sub.add_parser(
        "critic",
        help="Pre-score pending proposals with a second model (advisory "
             "only: sorts the queue and flags disagreements; never approves).",
    )
    p_critic.add_argument("--engine", default="mock",
                          type=engine_name_arg, metavar="ENGINE",
                          help="mock|claude|codex|gemini or api:<provider-id>.")
    p_critic.add_argument(
        "--model", default=None,
        help="Critic model. Default: the cheap Haiku-class CRITIC_MODEL tier "
             "for the claude engine (advisory triage needs no anchor model); "
             "other engines use their own default.")
    p_critic.add_argument("--limit", type=int, default=200,
                          help="Max pending items to score this run.")
    p_critic.add_argument("--batch-size", type=int, default=20)
    _add_data_dir(p_critic)
    p_critic.set_defaults(func=cmd_critic)

    p_merge_scan = sub.add_parser(
        "merge-scan",
        help="Scan for fuzzy duplicate entities -> merge candidates "
             "(proposals only; merging stays a human decision).",
    )
    p_merge_scan.add_argument(
        "--min-similarity", type=float, default=0.82,
        help="Minimum normalized-name similarity ratio (default 0.82).",
    )
    _add_data_dir(p_merge_scan)
    p_merge_scan.set_defaults(func=cmd_merge_scan)

    p_merge_queue = sub.add_parser(
        "merge-queue", help="Print pending merge candidates side by side."
    )
    p_merge_queue.add_argument("--limit", type=int, default=50)
    _add_data_dir(p_merge_queue)
    p_merge_queue.set_defaults(func=cmd_merge_queue)

    p_merge = sub.add_parser(
        "merge",
        help="Merge --source into --target (human gate; source becomes a "
             "rejected tombstone, aliases/citations/edges follow the target).",
    )
    p_merge.add_argument("--target", required=True, help="Surviving node id.")
    p_merge.add_argument("--source", required=True, help="Node id to merge away.")
    p_merge.add_argument("--by", default=paths.DEFAULT_ACTOR)
    p_merge.add_argument("--note", default=None)
    _add_data_dir(p_merge)
    p_merge.set_defaults(func=cmd_merge)

    p_merge_dismiss = sub.add_parser(
        "merge-dismiss", help="Dismiss a merge candidate (never re-proposed)."
    )
    p_merge_dismiss.add_argument("--id", required=True, help="Candidate id.")
    p_merge_dismiss.add_argument("--by", default=paths.DEFAULT_ACTOR)
    p_merge_dismiss.add_argument("--note", default=None)
    _add_data_dir(p_merge_dismiss)
    p_merge_dismiss.set_defaults(func=cmd_merge_dismiss)

    p_build = sub.add_parser("build-pack", help="Export verified subgraph as a pack.")
    p_build.add_argument("--name", required=True)
    p_build.add_argument("--packs-dir", default=str(paths.default_packs_dir()))
    p_build.add_argument(
        "--summarize-engine", default=None,
        type=engine_name_arg, metavar="ENGINE",
        help="Optional LLM for community summaries (mock|claude|codex|gemini "
             "or api:<provider-id>; default: extractive, model-free). Any "
             "failure falls back to extractive per community.",
    )
    p_build.add_argument("--summarize-model", default=None)
    _add_data_dir(p_build)
    p_build.set_defaults(func=cmd_build_pack)

    p_pack_diff = sub.add_parser(
        "pack-diff",
        help="Diff two built packs: manifest deltas + added/removed/changed "
             "nodes and edges (id-stable across rebuilds).",
    )
    p_pack_diff.add_argument("--a", required=True, help="Older pack id.")
    p_pack_diff.add_argument("--b", required=True, help="Newer pack id.")
    p_pack_diff.add_argument("--packs-dir", default=str(paths.default_packs_dir()))
    p_pack_diff.set_defaults(func=cmd_pack_diff)

    p_mcpb = sub.add_parser(
        "build-mcpb",
        help="Bundle a built pack as a single installable .mcpb file "
             "(drag-and-drop into Claude Desktop).",
    )
    p_mcpb.add_argument("--pack", required=True, help="Pack id to bundle.")
    p_mcpb.add_argument("--packs-dir", default=str(paths.default_packs_dir()))
    p_mcpb.add_argument("--out", default=None,
                        help="Output path (default: <packs-dir>/<pack>.mcpb).")
    p_mcpb.set_defaults(func=cmd_build_mcpb)

    p_search = sub.add_parser(
        "search",
        help="Lexical FTS5 search of the working KG "
             "(--expand adds fail-open LLM query expansion).",
    )
    p_search.add_argument("query", help="Search query.")
    p_search.add_argument("--top-k", type=int, default=10)
    p_search.add_argument("--type", default=None, help="Entity type filter.")
    p_search.add_argument("--include-proposed", action="store_true",
                          help="Include unverified (proposed) rows.")
    p_search.add_argument("--expand", action="store_true",
                          help="Expand the query with LLM lexical variants "
                               "(fails open to plain lexical search).")
    p_search.add_argument("--engine", default="mock",
                          type=engine_name_arg, metavar="ENGINE",
                          help="mock|claude|codex|gemini or api:<provider-id>.")
    p_search.add_argument("--model", default=None)
    p_search.add_argument(
        "--embedder", default=None,
        help="Enable tier-2 hybrid search (BM25+vector RRF): 'auto' (real "
             "MiniLM when sentence-transformers is installed, else the "
             "offline hash embedder), 'hash', or a sentence-transformers "
             "model name. Requires embeddings backfilled via "
             "`ontologylab embed`.",
    )
    _add_data_dir(p_search)
    p_search.set_defaults(func=cmd_search)

    p_embed = sub.add_parser(
        "embed",
        help="Backfill node embeddings for tier-2 hybrid search. "
             "'hash' is offline but lexical-only; real semantic quality "
             "needs a sentence-transformers model (one-time download).",
    )
    p_embed.add_argument(
        "--embedder", default="hash",
        help="'auto' (real MiniLM when sentence-transformers is installed, "
             "else hash), 'hash' (offline, deterministic, NOT semantic), or "
             "a sentence-transformers model name.",
    )
    _add_data_dir(p_embed)
    p_embed.set_defaults(func=cmd_embed)

    p_provider = sub.add_parser(
        "provider",
        help="Manage configurable API model providers (registry only — keys "
             "stay in env vars, never stored). Select one as `--engine api:<id>`.",
    )
    prov_sub = p_provider.add_subparsers(dest="provider_command", required=True)

    p_prov_list = prov_sub.add_parser(
        "list", help="List registered providers and whether each key env var is set."
    )
    _add_data_dir(p_prov_list)
    p_prov_list.set_defaults(func=cmd_provider_list)

    p_prov_add = prov_sub.add_parser(
        "add", help="Register (or update) a provider by id."
    )
    p_prov_add.add_argument("--id", required=True,
                            help="Slug id, e.g. 'my-anthropic' (^[a-z0-9][a-z0-9_-]{0,31}$).")
    p_prov_add.add_argument("--kind", required=True, choices=["anthropic", "openai"],
                            help="API dialect: anthropic or openai-compatible.")
    p_prov_add.add_argument("--base-url", required=True,
                            help="API base, e.g. https://api.anthropic.com/v1 "
                                 "(http only for localhost).")
    p_prov_add.add_argument("--api-key-env", required=True,
                            help="NAME of the env var holding the key (the key "
                                 "itself is never stored), e.g. ANTHROPIC_API_KEY.")
    p_prov_add.add_argument("--models", default=None,
                            help="Comma-separated model ids; the first is the default.")
    p_prov_add.add_argument("--label", default="",
                            help="Optional human label.")
    _add_data_dir(p_prov_add)
    p_prov_add.set_defaults(func=cmd_provider_add)

    p_prov_remove = prov_sub.add_parser("remove", help="Remove a provider by id.")
    p_prov_remove.add_argument("--id", required=True)
    _add_data_dir(p_prov_remove)
    p_prov_remove.set_defaults(func=cmd_provider_remove)

    p_prov_test = prov_sub.add_parser(
        "test",
        help="Send one tiny prompt to a provider (needs its key env var set). "
             "The only provider subcommand that touches the network.",
    )
    p_prov_test.add_argument("--id", required=True)
    p_prov_test.add_argument("--model", default=None,
                             help="Override the model for this test call.")
    _add_data_dir(p_prov_test)
    p_prov_test.set_defaults(func=cmd_provider_test)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
