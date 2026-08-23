"""All-member cascade preflight for grounded ReviewDecision."""

from __future__ import annotations

import sqlite3
from typing import assert_never

from ontologylab.citation import CitationReceipt, CitationRefused, list_citation_receipts
from ontologylab.citation_ids import fact_revision_id
from ontologylab.grounded_review_types import (
    GroundedReviewRefusalCode,
    ReviewAction,
    ReviewMember,
    refuse,
)


def load_item(conn: sqlite3.Connection, item_id: str) -> ReviewMember:
    node = conn.execute("SELECT * FROM nodes WHERE id = ?", (item_id,)).fetchone()
    if node is not None:
        return ReviewMember("node", item_id, str(node["status"]), None, None)
    edge = conn.execute("SELECT * FROM edges WHERE id = ?", (item_id,)).fetchone()
    if edge is not None:
        return ReviewMember(
            "edge",
            item_id,
            str(edge["status"]),
            str(edge["src_node_id"]),
            str(edge["dst_node_id"]),
        )
    refuse(
        GroundedReviewRefusalCode.UNKNOWN_ITEM,
        f"no node or edge with id {item_id!r}",
    )


def collect_members(
    conn: sqlite3.Connection,
    item_id: str,
    action: ReviewAction,
    *,
    cascade: bool,
) -> tuple[ReviewMember, ...]:
    root = load_item(conn, item_id)
    _assert_transition(root, action)
    match action:
        case ReviewAction.APPROVE | ReviewAction.APPROVE_WITH_GROUNDING_WAIVER:
            return _approval_members(conn, root, cascade=cascade)
        case (
            ReviewAction.REJECT
            | ReviewAction.QUARANTINE
            | ReviewAction.RETRACT
            | ReviewAction.COMPENSATE
        ):
            return (root,)
        case unreachable:
            assert_never(unreachable)


def citations_for(
    conn: sqlite3.Connection, member: ReviewMember,
) -> tuple[CitationReceipt, ...]:
    try:
        return list_citation_receipts(conn, member.kind, member.item_id)
    except CitationRefused as exc:
        refuse(
            GroundedReviewRefusalCode.CITATION_UNGROUNDED,
            str(exc),
            (member.item_id,),
        )


def require_grounding(
    conn: sqlite3.Connection, members: tuple[ReviewMember, ...],
) -> dict[str, tuple[CitationReceipt, ...]]:
    found: dict[str, tuple[CitationReceipt, ...]] = {}
    invalid: list[str] = []
    for member in members:
        receipts = citations_for(conn, member)
        found[member.item_id] = receipts
        if not receipts:
            invalid.append(member.item_id)
    if invalid:
        refuse(
            GroundedReviewRefusalCode.MISSING_CITATION,
            "every member needs a resolvable Citation receipt",
            tuple(invalid),
        )
    return found


def member_revision(
    member: ReviewMember, receipts: tuple[CitationReceipt, ...],
) -> str:
    expected = fact_revision_id(member.kind, member.item_id)
    if not receipts:
        return expected
    revisions = {item.fact_revision for item in receipts}
    if len(revisions) != 1:
        refuse(
            GroundedReviewRefusalCode.INVALID_MEMBER,
            f"{member.item_id} has mixed fact revisions",
            (member.item_id,),
        )
    return next(iter(revisions))


def grounding_identities(
    receipts: tuple[CitationReceipt, ...],
) -> tuple[str | None, str | None, str | None, str | None]:
    if not receipts:
        return None, None, None, None
    representations = {item.representation_id for item in receipts}
    selections = {item.selection_receipt_id for item in receipts}
    policies = {item.policy_identity for item in receipts}
    runs = {item.run_receipt_id for item in receipts}
    return (
        _single(representations),
        _single(selections),
        _single(policies),
        _single(runs),
    )


def _single(values: set[str] | set[str | None]) -> str | None:
    if len(values) == 1:
        return next(iter(values))
    return None


def _approval_members(
    conn: sqlite3.Connection, root: ReviewMember, *, cascade: bool,
) -> tuple[ReviewMember, ...]:
    if root.kind != "edge":
        return (root,)
    assert root.src_node_id is not None
    assert root.dst_node_id is not None
    pending: list[ReviewMember] = []
    for endpoint_id in (root.src_node_id, root.dst_node_id):
        endpoint = load_item(conn, endpoint_id)
        if endpoint.status == "verified":
            continue
        if cascade and endpoint.status == "proposed":
            pending.append(endpoint)
            continue
        if cascade:
            refuse(
                GroundedReviewRefusalCode.INVALID_TRANSITION,
                f"edge {root.item_id} endpoint {endpoint_id} is "
                f"{endpoint.status!r}; cascade only promotes "
                "proposed endpoints — reopen it first",
                (endpoint_id,),
            )
        refuse(
            GroundedReviewRefusalCode.ENDPOINT_NOT_VERIFIED,
            f"edge {root.item_id} endpoint {endpoint_id} is "
            f"{endpoint.status!r}; approve endpoints first",
            (endpoint_id,),
        )
    pending.append(root)
    return tuple(pending)


def _assert_transition(member: ReviewMember, action: ReviewAction) -> None:
    match action:
        case (
            ReviewAction.APPROVE
            | ReviewAction.APPROVE_WITH_GROUNDING_WAIVER
            | ReviewAction.REJECT
            | ReviewAction.QUARANTINE
        ):
            allowed = "proposed"
        case ReviewAction.RETRACT:
            allowed = "verified"
        case ReviewAction.COMPENSATE:
            if member.status in {"verified", "rejected"}:
                return
            refuse(
                GroundedReviewRefusalCode.INVALID_TRANSITION,
                f"cannot compensate a {member.status!r} item",
                (member.item_id,),
            )
        case unreachable:
            assert_never(unreachable)
    if member.status != allowed:
        refuse(
            GroundedReviewRefusalCode.INVALID_TRANSITION,
            f"cannot {action} a {member.status!r} item; reopen it first",
            (member.item_id,),
        )
