"""FastAPI API routes for the ontologylab local web layer.

Exposes /api/engines, /api/settings, /api/cost, /api/proposals
(list / approve / reject), and the M8 dashboard surface:
/api/documents, /api/collect, /api/extract, /api/jobs, /api/packs,
/api/mcp/status — everything needed to drive collect → extract →
review → build → serve status from the browser, no CLI required.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any
from urllib.error import URLError
from xml.etree.ElementTree import ParseError

from fastapi import APIRouter, HTTPException, Query

from ontologylab import paths
from ontologylab.connectors.allowlist import (
    NotAllowlisted,
    check_paper_query,
    check_url,
)
from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.paper_api import (
    PaperApiConnector,
    UnsupportedPaperSource,
    check_source_implemented,
)
from ontologylab.connectors.web_crawl import WebCrawlConnector
from ontologylab.kgstore import EndpointNotVerified, KGStore, KGStoreError, UnknownItem
from ontologylab.mcp_server import serve_args
from ontologylab.packbuilder import PackBuildError, build_pack, list_packs
from ontologylab.paths import default_data_dir, default_packs_dir, kg_db_path
from ontologylab.provenance import Provenance
from ontologylab.server import settings as settings_mod
from ontologylab.server.jobs import JobRegistry
from ontologylab.server.schemas import (
    CollectRequest,
    CostSummary,
    CriticRunRequest,
    EngineInfo,
    ExtractRequest,
    JobStatus,
    MergeAction,
    MergeDismiss,
    MergeScanRequest,
    PackBuildRequest,
    ProposalAction,
    Settings,
)

router = APIRouter(prefix="/api")

# Bound once by app.create_app(); holds the data-dir Path for the working KG.
_data_dir: Path = default_data_dir()

# Bound once by app.create_app(); holds the packs output directory.
_packs_dir: Path = default_packs_dir()

# Bound once by app.create_app(); holds the extraction-job registry.
_jobs_registry: JobRegistry | None = None


def attach_data_dir(data_dir: Path) -> None:
    global _data_dir
    _data_dir = Path(data_dir)


def attach_packs_dir(packs_dir: Path) -> None:
    global _packs_dir
    _packs_dir = Path(packs_dir)


def attach_jobs_registry(registry: JobRegistry) -> None:
    global _jobs_registry
    _jobs_registry = registry


def _registry() -> JobRegistry:
    # create_app always attaches; the fallback keeps bare-router usage working.
    global _jobs_registry
    if _jobs_registry is None:
        _jobs_registry = JobRegistry(_data_dir)
    return _jobs_registry


def _open_store() -> KGStore:
    # Creates an empty store on first open, so the review UI boots cleanly
    # even before any collect job has run.
    return KGStore.open(kg_db_path(_data_dir))


# ---------------------------------------------------------------------------
# Engines / settings / cost
# ---------------------------------------------------------------------------


@router.get("/engines", response_model=list[EngineInfo])
def get_engines() -> list[EngineInfo]:
    return settings_mod.engines()


@router.get("/settings", response_model=Settings)
def get_settings() -> Settings:
    return settings_mod.load_settings()


@router.put("/settings", response_model=Settings)
def put_settings(new_settings: Settings) -> Settings:
    return settings_mod.save_settings(new_settings)


@router.get("/cost", response_model=CostSummary)
def get_cost() -> CostSummary:
    return settings_mod.cost_summary()


# ---------------------------------------------------------------------------
# Proposals (HITL review)
# ---------------------------------------------------------------------------


@router.get("/proposals")
def list_proposals(
    kind: str | None = Query(None, description="node | edge"),
    type_name: str | None = Query(None),
    source_doc_id: str | None = Query(None),
    order: str = Query(
        "created",
        description="created | confidence (least-certain first) | "
        "confidence_desc | critic (lowest critic score first)",
    ),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    store = _open_store()
    try:
        try:
            items = store.pending_review(
                kind=kind,
                type_name=type_name,
                source_doc_id=source_doc_id,
                order=order,
                limit=limit,
            )
        except KGStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        counts = store.counts()
        return {"items": items, "counts": counts, "count": len(items)}
    finally:
        store.close()


@router.post("/proposals/approve")
def approve_proposal(body: ProposalAction) -> dict[str, Any]:
    store = _open_store()
    try:
        result = store.approve(
            body.id, by=body.by, note=body.note, cascade=body.cascade
        )
        return {"ok": True, **result}
    except EndpointNotVerified as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.post("/edges/{edge_id}/invalidate")
def invalidate_edge(edge_id: str, body: ProposalAction) -> dict[str, Any]:
    """W13: mark a verified edge as no-longer-current (kept as history)."""
    store = _open_store()
    try:
        result = store.invalidate_edge(edge_id, by=body.by, reason=body.note)
        return {"ok": True, **result}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.post("/proposals/reject")
def reject_proposal(body: ProposalAction) -> dict[str, Any]:
    store = _open_store()
    try:
        result = store.reject(body.id, by=body.by, note=body.note)
        return {"ok": True, **result}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Entity-centric review (W11 — read-only aggregation for one entity)
# ---------------------------------------------------------------------------


@router.get("/entity/{entity_id}/review")
def entity_review(entity_id: str) -> dict[str, Any]:
    store = _open_store()
    try:
        return store.entity_review_context(entity_id)
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Communities (W12 — read-only; rows exist only inside built packs, so the
# working-DB store returns an empty list rather than an error)
# ---------------------------------------------------------------------------


@router.get("/communities")
def get_communities(limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    store = _open_store()
    try:
        communities = store.list_communities(limit=limit)
        return {"communities": communities, "count": len(communities)}
    finally:
        store.close()


@router.get("/communities/{community_id}")
def get_community(community_id: str) -> dict[str, Any]:
    store = _open_store()
    try:
        # community_members 404s on an unknown id (UnknownItem); on success
        # we attach the community's own summary/metadata row for the header.
        members = store.community_members(community_id)
        community = next(
            (c for c in store.list_communities(limit=1000)
             if c["id"] == community_id),
            None,
        )
        return {"community": community, "members": members}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Critic triage (W8 — advisory scores; never a decision path)
# ---------------------------------------------------------------------------


@router.post("/critic/run")
async def critic_run(body: CriticRunRequest) -> dict[str, Any]:
    from ontologylab.critic import critic_review
    from ontologylab.engines import get_engine

    engine = get_engine(body.engine, body.model)
    store = _open_store()
    try:
        stats = await critic_review(
            store, engine, model=body.model,
            limit=body.limit, batch_size=body.batch_size,
        )
        return {"ok": True, **stats}
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Merge review (W7 — candidates from scan, decisions by human)
# ---------------------------------------------------------------------------


@router.post("/merge/scan")
def merge_scan(body: MergeScanRequest) -> dict[str, Any]:
    from ontologylab.merge import scan_merge_candidates

    store = _open_store()
    try:
        stats = scan_merge_candidates(store, name_threshold=body.min_similarity)
        return {"ok": True, **stats}
    finally:
        store.close()


@router.get("/merge/candidates")
def merge_candidates(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    store = _open_store()
    try:
        items = store.merge_candidates_pending(limit=limit)
        return {"items": items, "count": len(items)}
    finally:
        store.close()


@router.post("/merge/candidates/{candidate_id}/merge")
def merge_candidate_merge(candidate_id: str, body: MergeAction) -> dict[str, Any]:
    store = _open_store()
    try:
        candidate = store._merge_candidate_row(candidate_id)
        pair = {candidate["node_a_id"], candidate["node_b_id"]}
        if {body.target_id, body.source_id} != pair:
            raise HTTPException(
                status_code=400,
                detail="target/source ids do not match this candidate's pair",
            )
        if candidate["status"] != "proposed":
            raise HTTPException(
                status_code=409,
                detail=f"candidate already decided ({candidate['status']})",
            )
        report = store.merge_nodes(
            body.target_id, body.source_id, by=body.by, note=body.note
        )
        return {"ok": True, **report}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.post("/merge/candidates/{candidate_id}/dismiss")
def merge_candidate_dismiss(candidate_id: str, body: MergeDismiss) -> dict[str, Any]:
    store = _open_store()
    try:
        result = store.dismiss_merge_candidate(
            candidate_id, by=body.by, note=body.note
        )
        return {"ok": True, **result}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Documents / collect (Sources screen)
# ---------------------------------------------------------------------------


@router.get("/documents")
def get_documents() -> dict[str, Any]:
    store = _open_store()
    try:
        documents = [
            {
                "id": doc.id,
                "source_kind": doc.source_kind,
                "source_uri": doc.source_uri,
                "title": doc.title,
                "fetched_ts": doc.fetched_ts,
                "content_hash": doc.content_hash,
            }
            for doc in store.list_documents()
        ]
    finally:
        store.close()
    return {"documents": documents, "count": len(documents)}


@router.post("/collect")
def collect(body: CollectRequest) -> dict[str, Any]:
    """Run a collect synchronously, mirroring main.cmd_collect's gate order.

    Gate failures return 200 with {"ok": false, "error_kind", "detail"} so
    the dashboard can render them inline — never a 4xx/5xx.
    """
    job_dir = paths.new_job_dir(_data_dir, "collect")
    provenance = Provenance(str(job_dir), seed=0)
    provenance.log(
        "collect.start",
        {
            "urls": body.urls,
            "files": body.files,
            "paper_queries": body.paper_queries,
        },
    )

    if not (body.urls or body.files or body.paper_queries):
        detail = (
            "nothing to collect: pass urls, files, and/or paper_queries"
        )
        provenance.log("collect.rejected", {"error": detail})
        return {"ok": False, "error_kind": "rejected", "detail": detail}

    # Mixed-run pre-validation (mirrors cmd_collect): every gate for every
    # input is checked BEFORE any fetch, so one rejected/unsupported input
    # can never let an earlier input reach the network first.
    try:
        for url in body.urls:
            check_url(url)
        for paper_query in body.paper_queries:
            check_paper_query(body.paper_source, paper_query)
            check_source_implemented(body.paper_source)
    except NotAllowlisted as exc:
        provenance.log("collect.rejected", {"error": str(exc)})
        return {"ok": False, "error_kind": "rejected", "detail": str(exc)}
    except UnsupportedPaperSource as exc:
        provenance.log("collect.unsupported", {"error": str(exc)})
        return {"ok": False, "error_kind": "unsupported", "detail": str(exc)}

    error: dict[str, Any] | None = None

    def _run_connector(connector, spec: dict) -> list[RawDocument] | None:
        """Fetch via one connector; None means a logged, returnable failure.

        NotAllowlisted / UnsupportedPaperSource are re-checked in-fetch as
        defense in depth; URLError (incl. HTTPError) and Atom ParseError
        are fetch failures — all must end as a clean JSON error, never a
        500 (with no network, URL fetches fail here as fetch_failed).
        """
        nonlocal error
        try:
            return asyncio.run(connector.fetch(spec))
        except NotAllowlisted as exc:
            provenance.log("collect.rejected", {"error": str(exc)})
            error = {"ok": False, "error_kind": "rejected", "detail": str(exc)}
        except UnsupportedPaperSource as exc:
            provenance.log("collect.unsupported", {"error": str(exc)})
            error = {"ok": False, "error_kind": "unsupported", "detail": str(exc)}
        except (URLError, ParseError) as exc:
            provenance.log("collect.fetch_failed", {"error": str(exc)})
            error = {"ok": False, "error_kind": "fetch_failed", "detail": str(exc)}
        except (ValueError, OSError) as exc:
            provenance.log("collect.failed", {"error": str(exc)})
            error = {"ok": False, "error_kind": "fetch_failed", "detail": str(exc)}
        return None

    raw_docs: list[RawDocument] = []
    if body.urls:
        fetched = _run_connector(WebCrawlConnector(), {"urls": body.urls})
        if fetched is None:
            return error or {"ok": False, "error_kind": "fetch_failed",
                             "detail": "web crawl failed"}
        raw_docs.extend(fetched)
    for paper_query in body.paper_queries:
        fetched = _run_connector(
            PaperApiConnector(),
            {
                "source": body.paper_source,
                "query": paper_query,
                "limit": body.limit,
            },
        )
        if fetched is None:
            return error or {"ok": False, "error_kind": "fetch_failed",
                             "detail": "paper API fetch failed"}
        raw_docs.extend(fetched)
    for file_arg in body.files:
        path = Path(file_arg)
        try:
            raw_text = path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            provenance.log("collect.fetch_failed", {"error": str(exc)})
            return {"ok": False, "error_kind": "fetch_failed", "detail": str(exc)}
        raw_docs.append(
            RawDocument(
                source_kind="upload",
                source_uri=path.resolve().as_uri(),
                title=path.stem,
                raw_text=raw_text,
            )
        )

    if not raw_docs:
        provenance.log("collect.end", {"documents": 0, "created": 0})
        return {"ok": True, "documents": 0, "created": 0, "duplicates": 0}

    store = _open_store()
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
        provenance.log(
            "collect.end",
            {"documents": len(raw_docs), "created": created_count},
        )
    finally:
        store.close()
    return {
        "ok": True,
        "documents": len(raw_docs),
        "created": created_count,
        "duplicates": len(raw_docs) - created_count,
    }


# ---------------------------------------------------------------------------
# Extraction jobs (Extraction Jobs screen — polled, tui.py-style)
# ---------------------------------------------------------------------------


@router.post("/extract", status_code=202)
def start_extract(body: ExtractRequest) -> dict[str, Any]:
    job = _registry().create(
        engine=body.engine,
        model=body.model,
        doc_ids=body.doc_ids,
        max_engine_calls=body.max_engine_calls,
        time_budget=body.time_budget,
        seed=body.seed,
    )
    return {"job_id": job.job_id, "status": "running"}


@router.get("/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": [job.as_status() for job in _registry().list()]}


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    job = _registry().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job {job_id!r}")
    return JobStatus(**job.as_status())


# ---------------------------------------------------------------------------
# Packs (Packs screen)
# ---------------------------------------------------------------------------


@router.get("/packs")
def get_packs() -> dict[str, Any]:
    packs = list_packs(_packs_dir)
    return {"packs": packs, "count": len(packs)}


@router.post("/packs/build")
def packs_build(body: PackBuildRequest) -> dict[str, Any]:
    job_dir = paths.new_job_dir(_data_dir, "build-pack")
    provenance = Provenance(str(job_dir), seed=0)
    provenance.log("build_pack.start", {"name": body.name})
    # Zero collected documents / zero verified rows is still a buildable
    # (empty) pack: ensure the working DB exists before handing it over.
    _open_store().close()
    try:
        manifest = build_pack(
            kg_db_path(_data_dir),
            _packs_dir,
            body.name,
            source_job_id=job_dir.name,
            provenance_jsonl=provenance.jsonl_path,
        )
    except (PackBuildError, OSError) as exc:
        provenance.log("build_pack.failed", {"error": str(exc)})
        return {"ok": False, "detail": str(exc)}
    provenance.log(
        "build_pack.end",
        {"pack_id": manifest.pack_id, "counts": manifest.counts},
    )
    return {"ok": True, "manifest": dataclasses.asdict(manifest)}


@router.get("/packs/{pack_a_id}/diff/{pack_b_id}")
def packs_diff(pack_a_id: str, pack_b_id: str) -> dict[str, Any]:
    """W14: manifest + node/edge deltas between two built packs."""
    from ontologylab.packdiff import diff_packs

    try:
        return diff_packs(_packs_dir, pack_a_id, pack_b_id)
    except PackBuildError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/packs/{pack_id}/mcpb")
def packs_build_mcpb(pack_id: str) -> dict[str, Any]:
    """Bundle one built pack as a downloadable .mcpb file."""
    from ontologylab.mcpb import build_mcpb

    try:
        bundle = build_mcpb(_packs_dir, pack_id)
    except (PackBuildError, OSError) as exc:
        return {"ok": False, "detail": str(exc)}
    return {
        "ok": True,
        "pack_id": pack_id,
        "path": str(bundle),
        "size_bytes": bundle.stat().st_size,
        "download_url": f"/api/packs/{pack_id}/mcpb/download",
    }


@router.get("/packs/{pack_id}/mcpb/download")
def packs_download_mcpb(pack_id: str) -> Any:
    from fastapi.responses import FileResponse

    from ontologylab.mcpb import build_mcpb

    bundle = Path(_packs_dir) / f"{pack_id}.mcpb"
    if not bundle.is_file():
        try:
            bundle = build_mcpb(_packs_dir, pack_id)
        except (PackBuildError, OSError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        bundle,
        media_type="application/zip",
        filename=f"{pack_id}.mcpb",
    )


# ---------------------------------------------------------------------------
# MCP status (MCP Status screen)
# ---------------------------------------------------------------------------


@router.get("/mcp/status")
def mcp_status() -> dict[str, Any]:
    packs_abs = str(Path(_packs_dir).resolve())
    entries: list[dict[str, Any]] = []
    for manifest in list_packs(_packs_dir):
        pack_id = manifest.get("pack_id")
        entries.append(
            {
                "pack_id": pack_id,
                "counts": manifest.get("counts") or {},
                "created_ts": manifest.get("created_ts"),
                "serve_command": "python " + " ".join(
                    serve_args(packs_abs, pack_id)
                ),
                "stdio_config": {
                    "command": "python",
                    "args": serve_args(packs_abs, pack_id),
                },
            }
        )
    return {"packs_dir": packs_abs, "packs": entries, "count": len(entries)}
