"""Public append-only grounded ReviewDecision API."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import Final, TypeVar

from ontologylab.citation import CitationReceipt
from ontologylab.grounded_review_ids import build_decision
from ontologylab.grounded_review_payload import (
    batch_payload as batch_payload,
    machine_receipt as machine_receipt,
)
from ontologylab.grounded_review_preflight import (
    citations_for,
    collect_members,
    grounding_identities,
    member_revision,
    require_grounding,
)
from ontologylab.grounded_review_schema import (
    ensure_grounded_review_schema as ensure_grounded_review_schema,
)
from ontologylab.grounded_review_store import (
    apply_derived_status,
    decisions_as_of as decisions_as_of,
    latest_decision,
    list_decisions,
    persist_decision,
)
from ontologylab.grounded_review_types import (
    GroundedReviewRefusalCode as GroundedReviewRefusalCode,
    GroundedReviewRefused as GroundedReviewRefused,
    ReviewAction as ReviewAction,
    ReviewBatchResult as ReviewBatchResult,
    ReviewDecision as ReviewDecision,
    ReviewMember,
    ReviewRequest as ReviewRequest,
    WaiverRequest as WaiverRequest,
    derived_status,
    refuse,
)


_SAVEPOINT: Final = "grounded_review_v1"
_T = TypeVar("_T")


def list_review_decisions(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> tuple[ReviewDecision, ...]:
    return list_decisions(conn, fact_kind, fact_id)


def apply_review(
    conn: sqlite3.Connection, request: ReviewRequest,
) -> ReviewBatchResult:
    """Append decisions and update derived status inside a caller SAVEPOINT."""
    return _with_savepoint(conn, lambda: _apply(conn, request))


def approve_with_grounding_waiver(
    conn: sqlite3.Connection, request: WaiverRequest,
) -> ReviewBatchResult:
    """Scoped waiver: named members only, always default-pack-ineligible."""
    return _with_savepoint(conn, lambda: _waive(conn, request))


def _apply(conn: sqlite3.Connection, request: ReviewRequest) -> ReviewBatchResult:
    _require_actor_reason(request.actor, request.reason)
    members = collect_members(
        conn, request.item_id, request.action, cascade=request.cascade,
    )
    now = request.now if request.now is not None else time.time()
    require = _should_require(request, conn, members)
    citations = (
        require_grounding(conn, members)
        if require
        else {member.item_id: citations_for(conn, member) for member in members}
    )
    return _write_batch(
        conn,
        members,
        request.action,
        request.actor,
        request.reason,
        now,
        citations,
        pack_ineligible=False,
    )


def _waive(conn: sqlite3.Connection, request: WaiverRequest) -> ReviewBatchResult:
    _require_actor_reason(request.actor, request.reason)
    if not request.member_ids or not request.scoped_defects:
        refuse(
            GroundedReviewRefusalCode.GENERIC_WAIVER,
            "waiver must name member ids and scoped defects",
        )
    members = collect_members(
        conn,
        request.item_id,
        ReviewAction.APPROVE_WITH_GROUNDING_WAIVER,
        cascade=request.cascade,
    )
    needed = {member.item_id for member in members}
    named = set(request.member_ids)
    if needed - named:
        refuse(
            GroundedReviewRefusalCode.UNSCOPED_WAIVER,
            "waiver member ids must include every cascade member",
            tuple(sorted(needed - named)),
        )
    extra = named - needed
    if extra:
        refuse(
            GroundedReviewRefusalCode.UNSCOPED_WAIVER,
            "waiver cannot name facts outside this decision",
            tuple(sorted(extra)),
        )
    now = request.now if request.now is not None else time.time()
    citations = {
        member.item_id: citations_for(conn, member) for member in members
    }
    return _write_batch(
        conn,
        members,
        ReviewAction.APPROVE_WITH_GROUNDING_WAIVER,
        request.actor,
        request.reason,
        now,
        citations,
        pack_ineligible=True,
        waived_fact_ids=tuple(sorted(named)),
        waived_citation_ids=tuple(sorted(request.citation_ids)),
        scoped_defects=request.scoped_defects,
    )


def _write_batch(
    conn: sqlite3.Connection,
    members: tuple[ReviewMember, ...],
    action: ReviewAction,
    actor: str,
    reason: str,
    now: float,
    citations: dict[str, tuple[CitationReceipt, ...]],
    *,
    pack_ineligible: bool,
    waived_fact_ids: tuple[str, ...] = (),
    waived_citation_ids: tuple[str, ...] = (),
    scoped_defects: tuple[str, ...] = (),
) -> ReviewBatchResult:
    status = derived_status(action)
    written: list[ReviewDecision] = []
    for member in members:
        receipts = citations[member.item_id]
        citation_ids = tuple(item.receipt_id for item in receipts)
        representation, selection, policy, run = grounding_identities(receipts)
        predecessor = latest_decision(conn, member.kind, member.item_id)
        decision = build_decision(
            fact_kind=member.kind,
            fact_id=member.item_id,
            fact_revision=member_revision(member, receipts),
            action=action,
            actor=actor,
            reason=reason,
            now=now,
            citation_ids=citation_ids,
            representation_id=representation,
            selection_receipt_id=selection,
            policy_identity=policy,
            run_receipt_id=run,
            predecessor_receipt_id=(
                None if predecessor is None else predecessor.receipt_id
            ),
            pack_ineligible=pack_ineligible,
            waived_fact_ids=waived_fact_ids,
            waived_citation_ids=waived_citation_ids,
            scoped_defects=scoped_defects,
        )
        persist_decision(conn, decision)
        apply_derived_status(
            conn, member.kind, member.item_id, status, actor, reason, now,
        )
        written.append(decision)
    return ReviewBatchResult(
        kind=members[-1].kind,
        item_ids=tuple(member.item_id for member in members),
        decisions=tuple(written),
    )


def _should_require(
    request: ReviewRequest,
    conn: sqlite3.Connection,
    members: tuple[ReviewMember, ...],
) -> bool:
    if request.require_citations is not None:
        return request.require_citations
    if request.action is not ReviewAction.APPROVE:
        return False
    return any(citations_for(conn, member) for member in members)


def _require_actor_reason(actor: str, reason: str) -> None:
    if not actor.strip():
        refuse(GroundedReviewRefusalCode.MISSING_ACTOR, "actor is required")
    if not reason.strip():
        refuse(GroundedReviewRefusalCode.MISSING_REASON, "reason is required")


def _with_savepoint(
    conn: sqlite3.Connection, action: Callable[[], _T],
) -> _T:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    try:
        result = action()
    except (GroundedReviewRefused, sqlite3.Error):
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
    return result
