"""Caller-owned persistence for grounded ReviewDecision rows."""

from __future__ import annotations

import json
import sqlite3

from ontologylab.grounded_review_schema import ensure_grounded_review_schema
from ontologylab.grounded_review_types import (
    GroundedReviewRefusalCode,
    ReviewAction,
    ReviewDecision,
    refuse,
)


def persist_decision(conn: sqlite3.Connection, decision: ReviewDecision) -> None:
    ensure_grounded_review_schema(conn)
    if not decision.fact_revision.strip():
        refuse(
            GroundedReviewRefusalCode.MISSING_FACT_REVISION,
            "fact revision is required",
        )
    if not decision.citation_set_digest.strip():
        refuse(
            GroundedReviewRefusalCode.MISSING_CITATION_DIGEST,
            "citation-set digest is required",
        )
    if not decision.actor.strip() or not decision.reason.strip():
        code = (
            GroundedReviewRefusalCode.MISSING_ACTOR
            if not decision.actor.strip()
            else GroundedReviewRefusalCode.MISSING_REASON
        )
        refuse(code, f"{code} is required")
    existing = _get(conn, decision.receipt_id)
    if existing is not None:
        if _same_payload(existing, decision):
            return
        refuse(
            GroundedReviewRefusalCode.CONFLICT,
            "receipt id already stores a different ReviewDecision payload",
        )
    conn.execute(
        "INSERT INTO grounded_review_decisions ("
        "receipt_id, fact_kind, fact_id, proposal_id, fact_revision, action, "
        "actor, reason, decided_ts, as_of_ts, citation_set_digest, "
        "citation_receipt_ids_json, representation_id, selection_receipt_id, "
        "policy_identity, run_receipt_id, predecessor_receipt_id, "
        "pack_ineligible, waived_fact_ids_json, waived_citation_ids_json, "
        "scoped_defects_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            decision.receipt_id,
            decision.fact_kind,
            decision.fact_id,
            decision.proposal_id,
            decision.fact_revision,
            decision.action.value,
            decision.actor,
            decision.reason,
            decision.decided_ts,
            decision.as_of_ts,
            decision.citation_set_digest,
            json.dumps(decision.citation_receipt_ids),
            decision.representation_id,
            decision.selection_receipt_id,
            decision.policy_identity,
            decision.run_receipt_id,
            decision.predecessor_receipt_id,
            1 if decision.pack_ineligible else 0,
            json.dumps(decision.waived_fact_ids),
            json.dumps(decision.waived_citation_ids),
            json.dumps(decision.scoped_defects),
        ),
    )


