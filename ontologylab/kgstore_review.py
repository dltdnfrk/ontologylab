"""Human approval gate, merge review, curated annotations.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from ontologylab.paths import DEFAULT_ACTOR

from ontologylab.kgstore_base import (
    EndpointNotVerified,
    GroundingPreflightError,
    InvalidTransition,
    KGStoreError,
    SchemaValidationError,
    UnknownItem,
    _node_dict,
    normalize_name,
)

class ReviewMixin:

    # ------------------------------------------------------------------
    # Human approval gate (the only path to status='verified')
    # ------------------------------------------------------------------

    def _find_kind(self, item_id: str) -> tuple[str, sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is not None:
            return "node", row
        cur = self.conn.execute("SELECT * FROM edges WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is not None:
            return "edge", row
        raise UnknownItem(f"no node or edge with id {item_id!r}")

    def approve(
        self,
        item_id: str,
        *,
        by: str = DEFAULT_ACTOR,
        note: str | None = None,
        cascade: bool = False,
    ) -> dict[str, Any]:
        """Flip one proposed row to verified (human action, never automatic).

        For an edge, both endpoint nodes must already be verified, else
        EndpointNotVerified is raised. ``cascade=True`` approves an edge
        together with its endpoints in one explicit command — the endpoints
        get real approvals (verified_by/verified_ts), no invariant bypass.
        """
        from ontologylab.grounded_review import ReviewAction, ReviewRequest

        grounded = self._grounded_review(
            ReviewRequest(
                item_id=item_id,
                actor=by,
                reason=note or "human-review",
                action=ReviewAction.APPROVE,
                cascade=cascade,
            )
        )
        if grounded is not None:
            return grounded
        self._assert_writable()
        kind, row = self._find_kind(item_id)
        if row["status"] != "proposed":
            raise InvalidTransition(
                f"cannot approve a {row['status']!r} item; reopen it first"
            )
        approved: list[str] = []
        if kind == "edge":
            # Validate ALL endpoints before mutating ANY — checking while
            # promoting left the first endpoint verified when the second
            # one refused, half-applying the cascade.
            for endpoint_id in (row["src_node_id"], row["dst_node_id"]):
                _, endpoint = self._find_kind(endpoint_id)
                ep_status = endpoint["status"]
                if ep_status == "verified":
                    continue
                if cascade and ep_status == "proposed":
                    continue
                if cascade:
                    raise InvalidTransition(
                        f"edge {item_id} endpoint {endpoint_id} is "
                        f"{ep_status!r}; cascade only promotes "
                        "proposed endpoints — reopen it first"
                    )
                raise EndpointNotVerified(
                    f"edge {item_id} endpoint {endpoint_id} is "
                    f"{ep_status!r}; approve endpoints first"
                )
            for endpoint_id in (row["src_node_id"], row["dst_node_id"]):
                _, endpoint = self._find_kind(endpoint_id)
                if endpoint["status"] == "proposed":
                    self._set_status(
                        "node", endpoint_id, "verified", by=by, note=note
                    )
                    approved.append(endpoint_id)
        self._set_status(kind, item_id, "verified", by=by, note=note)
        approved.append(item_id)
        self.conn.commit()
        return {"kind": kind, "approved_ids": approved}

    def reject(
        self, item_id: str, *, by: str = DEFAULT_ACTOR, note: str | None = None
    ) -> dict[str, Any]:
        """Flip one proposed row to rejected (kept for audit, never served)."""
        from ontologylab.grounded_review import ReviewAction, ReviewRequest

        grounded = self._grounded_review(
            ReviewRequest(
                item_id=item_id,
                actor=by,
                reason=note or "human-review",
                action=ReviewAction.REJECT,
            )
        )
        if grounded is not None:
            return grounded
        self._assert_writable()
        kind, row = self._find_kind(item_id)
        if row["status"] != "proposed":
            raise InvalidTransition(
                f"cannot reject a {row['status']!r} item; reopen it first"
            )
        self._set_status(kind, item_id, "rejected", by=by, note=note)
        self.conn.commit()
        return {"kind": kind, "rejected_ids": [item_id]}

    def quarantine(
        self, item_id: str, *, by: str = DEFAULT_ACTOR, note: str | None = None
    ) -> dict[str, Any]:
        from ontologylab.grounded_review import ReviewAction, ReviewRequest

        return self._require_grounded_review(
            ReviewRequest(
                item_id=item_id,
                actor=by,
                reason=note or "human-review",
                action=ReviewAction.QUARANTINE,
            )
        )

    def retract_review(
        self, item_id: str, *, by: str = DEFAULT_ACTOR, note: str | None = None
    ) -> dict[str, Any]:
        from ontologylab.grounded_review import ReviewAction, ReviewRequest

        return self._require_grounded_review(
            ReviewRequest(
                item_id=item_id,
                actor=by,
                reason=note or "human-review",
                action=ReviewAction.RETRACT,
            )
        )

    def compensate_review(
        self, item_id: str, *, by: str = DEFAULT_ACTOR, note: str | None = None
    ) -> dict[str, Any]:
        from ontologylab.grounded_review import ReviewAction, ReviewRequest

        return self._require_grounded_review(
            ReviewRequest(
                item_id=item_id,
                actor=by,
                reason=note or "human-review",
                action=ReviewAction.COMPENSATE,
            )
        )

    def approve_with_grounding_waiver(self, request: Any) -> dict[str, Any]:
        from ontologylab.grounded_review import (
            GroundedReviewRefused,
            ReviewAction,
            approve_with_grounding_waiver,
            batch_payload,
        )

        self._assert_writable()
        try:
            result = approve_with_grounding_waiver(self.conn, request)
        except GroundedReviewRefused as exc:
            self._raise_grounded(exc)
        self.conn.commit()
        return batch_payload(result, ReviewAction.APPROVE_WITH_GROUNDING_WAIVER)

    def _grounded_review(self, request: Any) -> dict[str, Any] | None:
        from ontologylab.grounded_review import (
            GroundedReviewRefused,
            ReviewAction,
            apply_review,
            batch_payload,
        )
        from ontologylab.grounded_review_preflight import (
            collect_members,
            members_have_citations,
        )

        self._assert_writable()
        try:
            members = collect_members(
                self.conn,
                request.item_id,
                request.action,
                cascade=request.cascade,
            )
        except GroundedReviewRefused as exc:
            self._raise_grounded(exc)
        has_citations = members_have_citations(self.conn, members)
        if request.action is ReviewAction.APPROVE and not has_citations:
            return None
        if request.action is ReviewAction.REJECT and not has_citations:
            return None
        try:
            result = apply_review(self.conn, request)
        except GroundedReviewRefused as exc:
            self._raise_grounded(exc)
        self.conn.commit()
        return batch_payload(result, request.action)

    def _require_grounded_review(self, request: Any) -> dict[str, Any]:
        result = self._grounded_review(request)
        if result is None:
            from ontologylab.grounded_review import apply_review, batch_payload
            from ontologylab.grounded_review import GroundedReviewRefused

            try:
                applied = apply_review(self.conn, request)
            except GroundedReviewRefused as exc:
                self._raise_grounded(exc)
            self.conn.commit()
            return batch_payload(applied, request.action)
        return result

    def _raise_grounded(self, exc: Exception) -> None:
        from typing import assert_never

        from ontologylab.grounded_review import (
            GroundedReviewRefusalCode,
            GroundedReviewRefused,
        )

        if not isinstance(exc, GroundedReviewRefused):
            raise exc
        match exc.code:
            case GroundedReviewRefusalCode.UNKNOWN_ITEM:
                raise UnknownItem(exc.message) from exc
            case GroundedReviewRefusalCode.INVALID_TRANSITION:
                raise InvalidTransition(exc.message) from exc
            case GroundedReviewRefusalCode.ENDPOINT_NOT_VERIFIED:
                raise EndpointNotVerified(exc.message) from exc
            case (
                GroundedReviewRefusalCode.MISSING_ACTOR
                | GroundedReviewRefusalCode.MISSING_REASON
                | GroundedReviewRefusalCode.MISSING_FACT_REVISION
                | GroundedReviewRefusalCode.MISSING_CITATION_DIGEST
                | GroundedReviewRefusalCode.MISSING_CITATION
                | GroundedReviewRefusalCode.INVALID_MEMBER
                | GroundedReviewRefusalCode.GENERIC_WAIVER
                | GroundedReviewRefusalCode.UNSCOPED_WAIVER
                | GroundedReviewRefusalCode.CITATION_UNGROUNDED
                | GroundedReviewRefusalCode.CONFLICT
            ):
                raise GroundingPreflightError(str(exc)) from exc
            case unreachable:
                assert_never(unreachable)

    def reopen(
        self, item_id: str, *, by: str = DEFAULT_ACTOR, note: str | None = None
    ) -> dict[str, Any]:
        """Put a decided row back in the review queue (undo of approve/reject).

        Review is keyboard-driven and 'a'/'r' sit next to the 'j'/'k' cursor
        keys, so a decision made a keystroke too early was previously
        permanent — there was no way back to the queue at all.

        Reopening a NODE is refused while a current verified edge still points
        at it: approve() guarantees a verified edge has verified endpoints,
        and silently unapproving one of them would leave that invariant broken
        with nothing to notice it. Reject the edge (or invalidate it) first.
        Edges have no dependents, so they always reopen.

        Already-proposed rows are a no-op rather than an error — pressing undo
        twice should not punish you.
        """
        self._assert_writable()
        kind, row = self._find_kind(item_id)
        if row["status"] == "proposed":
            return {"kind": kind, "reopened_ids": [], "already_open": True}

        if kind == "node":
            blockers = self.conn.execute(
                "SELECT id FROM edges WHERE status = 'verified' "
                f"AND (src_node_id = ? OR dst_node_id = ?) "
                f"AND {self._edge_current_sql()} LIMIT 5",
                (item_id, item_id),
            ).fetchall()
            if blockers:
                ids = ", ".join(b["id"][:10] for b in blockers)
                raise KGStoreError(
                    f"node {item_id} is an endpoint of verified edge(s) {ids} "
                    "— reject or invalidate those first"
                )

        self.conn.execute(
            ("UPDATE nodes SET " if kind == "node" else "UPDATE edges SET ")
            + "status = 'proposed', verified_ts = NULL, verified_by = NULL, "
            "review_note = COALESCE(?, review_note) WHERE id = ?",
            (note, item_id),
        )
        self.conn.commit()
        return {"kind": kind, "reopened_ids": [item_id], "already_open": False}

    def _set_status(
        self, kind: str, item_id: str, status: str, *, by: str, note: str | None
    ) -> None:
        table = "nodes" if kind == "node" else "edges"
        self.conn.execute(
            f"UPDATE {table} SET status = ?, verified_ts = ?, verified_by = ?, "
            "review_note = COALESCE(?, review_note) WHERE id = ?",
            (status, time.time(), by, note, item_id),
        )

    def invalidate_edge(
        self,
        edge_id: str,
        *,
        by: str = DEFAULT_ACTOR,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """W13: mark a VERIFIED edge as no-longer-current (human action).

        Invalidation is the history-preserving alternative to deletion: the
        row keeps its status and audit trail but stops being served as
        current truth (queries, packs, traversals all exclude it), and its
        triple key is freed so a later re-assertion becomes a fresh proposed
        row coexisting with this one. A proposed edge has no history worth
        preserving — reject it instead.
        """
        self._assert_writable()
        kind, row = self._find_kind(edge_id)
        if kind != "edge":
            raise KGStoreError("invalidate_edge operates on edges only")
        if row["status"] != "verified":
            raise KGStoreError(
                f"edge {edge_id} is {row['status']!r}; only verified edges "
                "can be invalidated (reject proposed ones instead)"
            )
        if row["invalidated_ts"] is not None:
            raise KGStoreError(f"edge {edge_id} is already invalidated")
        now = time.time()
        self.conn.execute(
            "UPDATE edges SET invalidated_ts = ?, invalidated_by = ?, "
            "invalidation_reason = ? WHERE id = ?",
            (now, by, reason, edge_id),
        )
        self.conn.commit()
        return {
            "id": edge_id,
            "invalidated_ts": now,
            "invalidated_by": by,
            "reason": reason,
        }

    def bulk_approve(
        self,
        *,
        entity_type: str | None = None,
        relation_type: str | None = None,
        source_doc_id: str | None = None,
        min_confidence: float | None = None,
        by: str = DEFAULT_ACTOR,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Approve a filtered batch: nodes first, then edges whose endpoints
        are verified after the node pass; blocked edges are reported as
        skipped, never silently approved and never auto-approving endpoints.
        """
        self._assert_writable()
        node_where = ["status = 'proposed'"]
        node_args: list[Any] = []
        if entity_type:
            node_where.append("entity_type = ?")
            node_args.append(entity_type)
        if source_doc_id:
            node_where.append("source_doc_id = ?")
            node_args.append(source_doc_id)
        if min_confidence is not None:
            node_where.append("confidence >= ?")
            node_args.append(min_confidence)

        nodes_approved: list[str] = []
        if not relation_type:  # a relation_type filter targets edges only
            cur = self.conn.execute(
                f"SELECT id FROM nodes WHERE {' AND '.join(node_where)}", node_args
            )
            for row in cur.fetchall():
                self._set_status("node", row["id"], "verified", by=by, note=note)
                nodes_approved.append(row["id"])

        edge_where = ["e.status = 'proposed'"]
        edge_args: list[Any] = []
        if relation_type:
            edge_where.append("e.relation_type = ?")
            edge_args.append(relation_type)
        if entity_type:
            # Keep the edge pass inside the human's stated batch scope: only
            # edges BOTH of whose endpoints are of the filtered entity type.
            # Without this, any proposed edge between previously-verified
            # nodes of unrelated types would be silently over-approved.
            edge_where.append(
                "(SELECT entity_type FROM nodes WHERE id = e.src_node_id) = ? AND "
                "(SELECT entity_type FROM nodes WHERE id = e.dst_node_id) = ?"
            )
            edge_args.extend([entity_type, entity_type])
        if source_doc_id:
            edge_where.append("e.source_doc_id = ?")
            edge_args.append(source_doc_id)
        if min_confidence is not None:
            edge_where.append("e.confidence >= ?")
            edge_args.append(min_confidence)

        edges_approved: list[str] = []
        edges_skipped: list[str] = []
        cur = self.conn.execute(
            "SELECT e.*, s.status AS src_status, d.status AS dst_status "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.src_node_id "
            "JOIN nodes d ON d.id = e.dst_node_id "
            f"WHERE {' AND '.join(edge_where)}",
            edge_args,
        )
        for row in cur.fetchall():
            if row["src_status"] == "verified" and row["dst_status"] == "verified":
                self._set_status("edge", row["id"], "verified", by=by, note=note)
                edges_approved.append(row["id"])
            else:
                edges_skipped.append(row["id"])
        self.conn.commit()
        return {
            "nodes_approved": nodes_approved,
            "edges_approved": edges_approved,
            "edges_skipped": edges_skipped,
        }

    # ------------------------------------------------------------------
    # W7 entity-merge review (candidates proposed by scan, decided by human)
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_pair(node_a_id: str, node_b_id: str) -> tuple[str, str]:
        """Order a pair canonically so (a,b) and (b,a) are one candidate."""
        return (node_a_id, node_b_id) if node_a_id < node_b_id else (node_b_id, node_a_id)

    def record_merge_candidate(
        self, node_a_id: str, node_b_id: str, *, score: float, reasons: list[str]
    ) -> bool:
        """Store one fuzzy-duplicate pair for human review.

        Returns True if a new candidate row was created. A pair that already
        has a row in ANY status is left untouched — in particular a dismissed
        pair is never re-proposed (the human already said "not a duplicate").
        """
        self._assert_writable()
        if node_a_id == node_b_id:
            raise KGStoreError("a merge candidate needs two distinct nodes")
        a, b = self._canonical_pair(node_a_id, node_b_id)
        existing = self.conn.execute(
            "SELECT id FROM merge_candidates WHERE node_a_id = ? AND node_b_id = ?",
            (a, b),
        ).fetchone()
        if existing is not None:
            return False
        self.conn.execute(
            "INSERT INTO merge_candidates "
            "(id, node_a_id, node_b_id, score, reasons_json, status, created_ts) "
            "VALUES (?, ?, ?, ?, ?, 'proposed', ?)",
            (uuid.uuid4().hex, a, b, score, json.dumps(reasons), time.time()),
        )
        self.conn.commit()
        return True

    def _merge_candidate_row(self, candidate_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM merge_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise UnknownItem(f"unknown merge candidate id {candidate_id!r}")
        return row

    # ---------------------------------------------------------------
    # Annotations — curated-resource records, awaiting a human decision
    # ---------------------------------------------------------------

    def upsert_annotation(
        self,
        *,
        node_id: str,
        resource: str,
        external_id: str,
        record_url: str,
        matched_name: str,
        facts: dict[str, Any],
    ) -> tuple[str, bool]:
        """Propose one resource record for one node. Returns (id, created).

        Re-running a lookup REFRESHES the pending row rather than adding a
        second one: a resource that revises a record should not cost the
        reviewer an extra rejection, and two rows for one (node, resource)
        would let a reviewer approve a record the resource has since
        replaced.

        A decided annotation is never silently overwritten. Approval is the
        thing this whole table exists to record; discarding it because a
        refresh ran later would make the decision unstable.
        """
        self._assert_writable()
        node = self.conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if node is None:
            raise UnknownItem(f"unknown node id {node_id!r}")
        annotation_block = {
            "external_id": external_id,
            "record_url": record_url,
            "matched_name": matched_name,
            **facts,
        }
        self._validate_annotation_property(node, resource, annotation_block)
        now = time.time()
        existing = self.conn.execute(
            "SELECT id, status FROM annotations WHERE node_id = ? AND resource = ?",
            (node_id, resource),
        ).fetchone()
        if existing is not None:
            if existing["status"] != "proposed":
                return existing["id"], False
            self.conn.execute(
                "UPDATE annotations SET external_id = ?, record_url = ?, "
                "matched_name = ?, facts_json = ?, created_ts = ? WHERE id = ?",
                (
                    external_id,
                    record_url,
                    matched_name,
                    json.dumps(facts, ensure_ascii=False),
                    now,
                    existing["id"],
                ),
            )
            self.conn.commit()
            return existing["id"], False

        annotation_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO annotations (id, node_id, resource, external_id, "
            "record_url, matched_name, facts_json, status, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?)",
            (
                annotation_id,
                node_id,
                resource,
                external_id,
                record_url,
                matched_name,
                json.dumps(facts, ensure_ascii=False),
                now,
            ),
        )
        self.conn.commit()
        return annotation_id, True

    def annotations_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Pending annotations, each carrying the node name it would attach to.

        The node's own name travels with the row because it is the evidence:
        the reviewer's job is to compare "what we called it" with "what the
        resource calls it", and a queue that showed only the latter would be
        asking them to confirm a match they cannot see.
        """
        if not self._table_exists("annotations"):
            return []
        rows = self.conn.execute(
            "SELECT a.*, n.name AS node_name, n.entity_type AS node_type, "
            "       n.status AS node_status "
            "FROM annotations a JOIN nodes n ON n.id = a.node_id "
            "WHERE a.status = 'proposed' "
            "ORDER BY a.created_ts ASC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["facts"] = json.loads(row["facts_json"])
            except (TypeError, ValueError):
                item["facts"] = {}
            item.pop("facts_json", None)
            out.append(item)
        return out

    def decide_annotation(
        self,
        annotation_id: str,
        *,
        accept: bool,
        by: str = DEFAULT_ACTOR,
        note: str | None = None,
    ) -> bool:
        """Accept or reject one annotation. False when it is already decided.

        Accepting writes the facts onto the node under the resource's name,
        so an approved annotation becomes part of the node while staying
        attributable — `properties_json` gains one key per resource, never a
        flat merge, because a flat merge would lose which resource said what
        and let two resources silently overwrite each other.
        """
        self._assert_writable()
        row = self.conn.execute(
            "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
        ).fetchone()
        if row is None or row["status"] != "proposed":
            return False
        node = None
        if accept:
            node = self.conn.execute(
                "SELECT * FROM nodes WHERE id = ?", (row["node_id"],)
            ).fetchone()
            if node is None:
                raise UnknownItem(f"unknown node id {row['node_id']!r}")
            try:
                raw_facts = json.loads(row["facts_json"])
            except (TypeError, ValueError) as exc:
                raise SchemaValidationError(
                    f"annotation {annotation_id!r} has malformed facts"
                ) from exc
            facts_for_validation = raw_facts if isinstance(raw_facts, dict) else {}
            self._validate_annotation_property(
                node,
                row["resource"],
                {
                    "external_id": row["external_id"],
                    "record_url": row["record_url"],
                    "matched_name": row["matched_name"],
                    **facts_for_validation,
                },
            )
        now = time.time()
        status = "verified" if accept else "rejected"
        self.conn.execute(
            "UPDATE annotations SET status = ?, decided_ts = ?, decided_by = ?, "
            "decision_note = ? WHERE id = ?",
            (status, now, by, note, annotation_id),
        )
        if accept:
            if node is not None:
                try:
                    props = json.loads(node["properties_json"] or "{}")
                except (TypeError, ValueError):
                    props = {}
                if not isinstance(props, dict):
                    props = {}
                try:
                    facts = json.loads(row["facts_json"])
                except (TypeError, ValueError):
                    facts = {}
                props[row["resource"]] = {
                    "external_id": row["external_id"],
                    "record_url": row["record_url"],
                    "matched_name": row["matched_name"],
                    **(facts if isinstance(facts, dict) else {}),
                }
                self.conn.execute(
                    "UPDATE nodes SET properties_json = ? WHERE id = ?",
                    (json.dumps(props, ensure_ascii=False), row["node_id"]),
                )
        self.conn.commit()
        return True

    def annotation_counts(self) -> dict[str, int]:
        if not self._table_exists("annotations"):
            return {"proposed": 0, "verified": 0, "rejected": 0}
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM annotations GROUP BY status"
        ).fetchall()
        counts = {"proposed": 0, "verified": 0, "rejected": 0}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts

    def merge_candidates_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Pending merge candidates, hydrated with both nodes side-by-side."""
        if not self._table_exists("merge_candidates"):
            return []  # pre-W7 read-only store: no queue, not an error
        rows = self.conn.execute(
            "SELECT * FROM merge_candidates WHERE status = 'proposed' "
            "ORDER BY score DESC, created_ts ASC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            nodes = {}
            for key in ("node_a_id", "node_b_id"):
                node_row = self.conn.execute(
                    "SELECT * FROM nodes WHERE id = ?", (row[key],)
                ).fetchone()
                if node_row is None:
                    continue
                item = _node_dict(node_row)
                item["citation_count"] = len(self.citations("node", node_row["id"]))
                nodes[key] = item
            # A candidate whose node has since been rejected/merged away is
            # noise: hide it (and mark it stale so it stops coming back).
            hydrated = list(nodes.values())
            if len(hydrated) != 2 or any(
                n["status"] not in ("proposed", "verified") for n in hydrated
            ):
                if not self.read_only:
                    self.conn.execute(
                        "UPDATE merge_candidates SET status = 'stale', "
                        "decided_ts = ?, decided_by = 'system:hydrate' WHERE id = ?",
                        (time.time(), row["id"]),
                    )
                    self.conn.commit()
                continue
            out.append(
                {
                    "id": row["id"],
                    "score": row["score"],
                    "reasons": json.loads(row["reasons_json"]),
                    "created_ts": row["created_ts"],
                    "node_a": nodes["node_a_id"],
                    "node_b": nodes["node_b_id"],
                }
            )
        return out

    def dismiss_merge_candidate(
        self, candidate_id: str, *, by: str = DEFAULT_ACTOR, note: str | None = None
    ) -> dict[str, Any]:
        """Human decision: this pair is NOT a duplicate. Never re-proposed."""
        self._assert_writable()
        row = self._merge_candidate_row(candidate_id)
        if row["status"] != "proposed":
            raise KGStoreError(
                f"merge candidate {candidate_id} already decided ({row['status']})"
            )
        self.conn.execute(
            "UPDATE merge_candidates SET status = 'dismissed', decided_ts = ?, "
            "decided_by = ?, decision_note = ? WHERE id = ?",
            (time.time(), by, note, candidate_id),
        )
        self.conn.commit()
        return {"id": candidate_id, "status": "dismissed"}

    def merge_nodes(
        self,
        target_id: str,
        source_id: str,
        *,
        by: str = DEFAULT_ACTOR,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Merge ``source`` into ``target`` — an explicit human action.

        Aliases/properties union non-destructively into the target, citations
        and edges are re-pointed (duplicate triples collapse into a citation,
        would-be self-loops are rejected), and the source row becomes a
        ``rejected`` tombstone with ``review_note='merged-into:<target>'`` so
        it can never be served (§9.1) while staying auditable. The source's
        surfaces are registered as target aliases, so future extractions of
        the old name resolve to the merged node.

        Merging never verifies anything: the target keeps its own status.
        A verified source cannot merge into a proposed target (that would
        leave verified edges pointing at an unverified node) — merge in the
        other direction, or approve the target first.
        """
        self._assert_writable()
        if target_id == source_id:
            raise KGStoreError("cannot merge a node into itself")
        target_kind, target = self._find_kind(target_id)
        source_kind, source = self._find_kind(source_id)
        if target_kind != "node" or source_kind != "node":
            raise KGStoreError("merge_nodes operates on nodes only")
        for label, row in (("target", target), ("source", source)):
            if row["status"] not in ("proposed", "verified"):
                raise KGStoreError(
                    f"{label} node {row['id']} is {row['status']!r}; "
                    "only proposed/verified nodes can be merged"
                )
        if target["entity_type"] != source["entity_type"]:
            raise KGStoreError(
                f"cannot merge across entity types "
                f"({source['entity_type']!r} -> {target['entity_type']!r})"
            )
        if source["status"] == "verified" and target["status"] != "verified":
            raise KGStoreError(
                "cannot merge a verified node into a proposed one — merge in "
                "the other direction, or approve the target first"
            )

        # Validate the complete prospective mutation before changing aliases,
        # properties, citations, or endpoints. Each existing row is checked
        # against its own immutable schema version, not whichever is active.
        try:
            target_properties = json.loads(target["properties_json"] or "{}")
            source_properties = json.loads(source["properties_json"] or "{}")
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError("merge node has malformed properties") from exc
        if not isinstance(target_properties, dict) or not isinstance(
            source_properties, dict
        ):
            raise SchemaValidationError("merge node properties must be objects")
        self._validate_properties(
            schema_version_id=source["schema_version_id"],
            entity_type=source["entity_type"],
            properties=source_properties,
        )
        merged_properties = dict(target_properties)
        for prop_key, value in source_properties.items():
            merged_properties.setdefault(prop_key, value)
        self._validate_properties(
            schema_version_id=target["schema_version_id"],
            entity_type=target["entity_type"],
            properties=merged_properties,
        )
        prospective_edges = self.conn.execute(
            "SELECT * FROM edges WHERE (src_node_id = ? OR dst_node_id = ?) "
            f"AND status IN ('proposed','verified') AND {self._edge_current_sql()}",
            (source_id, source_id),
        ).fetchall()
        for edge in prospective_edges:
            src_id = target_id if edge["src_node_id"] == source_id else edge["src_node_id"]
            dst_id = target_id if edge["dst_node_id"] == source_id else edge["dst_node_id"]
            if src_id == dst_id:
                continue  # this edge is rejected rather than re-pointed
            endpoints = {
                row["id"]: row
                for row in self.conn.execute(
                    "SELECT id, schema_version_id, entity_type FROM nodes "
                    "WHERE id IN (?, ?)",
                    (src_id, dst_id),
                )
            }
            if len(endpoints) != 2:
                raise SchemaValidationError(
                    f"edge {edge['id']!r} has a missing merge endpoint"
                )
            src_node, dst_node = endpoints[src_id], endpoints[dst_id]
            if (
                src_node["schema_version_id"] != edge["schema_version_id"]
                or dst_node["schema_version_id"] != edge["schema_version_id"]
            ):
                raise SchemaValidationError(
                    f"edge {edge['id']!r} endpoints do not belong to its schema "
                    f"{edge['schema_version_id']}"
                )
            try:
                edge_properties = json.loads(edge["properties_json"] or "{}")
                edge_qualifiers = json.loads(edge["qualifiers_json"] or "{}")
            except (TypeError, ValueError) as exc:
                raise SchemaValidationError(
                    f"edge {edge['id']!r} has malformed properties or qualifiers"
                ) from exc
            self._validate_relation(
                schema_version_id=edge["schema_version_id"],
                relation_type=edge["relation_type"],
                src_type=src_node["entity_type"],
                dst_type=dst_node["entity_type"],
                properties=edge_properties,
                qualifiers=edge_qualifiers,
            )

        now = time.time()
        report: dict[str, Any] = {
            "target_id": target_id,
            "source_id": source_id,
            "edges_repointed": 0,
            "edges_deduplicated": 0,
            "edges_self_loop_rejected": 0,
        }

        # 1) Alias/property union into the target (non-destructive).
        aliases = json.loads(target["aliases_json"])
        known = {normalize_name(a) for a in aliases}
        known.add(target["normalized_name"])
        source_surfaces = [source["name"], *json.loads(source["aliases_json"])]
        source_surfaces.extend(
            r["surface"]
            for r in self.conn.execute(
                "SELECT surface FROM node_aliases WHERE node_id = ?", (source_id,)
            )
        )
        changed = False
        for surface in source_surfaces:
            key = normalize_name(surface)
            if key and key not in known:
                aliases.append(surface)
                known.add(key)
                changed = True
            self._add_alias(target_id, surface)

        properties = json.loads(target["properties_json"])
        for prop_key, value in json.loads(source["properties_json"]).items():
            if prop_key not in properties:
                properties[prop_key] = value
                changed = True

        if changed:
            # The embedding no longer matches the merged text: clear it so the
            # next `ontologylab embed` refreshes it (never silently stale).
            self.conn.execute(
                "UPDATE nodes SET aliases_json = ?, properties_json = ?, "
                "embedding = NULL, embedding_model = NULL WHERE id = ?",
                (json.dumps(aliases), json.dumps(properties), target_id),
            )

        # 2) Citations follow the surviving node.
        self.conn.execute(
            "UPDATE citations SET item_id = ? WHERE kind = 'node' AND item_id = ?",
            (target_id, source_id),
        )

        # 3) Re-point edges, collapsing duplicates and dropping self-loops.
        sv_id = source["schema_version_id"]
        edge_rows = self.conn.execute(
            "SELECT * FROM edges WHERE (src_node_id = ? OR dst_node_id = ?) "
            f"AND status IN ('proposed','verified') AND {self._edge_current_sql()}",
            (source_id, source_id),
        ).fetchall()
        for edge in edge_rows:
            new_src = target_id if edge["src_node_id"] == source_id else edge["src_node_id"]
            new_dst = target_id if edge["dst_node_id"] == source_id else edge["dst_node_id"]
            if new_src == new_dst:
                self._set_status(
                    "edge", edge["id"], "rejected",
                    by=by, note=f"self-loop after merge into {target_id}",
                )
                report["edges_self_loop_rejected"] += 1
                continue
            dup = self.conn.execute(
                "SELECT id FROM edges WHERE schema_version_id = ? AND "
                "relation_type = ? AND src_node_id = ? AND dst_node_id = ? AND "
                "status IN ('proposed','verified') AND id != ? AND "
                f"{self._edge_current_sql()}",
                (sv_id, edge["relation_type"], new_src, new_dst, edge["id"]),
            ).fetchone()
            if dup is not None:
                self.conn.execute(
                    "UPDATE citations SET item_id = ? "
                    "WHERE kind = 'edge' AND item_id = ?",
                    (dup["id"], edge["id"]),
                )
                self._set_status(
                    "edge", edge["id"], "rejected",
                    by=by, note=f"duplicate of {dup['id']} after merge",
                )
                report["edges_deduplicated"] += 1
            else:
                self.conn.execute(
                    "UPDATE edges SET src_node_id = ?, dst_node_id = ? WHERE id = ?",
                    (new_src, new_dst, edge["id"]),
                )
                report["edges_repointed"] += 1

        # 4) Tombstone the source (rejected = never served, kept for audit).
        self._set_status(
            "node", source_id, "rejected", by=by,
            note=note or f"merged-into:{target_id}",
        )
        self.conn.execute("DELETE FROM node_aliases WHERE node_id = ?", (source_id,))

        # 5) Bookkeeping on the candidate queue: the decided pair is 'merged';
        #    other pending pairs referencing the tombstoned source are 'stale'
        #    (bookkeeping only — no graph fact is auto-decided by this).
        a, b = self._canonical_pair(target_id, source_id)
        self.conn.execute(
            "UPDATE merge_candidates SET status = 'merged', decided_ts = ?, "
            "decided_by = ?, decision_note = ? "
            "WHERE node_a_id = ? AND node_b_id = ? AND status = 'proposed'",
            (now, by, note, a, b),
        )
        self.conn.execute(
            "UPDATE merge_candidates SET status = 'stale', decided_ts = ?, "
            "decided_by = ? WHERE status = 'proposed' "
            "AND (node_a_id = ? OR node_b_id = ?)",
            (now, f"system:merge-by:{by}", source_id, source_id),
        )
        self.conn.commit()
        return report
