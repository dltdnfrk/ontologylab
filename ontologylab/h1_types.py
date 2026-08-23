"""Typed H1 historical receipt migration values and refusals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import NoReturn

from ontologylab.migration import MigrationError


@unique
class H1Family(StrEnum):
    RUN = "run"
    CHUNK = "chunk"
    CITATION = "citation"
    REVIEW = "review"


@unique
class H1Classification(StrEnum):
    VERIFIED = "verified"
    QUARANTINED = "quarantined"


@unique
class H1QuarantineReason(StrEnum):
    MISSING_SPAN = "missing_span"
    MALFORMED_SPAN = "malformed_span"
    OUT_OF_RANGE = "out_of_range"
    MISMATCHED_SPAN = "mismatched_span"
    MISSING_END = "missing_end"
    MISSING_RUN = "missing_run"
    MISSING_CHUNK = "missing_chunk"
    MISSING_ACTOR = "missing_actor"
    MISSING_REASON = "missing_reason"
    UNREADABLE_SOURCE = "unreadable_source"
    HASH_MISMATCH = "hash_mismatch"
    UNGROUNDED = "ungrounded"
    MISSING_TIMESTAMP = "missing_timestamp"


@unique
class H1RefusalCode(StrEnum):
    MISSING_SOURCE = "missing_source"
    UNREADABLE_SOURCE = "unreadable_source"
    NOT_SQLITE = "not_sqlite"
    TARGET_MISSING = "target_missing"
    SOURCE_OVERLAP = "source_overlap"


@dataclass(frozen=True, slots=True)
class H1SourceRefused(MigrationError):
    code: H1RefusalCode
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class H1Interruption(MigrationError):
    """A failpoint aborted after the current anchor was checkpointed."""

    anchor_id: str

    def __str__(self) -> str:
        return f"h1 interruption at {self.anchor_id}"


@dataclass(frozen=True, slots=True)
class H1FamilyCount:
    family: H1Family
    verified: int
    quarantined: int
    pending: int
    anchor_count: int


@dataclass(frozen=True, slots=True)
class H1Inventory:
    verified: int
    quarantined: int
    pending: int
    anchor_count: int
    families: tuple[H1FamilyCount, ...]


@dataclass(frozen=True, slots=True)
class H1Receipt:
    inventory: H1Inventory
    dump_sha256: str
    receipt_sha256: str
    complete: bool


@dataclass(frozen=True, slots=True)
class H1RunAnchor:
    anchor_id: str
    legacy_pk: str
    run_id: str
    representation_id: str
    stored_content_hash: str
    schema_version_id: int
    extractor_engine: str
    extractor_model: str
    prompt_version: str
    decode_params: str
    chunk_plan_hash: str


@dataclass(frozen=True, slots=True)
class H1ChunkAnchor:
    anchor_id: str
    legacy_pk: str
    run_id: str
    chunk_index: int
    start_offset: int
    stored_hash: str
    representation_id: str


@dataclass(frozen=True, slots=True)
class H1CitationAnchor:
    anchor_id: str
    legacy_pk: str
    fact_kind: str
    fact_id: str
    representation_id: str
    source_span: str | None


@dataclass(frozen=True, slots=True)
class H1ReviewAnchor:
    anchor_id: str
    legacy_pk: str
    fact_kind: str
    fact_id: str
    status: str
    actor: str
    reason: str
    decided_ts: float | None
    representation_id: str | None


H1Anchor = H1RunAnchor | H1ChunkAnchor | H1CitationAnchor | H1ReviewAnchor
H1Failpoint = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class H1Decision:
    anchor_id: str
    family: H1Family
    legacy_pk: str
    classification: H1Classification
    reason: H1QuarantineReason | None
    representation_id: str | None
    family_receipt_id: str | None
    raw_byte_seal: str | None
    file_hash: str | None
    span_hash: str | None
    evidence_json: str


def refuse_source(code: H1RefusalCode, message: str) -> NoReturn:
    raise H1SourceRefused(code, message)
