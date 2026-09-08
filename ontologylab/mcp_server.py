"""Local MCP stdio server for ontologylab knowledge packs.

Exposes fifteen read-only/session tools against one active immutable pack
(``pack.sqlite`` opened ``file:...?mode=ro&immutable=1``). The only tool
that mutates anything is ``load_pack``, and it only updates in-memory
session state (which file is open) — never KG rows.

Tool logic lives on ``PackSession``; the local ``McpApp`` registry owns
schema validation and stdio delivery without requiring the ``mcp`` SDK.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:  # pydantic (FastMCP schema generation) needs this variant on py<3.12
    from typing_extensions import TypedDict
except ImportError:  # pragma: no cover
    from typing import TypedDict

from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.method_mcp import (
    MethodDetailResult,
    MethodGapsResult,
    MethodListResult,
    MethodPackReader,
    MethodTraceResult,
)
from ontologylab.method_mcp_sql import MethodPackSql
from ontologylab.mcp_runtime import McpApp
from ontologylab.engines import EngineError, engine_name_arg, resolve_engine
from ontologylab.expansion import expand_query
from ontologylab.packbuilder import (
    list_packs as discover_packs,
    safe_pack_component,
)
from ontologylab.paths import default_packs_dir
from ontologylab.semantic_staleness import baseline_compatible, semantic_deltas
from ontologylab.pack_v2_derive import fact_receipts, resolve_pack_evidence
from ontologylab.verified_pack_reader import (
    PackIntegrityError,
    VerifiedPackSnapshot,
    activate_pack,
    inspect_verified_manifest,
    opened_verified_pack,
)


class NoActivePack(Exception):
    """Raised when a query tool is called before any pack is loaded."""


def serve_args(packs_dir: str | Path, pack_id: str) -> list[str]:
    """argv (after the Python interpreter) that serves one pack over stdio.

    Single authority for the launch invocation — the dashboard's MCP screen
    and the CLI's build-pack hint both render from this, so an argparse flag
    rename here can't silently strand them.
    """
    return [
        "-m",
        "ontologylab.mcp_server",
        "--packs-dir",
        str(packs_dir),
        "--pack",
        pack_id,
    ]



# ---------------------------------------------------------------------------
# W9 two-tier responses: list-shaped tools return COMPACT rows by default
# (id / label / score / snippet) — full records are one follow-up away via
# the get_entity tool, detail=True, or the pack://.../entity/{id} resource.
# Rationale: compact-first cuts per-result tokens roughly to a third while
# keeping enough signal to decide what to fetch next.
# ---------------------------------------------------------------------------

SNIPPET_MAX_CHARS = 120


# Fields a curated-resource annotation may carry that are worth a snippet,
# best first. `matched_name` is the floor: it is always present, and it is
# the one thing that tells a reader which record this is.
_ANNOTATION_SUMMARY_FIELDS = (
    "function",
    "summary",
    "description",
    "protein_name",
    "gene_name",
    "matched_name",
)


def _property_summary(key: str, value: Any) -> str:
    """Render one property for a compact row.

    Scalars keep the original `key=value` shape. A dict does not: an
    annotation block rendered that way becomes a Python repr, and the
    snippet budget is spent on braces and quotes before any prose arrives —

        uniprot={'external_id': 'P38398', 'record_url': 'https://www.uniprot.o

    truncated mid-URL, which is the first thing an MCP client sees for every
    annotated entity. The block's identifier and its most readable field say
    the same thing in a fraction of the space.
    """
    if not isinstance(value, dict):
        return f"{key}={value}"
    external_id = str(value.get("external_id") or "").strip()
    for field_name in _ANNOTATION_SUMMARY_FIELDS:
        text = " ".join(str(value.get(field_name) or "").split())
        if text:
            head = f"{key}:{external_id}" if external_id else key
            return f"{head} {text}"
    return f"{key}:{external_id}" if external_id else key


def _node_snippet(item: dict[str, Any]) -> str:
    """One short line summarizing aliases + properties for a compact row."""
    parts: list[str] = []
    aliases = item.get("aliases") or []
    if aliases:
        parts.append("aka " + ", ".join(str(a) for a in aliases[:3]))
    properties = item.get("properties") or {}
    if properties:
        parts.append(
            "; ".join(
                _property_summary(key, properties[key])
                for key in list(properties)[:3]
            )
        )
    return " · ".join(parts)[:SNIPPET_MAX_CHARS]


def compact_node(item: dict[str, Any]) -> dict[str, Any]:
    """Compact row: identity, label, score/hop, snippet, doc provenance.

    Drops aliases/properties/source_span (recoverable via get_entity), but
    NEVER drops document-level provenance — the W2 invariant (every response
    says where a fact came from) holds at both detail tiers.
    """
    out: dict[str, Any] = {
        "id": item["id"],
        "name": item["name"],
        "entity_type": item["entity_type"],
        "status": item["status"],
        "snippet": _node_snippet(item),
    }
    for key in ("match_score", "hop"):
        if key in item:
            out[key] = item[key]
    if "source_document_ids" in item:
        out["source_document_ids"] = item["source_document_ids"]
    elif "source_doc_id" in item:
        out["source_doc_id"] = item["source_doc_id"]
    for key in (
        "work_id", "representation_id", "representation_content_hash",
        "citation_id", "selected_text_hash", "start_offset", "end_offset",
        "policy_identity",
    ):
        if key in item:
            out[key] = item[key]
    return out


def compact_edge(edge: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": edge["id"],
        "relation_type": edge["relation_type"],
        "source_id": edge["source_id"],
        "target_id": edge["target_id"],
        "status": edge["status"],
        "source_doc_id": edge.get("source_doc_id"),
    }
    for key in (
        "work_id", "representation_id", "representation_content_hash",
        "citation_id", "selected_text_hash", "start_offset", "end_offset",
        "policy_identity",
    ):
        if key in edge:
            out[key] = edge[key]
    return out


def _with_fact_receipts(
    conn: Any, item: dict[str, Any], fact_kind: str,
) -> dict[str, Any]:
    enriched = dict(item)
    enriched.update(fact_receipts(conn, fact_kind, str(item["id"])))
    return enriched


def _entity_detail(store: KGStore, entity_id: str, *, include_proposed: bool) -> dict[str, Any]:
    """Full record for one entity: node fields + citations + adjacent edges
    (endpoint names resolved). Shared by the get_entity tool and the
    pack://.../entity/{id} resource."""
    matches = store.entity_lookup(
        id=entity_id, fuzzy=False, include_proposed=include_proposed, limit=1
    )
    if not matches:
        raise KGStoreError(f"no visible entity with id {entity_id!r}")
    entity = _with_fact_receipts(store.conn, matches[0], "node")
    entity["citations"] = store.citations("node", entity_id)
    neighborhood = store.traverse_relations(
        [entity_id], max_hops=1, include_proposed=include_proposed
    )
    names = {n["id"]: n["name"] for n in neighborhood["nodes"]}
    edges = []
    for edge in neighborhood["edges"]:
        edge = dict(edge)
        edge["source_name"] = names.get(edge["source_id"])
        edge["target_name"] = names.get(edge["target_id"])
        edges.append(edge)
    entity["edges"] = edges
    return entity


def _ontology_tables_present(store: KGStore) -> bool:
    """Whether a pack carries the P1 ontology publication tables."""
    names = {
        row[0]
        for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('ontology_term', 'term_alias', 'term_xref')"
        )
    }
    return names == {"ontology_term", "term_alias", "term_xref"}


