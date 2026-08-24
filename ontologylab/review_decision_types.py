"""Typed review-decision values and grounding refusal codes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import NoReturn


@unique
class DecisionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    WAIVER = "waiver"


@unique
class GroundingClass(StrEnum):
    GROUNDED = "grounded"
    UNGROUNDED = "ungrounded"
    WAIVED = "waived"


@unique
class PublicationClass(StrEnum):
    SOURCED = "sourced"
    WORKING_ONLY = "working_only"


@unique
class ReviewRefusalCode(StrEnum):
    UNGROUNDED_MEMBER = "ungrounded_member"
    ROOT_ONLY_CASCADE = "root_only_cascade"
    MISSING_REASON = "missing_reason"
    EMPTY_IDS = "empty_ids"
    UNKNOWN_ITEM = "unknown_item"
    INVALID_TRANSITION = "invalid_transition"
    GENERIC_IS_NOT_WAIVER = "generic_is_not_waiver"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class ReviewRefused(Exception):
    code: ReviewRefusalCode
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class MemberGrounding:
    fact_kind: str
    fact_id: str
    fact_revision: str
    grounding_class: GroundingClass
    citation_set_hash: str
    citation_receipt_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    decision_id: str
    decision_kind: str
    fact_kind: str
    fact_id: str
    fact_revision: str
    citation_set_hash: str
    grounding_class: str
    actor: str
    reason: str | None
    batch_id: str
    member_ids: tuple[str, ...]
    created: bool


@dataclass(frozen=True, slots=True)
class ReviewBatchResult:
    decision_kind: str
    batch_id: str
    approved_ids: tuple[str, ...]
    decisions: tuple[ReviewDecision, ...]
    publication_class: str


def refuse(code: ReviewRefusalCode, message: str) -> NoReturn:
    raise ReviewRefused(code, message)
