"""Typed grounded ReviewDecision values and refusal codes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import NoReturn


@unique
class ReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    QUARANTINE = "quarantine"
    RETRACT = "retract"
    COMPENSATE = "compensate"
    APPROVE_WITH_GROUNDING_WAIVER = "approve_with_grounding_waiver"


@unique
class GroundedReviewRefusalCode(StrEnum):
    MISSING_ACTOR = "missing_actor"
    MISSING_REASON = "missing_reason"
    MISSING_FACT_REVISION = "missing_fact_revision"
    MISSING_CITATION_DIGEST = "missing_citation_digest"
    MISSING_CITATION = "missing_citation"
    INVALID_MEMBER = "invalid_member"
    INVALID_TRANSITION = "invalid_transition"
    UNKNOWN_ITEM = "unknown_item"
    ENDPOINT_NOT_VERIFIED = "endpoint_not_verified"
    GENERIC_WAIVER = "generic_waiver"
    UNSCOPED_WAIVER = "unscoped_waiver"
    CITATION_UNGROUNDED = "citation_ungrounded"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class GroundedReviewRefused(Exception):
    code: GroundedReviewRefusalCode
    message: str
    member_ids: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    receipt_id: str
    fact_kind: str
    fact_id: str
    proposal_id: str
    fact_revision: str
    action: ReviewAction
    actor: str
    reason: str
    decided_ts: float
    as_of_ts: float
    citation_set_digest: str
    citation_receipt_ids: tuple[str, ...]
    representation_id: str | None
    selection_receipt_id: str | None
    policy_identity: str | None
    run_receipt_id: str | None
    predecessor_receipt_id: str | None
    pack_ineligible: bool
    waived_fact_ids: tuple[str, ...]
    waived_citation_ids: tuple[str, ...]
    scoped_defects: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewMember:
    kind: str
    item_id: str
    status: str
    src_node_id: str | None
    dst_node_id: str | None


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    item_id: str
    actor: str
    reason: str
    action: ReviewAction
    cascade: bool = False
    require_citations: bool | None = None
    now: float | None = None


@dataclass(frozen=True, slots=True)
class WaiverRequest:
    item_id: str
    actor: str
    reason: str
    member_ids: tuple[str, ...]
    citation_ids: tuple[str, ...]
    scoped_defects: tuple[str, ...]
    cascade: bool = False
    now: float | None = None


@dataclass(frozen=True, slots=True)
class ReviewBatchResult:
    kind: str
    item_ids: tuple[str, ...]
    decisions: tuple[ReviewDecision, ...]


def refuse(
    code: GroundedReviewRefusalCode,
    message: str,
    member_ids: tuple[str, ...] = (),
) -> NoReturn:
    raise GroundedReviewRefused(code, message, member_ids)


def derived_status(action: ReviewAction) -> str:
    match action:
        case ReviewAction.APPROVE | ReviewAction.APPROVE_WITH_GROUNDING_WAIVER:
            return "verified"
        case (
            ReviewAction.REJECT
            | ReviewAction.QUARANTINE
            | ReviewAction.RETRACT
            | ReviewAction.COMPENSATE
        ):
            return "rejected"
        case unreachable:
            from typing import assert_never

            assert_never(unreachable)
