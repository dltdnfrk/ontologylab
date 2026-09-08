"""Immutable input and output values for post-extraction assessment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from ontologylab.research_spec import JsonValue


class SupportState(StrEnum):
    RECEIPT_LINKED = "receipt_linked"
    RECEIPT_MISSING = "receipt_missing"
    NOT_ASSESSED = "not_assessed"


class ContradictionState(StrEnum):
    NOT_OBSERVED = "not_observed"
    POTENTIAL_CONFLICT = "potential_conflict"
    NOT_ASSESSED = "not_assessed"


SupportResult: TypeAlias = tuple[
    SupportState,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]


@dataclass(frozen=True, slots=True)
class SemanticField:
    location: str
    semantic_key: str
    value: JsonValue


@dataclass(frozen=True, slots=True)
class FactRow:
    fact_kind: str
    fact_id: str
    schema_version_id: int
    type_name: str
    subject_key: str
    target_key: str | None
    source_document_id: str
    fields: tuple[SemanticField, ...]


@dataclass(frozen=True, slots=True)
class SingleValueRule:
    fact_kind: str
    type_name: str
    location: str
    semantic_key: str


@dataclass(frozen=True, slots=True)
class CitationRow:
    receipt_id: str
    fact_kind: str
    fact_id: str
    fact_revision: str
    representation_id: str
    representation_content_hash: str
    run_receipt_id: str
    chunk_receipt_id: str


@dataclass(frozen=True, slots=True)
class RunReceiptRow:
    receipt_id: str
    representation_id: str
    document_content_hash: str


@dataclass(frozen=True, slots=True)
class ChunkReceiptRow:
    receipt_id: str
    run_receipt_id: str


@dataclass(frozen=True, slots=True)
class DocumentRow:
    representation_id: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class ReceiptIssue:
    fact_kind: str
    fact_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ReceiptSnapshot:
    citations: tuple[CitationRow, ...]
    runs: tuple[RunReceiptRow, ...]
    chunks: tuple[ChunkReceiptRow, ...]
    documents: tuple[DocumentRow, ...]
    inventory_root_before: str | None
    inventory_root_after: str | None
    issues: tuple[ReceiptIssue, ...]


@dataclass(frozen=True, slots=True)
class AssessmentInput:
    facts: tuple[FactRow, ...]
    schema_rules: tuple[SingleValueRule, ...]
    receipts: ReceiptSnapshot


@dataclass(frozen=True, slots=True)
class AdvisoryRecord:
    proposed_fact_id: str
    fact_kind: str
    fact_revision: str
    fact_hash: str
    citation_receipt_ids: tuple[str, ...]
    extraction_run_receipt_ids: tuple[str, ...]
    extraction_chunk_receipt_ids: tuple[str, ...]
    support_state: SupportState
    contradiction_state: ContradictionState
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PostExtractionAssessment:
    records: tuple[AdvisoryRecord, ...]
    assessment_hash: str
