"""Public review-decision API: grounded approve, cascade preflight, waiver."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from typing import Final, TypeVar

from ontologylab.review_decision_ids import review_batch_id
from ontologylab.review_decision_schema import (
    ensure_review_decision_schema as ensure_review_decision_schema,
)
from ontologylab.review_decision_store import (
    latest_decision as latest_decision,
    list_decisions_for_fact as list_decisions_for_fact,
    put_decisions,
)
from ontologylab.review_decision_types import (
    DecisionKind,
    GroundingClass,
    MemberGrounding,
    PublicationClass,
    ReviewBatchResult,
    ReviewDecision,
    ReviewRefusalCode,
    ReviewRefused,
    refuse,
)
from ontologylab.review_grounding import classify_member, default_publication_allows


_SAVEPOINT: Final = "review_decisions_v1"
_T = TypeVar("_T")


def preflight_members(
    conn: sqlite3.Connection,
    members: Sequence[tuple[str, str]],
) -> tuple[MemberGrounding, ...]:
    """Classify every member. Does not mutate."""
    return tuple(classify_member(conn, kind, fact_id) for kind, fact_id in members)


def assert_cascade_grounded(
    conn: sqlite3.Connection,
    members: Sequence[tuple[str, str]],
) -> tuple[MemberGrounding, ...]:
    """Refuse unless every cascade member is grounded.

    Validates every member before any caller write. Root-only validation is
    a named mutant: an edge alone must not pass when an endpoint is bare.
    """
    if not members:
        refuse(ReviewRefusalCode.EMPTY_IDS, "cascade requires at least one member")
    classified = preflight_members(conn, members)
    ungrounded = [
        m for m in classified if m.grounding_class is GroundingClass.UNGROUNDED
    ]
    if ungrounded:
        sample = ungrounded[0]
        refuse(
            ReviewRefusalCode.UNGROUNDED_MEMBER,
            f"ungrounded {sample.fact_kind} {sample.fact_id}; "
            "ordinary cascade writes zero — use approve_with_grounding_waiver "
            "with exact IDs",
        )
    return classified


def record_grounded_approval(
    conn: sqlite3.Connection,
    *,
    actor: str,
    members: Sequence[tuple[str, str]],
    note: str | None = None,
) -> ReviewBatchResult:
    """Append approve decisions for a preflighted grounded member set."""
    return _with_savepoint(
        conn,
        lambda: _record(
            conn,
            decision_kind=DecisionKind.APPROVE,
            actor=actor,
            reason=note,
            members=members,
            force_waived=False,
        ),
    )


def record_grounding_waiver(
    conn: sqlite3.Connection,
    *,
    actor: str,
    reason: str,
    members: Sequence[tuple[str, str]],
) -> ReviewBatchResult:
    """Append durable waiver decisions for exact IDs (working-graph only)."""
    if not reason or not reason.strip():
        refuse(ReviewRefusalCode.MISSING_REASON, "waiver requires a non-empty reason")
    if not members:
        refuse(ReviewRefusalCode.EMPTY_IDS, "waiver requires exact member IDs")
    return _with_savepoint(
        conn,
        lambda: _record(
            conn,
            decision_kind=DecisionKind.WAIVER,
            actor=actor,
            reason=reason.strip(),
            members=members,
            force_waived=True,
        ),
    )


def publication_class_for(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> str:
    if default_publication_allows(conn, fact_kind, fact_id):
        return PublicationClass.SOURCED.value
    return PublicationClass.WORKING_ONLY.value


def _record(
    conn: sqlite3.Connection,
    *,
    decision_kind: DecisionKind,
    actor: str,
    reason: str | None,
    members: Sequence[tuple[str, str]],
    force_waived: bool,
) -> ReviewBatchResult:
    ensure_review_decision_schema(conn)
    member_ids = tuple(fact_id for _kind, fact_id in members)
    batch_id = review_batch_id(
        decision_kind=decision_kind.value,
        actor=actor,
        member_ids=member_ids,
        reason=reason,
    )
    classified = preflight_members(conn, members)
    payload: list[tuple[str, str, str, str, GroundingClass]] = []
    for member in classified:
        if force_waived:
            grounding = GroundingClass.WAIVED
        elif member.grounding_class is GroundingClass.UNGROUNDED:
            refuse(
                ReviewRefusalCode.UNGROUNDED_MEMBER,
                f"ungrounded {member.fact_kind} {member.fact_id}",
            )
        else:
            grounding = GroundingClass.GROUNDED
        payload.append((
            member.fact_kind,
            member.fact_id,
            member.fact_revision,
            member.citation_set_hash,
            grounding,
        ))
    decisions = put_decisions(
        conn,
        batch_id=batch_id,
        decision_kind=decision_kind,
        actor=actor,
        reason=reason,
        members=tuple(payload),
        member_ids=member_ids,
    )
    publication = (
        PublicationClass.WORKING_ONLY.value
        if decision_kind is DecisionKind.WAIVER
        else PublicationClass.SOURCED.value
    )
    return ReviewBatchResult(
        decision_kind=decision_kind.value,
        batch_id=batch_id,
        approved_ids=member_ids,
        decisions=decisions,
        publication_class=publication,
    )


def _with_savepoint(
    conn: sqlite3.Connection, action: Callable[[], _T],
) -> _T:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    try:
        result = action()
    except (ReviewRefused, sqlite3.Error):
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
    return result


__all__ = [
    "DecisionKind",
    "GroundingClass",
    "PublicationClass",
    "ReviewBatchResult",
    "ReviewDecision",
    "ReviewRefusalCode",
    "ReviewRefused",
    "assert_cascade_grounded",
    "ensure_review_decision_schema",
    "latest_decision",
    "list_decisions_for_fact",
    "preflight_members",
    "publication_class_for",
    "record_grounded_approval",
    "record_grounding_waiver",
]
