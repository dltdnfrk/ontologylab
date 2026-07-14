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
from ontologylab.engines import EngineError, get_engine
from ontologylab.expansion import expand_query
from ontologylab.packbuilder import list_packs as discover_packs, pack_sqlite_path
from ontologylab.paths import default_packs_dir


class NoActivePack(Exception):
    """Raised when a query tool is called before any pack is loaded."""


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
    ) -> dict[str, Any]:
        matches = self._require_store().entity_lookup(
            id=id,
            name=name,
            entity_type=entity_type,
            fuzzy=fuzzy,
            include_proposed=include_proposed,
            limit=limit,
        )
        return {"matches": matches, "count": len(matches), "pack": self._provenance()}

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
        return {
            "query": query,
            "search_tier": tier,
            "expansion_terms": [],
            "expansion_error": None,
            "results": results,
            "count": len(results),
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
        return {
            "query": query,
            "search_tier": tier,
            "expansion_terms": variants,
            "expansion_error": expansion_error,
            "results": results,
            "count": len(results),
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
    ) -> dict[str, Any]:
        result = self._require_store().graph_query(
            entity_type=entity_type,
            relation_type=relation_type,
            property_filters=property_filters,
            include_proposed=include_proposed,
            limit=limit,
            offset=offset,
        )
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
    ) -> dict[str, Any]:
        result = self._require_store().traverse_relations(
            start_ids,
            relation_types=relation_types,
            direction=direction,
            max_hops=max_hops,
            include_proposed=include_proposed,
            limit=limit,
        )
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
    pack: PackProvenance


class SubgraphResult(TypedDict):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
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
    ) -> LookupResult:
        """Resolve a node by id or name. Defaults to verified-only rows."""
        return session.entity_lookup(
            id=id,
            name=name,
            entity_type=entity_type,
            fuzzy=fuzzy,
            include_proposed=include_proposed,
            limit=limit,
        )

    @mcp.tool()
    async def semantic_search(
        query: str,
        entity_type: str | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
        include_proposed: bool = False,
        expand: bool = False,
    ) -> SearchResult:
        """Lexical FTS5/BM25 search over node names/aliases/properties (0..1
        match_score). With expand=True, an LLM adds lexical query variants
        (fail-open; requires --expansion-engine at server start). NOT vector
        search — no embeddings are involved."""
        if not expand:
            return session.semantic_search(
                query,
                entity_type=entity_type,
                top_k=top_k,
                min_score=min_score,
                include_proposed=include_proposed,
            )
        result = await session.semantic_search_expanded(
            query,
            engine_name=session.expansion_engine,
            model=session.expansion_model,
            top_k=top_k,
            entity_type=entity_type,
            min_score=min_score,
            include_proposed=include_proposed,
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
    ) -> SubgraphResult:
        """Filtered subgraph query over the active pack."""
        return session.graph_query(
            entity_type=entity_type,
            relation_type=relation_type,
            property_filters=property_filters,
            include_proposed=include_proposed,
            limit=limit,
            offset=offset,
        )

    @mcp.tool()
    def traverse_relations(
        start_ids: list[str],
        relation_types: list[str] | None = None,
        direction: str = "both",
        max_hops: int = 2,
        include_proposed: bool = False,
        limit: int = 200,
    ) -> SubgraphResult:
        """N-hop neighborhood from seed node ids (BFS)."""
        return session.traverse_relations(
            start_ids,
            relation_types=relation_types,
            direction=direction,
            max_hops=max_hops,
            include_proposed=include_proposed,
            limit=limit,
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
        choices=["mock", "claude", "codex", "gemini"],
        help="Optional LLM engine for semantic_search query expansion "
        "(expand=True). Default: none (plain lexical search only).",
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