def list_decisions(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> tuple[ReviewDecision, ...]:
    ensure_grounded_review_schema(conn)
    rows = conn.execute(
        "SELECT * FROM grounded_review_decisions "
        "WHERE fact_kind = ? AND fact_id = ? "
        "ORDER BY as_of_ts ASC, receipt_id ASC",
        (fact_kind, fact_id),
    ).fetchall()
    return tuple(_row_decision(row) for row in rows)


def decisions_as_of(
    conn: sqlite3.Connection,
    fact_kind: str,
    fact_id: str,
    as_of_ts: float,
) -> tuple[ReviewDecision, ...]:
    ensure_grounded_review_schema(conn)
    rows = conn.execute(
        "SELECT * FROM grounded_review_decisions "
        "WHERE fact_kind = ? AND fact_id = ? AND as_of_ts <= ? "
        "ORDER BY as_of_ts ASC, receipt_id ASC",
        (fact_kind, fact_id, as_of_ts),
    ).fetchall()
    return tuple(_row_decision(row) for row in rows)


def get_decision(
    conn: sqlite3.Connection, receipt_id: str,
) -> ReviewDecision | None:
    ensure_grounded_review_schema(conn)
    return _get(conn, receipt_id)


def current_decision_id(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> str | None:
    ensure_grounded_review_schema(conn)
    row = conn.execute(
        "SELECT receipt_id FROM grounded_review_current "
        "WHERE fact_kind = ? AND fact_id = ?",
        (fact_kind, fact_id),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def set_current_decision(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str, receipt_id: str,
) -> None:
    ensure_grounded_review_schema(conn)
    existing = conn.execute(
        "SELECT receipt_id FROM grounded_review_current "
        "WHERE fact_kind = ? AND fact_id = ?",
        (fact_kind, fact_id),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO grounded_review_current "
            "(fact_kind, fact_id, receipt_id) VALUES (?,?,?)",
            (fact_kind, fact_id, receipt_id),
        )
        return
    if str(existing[0]) == receipt_id:
        return
    conn.execute(
        "UPDATE grounded_review_current SET receipt_id = ? "
        "WHERE fact_kind = ? AND fact_id = ?",
        (receipt_id, fact_kind, fact_id),
    )


def latest_decision(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> ReviewDecision | None:
    rows = list_decisions(conn, fact_kind, fact_id)
    if not rows:
        return None
    return rows[-1]


def apply_derived_status(
    conn: sqlite3.Connection,
    kind: str,
    item_id: str,
    status: str,
    actor: str,
    note: str,
    now: float,
) -> None:
    table = "nodes" if kind == "node" else "edges"
    conn.execute(
        f"UPDATE {table} SET status = ?, verified_ts = ?, verified_by = ?, "
        "review_note = COALESCE(?, review_note) WHERE id = ?",
        (status, now, actor, note, item_id),
    )


def _row_decision(row: sqlite3.Row) -> ReviewDecision:
    return ReviewDecision(
        receipt_id=str(row["receipt_id"]),
        fact_kind=str(row["fact_kind"]),
        fact_id=str(row["fact_id"]),
        proposal_id=str(row["proposal_id"]),
        fact_revision=str(row["fact_revision"]),
        action=ReviewAction(str(row["action"])),
        actor=str(row["actor"]),
        reason=str(row["reason"]),
        decided_ts=float(row["decided_ts"]),
        as_of_ts=float(row["as_of_ts"]),
        citation_set_digest=str(row["citation_set_digest"]),
        citation_receipt_ids=tuple(json.loads(row["citation_receipt_ids_json"])),
        representation_id=_opt(row["representation_id"]),
        selection_receipt_id=_opt(row["selection_receipt_id"]),
        policy_identity=_opt(row["policy_identity"]),
        run_receipt_id=_opt(row["run_receipt_id"]),
        predecessor_receipt_id=_opt(row["predecessor_receipt_id"]),
        pack_ineligible=bool(row["pack_ineligible"]),
        waived_fact_ids=tuple(json.loads(row["waived_fact_ids_json"])),
        waived_citation_ids=tuple(json.loads(row["waived_citation_ids_json"])),
        scoped_defects=tuple(json.loads(row["scoped_defects_json"])),
    )


def _opt(value: str | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _get(conn: sqlite3.Connection, receipt_id: str) -> ReviewDecision | None:
    row = conn.execute(
        "SELECT * FROM grounded_review_decisions WHERE receipt_id = ?",
        (receipt_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_decision(row)


def _same_payload(left: ReviewDecision, right: ReviewDecision) -> bool:
    return (
        left.receipt_id == right.receipt_id
        and left.fact_kind == right.fact_kind
        and left.fact_id == right.fact_id
        and left.proposal_id == right.proposal_id
        and left.fact_revision == right.fact_revision
        and left.action is right.action
        and left.actor == right.actor
        and left.reason == right.reason
        and left.decided_ts == right.decided_ts
        and left.as_of_ts == right.as_of_ts
        and left.citation_set_digest == right.citation_set_digest
        and left.citation_receipt_ids == right.citation_receipt_ids
        and left.representation_id == right.representation_id
        and left.selection_receipt_id == right.selection_receipt_id
        and left.policy_identity == right.policy_identity
        and left.run_receipt_id == right.run_receipt_id
        and left.predecessor_receipt_id == right.predecessor_receipt_id
        and left.pack_ineligible is right.pack_ineligible
        and left.waived_fact_ids == right.waived_fact_ids
        and left.waived_citation_ids == right.waived_citation_ids
        and left.scoped_defects == right.scoped_defects
    )
