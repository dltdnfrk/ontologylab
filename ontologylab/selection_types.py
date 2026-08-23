"""Typed F9 preferred-representation selection values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, NoReturn


POLICY_V1: Final = "preferred-representation-v1"
POLICY_V2: Final = "preferred-representation-v2"
NOT_READY: Final = "not_ready"


@unique
class PolicyVersion(StrEnum):
    V1 = POLICY_V1
    V2 = POLICY_V2


@unique
class ReadyState(StrEnum):
    READY = "ready"
    STAGED = "staged"
    QUARANTINED = "quarantined"
    OTHER = "other"


@unique
class ContentKind(StrEnum):
    FULLTEXT = "fulltext"
    ABSTRACT = "abstract"
    EXCERPT = "excerpt"
    METADATA_ONLY = "metadata_only"


@unique
class EvidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


@unique
class PublicationStage(StrEnum):
    PUBLISHED = "published"
    ACCEPTED = "accepted"
    SUBMITTED = "submitted"
    UNKNOWN = "unknown"


@unique
class SourceTier(StrEnum):
    PUBLISHER = "publisher"
    PMC = "pmc"
    REGISTRY = "registry"
    AGGREGATOR = "aggregator"
    WEB = "web"
    UPLOAD = "upload"
    SAMPLE = "sample"
    OTHER = "other"


@unique
class SelectionRefusalCode(StrEnum):
    NO_ELIGIBLE_READY_FULL_TEXT = "no_eligible_ready_full_text"
    UNKNOWN_WORK = "unknown_work"
    MISSING_BINDING = "missing_binding"


@dataclass(frozen=True, slots=True)
class SelectionRefused(Exception):
    code: SelectionRefusalCode
    work_id: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class SelectionInventoryError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class RepresentationCandidate:
    representation_id: str
    content_hash: str
    byte_length: int
    stage: str
    kind: str
    source: str
    evidence_grade: str
    state: str


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    representation_id: str
    ready_rank: int
    usable_full_text_rank: int
    grade_rank: int
    source_rank: int
    stage_rank: int
    byte_length: int
    content_hash: str
    rejection_reason: str | None


@dataclass(frozen=True, slots=True)
class SelectionReceipt:
    receipt_id: str
    work_id: str
    policy_version: str
    policy_hash: str
    selected_representation_id: str | None
    selected_content_hash: str | None
    inventory: tuple[InventoryEntry, ...]
    created: bool


def refuse(
    code: SelectionRefusalCode, work_id: str, message: str,
) -> NoReturn:
    raise SelectionRefused(code, work_id, message)
