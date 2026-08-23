"""Typed citation receipt values and refusal codes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import NoReturn

from ontologylab.models import ProposedEntity, ProposedRelation


@unique
class FactKind(StrEnum):
    NODE = "node"
    EDGE = "edge"


@unique
class CitationRefusalCode(StrEnum):
    MISSING_BINDING = "missing_binding"
    INVALID_RANGE = "invalid_range"
    INVALID_HASH = "invalid_hash"
    INVALID_PROFILE = "invalid_profile"
    INVALID_TEXT = "invalid_text"
    CROSS_BIND = "cross_bind"
    CONFLICT = "conflict"
    NOT_READY = "not_ready"
    UNKNOWN_REPRESENTATION = "unknown_representation"
    MISSING_RECEIPT = "missing_receipt"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class CitationRefused(Exception):
    code: CitationRefusalCode
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class CitationBinding:
    representation_id: str
    representation_content_hash: str
    run_receipt_id: str
    chunk_receipt_id: str
    chunk_start_offset: int
    chunk_end_offset: int
    coordinate_profile: str
    chunk_text_hash: str
    chunk_plan_receipt_id: str
    selection_receipt_id: str | None
    policy_identity: str | None
    fact_kind: str
    fact_id: str
    proposal_id: str
    fact_revision: str
    start_offset: int
    end_offset: int
    selected_text: str
    selected_text_hash: str


@dataclass(frozen=True, slots=True)
class CitationReceipt:
    receipt_id: str
    representation_id: str
    representation_content_hash: str
    run_receipt_id: str
    chunk_receipt_id: str
    chunk_start_offset: int
    chunk_end_offset: int
    coordinate_profile: str
    chunk_text_hash: str
    chunk_plan_receipt_id: str
    selection_receipt_id: str | None
    policy_identity: str | None
    fact_kind: str
    fact_id: str
    proposal_id: str
    fact_revision: str
    start_offset: int
    end_offset: int
    selected_text: str
    selected_text_hash: str
    created: bool


@dataclass(frozen=True, slots=True)
class ChunkCitationBatch:
    representation_id: str
    chunk_index: int
    chunk_start_offset: int
    entities: tuple[ProposedEntity, ...]
    relations: tuple[ProposedRelation, ...]
    id_map: Mapping[str, str]
    run_receipt_id: str | None = None
    chunk_receipt_id: str | None = None


def refuse(code: CitationRefusalCode, message: str) -> NoReturn:
    raise CitationRefused(code, message)
