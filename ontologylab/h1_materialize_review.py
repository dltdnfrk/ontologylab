"""Materialize one grounded ReviewDecision for a verified H1 review."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from ontologylab.citation_ids import fact_revision_id
from ontologylab.grounded_review_ids import build_decision
from ontologylab.grounded_review_store import persist_decision
from ontologylab.grounded_review_types import ReviewAction, ReviewDecision
from ontologylab.h1_existing_review import existing_review
from ontologylab.h1_ids import LEGACY_POLICY
from ontologylab.h1_types import H1ReviewAnchor


def materialize_review(
    conn: sqlite3.Connection, anchor: H1ReviewAnchor,
) -> ReviewDecision | None:
    if anchor.decided_ts is None:
        return None
    action = _review_action(anchor.status)
    if action is None:
        return None
    existing = existing_review(conn, anchor)
    if existing is not None:
        return existing
    cite_ids = tuple(
        str(row[0])
        for row in conn.execute(
            "SELECT receipt_id FROM citation_receipts "
            "WHERE fact_kind = ? AND fact_id = ? ORDER BY receipt_id",
            (anchor.fact_kind, anchor.fact_id),
        )
    )
    if not cite_ids:
        return None
    identities = conn.execute(
        "SELECT representation_id, run_receipt_id FROM citation_receipts "
        "WHERE fact_kind = ? AND fact_id = ? ORDER BY receipt_id",
        (anchor.fact_kind, anchor.fact_id),
    ).fetchall()
    decision = build_decision(
        fact_kind=anchor.fact_kind,
        fact_id=anchor.fact_id,
        fact_revision=fact_revision_id(anchor.fact_kind, anchor.fact_id),
        action=action,
        actor=anchor.actor,
        reason=anchor.reason,
        now=anchor.decided_ts,
        citation_ids=cite_ids,
        representation_id=_unique(str(row[0]) for row in identities),
        selection_receipt_id=None,
        policy_identity=LEGACY_POLICY,
        run_receipt_id=_unique(str(row[1]) for row in identities),
        predecessor_receipt_id=None,
        pack_ineligible=False,
    )
    persist_decision(conn, decision)
    return decision


def _review_action(status: str) -> ReviewAction | None:
    match status:
        case "verified" | "proposed":
            return ReviewAction.APPROVE
        case "rejected":
            return ReviewAction.REJECT
        case _:
            return None


def _unique(values: Iterable[str]) -> str | None:
    items = tuple(dict.fromkeys(values))
    if len(items) == 1:
        return items[0]
    return None
