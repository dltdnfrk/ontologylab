"""Typed validation and persistence records for Method storage."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib, re, time
from pathlib import Path
from typing import Any, NamedTuple, Protocol, Sequence

from ontologylab.method_ir import StatementOccurrence, canonical_json_bytes


class MethodError(Exception):
    """Base Method persistence error."""




class MethodValidationError(MethodError):
    """A caller supplied an invalid Method value."""


class MethodNotFoundError(MethodError):
    """A requested Method row does not exist."""


class MethodStateError(MethodError):
    """A Method state transition or transaction ownership is invalid."""


class MethodConflictError(MethodError):
    """A Method identity conflicts with an existing row."""


class MethodBusyError(MethodConflictError):
    """Another SQLite writer currently owns the database."""


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


def method_id(value: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise MethodValidationError("invalid Method id")
    return value


def nonempty_text(field: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MethodValidationError(f"{field} must be non-empty")
    return value.strip()


def sha256_hash(field: str, value: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise MethodValidationError(f"{field} must be a sha256 digest")
    return value


def exact_bool(field: str, value: Any) -> bool:
    if type(value) is not bool:
        raise MethodValidationError(f"{field} must be an exact bool")
    return value


def canonical_json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def decision_subject_parameters(
    kind: str, subject_id: str,
) -> tuple[str, ...]:
    """Return the five typed-subject lookup pairs in stable order."""
    return (kind, subject_id) * 5


class DocumentRecord(NamedTuple):
    database_path: Path
    content_hash: str
    raw_text_path: str


def document_bytes(record: DocumentRecord, expected_hash: str) -> bytes:
    if record.content_hash != expected_hash:
        raise MethodValidationError("document hash is stale")
    raw_path = (record.database_path.parent / record.raw_text_path).resolve()
    if record.database_path.parent not in raw_path.parents:
        raise MethodValidationError("document raw-text path escapes database root")
    try:
        raw = raw_path.read_bytes()
    except OSError as exc:
        raise MethodValidationError("document raw text is unavailable") from exc
    actual_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    if actual_hash != expected_hash:
        raise MethodValidationError("current document bytes do not match hash")
    return raw


def validate_selector(occurrence: StatementOccurrence, raw: bytes) -> None:
    selector = occurrence.selector
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MethodValidationError("document raw text is not UTF-8") from exc
    if selector.span_start < 0 or selector.span_end > len(text):
        raise MethodValidationError("selector span is outside the document")
    selected = text[selector.span_start : selector.span_end]
    selected_hash = "sha256:" + hashlib.sha256(selected.encode()).hexdigest()
    if selected_hash != selector.selected_text_hash:
        raise MethodValidationError("selector selected-text hash does not match")
    if selected != occurrence.statement_text:
        raise MethodValidationError("statement text does not match exact selector")


@dataclass(frozen=True, slots=True)
class SourcePolicyWrite:
    policy_id: str
    origin_pattern: str
    policy_version: str
    allowed_quote: bool
    allowed_extract: bool
    allowed_pack: bool
    allowed_train: bool
    allowed_redistribute: bool
    sensitivity: str
    allowed_processors_json: str
    allowed_regions_json: str
    decision_note: str
    decided_by: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class DocumentPolicySnapshotWrite:
    snapshot_id: str
    document_id: str
    document_content_hash: str
    source_policy_id: str
    resolution_status: str
    resolved_by: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class WorkspaceWrite:
    workspace_id: str
    name: str
    objective: str
    scope_json: str
    method_schema_version: str
    status: str
    created_by: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class OccurrenceWrite:
    workspace_id: str
    occurrence: StatementOccurrence
    extractor_engine: str
    extractor_model: str | None
    prompt_version: str
    decode_params_json: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class FragmentWrite:
    fragment_id: str
    workspace_id: str
    kind: str
    epistemic_class: str
    payload_json: str
    generator: str
    parser_version: str
    status: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class FragmentEvidenceWrite:
    evidence_id: str
    fragment_id: str
    field_path: str
    occurrence_id: str
    evidence_role: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class LinkWrite:
    link_id: str
    workspace_id: str
    src_fragment_id: str
    dst_fragment_id: str
    kind: str
    provenance_json: str
    status: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class GapWrite:
    gap_id: str
    workspace_id: str
    gap_class: str
    target_fragment_id: str | None
    field_path: str | None
    detector_id: str
    detector_version: str
    input_snapshot_hash: str
    detail_json: str
    created_ts: float
    updated_ts: float


@dataclass(frozen=True, slots=True)
class BridgeWrite:
    bridge_id: str
    workspace_id: str
    gap_id: str
    hypothesis: str
    assumptions_json: str
    scope: str
    limits_json: str
    falsifier: str
    minimum_validation: str
    decision_status: str
    epistemic_class: str
    generator: str
    model: str | None
    prompt_version: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class CounterSearchWrite:
    search_id: str
    workspace_id: str
    gap_id: str
    bridge_id: str
    query: str
    scope_json: str
    corpus_snapshot_hash: str
    result_occurrence_ids_json: str
    searched_by: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class BridgeEvidenceWrite:
    evidence_id: str
    bridge_id: str
    occurrence_id: str
    evidence_role: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class ReviewEventWrite:
    event_id: str
    workspace_id: str
    subject_kind: str
    subject_id: str
    decision: str
    reviewer: str
    note: str
    created_ts: float


class ValidationPersistence(Protocol):
    def ensure_active(self) -> None:
        ...

    def insert_source_policy(self, row: SourcePolicyWrite) -> None:
        ...

    def insert_bridge_evidence(
        self,
        row: BridgeEvidenceWrite,
    ) -> None:
        ...


class MethodValidationCommands:
    """Validate source-rights and evidence writes before persistence."""

    _validation_persistence: ValidationPersistence

    def create_source_policy(
        self, policy_id: str, *, origin_pattern: str, policy_version: str,
        allowed_quote: bool, allowed_extract: bool, allowed_pack: bool,
        allowed_train: bool, allowed_redistribute: bool, sensitivity: str,
        allowed_processors: Sequence[str], allowed_regions: Sequence[str],
        decision_note: str, decided_by: str,
    ) -> None:
        self._validation_persistence.ensure_active()
        self._validation_persistence.insert_source_policy(SourcePolicyWrite(
            method_id(policy_id),
            nonempty_text("origin_pattern", origin_pattern),
            nonempty_text("policy_version", policy_version),
            exact_bool("allowed_quote", allowed_quote),
            exact_bool("allowed_extract", allowed_extract),
            exact_bool("allowed_pack", allowed_pack),
            exact_bool("allowed_train", allowed_train),
            exact_bool("allowed_redistribute", allowed_redistribute),
            nonempty_text("sensitivity", sensitivity),
            canonical_json(tuple(allowed_processors)),
            canonical_json(tuple(allowed_regions)),
            nonempty_text("decision_note", decision_note),
            nonempty_text("decided_by", decided_by),
            time.time(),
        ))

    def add_bridge_evidence(
        self, evidence_id: str, *, bridge_id: str, occurrence_id: str,
        evidence_role: str,
    ) -> None:
        self._validation_persistence.ensure_active()
        if evidence_role not in {"supports", "counters", "bounds"}:
            raise MethodValidationError("invalid bridge evidence role")
        self._validation_persistence.insert_bridge_evidence(
            BridgeEvidenceWrite(
                method_id(evidence_id), method_id(bridge_id),
                method_id(occurrence_id), evidence_role, time.time(),
            )
        )
