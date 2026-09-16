"""Tier-2 embeddings: backfill, vector search, hybrid fusion.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ontologylab.kgstore_base import (
    MATCH_SCORE_PRECISION,
    VEC_SHORTLIST_FACTOR,
    VEC_SHORTLIST_MIN_MARGIN,
    _node_dict,
    _status_clause,
)

class SearchMixin:

    # ------------------------------------------------------------------
    # Tier-2 embeddings: backfill, cosine search, hybrid RRF fusion (§5.4)
    # ------------------------------------------------------------------

    def _embedding_text(self, row: sqlite3.Row) -> str:
        """The text an embedder sees for a node: name + aliases + properties."""
        aliases = json.loads(row["aliases_json"])
        properties = json.loads(row["properties_json"])
        parts = [row["name"], *aliases]
        parts.extend(f"{k}: {v}" for k, v in properties.items())
        return " | ".join(str(p) for p in parts)

    def embed_nodes(self, embedder, *, batch_size: int = 64) -> dict[str, int]:
        """Backfill embeddings for nodes missing one from this embedder.

        Covers proposed + verified rows (so the review UI can search pending
        items too); rejected rows are never embedded. Idempotent: rows whose
        embedding_model already matches are skipped.
        """
        self._assert_writable()
        from ontologylab.embeddings import pack_vector

        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE status IN ('proposed','verified') "
            "AND (embedding IS NULL OR embedding_model IS NOT ?)",
            (embedder.name(),),
        ).fetchall()
        embedded = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            texts = [self._embedding_text(r) for r in batch]
            vectors = embedder.embed(texts)
            for row, vec in zip(batch, vectors):
                self.conn.execute(
                    "UPDATE nodes SET embedding = ?, embedding_model = ? WHERE id = ?",
                    (pack_vector(vec), embedder.name(), row["id"]),
                )
                embedded += 1
        self.conn.commit()
        # Keep the optional sqlite-vec index in step with the embeddings it
        # accelerates (no-op when the extension isn't available).
        if embedded and self._vec_available():
            self._rebuild_vec_index(embedder)
        return {"embedded": embedded, "skipped": self.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE embedding_model = ?",
            (embedder.name(),),
        ).fetchone()[0] - embedded}

    def _rebuild_vec_index(self, embedder) -> None:
        """(Re)build the vec0 KNN index over this store's embeddings.

        Sized to the embedder's dimension and populated from the existing
        ``embedding`` BLOBs (byte-identical to sqlite-vec's own encoding).
        Working-DB only — packs stay portable (no extension needed to serve
        them), so a pack simply has no vec index and uses brute force.
        """
        self._assert_writable()
        dim = embedder.dim
        self.conn.execute("DROP TABLE IF EXISTS vec_nodes")
        self.conn.execute(
            f"CREATE VIRTUAL TABLE vec_nodes USING vec0("
            f"node_id TEXT PRIMARY KEY, embedding float[{dim}])"
        )
        self.conn.execute(
            "INSERT INTO vec_nodes(node_id, embedding) "
            "SELECT id, embedding FROM nodes "
            "WHERE embedding_model = ? AND embedding IS NOT NULL "
            "AND status IN ('proposed','verified')",
            (embedder.name(),),
        )
        self.conn.commit()

    def embedding_model(self) -> str | None:
        """The embedding model present on this store's nodes (if any)."""
        row = self.conn.execute(
            "SELECT embedding_model FROM nodes "
            "WHERE embedding_model IS NOT NULL LIMIT 1"
        ).fetchone()
        return row["embedding_model"] if row else None

    def vector_search(
        self,
        query: str,
        embedder,
        *,
        top_k: int = 10,
        entity_type: str | None = None,
        include_proposed: bool = False,
    ) -> list[dict[str, Any]]:
        """Cosine over stored embeddings, sqlite-vec-accelerated when present.

        Only compares against vectors produced by the SAME embedder
        (embedding_model match) — a model-A pack is never scored with a
        model-B query. match_score = (cosine+1)/2 per the §5.4 contract.

        When sqlite-vec is loaded and a vec index exists for this embedder,
        a KNN prefilter narrows the candidate set; every candidate is then
        rescored with the exact cosine, so the accelerated path returns the
        SAME results as brute force — it just examines fewer rows.
        """
        query_vec = embedder.embed([query])[0]
        candidates = self._vector_candidates(
            query_vec, embedder, top_k, entity_type, include_proposed
        )
        return self._score_vector_candidates(query_vec, candidates, top_k)

    def _vector_candidates(
        self, query_vec, embedder, top_k, entity_type, include_proposed
    ) -> list[sqlite3.Row]:
        """Node rows to cosine-rank: a KNN shortlist when vec0 is available
        (over-fetched so status/type filtering can't starve the top_k), else
        every embedded row for this embedder (brute force)."""
        status_sql = _status_clause(include_proposed)
        type_sql = " AND entity_type = ?" if entity_type else ""
        use_vec = (
            self._vec_available()
            and self._table_exists("vec_nodes")
            and self.embedding_model() == embedder.name()
        )
        if use_vec:
            from ontologylab.embeddings import pack_vector

            # Over-fetch generously: KNN is global, so status/type filters are
            # applied after; a wide shortlist keeps results identical to brute
            # force at local scale.
            shortlist = max(
                top_k * VEC_SHORTLIST_FACTOR, top_k + VEC_SHORTLIST_MIN_MARGIN
            )
            try:
                knn = self.conn.execute(
                    "SELECT node_id FROM vec_nodes WHERE embedding MATCH ? "
                    "ORDER BY distance LIMIT ?",
                    (pack_vector(query_vec), shortlist),
                ).fetchall()
            except sqlite3.OperationalError:
                use_vec = False  # index shape mismatch etc. -> brute force
            else:
                ids = [r["node_id"] for r in knn]
                if not ids:
                    return []
                placeholders = ",".join("?" for _ in ids)
                rows = self.conn.execute(
                    f"SELECT * FROM nodes WHERE id IN ({placeholders}) "
                    f"AND embedding_model = ? AND {status_sql}{type_sql}",
                    [*ids, embedder.name(), *([entity_type] if entity_type else [])],
                ).fetchall()
                # preserve KNN order isn't needed — we rescore exactly below.
                return rows
        args: list[Any] = [embedder.name()]
        if entity_type:
            args.append(entity_type)
        return self.conn.execute(
            f"SELECT * FROM nodes WHERE embedding_model = ? AND {status_sql}{type_sql}",
            args,
        ).fetchall()

    def _score_vector_candidates(
        self, query_vec, rows, top_k
    ) -> list[dict[str, Any]]:
        from ontologylab.embeddings import cosine, unpack_vector

        scored = [
            (cosine(query_vec, unpack_vector(row["embedding"])), row) for row in rows
        ]
        # Deterministic tie-break by id so the ranking is identical whether the
        # candidate rows arrived in rowid order (brute force) or PK-index order
        # (the sqlite-vec KNN shortlist) — equal-cosine ties can't reorder.
        scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        results = []
        for sim, row in scored[:top_k]:
            item = _node_dict(row)
            item["match_score"] = round((sim + 1.0) / 2.0, MATCH_SCORE_PRECISION)
            item["source_document_ids"] = sorted(
                {c["source_doc_id"] for c in self.citations("node", row["id"])}
                or {row["source_doc_id"]}
            )
            results.append(item)
        return results

    def hybrid_search(
        self,
        query: str,
        embedder,
        *,
        top_k: int = 10,
        entity_type: str | None = None,
        min_score: float = 0.0,
        include_proposed: bool = False,
        extra_lexical_queries: list[str] | None = None,
        reranker: Any | None = None,
    ) -> list[dict[str, Any]]:
        """BM25 + vector fused with Reciprocal Rank Fusion (§5.4 tier-2).

        ``reranker`` (anything with ``score(query, texts) -> list[float]``)
        adds a second stage: the fused shortlist (3×top_k) is re-scored
        jointly against the query and re-ordered. RRF alone never reads the
        query against a candidate — it only merges ranks — which is the gap
        second-stage rerankers exist to close. With a reranker,
        ``match_score`` is the sigmoid of the cross-encoder logit (still
        0..1, higher is better); ties break by id, so the ordering stays a
        pure function of the store.

        All backends run status-filtered, their ranked id lists are fused
        with RRF (k=60), and match_score carries the normalized 0..1 fused
        score (rank-based relevance, higher is better — documented meaning
        consistent across tiers).

        ``extra_lexical_queries`` adds one ranked list per entry (e.g. the
        LLM-expanded variant query) as an INDEPENDENT fusion signal — the
        vector leg always embeds the original ``query`` only, so expansion
        terms never pollute the semantic embedding. This is the 3-signal
        hybrid: plain lexical + expanded lexical + vector.
        """
        from ontologylab.embeddings import rrf_fuse

        lexical = self.semantic_search(
            query,
            top_k=top_k * 2,
            entity_type=entity_type,
            include_proposed=include_proposed,
        )
        extra_lists: list[list[dict[str, Any]]] = []
        for extra_query in extra_lexical_queries or []:
            if not extra_query or extra_query == query:
                continue
            extra_lists.append(
                self.semantic_search(
                    extra_query,
                    top_k=top_k * 2,
                    entity_type=entity_type,
                    include_proposed=include_proposed,
                )
            )
        vector = self.vector_search(
            query,
            embedder,
            top_k=top_k * 2,
            entity_type=entity_type,
            include_proposed=include_proposed,
        )
        all_lists = [lexical, *extra_lists, vector]
        # dict 채우기는 역순 — 기존 [*vector, *lexical] 규약대로 lexical
        # 행이 같은 id의 vector 행을 덮어쓴다
        by_id = {
            item["id"]: item
            for ranked in reversed(all_lists)
            for item in ranked
        }
        fused = rrf_fuse([[i["id"] for i in ranked] for ranked in all_lists])
        shortlist_size = top_k * 3 if reranker is not None else top_k
        results = []
        for item_id, fused_score in fused:
            if fused_score < min_score:
                continue
            item = dict(by_id[item_id])
            item["match_score"] = round(fused_score, MATCH_SCORE_PRECISION)
            results.append(item)
            if len(results) >= shortlist_size:
                break
        if reranker is None or not results:
            return results

        from ontologylab.rerankers import sigmoid

        texts = [
            " | ".join(
                str(part)
                for part in (
                    item["name"],
                    item["entity_type"],
                    *item.get("aliases", []),
                    *(f"{k}: {v}" for k, v in item.get("properties", {}).items()),
                )
            )
            for item in results
        ]
        scores = reranker.score(query, texts)
        order = sorted(
            range(len(results)),
            key=lambda i: (-scores[i], results[i]["id"]),
        )
        reranked = []
        for i in order[:top_k]:
            item = results[i]
            item["match_score"] = round(sigmoid(scores[i]), MATCH_SCORE_PRECISION)
            reranked.append(item)
        return reranked
