"""Local MCP stdio server for ontologylab knowledge packs.

Exposes eight read-only tools against one active immutable pack
(``pack.sqlite`` opened ``file:...?mode=ro&immutable=1``). The only tool
that mutates anything is ``load_pack``, and it only updates in-memory
session state (which file is open) — never KG rows.

Tool logic lives on ``PackSession`` so it is unit-testable without the
``mcp`` SDK. ``FastMCP`` is only required when running the stdio process.
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
from ontologylab.engines import EngineError, engine_name_arg, get_engine
from ontologylab.expansion import expand_query
from ontologylab.packbuilder import list_packs as discover_packs, pack_sqlite_path
from ontologylab.paths import default_packs_dir


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


def _node_snippet(item: dict[str, Any]) -> str:
    """One short line summarizing aliases + properties for a compact row."""
    parts: list[str] = []
    aliases = item.get("aliases") or []
    if aliases:
        parts.append("aka " + ", ".join(str(a) for a in aliases[:3]))
    properties = item.get("properties") or {}
    if properties:
        parts.append(
            "; ".join(f"{k}={properties[k]}" for k in list(properties)[:3])
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
    return out


def compact_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": edge["id"],
        "relation_type": edge["relation_type"],
        "source_id": edge["source_id"],
        "target_id": edge["target_id"],
        "status": edge["status"],
        "source_doc_id": edge.get("source_doc_id"),
    }


def _entity_detail(store: KGStore, entity_id: str, *, include_proposed: bool) -> dict[str, Any]:
    """Full record for one entity: node fields + citations + adjacent edges
    (endpoint names resolved). Shared by the get_entity tool and the
    pack://.../entity/{id} resource."""
    matches = store.entity_lookup(
        id=entity_id, fuzzy=False, include_proposed=include_proposed, limit=1
    )
    if not matches:
        raise KGStoreError(f"no visible entity with id {entity_id!r}")
    entity = matches[0]
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
    ) -> None:
        self.packs_dir = Path(packs_dir)
        self.store: KGStore | None = None
        self.pack_id: str | None = None
        self.pack_hash: str | None = None
        self.expansion_engine = expansion_engine
        self.expansion_model = expansion_model
        self.embedder = embedder

    def _provenance(self) -> dict[str, Any]:
        """Pack identity attached to every query response, so a caller can
        always say WHICH immutable pack produced an answer."""
        return {"pack_id": self.pack_id, "content_hash": self.pack_hash}

    def close(self) -> None:
        if self.store is not None:
            self.store.close()
            self.store = None
            self.pack_id = None

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

    def load_pack(self, pack_id: str) -> dict[str, Any]:
        sqlite_path = pack_sqlite_path(self.packs_dir, pack_id)
        if self.store is not None:
            self.store.close()
            self.store = None
            self.pack_id = None
            self.pack_hash = None
        store = KGStore.open(sqlite_path, read_only=True)
        self.store = store
        self.pack_id = pack_id
        self.pack_hash = None
        manifest_path = sqlite_path.parent / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.pack_hash = manifest.get("content_hash")
        except (OSError, json.JSONDecodeError):
            pass  # provenance degrades to pack_id-only, never blocks loading
        counts = store.counts()
        return {
            "pack_id": pack_id,
            "content_hash": self.pack_hash,
            "sqlite_path": str(sqlite_path),
            "counts": counts,
            "schema": store.get_schema(),
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

    def get_schema(self, pack_id: str | None = None) -> dict[str, Any]:
        if pack_id is not None and pack_id != self.pack_id:
            # Ephemeral open for a non-active pack; does not switch session.
            path = pack_sqlite_path(self.packs_dir, pack_id)
            store = KGStore.open(path, read_only=True)
            try:
                return store.get_schema()
            finally:
                store.close()
        return self._require_store().get_schema()

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
        matches = self._require_store().entity_lookup(
            id=id,
            name=name,
            entity_type=entity_type,
            fuzzy=fuzzy,
            include_proposed=include_proposed,
            limit=limit,
        )
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
        entity = _entity_detail(
            self._require_store(), id, include_proposed=include_proposed
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
        """(store, ephemeral) for the named pack — active store when it
        matches, else a read-only ephemeral open that the caller closes."""
        if pack_id == self.pack_id and self.store is not None:
            return self.store, False
        path = pack_sqlite_path(self.packs_dir, pack_id)
        return KGStore.open(path, read_only=True), True

    def resource_manifest(self, pack_id: str) -> dict[str, Any]:
        manifest_path = self.packs_dir / pack_id / "manifest.json"
        if not manifest_path.is_file():
            raise KGStoreError(f"pack {pack_id!r} has no manifest")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def resource_schema(self, pack_id: str) -> dict[str, Any]:
        store, ephemeral = self._store_for(pack_id)
        try:
            return store.get_schema()
        finally:
            if ephemeral:
                store.close()

    def resource_entity(self, pack_id: str, entity_id: str) -> dict[str, Any]:
        store, ephemeral = self._store_for(pack_id)
        try:
            return _entity_detail(store, entity_id, include_proposed=False)
        finally:
            if ephemeral:
                store.close()

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
        """Lexical FTS5 search with optional fail-open LLM query expansion.

        When ``engine_name`` is set, an LLM proposes lexical query variants
        that are OR-composed into the same FTS5 MATCH; any expansion failure
        fails open to the plain lexical query. The ``search_tier`` label is
        ``"fts5+llm-expansion"`` ONLY when at least one variant was actually
        used, ``"fts5"`` otherwise. Never vector search.
        """
        store = self._require_store()
        variants: list[str] = []
        expansion_error: str | None = None
        if engine_name:
            try:
                engine = get_engine(engine_name, model)
            except EngineError as exc:
                expansion_error = str(exc)
            else:
                variants, usage = await expand_query(query, engine, model=model)
                expansion_error = usage.get("error")
        fts_query = " ".join([query, *variants]) if variants else query
        results, tier = self._run_search(
            fts_query,
            top_k=top_k,
            entity_type=entity_type,
            min_score=min_score,
            include_proposed=include_proposed,
        )
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
        result = self._require_store().graph_query(
            entity_type=entity_type,
            relation_type=relation_type,
            property_filters=property_filters,
            include_proposed=include_proposed,
            limit=limit,
            offset=offset,
        )
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
        result = self._require_store().traverse_relations(
            start_ids,
            relation_types=relation_types,
            direction=direction,
            max_hops=max_hops,
            include_proposed=include_proposed,
            limit=limit,
        )
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


# ---------------------------------------------------------------------------
# Structured tool result envelopes. FastMCP derives each tool's outputSchema
# from these TypedDicts, so MCP clients know result shapes ahead of time.
# Inner node/edge dicts stay dynamic (dict[str, Any]) — only the stable
# envelope is typed, so schemas inform without over-constraining.
# ---------------------------------------------------------------------------


class PackProvenance(TypedDict):
    """Which immutable pack produced a response (id + content hash)."""

    pack_id: str | None
    content_hash: str | None


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
    """Wire ``PackSession`` methods onto a FastMCP app (requires ``mcp``)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "mcp package not installed; pip install 'ontologylab[mcp]'"
        ) from exc

    mcp = FastMCP("ontologylab")

    @mcp.tool()
    def list_packs() -> PackListResult:
        """Discover local knowledge packs (directory + manifest.json scan)."""
        return session.list_packs()

    @mcp.tool()
    def load_pack(pack_id: str) -> LoadPackResult:
        """Set/switch the active pack (read-only connection; never mutates KG)."""
        return session.load_pack(pack_id)

    @mcp.tool()
    def get_schema(pack_id: str | None = None) -> dict[str, Any]:
        """Return ontology (entity/relation types) for the active or named pack."""
        return session.get_schema(pack_id=pack_id)

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
        """Lexical FTS5/BM25 search over node names/aliases/properties (0..1
        match_score). With expand=True, an LLM adds lexical query variants
        (fail-open; requires --expansion-engine at server start). NOT vector
        search — no embeddings are involved. Results are COMPACT rows
        (id/name/type/score/snippet) unless detail=true; use get_entity(id)
        for one full record."""
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
        "--embedder",
        default=None,
        help="Enable BM25+vector RRF search for packs that carry matching "
             "embeddings: 'hash' (offline test embedder) or a "
             "sentence-transformers model name. Default: lexical only.",
    )
    args = parser.parse_args(argv)

    embedder = None
    if args.embedder:
        from ontologylab.embeddings import get_embedder

        try:
            embedder = get_embedder(args.embedder)
        except RuntimeError as exc:
            print(f"[ontologylab.mcp] embedder unavailable: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    session = PackSession(
        args.packs_dir,
        expansion_engine=args.expansion_engine,
        expansion_model=args.expansion_model,
        embedder=embedder,
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
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