def _ontology_term_detail(store: KGStore, term_id: str) -> dict[str, Any]:
    """One published term with append-ordered aliases and xref history."""
    if not _ontology_tables_present(store):
        raise KGStoreError("pack predates ontology term publication")
    return {
        "term": store.get_ontology_term(term_id),
        "aliases": store.list_term_aliases(term_id),
        "xrefs": store.list_term_xrefs(term_id),
    }


def _term_xref_detail(store: KGStore, xref_id: str) -> dict[str, Any]:
    """One published xref row; mapping predicates never merge identities."""
    if not _ontology_tables_present(store):
        raise KGStoreError("pack predates ontology term publication")
    return {"xref": store.get_term_xref(xref_id)}


class PackSession:
    """In-memory MCP session: packs-dir + one active read-only KGStore.

    Pure logic — no FastMCP dependency. Tests construct this directly.
    """

    def __init__(
        self,
        packs_dir: str | Path,
        *,
        expansion_engine: str | None = None,
        expansion_model: str | None = None,
        embedder=None,
        live_store_path: str | Path | None = None,
    ) -> None:
        self.packs_dir = Path(packs_dir)
        self.store: KGStore | None = None
        self._snapshot: VerifiedPackSnapshot | None = None
        self.pack_id: str | None = None
        self.pack_hash: str | None = None
        self._methodology: dict[str, Any] | None = None
        self.expansion_engine = expansion_engine
        self.expansion_model = expansion_model
        self.embedder = embedder
        self.live_store_path = (
            Path(live_store_path) if live_store_path is not None else None
        )
        self._live_store: KGStore | None = None

    def _live(self) -> KGStore | None:
        """The working store, opened read-only on first use.

        Staleness is a live question — "what is verified now that the latest
        pack does not reflect" — so it cannot be answered from the immutable
        packs alone. Absent path means the feature is off, and the caller
        reports that honestly instead of inventing a zero.
        """
        if self.live_store_path is None:
            return None
        if self._live_store is None:
            self._live_store = KGStore.open(
                self.live_store_path, read_only=True, immutable=False
            )
        return self._live_store

    def get_staleness(self) -> dict[str, Any]:
        """Compare the latest immutable baseline with current verified truth.

        ``pending_verified_count`` remains the historical count-difference
        advisory. The semantic categories are authoritative and disjoint by
        stable id: live-only, pack-only, and same-id changed content.
        """
        packs = discover_packs(self.packs_dir)
        unknown = {
            "semantic_additions": None,
            "semantic_invalidations": None,
            "semantic_replacements": None,
        }
        if not packs:
            return {
                "latest_pack_id": None,
                "basis_commit": None,
                "created_ts": None,
                "staleness_policy": None,
                "pack_verified_count": None,
                "store_verified_count": None,
                "pending_verified_count": None,
                **unknown,
                "note": "no packs found in packs_dir; semantic deltas unavailable",
            }
        latest = max(packs, key=lambda p: p.get("created_ts", 0))
        counts = latest.get("counts") or {}
        pack_count = int(counts.get("nodes_verified", 0)) + int(
            counts.get("edges_verified", 0)
        )
        result: dict[str, Any] = {
            "latest_pack_id": latest.get("pack_id"),
            "basis_commit": latest.get("basis_commit"),
            "created_ts": latest.get("created_ts"),
            "staleness_policy": latest.get("staleness_policy"),
            "pack_verified_count": pack_count,
        }
        live = self._live()
        if live is None:
            result.update(
                store_verified_count=None,
                pending_verified_count=None,
                **unknown,
                note="live store not configured; semantic deltas and advisory "
                "pending count are unavailable (pass --live-store)",
            )
            return result
        # BEGIN is deliberately explicit: Python's sqlite wrapper does not
        # start a transaction for SELECTs. Count and all semantic fingerprint
        # queries must describe the same live WAL snapshot.
        live.conn.execute("BEGIN")
        try:
            store_count = live.conn.execute(
                "SELECT (SELECT COUNT(*) FROM nodes WHERE status='verified') + "
                "(SELECT COUNT(*) FROM edges WHERE status='verified' AND "
                "invalidated_ts IS NULL)"
            ).fetchone()[0]
            result.update(
                store_verified_count=store_count,
                pending_verified_count=max(0, store_count - pack_count),
            )
            marker = latest.get("semantic_fact_baseline")
            if not baseline_compatible(marker):
                result.update(
                    **unknown,
                    note="legacy or unsupported pack semantic baseline; semantic "
                    "deltas unavailable, advisory pending count retained",
                )
                return result
            ephemeral = self.store is None or self.pack_id != latest["pack_id"]
            packed_snapshot: VerifiedPackSnapshot | None = None
            if ephemeral:
                packed_snapshot = self._activate(str(latest["pack_id"]))
                packed = packed_snapshot.open_store()
            else:
                packed = self.store
            assert packed is not None
            try:
                deltas = semantic_deltas(packed.conn, live.conn)
            finally:
                if packed_snapshot is not None:
                    packed.close()
                    packed_snapshot.close()
            result.update(**deltas, note=None)
            return result
        finally:
            live.conn.rollback()

    def _provenance(self) -> dict[str, Any]:
        """Pack identity attached to every query response, so a caller can
        always say WHICH immutable pack produced an answer."""
        payload: dict[str, Any] = {
            "pack_id": self.pack_id, "content_hash": self.pack_hash,
        }
        if self._snapshot is not None:
            manifest = self._snapshot.manifest
            payload["pack_schema_version"] = manifest.get("pack_schema_version", 1)
            payload["integrity_level"] = self._snapshot.integrity_level
            payload["evidence_mode"] = manifest.get("evidence_mode")
        return payload

    def _method_reader(self) -> MethodPackReader:
        store = self._require_store()
        assert self.pack_id is not None
        assert self.pack_hash is not None
        # Method tools keep serving snapshot rows, but refuse if the published
        # source directory is gone or its methodology claim drifted.
        published = self._activate(self.pack_id)
        try:
            if published.content_hash != self.pack_hash:
                raise PackIntegrityError(
                    f"active pack {self.pack_id!r} identity changed"
                )
            methodology = published.manifest.get("methodology")
            if methodology != self._methodology:
                raise PackIntegrityError(
                    f"active pack {self.pack_id!r} manifest changed"
                )
        finally:
            published.close()
        return MethodPackReader(
            MethodPackSql(store.conn),
            pack_id=self.pack_id,
            pack_hash=self.pack_hash,
            methodology=self._methodology or {},
        )

    def list_methods(
        self,
        query: str | None = None,
        limit: int = 20,
    ) -> MethodListResult:
        return self._method_reader().list_methods(search=query, limit=limit)

    def get_method(
        self,
        method_id: str,
        version: int | None = None,
    ) -> MethodDetailResult:
        return self._method_reader().get_method(method_id, version=version)

    def trace_method(
        self,
        method_id: str,
        field_path: str | None = None,
    ) -> MethodTraceResult:
        return self._method_reader().trace_method(
            method_id,
            field_path=field_path,
        )

    def list_method_gaps(self, method_id: str) -> MethodGapsResult:
        return self._method_reader().list_method_gaps(method_id)

    def close(self) -> None:
        if self.store is not None:
            self.store.close()
            self.store = None
        if self._snapshot is not None:
            self._snapshot.close()
            self._snapshot = None
        self.pack_id = None
        self.pack_hash = None
        self._methodology = None
        if self._live_store is not None:
            self._live_store.close()
            self._live_store = None

    def _require_store(self) -> KGStore:
        if self.store is None:
            raise NoActivePack(
                "no pack loaded; call load_pack first (or start with --pack)"
            )
        return self.store

    # ------------------------------------------------------------------
    # Pack management
    # ------------------------------------------------------------------

    def list_packs(self) -> dict[str, Any]:
        packs = discover_packs(self.packs_dir)
        return {
            "packs_dir": str(self.packs_dir),
            "active_pack_id": self.pack_id,
            "packs": packs,
            "count": len(packs),
        }

    def _activate(self, pack_id: str) -> VerifiedPackSnapshot:
        safe_pack_component(pack_id, kind="pack id")
        return activate_pack(self.packs_dir / pack_id, working=self.live_store_path)

    def load_pack(self, pack_id: str) -> dict[str, Any]:
        snapshot = self._activate(pack_id)
        try:
            store = snapshot.open_store()
        except Exception:  # noqa: BROAD_EXCEPT_OK
            snapshot.close()
            raise
        try:
            counts = store.counts()
            schema = store.get_schema()
        except Exception:  # noqa: BROAD_EXCEPT_OK
            store.close()
            snapshot.close()
            raise
        if self.store is not None:
            self.store.close()
        if self._snapshot is not None:
            self._snapshot.close()
        self.store = store
        self._snapshot = snapshot
        self.pack_id = pack_id
        self.pack_hash = snapshot.content_hash
        methodology = snapshot.manifest.get("methodology")
        self._methodology = (
            dict(methodology) if isinstance(methodology, dict) else None
        )
        return {
            "pack_id": pack_id,
            "content_hash": self.pack_hash,
            "sqlite_path": str(snapshot.sqlite_path),
            "counts": counts,
            "schema": schema,
        }

    def try_autoload(self) -> str | None:
        """If exactly one pack exists, load it. Return its id or None."""
        packs = discover_packs(self.packs_dir)
        if len(packs) == 1:
            pid = packs[0]["pack_id"]
            self.load_pack(pid)
            return pid
        return None

    # ------------------------------------------------------------------
    # Read tools (verified-only by default; packs have no proposed rows)
    # ------------------------------------------------------------------

    def get_schema(
        self,
        pack_id: str | None = None,
        schema_version_id: int | None = None,
    ) -> dict[str, Any]:
        if pack_id is not None and pack_id != self.pack_id:
            safe_pack_component(pack_id, kind="pack id")
            with opened_verified_pack(
                self.packs_dir / pack_id, working=self.live_store_path
            ) as (_snapshot, store):
                return store.get_schema(schema_version_id=schema_version_id)
        return self._require_store().get_schema(schema_version_id=schema_version_id)

    def entity_lookup(
        self,
        id: str | None = None,
        name: str | None = None,
        entity_type: str | None = None,
        fuzzy: bool = True,
        include_proposed: bool = False,
        limit: int = 5,
        detail: bool = False,
    ) -> dict[str, Any]:
        store = self._require_store()
        matches = store.entity_lookup(
            id=id,
            name=name,
            entity_type=entity_type,
            fuzzy=fuzzy,
            include_proposed=include_proposed,
            limit=limit,
        )
        matches = [_with_fact_receipts(store.conn, m, "node") for m in matches]
        if not detail:
            matches = [compact_node(m) for m in matches]
        return {
            "matches": matches,
            "count": len(matches),
            "detail": detail,
            "pack": self._provenance(),
        }

    def get_entity(
        self, id: str, *, include_proposed: bool = False
    ) -> dict[str, Any]:
        """Tier-2 follow-up: the full record behind one compact row."""
        store = self._require_store()
        entity = _with_fact_receipts(
            store.conn,
            _entity_detail(store, id, include_proposed=include_proposed),
            "node",
        )
        return {"entity": entity, "pack": self._provenance()}

    def get_communities(
        self, community_id: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """W12 global view: build-time community summaries of the pack.

        Without ``community_id``: the community list (largest first) —
        enough to answer "what is this corpus about". With it: that
        community's row plus its full member list for drill-down.
        """
        store = self._require_store()
        if community_id is None:
            communities = store.list_communities(limit=limit)
            members: list[dict[str, Any]] = []
        else:
            communities = [
                c for c in store.list_communities(limit=1000)
                if c["id"] == community_id
            ]
            members = store.community_members(community_id)
        return {
            "communities": communities,
            "members": members,
            "count": len(communities),
            "pack": self._provenance(),
        }

    # ------------------------------------------------------------------
    # Resources (pack://... addressing; read-only, JSON payloads)
    # ------------------------------------------------------------------

    def _store_for(self, pack_id: str):
        """(store, snapshot) for the named pack — active store when it
        matches, else a verified snapshot the caller must close."""
        if pack_id == self.pack_id and self.store is not None:
            return self.store, None
        snapshot = self._activate(pack_id)
        try:
            return snapshot.open_store(), snapshot
        except Exception:  # noqa: BROAD_EXCEPT_OK
            snapshot.close()
            raise

    def resource_manifest(self, pack_id: str) -> dict[str, Any]:
        if pack_id == self.pack_id and self._snapshot is not None:
            return dict(self._snapshot.manifest)
        safe_pack_component(pack_id, kind="pack id")
        return inspect_verified_manifest(
            self.packs_dir / pack_id, working=self.live_store_path
        )

    def resource_schema(self, pack_id: str) -> dict[str, Any]:
        store, snapshot = self._store_for(pack_id)
        try:
            return store.get_schema()
        finally:
            if snapshot is not None:
                store.close()
                snapshot.close()

    def resource_entity(self, pack_id: str, entity_id: str) -> dict[str, Any]:
        store, snapshot = self._store_for(pack_id)
        try:
            return _entity_detail(store, entity_id, include_proposed=False)
        finally:
            if snapshot is not None:
                store.close()
                snapshot.close()

    def resource_term(self, pack_id: str, term_id: str) -> dict[str, Any]:
        store, snapshot = self._store_for(pack_id)
        try:
            return _ontology_term_detail(store, term_id)
        finally:
            if snapshot is not None:
                store.close()
                snapshot.close()

    def resource_xref(self, pack_id: str, xref_id: str) -> dict[str, Any]:
        store, snapshot = self._store_for(pack_id)
        try:
            return _term_xref_detail(store, xref_id)
        finally:
            if snapshot is not None:
                store.close()
                snapshot.close()

    def resource_method(
        self,
        pack_id: str,
        method_id: str,
    ) -> MethodDetailResult:
        if pack_id != self.pack_id:
            raise ValueError(
                "Method resources only serve the active physical pack"
            )
        return self._method_reader().get_method(method_id)

    def resource_method_trace(
        self,
        pack_id: str,
        method_id: str,
        field_path: str,
    ) -> MethodTraceResult:
        from urllib.parse import unquote

        if pack_id != self.pack_id:
            raise ValueError(
                "Method resources only serve the active physical pack"
            )
        return self._method_reader().trace_method(
            method_id,
            field_path=unquote(field_path),
        )

    def _active_reranker(self):
        """Second-stage reranker, resolved once per server, cached-only.

        `auto` never downloads (HF_HUB_OFFLINE during load): an MCP query
        must not be the thing that opens a network connection. No cached
        model → None → results keep their RRF order.
        """
        if not hasattr(self, "_reranker_resolved"):
            from ontologylab.rerankers import get_reranker

            self._reranker_resolved = get_reranker("auto")
        return self._reranker_resolved

    def _active_embedder(self):
        """The session embedder, but only when the ACTIVE pack was embedded
        by the same model — a model-A pack is never scored with model-B."""
        if self.embedder is None or self.store is None:
            return None
        if self.store.embedding_model() != self.embedder.name():
            return None
        return self.embedder

    def _run_search(
        self,
        fts_query: str,
        *,
        top_k: int,
        entity_type: str | None,
        min_score: float,
        include_proposed: bool,
    ) -> tuple[list[dict[str, Any]], str]:
        """Route to hybrid (BM25+vector RRF) when embeddings line up, else
        plain lexical; returns (results, tier_label) with honest labeling."""
        store = self._require_store()
        embedder = self._active_embedder()
        if embedder is not None:
            results = store.hybrid_search(
                fts_query,
                embedder,
                top_k=top_k,
                entity_type=entity_type,
                min_score=min_score,
                include_proposed=include_proposed,
                reranker=self._active_reranker(),
            )
            return results, "fts5+vec-rrf"
        results = store.semantic_search(
            fts_query,
            top_k=top_k,
            entity_type=entity_type,
            min_score=min_score,
            include_proposed=include_proposed,
        )
        return results, "fts5"

    def semantic_search(
        self,
        query: str,
        entity_type: str | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
        include_proposed: bool = False,
        detail: bool = False,
    ) -> dict[str, Any]:
        """Lexical FTS5 search, or BM25+vector RRF when the active pack
        carries embeddings from the server's configured embedder."""
        results, tier = self._run_search(
            query,
            top_k=top_k,
            entity_type=entity_type,
            min_score=min_score,
            include_proposed=include_proposed,
        )
        store = self._require_store()
        results = [_with_fact_receipts(store.conn, r, "node") for r in results]
        if not detail:
            results = [compact_node(r) for r in results]
        return {
            "query": query,
            "search_tier": tier,
            "expansion_terms": [],
            "expansion_error": None,
            "results": results,
            "count": len(results),
            "detail": detail,
            "pack": self._provenance(),
        }

    async def semantic_search_expanded(
        self,
        query: str,
        *,
        engine_name: str | None = None,
        model: str | None = None,
        top_k: int = 10,
        entity_type: str | None = None,
        min_score: float = 0.0,
        include_proposed: bool = False,
        detail: bool = False,
    ) -> dict[str, Any]:
        """Search with optional fail-open LLM query expansion.

        When ``engine_name`` is set, an LLM proposes lexical query variants;
        any expansion failure fails open to the plain query. When the active
        pack's embeddings line up with the server's embedder this becomes
        the 3-signal hybrid — plain lexical + expanded lexical + vector on
        the ORIGINAL query (variants never pollute the embedding) — fused
        with RRF. Otherwise plain lexical FTS5 on the expanded query.
        ``search_tier`` composes honestly: ``+vec-rrf`` only when the
        vector leg ran, ``+llm-expansion`` only when a variant was used.
        """
        store = self._require_store()
        variants: list[str] = []
        expansion_error: str | None = None
        if engine_name:
            try:
                engine = resolve_engine(engine_name, model=model)
            except EngineError as exc:
                expansion_error = str(exc)
            else:
                variants, usage = await expand_query(query, engine, model=model)
                expansion_error = usage.get("error")
        expanded_query = " ".join([query, *variants]) if variants else query
        embedder = self._active_embedder()
        if embedder is not None:
            # 세 번째 신호는 변형들"만" — 원 쿼리를 다시 섞으면 plain
            # lexical과 강하게 상관된 리스트가 되어 lexical에 2배 가중치를
            # 주는 꼴이 된다 (독립 신호 원칙)
            results = store.hybrid_search(
                query,
                embedder,
                top_k=top_k,
                entity_type=entity_type,
                min_score=min_score,
                include_proposed=include_proposed,
                extra_lexical_queries=[" ".join(variants)] if variants else None,
                reranker=self._active_reranker(),
            )
            tier = "fts5+vec-rrf"
        else:
            results = store.semantic_search(
                expanded_query,
                top_k=top_k,
                entity_type=entity_type,
                min_score=min_score,
                include_proposed=include_proposed,
            )
            tier = "fts5"
        if variants:
            tier += "+llm-expansion"
        if not detail:
            results = [compact_node(r) for r in results]
        return {
            "query": query,
            "search_tier": tier,
            "expansion_terms": variants,
            "expansion_error": expansion_error,
            "results": results,
            "count": len(results),
            "detail": detail,
            "pack": self._provenance(),
        }

    def graph_query(
        self,
        entity_type: str | None = None,
        relation_type: str | None = None,
        property_filters: dict[str, Any] | None = None,
        include_proposed: bool = False,
        limit: int = 100,
        offset: int = 0,
        detail: bool = False,
    ) -> dict[str, Any]:
        store = self._require_store()
        result = store.graph_query(
            entity_type=entity_type,
            relation_type=relation_type,
            property_filters=property_filters,
            include_proposed=include_proposed,
            limit=limit,
            offset=offset,
        )
        result["nodes"] = [_with_fact_receipts(store.conn, n, "node") for n in result["nodes"]]
        result["edges"] = [_with_fact_receipts(store.conn, e, "edge") for e in result["edges"]]
        if not detail:
            result["nodes"] = [compact_node(n) for n in result["nodes"]]
            result["edges"] = [compact_edge(e) for e in result["edges"]]
        result["detail"] = detail
        result["pack"] = self._provenance()
        return result

    def traverse_relations(
        self,
        start_ids: list[str],
        relation_types: list[str] | None = None,
        direction: str = "both",
        max_hops: int = 2,
        include_proposed: bool = False,
        limit: int = 200,
        detail: bool = False,
    ) -> dict[str, Any]:
        store = self._require_store()
        result = store.traverse_relations(
            start_ids,
            relation_types=relation_types,
            direction=direction,
            max_hops=max_hops,
            include_proposed=include_proposed,
            limit=limit,
        )
        result["nodes"] = [_with_fact_receipts(store.conn, n, "node") for n in result["nodes"]]
        result["edges"] = [_with_fact_receipts(store.conn, e, "edge") for e in result["edges"]]
        if not detail:
            result["nodes"] = [compact_node(n) for n in result["nodes"]]
            result["edges"] = [compact_edge(e) for e in result["edges"]]
        result["detail"] = detail
        result["pack"] = self._provenance()
        return result

    def find_path(
        self,
        source_id: str,
        target_id: str,
        max_hops: int = 6,
        relation_types: list[str] | None = None,
        include_proposed: bool = False,
    ) -> dict[str, Any]:
        result = self._require_store().find_path(
            source_id,
            target_id,
            max_hops=max_hops,
            relation_types=relation_types,
            include_proposed=include_proposed,
        )
        result["pack"] = self._provenance()
        return result

    def document_raw_text(self, representation_id: str) -> dict[str, Any]:
        """Return FULL evidence bytes from the process-owned pack snapshot."""
        if self._snapshot is None:
            raise NoActivePack(
                "no pack loaded; call load_pack first (or start with --pack)"
            )
        evidence = resolve_pack_evidence(
            self._snapshot.sqlite_path.parent,
            self._require_store().conn,
            representation_id,
        )
        return {
            "representation_id": evidence.representation_id,
            "evidence_mode": evidence.evidence_mode,
            "available": evidence.available,
            "text": evidence.text,
            "limitation": evidence.limitation,
            "path": evidence.path,
            "pack": self._provenance(),
        }


# ---------------------------------------------------------------------------
# Structured tool result envelopes. FastMCP derives each tool's outputSchema
# from these TypedDicts, so MCP clients know result shapes ahead of time.
# Inner node/edge dicts stay dynamic (dict[str, Any]) — only the stable
# envelope is typed, so schemas inform without over-constraining.
# ---------------------------------------------------------------------------


class PackProvenance(TypedDict, total=False):
    """Which immutable pack produced a response."""

    pack_id: str | None
    content_hash: str | None
    pack_schema_version: int
    integrity_level: str
    evidence_mode: str | None


class PackListResult(TypedDict):
    packs_dir: str
    active_pack_id: str | None
    packs: list[dict[str, Any]]
    count: int


class LoadPackResult(TypedDict):
    pack_id: str
    content_hash: str | None
    sqlite_path: str
    counts: dict[str, int]
    schema: dict[str, Any]


class LookupResult(TypedDict):
    matches: list[dict[str, Any]]
    count: int
    detail: bool
    pack: PackProvenance


class EntityDetailResult(TypedDict):
    """Full record for one entity (tier-2 follow-up to compact rows)."""

    entity: dict[str, Any]
    pack: PackProvenance


class CommunitiesResult(TypedDict):
    """Build-time community summaries; members filled when one is named."""

    communities: list[dict[str, Any]]
    members: list[dict[str, Any]]
    count: int
    pack: PackProvenance


class SearchResult(TypedDict):
    """Uniform search envelope: expansion fields are always present
    (empty/None when expansion was not used) so the outputSchema is exact."""

    query: str
    search_tier: str
    expansion_terms: list[str]
    expansion_error: str | None
    results: list[dict[str, Any]]
    count: int
    detail: bool
    pack: PackProvenance


class SubgraphResult(TypedDict):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    detail: bool
    pack: PackProvenance


class PathResult(TypedDict):
    found: bool
    hop_count: int | None
    path: list[dict[str, Any]]
    path_edges: list[dict[str, Any]]
    pack: PackProvenance


def build_mcp_app(session: PackSession) -> Any:
    """Wire ``PackSession`` onto the bounded local MCP stdio registry."""
    mcp = McpApp("ontologylab")

    @mcp.tool()
    def list_packs() -> PackListResult:
        """Discover local knowledge packs (directory + manifest.json scan)."""
        return session.list_packs()

    @mcp.tool()
    def get_staleness() -> dict[str, Any]:
        """Compare the latest pack's semantic fact baseline with current
        verified truth. Additions, invalidations, and same-id replacements are
        authoritative; pending_verified_count is backward-compatible advisory."""
        return session.get_staleness()

    @mcp.tool()
    def load_pack(pack_id: str) -> LoadPackResult:
        """Set/switch the active pack (read-only connection; never mutates KG)."""
        return session.load_pack(pack_id)

    @mcp.tool()
    def get_schema(
        pack_id: str | None = None, schema_version_id: int | None = None
    ) -> dict[str, Any]:
        """Return ontology (entity/relation types) for the active or named pack.
        Pass schema_version_id to resolve one historical version the pack
        carries — multi-schema packs preserve facts judged under each version;
        an unknown id is a typed lookup error, never a silent active fallback."""
        return session.get_schema(
            pack_id=pack_id, schema_version_id=schema_version_id
        )

    @mcp.tool()
    def entity_lookup(
        id: str | None = None,
        name: str | None = None,
        entity_type: str | None = None,
        fuzzy: bool = True,
        include_proposed: bool = False,
        limit: int = 5,
        detail: bool = False,
    ) -> LookupResult:
        """Resolve a node by id or name. Defaults to verified-only rows and
        COMPACT matches (id/name/type/score/snippet); pass detail=true or
        follow up with get_entity(id) for full records."""
        return session.entity_lookup(
            id=id,
            name=name,
            entity_type=entity_type,
            fuzzy=fuzzy,
            include_proposed=include_proposed,
            limit=limit,
            detail=detail,
        )

    @mcp.tool()
    def get_communities(
        community_id: str | None = None, limit: int = 20
    ) -> CommunitiesResult:
        """Corpus-level view of the pack: communities detected at build time
        with per-community summaries (largest first). Use for "what are the
        main themes?" questions BFS tools can't answer; pass community_id to
        drill into one community's members."""
        return session.get_communities(community_id=community_id, limit=limit)

    @mcp.tool()
    def get_entity(id: str, include_proposed: bool = False) -> EntityDetailResult:
        """Full record for one entity id: aliases, properties, source-span
        citations, and adjacent edges with endpoint names. The detail
        follow-up for compact search/lookup rows; the same payload is
        addressable as the resource pack://{pack_id}/entity/{id}."""
        return session.get_entity(id, include_proposed=include_proposed)

    @mcp.tool()
    async def semantic_search(
        query: str,
        entity_type: str | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
        include_proposed: bool = False,
        expand: bool = False,
        detail: bool = False,
    ) -> SearchResult:
        """FTS5/BM25 search over node names/aliases/properties (0..1
        match_score). With expand=True, an LLM adds lexical query variants
        (fail-open; requires --expansion-engine at server start). Vector
        search joins the RRF fusion ONLY when the server was started with
        --embedder AND the active pack carries matching embeddings — the
        search_tier field in every response states which signals actually
        ran. Results are COMPACT rows (id/name/type/score/snippet) unless
        detail=true; use get_entity(id) for one full record."""
        if not expand:
            return session.semantic_search(
                query,
                entity_type=entity_type,
                top_k=top_k,
                min_score=min_score,
                include_proposed=include_proposed,
                detail=detail,
            )
        result = await session.semantic_search_expanded(
            query,
            engine_name=session.expansion_engine,
            model=session.expansion_model,
            top_k=top_k,
            entity_type=entity_type,
            min_score=min_score,
            include_proposed=include_proposed,
            detail=detail,
        )
        if session.expansion_engine is None:
            result["expansion_error"] = (
                "no expansion engine configured (start with --expansion-engine)"
            )
        return result

    @mcp.tool()
    def graph_query(
        entity_type: str | None = None,
        relation_type: str | None = None,
        property_filters: dict | None = None,
        include_proposed: bool = False,
        limit: int = 100,
        offset: int = 0,
        detail: bool = False,
    ) -> SubgraphResult:
        """Filtered subgraph query over the active pack. Compact rows by
        default; detail=true for full node/edge records."""
        return session.graph_query(
            entity_type=entity_type,
            relation_type=relation_type,
            property_filters=property_filters,
            include_proposed=include_proposed,
            limit=limit,
            offset=offset,
            detail=detail,
        )

    @mcp.tool()
    def traverse_relations(
        start_ids: list[str],
        relation_types: list[str] | None = None,
        direction: str = "both",
        max_hops: int = 2,
        include_proposed: bool = False,
        limit: int = 200,
        detail: bool = False,
    ) -> SubgraphResult:
        """N-hop neighborhood from seed node ids (BFS). Compact rows by
        default; detail=true for full node/edge records."""
        return session.traverse_relations(
            start_ids,
            relation_types=relation_types,
            direction=direction,
            max_hops=max_hops,
            include_proposed=include_proposed,
            limit=limit,
            detail=detail,
        )

    @mcp.tool()
    def find_path(
        source_id: str,
        target_id: str,
        max_hops: int = 6,
        relation_types: list[str] | None = None,
        include_proposed: bool = False,
    ) -> PathResult:
        """Shortest relation path between two nodes."""
        return session.find_path(
            source_id,
            target_id,
            max_hops=max_hops,
            relation_types=relation_types,
            include_proposed=include_proposed,
        )

    @mcp.tool()
    def list_methods(
        query: str | None = None,
        limit: int = 20,
    ) -> MethodListResult:
        """List selected immutable Methods as compact, bounded rows."""
        return session.list_methods(query=query, limit=limit)

    @mcp.tool()
    def get_method(
        method_id: str,
        version: int | None = None,
    ) -> MethodDetailResult:
        """Return one selected immutable Method and its hash-bound receipts."""
        return session.get_method(method_id, version=version)

    @mcp.tool()
    def trace_method(
        method_id: str,
        field_path: str | None = None,
    ) -> MethodTraceResult:
        """Trace exact Method source anchors, links, and accepted assumptions."""
        return session.trace_method(method_id, field_path=field_path)

    @mcp.tool()
    def list_method_gaps(method_id: str) -> MethodGapsResult:
        """List the packed open or waived gaps for one selected Method."""
        return session.list_method_gaps(method_id)

    # -- Resources: stable pack:// addresses for entities and pack metadata.
    # Read-only JSON; lets clients cite/refetch a fact by URI instead of
    # re-running a query tool.

    @mcp.resource("pack://{pack_id}/manifest")
    def pack_manifest(pack_id: str) -> str:
        """Pack manifest (identity, counts, search tier, content hash)."""
        return json.dumps(session.resource_manifest(pack_id), indent=2)

    @mcp.resource("pack://{pack_id}/schema")
    def pack_schema(pack_id: str) -> str:
        """Ontology schema (entity/relation types) of one pack."""
        return json.dumps(session.resource_schema(pack_id), indent=2)

    @mcp.resource("pack://{pack_id}/entity/{entity_id}")
    def pack_entity(pack_id: str, entity_id: str) -> str:
        """Full record of one verified entity, same payload as get_entity."""
        return json.dumps(
            session.resource_entity(pack_id, entity_id), indent=2
        )

    @mcp.resource("pack://{pack_id}/term/{term_id}")
    def pack_term(pack_id: str, term_id: str) -> str:
        """Published reviewed term with aliases and typed xref history."""
        return json.dumps(session.resource_term(pack_id, term_id), indent=2)

    @mcp.resource("pack://{pack_id}/xref/{xref_id}")
    def pack_xref(pack_id: str, xref_id: str) -> str:
        """One published typed xref; mapping predicates do not merge identity."""
        return json.dumps(session.resource_xref(pack_id, xref_id), indent=2)

    @mcp.resource("pack://{pack_id}/method/{method_id}")
    def pack_method(pack_id: str, method_id: str) -> str:
        """One selected immutable Method plus release/publication receipts."""
        return json.dumps(
            session.resource_method(pack_id, method_id),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @mcp.resource(
        "pack://{pack_id}/method/{method_id}/trace/{field_path}"
    )
    def pack_method_trace(
        pack_id: str,
        method_id: str,
        field_path: str,
    ) -> str:
        """One percent-encoded field path traced to immutable source rows."""
        return json.dumps(
            session.resource_method_trace(
                pack_id,
                method_id,
                field_path,
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ontologylab.mcp_server",
        description=(
            "Serve an ontologylab knowledge pack over MCP stdio "
            "(read-only tools only)."
        ),
    )
    parser.add_argument(
        "--packs-dir",
        default=str(default_packs_dir()),
        help="Directory of knowledge packs (default: ROOT/packs).",
    )
    parser.add_argument(
        "--pack",
        default=None,
        help="Optional pack_id to load at startup. If omitted and exactly one "
        "pack exists, it is auto-loaded.",
    )
    parser.add_argument(
        "--expansion-engine",
        default=None,
        type=engine_name_arg,
        metavar="ENGINE",
        help="Optional LLM engine for semantic_search query expansion "
        "(expand=True): mock|claude|codex|gemini or api:<provider-id>. "
        "Default: none (plain lexical search only).",
    )
    parser.add_argument(
        "--expansion-model",
        default=None,
        help="Optional model name for the expansion engine.",
    )
    parser.add_argument(
        "--live-store",
        default=None,
        metavar="KG_SQLITE",
        help=(
            "Path to the working kg.sqlite, opened read-only. Enables "
            "get_staleness to compute semantic deltas and the advisory "
            "pending count; without it they are unavailable, never zero."
        ),
    )
    parser.add_argument(
        "--embedder",
        default=None,
        help="Enable BM25+vector RRF search for packs that carry matching "
             "embeddings: 'auto' (real MiniLM when sentence-transformers is "
             "installed, else hash), 'hash' (offline test embedder), or a "
             "sentence-transformers model name. Default: lexical only.",
    )
    args = parser.parse_args(argv)

    embedder = None
    if args.embedder:
        from ontologylab.embeddings import get_embedder

        try:
            embedder = get_embedder(args.embedder)
        except Exception as exc:  # noqa: BLE001 — 다운로드/임포트 실패 등
            # sentence-transformers 초기화는 첫 실행 시 모델 다운로드까지
            # 시도하므로 RuntimeError 외에 OSError/HFHub 계열도 나온다 —
            # 어떤 실패든 raw traceback 대신 깔끔히 종료한다.
            print(f"[ontologylab.mcp] embedder unavailable: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    session = PackSession(
        args.packs_dir,
        expansion_engine=args.expansion_engine,
        expansion_model=args.expansion_model,
        embedder=embedder,
        live_store_path=args.live_store,
    )
    if args.pack:
        try:
            session.load_pack(args.pack)
        except Exception as exc:
            print(f"[ontologylab.mcp] failed to load pack {args.pack!r}: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    else:
        auto = session.try_autoload()
        if auto:
            print(f"[ontologylab.mcp] auto-loaded pack {auto}", file=sys.stderr)

    mcp = build_mcp_app(session)
    try:
        mcp.run(transport="stdio")
    finally:
        session.close()


if __name__ == "__main__":
    main()
