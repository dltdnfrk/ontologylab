"""Verified-only reads and the shared query surface.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ontologylab.kgstore_base import (
    KGStoreError,
    MATCH_SCORE_PRECISION,
    UnknownItem,
    _edge_dict,
    _node_dict,
    _status_clause,
    normalize_name,
    span_excerpt,
)

class QueryMixin:

    # ------------------------------------------------------------------
    # Verified-only reads (pack build + ground-truth queries)
    # ------------------------------------------------------------------

    def verified_subgraph(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return (nodes, edges) with status='verified' only; an edge is
        included only when both endpoints are in the verified node set."""
        nodes = [
            _node_dict(r)
            for r in self.conn.execute("SELECT * FROM nodes WHERE status = 'verified'")
        ]
        edges = [
            _edge_dict(r)
            for r in self.conn.execute(
                "SELECT e.* FROM edges e "
                "JOIN nodes s ON s.id = e.src_node_id AND s.status = 'verified' "
                "JOIN nodes d ON d.id = e.dst_node_id AND d.status = 'verified' "
                f"WHERE e.status = 'verified' AND {self._edge_current_sql('e')}"
            )
        ]
        return nodes, edges

    # ------------------------------------------------------------------
    # Query surface (shared by dashboard, CLI, and the MCP server)
    # ------------------------------------------------------------------

    def entity_lookup(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        entity_type: str | None = None,
        fuzzy: bool = True,
        include_proposed: bool = False,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Resolve a node by id or by (normalized/alias/fuzzy) name."""
        status_sql = _status_clause(include_proposed)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(row: sqlite3.Row, score: float) -> None:
            if row["id"] in seen:
                return
            seen.add(row["id"])
            item = _node_dict(row)
            item["match_score"] = round(score, MATCH_SCORE_PRECISION)
            item["source_document_ids"] = sorted(
                {c["source_doc_id"] for c in self.citations("node", row["id"])}
                or {row["source_doc_id"]}
            )
            results.append(item)

        if id is not None:
            cur = self.conn.execute(
                f"SELECT * FROM nodes WHERE id = ? AND {status_sql}", (id,)
            )
            row = cur.fetchone()
            if row is not None:
                add(row, 1.0)
            return results[:limit]

        if name is None:
            raise KGStoreError("entity_lookup requires id or name")

        key = normalize_name(name)
        type_sql, type_args = self._type_filter_sql(entity_type, "entity_type")

        cur = self.conn.execute(
            f"SELECT * FROM nodes WHERE normalized_name = ? AND {status_sql}{type_sql}",
            [key, *type_args],
        )
        for row in cur.fetchall():
            add(row, 1.0)

        aliased_type_sql, _ = self._type_filter_sql(entity_type, "n.entity_type")
        cur = self.conn.execute(
            "SELECT n.* FROM node_aliases a JOIN nodes n ON n.id = a.node_id "
            f"WHERE a.normalized_alias = ? AND {_status_clause(include_proposed, 'n')}"
            f"{aliased_type_sql}",
            [key, *type_args],
        )
        for row in cur.fetchall():
            add(row, 0.95)

        if fuzzy and len(results) < limit:
            for item in self.semantic_search(
                name,
                top_k=limit,
                entity_type=entity_type,
                include_proposed=include_proposed,
            ):
                if item["id"] not in seen:
                    seen.add(item["id"])
                    results.append(item)
        return results[:limit]

    def provenance(self, kind: str, item_id: str) -> dict[str, Any]:
        """Everything known about where one node or edge came from.

        The columns have been carried since the first schema — extractor
        engine and model, prompt version, the source document and span, who
        approved it and when — and none of them left the database. The
        review screen showed the evidence excerpt and nothing else, so the
        question this tool exists to answer ("why does the graph believe
        this?") could only be answered by opening sqlite.

        Returned as one record rather than assembled by the caller, because
        a lineage split across three requests is a lineage nobody reads.
        """
        if kind not in ("node", "edge"):
            raise KGStoreError(f"unknown kind {kind!r}: expected node or edge")
        table = "nodes" if kind == "node" else "edges"
        row = self.conn.execute(
            f"SELECT * FROM {table} WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise UnknownItem(f"unknown {kind} id {item_id!r}")

        keys = row.keys()
        record: dict[str, Any] = {
            "kind": kind,
            "id": row["id"],
            "status": row["status"],
            "confidence": row["confidence"],
            "extraction": {
                "engine": row["extractor_engine"],
                "model": row["extractor_model"] if "extractor_model" in keys else None,
                "prompt_version": row["prompt_version"] if "prompt_version" in keys else None,
                "created_ts": row["created_ts"],
            },
            "review": {
                "verified_by": row["verified_by"] if "verified_by" in keys else None,
                "verified_ts": row["verified_ts"] if "verified_ts" in keys else None,
                "note": row["review_note"] if "review_note" in keys else None,
            },
        }
        record["label"] = (
            row["name"] if kind == "node" else row["relation_type"]
        )
        if kind == "edge":
            record["qualifiers"] = (
                json.loads(row["qualifiers_json"])
                if "qualifiers_json" in keys and row["qualifiers_json"]
                else {}
            )

        # The document is the anchor of the whole claim; without its title
        # and URI the engine/model line is trivia.
        doc_row = self.conn.execute(
            "SELECT id, title, source_uri, source_kind, fetched_ts "
            "FROM documents WHERE id = ?",
            (row["source_doc_id"],),
        ).fetchone()
        record["document"] = dict(doc_row) if doc_row is not None else None

        span = json.loads(row["source_span"]) if row["source_span"] else None
        record["source_span"] = span
        record["excerpt"] = (
            span_excerpt(self.document_raw_text(row["source_doc_id"]), span)
            if span else None
        )

        # Advisory only, and labelled as such wherever it surfaces: the
        # critic never approved anything and its score is not part of the
        # lineage, only of the queue's ordering.
        record["critic"] = None
        critic_stream = (
            self._current_critic_stream(kind)
            if self._table_exists("critic_reviews") else None
        )
        if critic_stream is not None:
            critic = self.conn.execute(
                "SELECT engine, model, score, rationale, created_ts "
                "FROM critic_reviews WHERE kind = ? AND item_id = ? "
                "AND engine = ? AND model IS ? AND prompt_version = ? "
                "ORDER BY created_ts DESC LIMIT 1",
                (kind, item_id, *critic_stream),
            ).fetchone()
            if critic is not None:
                record["critic"] = dict(critic)
        return record

    def name_search(
        self,
        query: str,
        *,
        limit: int = 8,
        include_proposed: bool = True,
    ) -> list[dict[str, Any]]:
        """Substring name search, ranked exact → prefix → contained.

        `entity_lookup` resolves an identity: it wants the node the caller
        already means, so it matches the normalized name exactly, then
        aliases, then falls back to FTS. That is the wrong shape for a
        finder. FTS tokenizes on word boundaries, so `Cas9` does not match
        `HiFiCas9` — typing three letters of a name a user can see on screen
        returned nothing, which makes a command palette useless for the one
        thing it exists to do.

        This matches on the same `normalized_name` key entity resolution
        uses, so the palette and the store agree on what "the same name"
        means, and the ranking puts an exact hit above a prefix above a
        substring — the order a person scanning a dropdown expects.
        """
        key = normalize_name(query)
        if not key:
            return []
        status_sql = _status_clause(include_proposed)
        # The normalized key may now CONTAIN % or _ (short symbols keep
        # punctuation), so LIKE patterns must escape them — normalization
        # was never a sanitizer, and widening a literal keystroke into a
        # wildcard match returns the whole graph.
        escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.conn.execute(
            f"""
            SELECT *,
                   CASE WHEN normalized_name = ?      THEN 0
                        WHEN normalized_name LIKE ? ESCAPE '\\'   THEN 1
                        ELSE 2 END AS rank_bucket
            FROM nodes
            WHERE {status_sql} AND normalized_name LIKE ? ESCAPE '\\'
            ORDER BY rank_bucket, LENGTH(name), name
            LIMIT ?
            """,
            (key, escaped + "%", "%" + escaped + "%", limit),
        ).fetchall()
        return [_node_dict(row) for row in rows]

    def semantic_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        entity_type: str | None = None,
        min_score: float = 0.0,
        include_proposed: bool = False,
    ) -> list[dict[str, Any]]:
        """Tier-1 **lexical** (FTS5/BM25) search over node names/aliases/properties.

        Not vector search. The raw sqlite bm25() rank (negative,
        smaller-is-better) is normalized rank-preservingly into the stable
        0..1 higher-is-better ``match_score`` contract of §5.4:
        ``relevance = max(0, -bm25_raw)``, ``match_score = relevance / (1 + relevance)``.
        """
        terms = [t for t in re.findall(r"\w+", query) if t]
        if not terms:
            return []
        match_expr = " OR ".join(f'"{t}"' for t in terms)
        status_sql = _status_clause(include_proposed, "n")
        type_sql, type_args = self._type_filter_sql(entity_type, "n.entity_type")
        args: list[Any] = [match_expr, *type_args]
        args.append(top_k * 4)  # over-fetch before status/type/score filtering
        cur = self.conn.execute(
            "SELECT n.*, bm25(nodes_fts) AS raw_rank FROM nodes_fts "
            "JOIN nodes n ON n.rowid = nodes_fts.rowid "
            f"WHERE nodes_fts MATCH ? AND {status_sql}{type_sql} "
            "ORDER BY raw_rank ASC LIMIT ?",
            args,
        )
        results = []
        for row in cur.fetchall():
            relevance = max(0.0, -float(row["raw_rank"]))
            score = relevance / (1.0 + relevance)
            if score < min_score:
                continue
            item = _node_dict(row)
            item["match_score"] = round(score, MATCH_SCORE_PRECISION)
            item["source_document_ids"] = sorted(
                {c["source_doc_id"] for c in self.citations("node", row["id"])}
                or {row["source_doc_id"]}
            )
            results.append(item)
            if len(results) >= top_k:
                break
        return results
