"""Document- and entity-centric review context payloads.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

import json
from typing import Any

from ontologylab.kgstore_base import (
    DOCUMENT_PANEL_MAX_CHARS,
    KGStoreError,
    SPAN_EXCERPT_CONTEXT_CHARS,
    UnknownItem,
    _node_dict,
    span_excerpt,
)

class ReviewContextMixin:

    # ------------------------------------------------------------------
    # Document-centric review: the source text, and what was drawn from it
    # ------------------------------------------------------------------

    def document_review_context(
        self, doc_id: str, *, max_chars: int = DOCUMENT_PANEL_MAX_CHARS
    ) -> dict[str, Any]:
        """One document plus every proposal that cites it.

        The inverse of `entity_review_context`, and the view the product has
        been missing. Approving a proposal means judging whether the source
        actually says it — a question the entity view answers one 160-char
        excerpt at a time, which is enough to check a single mention and not
        enough to notice that eleven proposals all came from the same
        sentence, or that a paper's own hedging ("we did not observe") sits
        just outside every excerpt.

        Returns the text, capped, and the cited spans as offsets into it.
        Nothing is marked up here: the caller decides how to draw a span,
        and a server that shipped HTML would be a server that decides what
        a document looks like — and a path for document text to reach
        innerHTML as markup rather than as text.
        """
        document = self.get_document(doc_id)
        try:
            text = self.document_raw_text(doc_id)
        except (KGStoreError, OSError):
            # The proposals are in sqlite; the raw text is a file beside it.
            # One can be missing without the other, and this panel is how a
            # reviewer would find out — so it must not be the thing that
            # breaks.
            text = ""
        truncated = len(text) > max_chars

        rows = self.conn.execute(
            "SELECT kind, item_id, source_span FROM citations "
            "WHERE source_doc_id = ? ORDER BY created_ts ASC",
            (doc_id,),
        ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            invalidated: bool | None = None
            span = json.loads(row["source_span"]) if row["source_span"] else None
            qualifiers: dict[str, Any] = {}
            if row["kind"] == "node":
                nrow = self.conn.execute(
                    "SELECT name, entity_type, status FROM nodes WHERE id = ?",
                    (row["item_id"],),
                ).fetchone()
                if nrow is None:
                    continue
                label, kind_label, status = (
                    nrow["name"], nrow["entity_type"], nrow["status"],
                )
            else:
                invalidated_column = (
                    ", e.invalidated_ts" if self._edges_bitemporal() else ""
                )
                qualifier_column = (
                    ", e.qualifiers_json" if self._edges_have_qualifiers() else ""
                )
                erow = self.conn.execute(
                    "SELECT e.relation_type, e.status, s.name AS src, "
                    f"d.name AS dst{qualifier_column}{invalidated_column} FROM edges e "
                    "JOIN nodes s ON s.id = e.src_node_id "
                    "JOIN nodes d ON d.id = e.dst_node_id WHERE e.id = ?",
                    (row["item_id"],),
                ).fetchone()
                if erow is None:
                    continue
                # An edge shown as `related_to` alone cannot be judged.
                label = f"{erow['src']} → {erow['dst']}"
                kind_label, status = erow["relation_type"], erow["status"]
                qualifiers = (
                    json.loads(erow["qualifiers_json"])
                    if "qualifiers_json" in erow.keys() and erow["qualifiers_json"]
                    else {}
                )
                # A superseded edge stays visible in the document's history
                # but marked — presenting it as live would assert a fact the
                # reviewer already withdrew.
                if self._edges_bitemporal():
                    invalidated = bool(erow["invalidated_ts"])
            items.append({
                "kind": row["kind"],
                "id": row["item_id"],
                "label": label,
                "type": kind_label,
                "status": status,
                "invalidated": invalidated,
                "qualifiers": qualifiers if row["kind"] == "edge" else None,
                # A span past the cap is reported as absent rather than as a
                # position the caller would draw in the wrong place —
                # highlighting the wrong sentence asserts evidence that is
                # not there, which is worse than highlighting nothing.
                "span": span if (
                    span and int(span.get("end", 0)) <= max_chars
                ) else None,
            })

        return {
            "doc_id": document.id,
            "title": document.title,
            "source_uri": document.source_uri,
            "source_kind": document.source_kind,
            "fetched_ts": document.fetched_ts,
            "text": text[:max_chars],
            "truncated": truncated,
            "total_chars": len(text),
            "items": items,
        }

    # ------------------------------------------------------------------
    # W11 entity-centric review: everything about ONE entity in one payload
    # ------------------------------------------------------------------

    def entity_review_context(
        self, entity_id: str, *, context_chars: int = SPAN_EXCERPT_CONTEXT_CHARS
    ) -> dict[str, Any]:
        """One entity's full review context: every mention (span excerpt in
        source context), every proposed/verified relation with the other
        endpoint's name+status, the latest critic score, and any pending
        merge candidates involving it.

        Read-only aggregation — approving/rejecting stays per-item through
        the existing gate. Rationale (RESEARCH W11): most of what a reviewer
        needs to judge an entity lives outside the single row being staring
        at — its other mentions and its relations.
        """
        kind, row = self._find_kind(entity_id)
        if kind != "node":
            raise KGStoreError("entity review is for nodes; got an edge id")
        entity = _node_dict(row)

        critic = None
        node_stream = (
            self._current_critic_stream("node")
            if self._table_exists("critic_reviews") else None
        )
        if node_stream is not None:
            crow = self.conn.execute(
                "SELECT c.engine, c.model, c.score, c.rationale, "
                "MAX(c.created_ts) AS ts FROM critic_reviews c "
                "WHERE c.kind = 'node' AND c.item_id = ? "
                "AND c.engine = ? AND c.model IS ? AND c.prompt_version = ? "
                "GROUP BY c.item_id",
                (entity_id, *node_stream),
            ).fetchone()
            if crow is not None and crow["score"] is not None:
                critic = {
                    "engine": crow["engine"],
                    "model": crow["model"],
                    "score": crow["score"],
                    "rationale": crow["rationale"],
                }

        mentions = []
        doc_cache: dict[str, str] = {}
        for citation in self.citations("node", entity_id):
            doc_id = citation["source_doc_id"]
            if doc_id not in doc_cache:
                try:
                    doc_cache[doc_id] = self.document_raw_text(doc_id)
                except (KGStoreError, OSError):
                    doc_cache[doc_id] = ""
            try:
                title = self.get_document(doc_id).title
            except UnknownItem:
                title = None
            mentions.append(
                {
                    "source_doc_id": doc_id,
                    "doc_title": title,
                    "source_span": citation["source_span"],
                    "excerpt": span_excerpt(
                        doc_cache[doc_id],
                        citation["source_span"],
                        context_chars=context_chars,
                    ),
                }
            )

        edge_rows = self.conn.execute(
            "SELECT e.*, s.name AS src_name, s.status AS src_status, "
            "d.name AS dst_name, d.status AS dst_status FROM edges e "
            "JOIN nodes s ON s.id = e.src_node_id "
            "JOIN nodes d ON d.id = e.dst_node_id "
            "WHERE (e.src_node_id = ? OR e.dst_node_id = ?) "
            "AND e.status IN ('proposed','verified') "
            f"AND {self._edge_current_sql('e')} "
            "ORDER BY e.status DESC, e.created_ts ASC",
            (entity_id, entity_id),
        ).fetchall()
        edge_critic: dict[str, float] = {}
        edge_stream = (
            self._current_critic_stream("edge")
            if edge_rows and self._table_exists("critic_reviews") else None
        )
        if edge_stream is not None:
            placeholders = ",".join("?" for _ in edge_rows)
            for crow in self.conn.execute(
                "SELECT c.item_id, c.score, MAX(c.created_ts) AS ts "
                "FROM critic_reviews c "
                f"WHERE c.kind = 'edge' AND c.item_id IN ({placeholders}) "
                "AND c.engine = ? AND c.model IS ? AND c.prompt_version = ? "
                "GROUP BY c.item_id",
                [*[e["id"] for e in edge_rows], *edge_stream],
            ):
                edge_critic[crow["item_id"]] = crow["score"]
        relations = []
        for edge in edge_rows:
            outgoing = edge["src_node_id"] == entity_id
            relations.append(
                {
                    "id": edge["id"],
                    "relation_type": edge["relation_type"],
                    "direction": "out" if outgoing else "in",
                    "other": {
                        "id": edge["dst_node_id"] if outgoing else edge["src_node_id"],
                        "name": edge["dst_name"] if outgoing else edge["src_name"],
                        "status": (
                            edge["dst_status"] if outgoing else edge["src_status"]
                        ),
                    },
                    "status": edge["status"],
                    "confidence": edge["confidence"],
                    "qualifiers": (
                        json.loads(edge["qualifiers_json"])
                        if "qualifiers_json" in edge.keys()
                        and edge["qualifiers_json"]
                        else {}
                    ),
                    "critic_score": edge_critic.get(edge["id"]),
                    "source_doc_id": edge["source_doc_id"],
                }
            )

        merge_candidates = []
        if self._table_exists("merge_candidates"):
            for mrow in self.conn.execute(
                "SELECT m.*, n.name AS other_name, n.status AS other_status "
                "FROM merge_candidates m JOIN nodes n ON n.id = "
                "  (CASE WHEN m.node_a_id = ? THEN m.node_b_id "
                "        ELSE m.node_a_id END) "
                "WHERE (m.node_a_id = ? OR m.node_b_id = ?) "
                "AND m.status = 'proposed' ORDER BY m.score DESC",
                (entity_id, entity_id, entity_id),
            ):
                merge_candidates.append(
                    {
                        "id": mrow["id"],
                        "score": mrow["score"],
                        "reasons": json.loads(mrow["reasons_json"]),
                        "other": {
                            "id": (
                                mrow["node_b_id"]
                                if mrow["node_a_id"] == entity_id
                                else mrow["node_a_id"]
                            ),
                            "name": mrow["other_name"],
                            "status": mrow["other_status"],
                        },
                    }
                )

        return {
            "entity": entity,
            "critic": critic,
            "mentions": mentions,
            "relations": relations,
            "merge_candidates": merge_candidates,
            "counts": {
                "mentions": len(mentions),
                "relations_proposed": sum(
                    1 for r in relations if r["status"] == "proposed"
                ),
                "relations_verified": sum(
                    1 for r in relations if r["status"] == "verified"
                ),
                "merge_candidates": len(merge_candidates),
            },
        }
