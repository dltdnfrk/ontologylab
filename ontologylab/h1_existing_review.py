"""Exact classified Task 5 review lookup for H1 family linking."""

from __future__ import annotations

import sqlite3

from ontologylab.citation_ids import fact_revision_id
from ontologylab.grounded_review_ids import (
    citation_set_digest,
    historical_review_decision_id,
    review_decision_id,
)
from ontologylab.grounded_review_store import (
    current_decision_id,
    get_decision,
    list_decisions,
)
from ontologylab.grounded_review_types import ReviewAction, ReviewDecision
from ontologylab.h1_existing import has_table
from ontologylab.h1_existing_cite import expected_cite_ids, verified_citation
from ontologylab.h1_types import H1ReviewAnchor


def existing_review(
    conn: sqlite3.Connection, anchor: H1ReviewAnchor,
) -> ReviewDecision | None:
    action = _review_action(anchor.status)
    if action is None or anchor.decided_ts is None:
        return None
    if not has_table(conn, "grounded_review_decisions"):
        return None
    history = list_decisions(conn, anchor.fact_kind, anchor.fact_id)
    aligned = [
        item for item in history
        if item.actor == anchor.actor
        and item.reason == anchor.reason
        and item.decided_ts == anchor.decided_ts
        and item.as_of_ts == anchor.decided_ts
        and _review_id_ok(item)
        and _action_fits(item.action, action)
    ]
    cite_ids = expected_cite_ids(conn, anchor.fact_kind, anchor.fact_id)
    if not cite_ids:
        return None
    grounding = _grounding_from_cites(conn, cite_ids)
    if grounding is None:
        return None
    pointed_id = current_decision_id(conn, anchor.fact_kind, anchor.fact_id)
    if pointed_id is not None:
        pointed = get_decision(conn, pointed_id)
        if (
            pointed is not None
            and pointed in aligned
            and _review_matches(pointed, anchor, action, cite_ids, grounding)
        ):
            return pointed
    found = [
        item for item in aligned
        if _review_matches(item, anchor, action, cite_ids, grounding)
    ]
    if len(found) == 1:
        return found[0]
    return None


def _grounding_from_cites(
    conn: sqlite3.Connection, cite_ids: tuple[str, ...],
) -> tuple[str | None, str | None, str | None] | None:
    selections: set[str | None] = set()
    policies: set[str | None] = set()
    runs: set[str] = set()
    for receipt_id in cite_ids:
        loaded = verified_citation(conn, receipt_id)
        if loaded is None:
            return None
        selections.add(loaded.selection_receipt_id)
        policies.add(loaded.policy_identity)
        runs.add(loaded.run_receipt_id)
    if len(selections) != 1 or len(policies) != 1 or len(runs) != 1:
        return None
    return next(iter(selections)), next(iter(policies)), next(iter(runs))


def _review_matches(
    item: ReviewDecision,
    anchor: H1ReviewAnchor,
    action: ReviewAction,
    cite_ids: tuple[str, ...],
    grounding: tuple[str | None, str | None, str | None],
) -> bool:
    if not _action_fits(item.action, action):
        return False
    if item.fact_revision != fact_revision_id(anchor.fact_kind, anchor.fact_id):
        return False
    if item.actor != anchor.actor or item.reason != anchor.reason:
        return False
    if item.decided_ts != anchor.decided_ts or item.as_of_ts != anchor.decided_ts:
        return False
    if item.citation_receipt_ids != tuple(sorted(cite_ids)):
        return False
    if item.citation_set_digest != citation_set_digest(cite_ids):
        return False
    if (
        anchor.representation_id is not None
        and item.representation_id != anchor.representation_id
    ):
        return False
    if item.selection_receipt_id != grounding[0]:
        return False
    if item.policy_identity != grounding[1]:
        return False
    if item.run_receipt_id != grounding[2]:
        return False
    if item.action is ReviewAction.APPROVE_WITH_GROUNDING_WAIVER:
        return item.pack_ineligible and bool(item.scoped_defects)
    if item.predecessor_receipt_id is not None:
        return False
    if item.pack_ineligible:
        return False
    return not (
        item.waived_fact_ids or item.waived_citation_ids or item.scoped_defects
    )


def _action_fits(stored: ReviewAction, classified: ReviewAction) -> bool:
    if stored is classified:
        return True
    if classified is ReviewAction.APPROVE:
        return stored is ReviewAction.APPROVE_WITH_GROUNDING_WAIVER
    return False


def _review_id_ok(item: ReviewDecision) -> bool:
    v1 = historical_review_decision_id(
        fact_kind=item.fact_kind,
        fact_id=item.fact_id,
        fact_revision=item.fact_revision,
        action=item.action,
        digest_value=item.citation_set_digest,
        actor=item.actor,
        reason=item.reason,
        predecessor_receipt_id=item.predecessor_receipt_id,
        waived_fact_ids=item.waived_fact_ids,
        waived_citation_ids=item.waived_citation_ids,
        scoped_defects=item.scoped_defects,
    )
    v2 = review_decision_id(
        fact_kind=item.fact_kind,
        fact_id=item.fact_id,
        fact_revision=item.fact_revision,
        action=item.action,
        digest_value=item.citation_set_digest,
        actor=item.actor,
        reason=item.reason,
        predecessor_receipt_id=item.predecessor_receipt_id,
        representation_id=item.representation_id,
        selection_receipt_id=item.selection_receipt_id,
        policy_identity=item.policy_identity,
        run_receipt_id=item.run_receipt_id,
        pack_ineligible=item.pack_ineligible,
        decided_ts=item.decided_ts,
        as_of_ts=item.as_of_ts,
        waived_fact_ids=item.waived_fact_ids,
        waived_citation_ids=item.waived_citation_ids,
        scoped_defects=item.scoped_defects,
    )
    return item.receipt_id in {v1, v2}


def _review_action(status: str) -> ReviewAction | None:
    match status:
        case "verified" | "proposed":
            return ReviewAction.APPROVE
        case "rejected":
            return ReviewAction.REJECT
        case _:
            return None
