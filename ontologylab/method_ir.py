"""Strict stdlib Method IR parsing and canonical serialization."""

from __future__ import annotations

import dataclasses
from enum import Enum
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Never
import unicodedata

from ontologylab.method_ir_codec import MethodIRCodec, pointer_tokens


class IRValidationError(ValueError):
    pass


class ValueState(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    ABSENT = "absent"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ValueKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    REAL = "real"
    BOOLEAN = "boolean"
    RANGE = "range"


class EpistemicClass(str, Enum):
    SOURCE_SUPPORTED = "source_supported"
    DETERMINISTIC_DERIVATION = "deterministic_derivation"
    BRIDGE_ASSUMPTION = "bridge_assumption"
    OPERATOR_CONSTRAINT = "operator_constraint"


class FragmentKind(str, Enum):
    OBJECTIVE = "objective"
    PREREQUISITE = "prerequisite"
    INPUT = "input"
    STEP = "step"
    CONDITION = "condition"
    MEASUREMENT = "measurement"
    RESULT = "result"
    CONSTRAINT = "constraint"
    RISK = "risk"


class EvidenceRole(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"


class LinkKind(str, Enum):
    PRECEDES = "precedes"
    REQUIRES = "requires"
    CONDITIONED_BY = "conditioned_by"
    MEASURES = "measures"
    PRODUCES = "produces"
    INVALIDATES = "invalidates"


@dataclasses.dataclass(frozen=True, slots=True)
class SourceSelector:
    document_id: str
    document_content_hash: str
    span_start: int
    span_end: int
    selected_text_hash: str


@dataclasses.dataclass(frozen=True, slots=True)
class Unit:
    symbol: str
    dimension: str
    recognized: bool


@dataclasses.dataclass(frozen=True, slots=True)
class ValueRange:
    minimum: int | float
    maximum: int | float
    minimum_inclusive: bool
    maximum_inclusive: bool


@dataclasses.dataclass(frozen=True, slots=True)
class TypedValue:
    state: ValueState
    kind: ValueKind
    value: str | int | float | bool | ValueRange | None = None
    unit: Unit | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class StatementOccurrence:
    id: str
    selector: SourceSelector
    statement_text: str
    polarity: str
    modality: str
    temporal_scope: TypedValue
    applicability_scope: TypedValue


@dataclasses.dataclass(frozen=True, slots=True)
class MethodFragment:
    id: str
    kind: FragmentKind
    epistemic_class: EpistemicClass
    payload: Mapping[str, TypedValue]


@dataclasses.dataclass(frozen=True, slots=True)
class FieldEvidence:
    id: str
    fragment_id: str
    field_path: str
    occurrence_id: str
    role: EvidenceRole


@dataclasses.dataclass(frozen=True, slots=True)
class MethodLink:
    id: str
    src_fragment_id: str
    dst_fragment_id: str
    kind: LinkKind


@dataclasses.dataclass(frozen=True, slots=True)
class MethodGap:
    id: str
    gap_class: str
    status: str
    target_fragment_id: str | None
    field_path: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class BridgeAssumption:
    id: str
    gap_id: str
    hypothesis: str
    assumptions: tuple[str, ...]
    scope: str
    limits: tuple[str, ...]
    falsifier: str
    minimum_validation: str
    decision_status: str
    epistemic_class: EpistemicClass


@dataclasses.dataclass(frozen=True, slots=True)
class ReviewReceipt:
    id: str
    subject_kind: str
    subject_id: str
    decision: str
    reviewer: str
    note: str


@dataclasses.dataclass(frozen=True, slots=True)
class CompilerGateResult:
    id: str
    gate: str
    passed: bool
    reasons: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class SourceIndexRow:
    id: str
    method_id: str
    field_path: str
    document_id: str
    document_content_hash: str
    span_start: int
    span_end: int
    selected_text_hash: str
    evidence_role: EvidenceRole
    epistemic_class: EpistemicClass
    occurrence_id: str
    receipt_ref: str


@dataclasses.dataclass(frozen=True, slots=True)
class MethodRelease:
    id: str
    workspace_id: str
    version: int
    compiler_version: str
    content_hash: str


@dataclasses.dataclass(frozen=True, slots=True)
class MethodIR:
    schema_version: str
    id: str
    version: int
    name: str
    fragments: tuple[MethodFragment, ...]
    field_evidence: tuple[FieldEvidence, ...]
    links: tuple[MethodLink, ...]
    gaps: tuple[MethodGap, ...]
    bridge_assumptions: tuple[BridgeAssumption, ...]
    review_receipts: tuple[ReviewReceipt, ...]
    gate_results: tuple[CompilerGateResult, ...]
    source_index: tuple[SourceIndexRow, ...]
    release: MethodRelease


def _fail(path: str, message: str) -> Never:
    raise IRValidationError(f"{path}: {message}")


_CODEC = MethodIRCodec(
    validation_error=IRValidationError,
    fail=_fail,
    value_state=ValueState,
    value_kind=ValueKind,
    epistemic_class=EpistemicClass,
    fragment_kind=FragmentKind,
    evidence_role=EvidenceRole,
    link_kind=LinkKind,
    source_selector=SourceSelector,
    unit=Unit,
    value_range=ValueRange,
    typed_value=TypedValue,
    statement_occurrence=StatementOccurrence,
    method_fragment=MethodFragment,
    field_evidence=FieldEvidence,
    method_link=MethodLink,
    method_gap=MethodGap,
    bridge_assumption=BridgeAssumption,
    review_receipt=ReviewReceipt,
    compiler_gate_result=CompilerGateResult,
    source_index_row=SourceIndexRow,
    method_release=MethodRelease,
    method_ir=MethodIR,
)


def _relations(method: MethodIR) -> None:
    fragments = {
        fragment.id: fragment
        for fragment in method.fragments
    }
    for index, evidence in enumerate(method.field_evidence):
        fragment = fragments.get(evidence.fragment_id)
        if (
            fragment is not None
            and fragment.epistemic_class
            is EpistemicClass.BRIDGE_ASSUMPTION
            and evidence.role is EvidenceRole.SUPPORTS
        ):
            _fail(
                f"$.field_evidence[{index}].role",
                (
                    "bridge_assumption cannot be promoted by "
                    "supporting source evidence"
                ),
            )
    for index, row in enumerate(method.source_index):
        tokens = pointer_tokens(row.field_path)
        fragment = fragments.get(
            tokens[1]
            if len(tokens) > 1 and tokens[0] == "fragments"
            else ""
        )
        if (
            fragment is not None
            and fragment.epistemic_class
            is EpistemicClass.BRIDGE_ASSUMPTION
            and row.epistemic_class
            is EpistemicClass.SOURCE_SUPPORTED
        ):
            _fail(
                f"$.source_index[{index}].epistemic_class",
                (
                    "bridge_assumption cannot be promoted to "
                    "source_supported"
                ),
            )


def parse_method(raw: Any) -> MethodIR:
    method = _CODEC.parse_method(raw)
    _relations(method)
    return method


def parse_occurrences(
    raw: Any,
) -> tuple[StatementOccurrence, ...]:
    return _CODEC.parse_occurrences(raw)


def _plain(value: Any) -> Any:
    if (
        isinstance(value, BridgeAssumption)
        and value.epistemic_class
        is not EpistemicClass.BRIDGE_ASSUMPTION
    ):
        _fail(
            "$",
            "bridge assumption cannot serialize as source_supported",
        )
    if (
        isinstance(value, SourceIndexRow)
        and value.epistemic_class
        is EpistemicClass.BRIDGE_ASSUMPTION
        and value.evidence_role is EvidenceRole.SUPPORTS
    ):
        _fail(
            "$",
            (
                "bridge assumption cannot serialize as "
                "source-supported evidence"
            ),
        )
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Unit):
        return {
            "symbol": value.symbol,
            "dimension": value.dimension,
        }
    if dataclasses.is_dataclass(value):
        return {
            field.name: _plain(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if (
                field.name != "id"
                or not isinstance(value, CompilerGateResult)
            )
            and getattr(value, field.name) is not None
        }
    if isinstance(value, Mapping):
        return {
            str(key): _plain(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _nfc(value: Any, path: str = "$") -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        originals: dict[str, str] = {}
        for key, item in value.items():
            normalized = unicodedata.normalize("NFC", key)
            if normalized in result:
                _fail(
                    path,
                    (
                        f"keys {originals[normalized]!r} and {key!r} "
                        f"normalize to duplicate {normalized!r}"
                    ),
                )
            originals[normalized] = key
            result[normalized] = _nfc(
                item,
                f"{path}.{normalized}",
            )
        return result
    if isinstance(value, list):
        return [
            _nfc(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


def canonical_json_bytes(v: Any) -> bytes:
    if isinstance(v, MethodIR):
        _relations(v)
    return json.dumps(
        _nfc(_plain(v)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def sha256_digest(v: bytes) -> str:
    return "sha256:" + hashlib.sha256(v).hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "usage: python -m ontologylab.method_ir <json-path>",
            file=sys.stderr,
        )
        return 2
    try:
        data = Path(args[0]).read_bytes()
        if len(data) > 10_000_000:
            _fail("$", "input exceeds 10000000 bytes")
        canonical = canonical_json_bytes(parse_method(data))
    except (IRValidationError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, IRValidationError)
            else (
                "$: cannot read input "
                f"({error.strerror or 'OS error'})"
            )
        )
        print(message, file=sys.stderr)
        return 2
    sys.stdout.buffer.write(
        canonical
        + b"\n"
        + sha256_digest(canonical).encode()
        + b"\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
