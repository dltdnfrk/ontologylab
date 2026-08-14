"""Closed compiler gate and receipt contract shared across persistence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any

from ontologylab.method_validation import (
    MethodValidationError,
    canonical_json,
    exact_bool,
    method_id,
    nonempty_text,
    sha256_hash,
)


COMPILER_REASON_CATALOG_VERSION = "method-compiler-reasons-v1"
COMPILER_REPLAY_KINDS = (
    "expected_output",
    "expected_error",
    "expected_no_output",
    "unknown",
)


class GateId(StrEnum):
    G0 = "G0"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"
    G8 = "G8"


COMPILER_REASON_CATALOG: dict[GateId, tuple[str, ...]] = {
    GateId.G0: ("rights-ambiguous", "rights-denied", "rights-unresolved"),
    GateId.G1: (
        "mismatched-selector", "missing-source-anchor", "stale-source-anchor",
    ),
    GateId.G2: ("bridge-as-verified-evidence", "epistemic-class-mixed"),
    GateId.G3: (
        "fabricated-value", "invalid-dimension", "invalid-reference",
        "invalid-unit", "unsupported-schema-keyword",
    ),
    GateId.G4: (
        "dangling-reference", "input-output-discontinuity",
        "step-dependency-cycle", "unreachable-output",
    ),
    GateId.G5: ("blocking-conflict", "unscoped-conflict"),
    GateId.G6: ("missing-human-decision", "self-approval"),
    GateId.G7: (
        "expected-error-omitted", "fixture-failed",
        "invalid-replay-fixture", "no-output-omitted",
        "replay-limit-exceeded",
        "unknown-output-omitted",
    ),
    GateId.G8: (
        "canonical-artifact-hash-mismatch", "receipt-binding-mismatch",
        "release-not-immutable",
    ),
}


@dataclass(frozen=True, slots=True)
class CompilationGateResult:
    gate_id: GateId
    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompilerPolicySnapshot:
    snapshot_id: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class CompilerAcceptedObject:
    object_id: str
    row_hash: str
    input_hash: str


@dataclass(frozen=True, slots=True)
class CompilerReplayKindCount:
    kind: str
    fixture_count: int
    passed_count: int


@dataclass(frozen=True, slots=True)
class CompilerReplayResult:
    fixture_id: str
    kind: str
    passed: bool


@dataclass(frozen=True, slots=True)
class CompilerReceipt:
    attempt_id: str
    release_id: str
    workspace_id: str
    release_version: int
    method_schema_version: str
    compiler_version: str
    input_snapshot_hash: str
    policy_snapshots: tuple[CompilerPolicySnapshot, ...]
    accepted_objects: tuple[CompilerAcceptedObject, ...]
    method_json_hash: str
    source_index_hash: str
    fixture_set_hash: str
    reason_catalog_version: str
    replay_fixture_count: int
    replay_result_count: int
    replay_kind_counts: tuple[CompilerReplayKindCount, ...]
    replay_results: tuple[CompilerReplayResult, ...]
    replay_receipt_hash: str
    gates: tuple[CompilationGateResult, ...]
    assumption_gap_inventory_hash: str
    reviewer_receipt_hash: str
    passed: bool
    content_hash: str | None


_RECEIPT_HASHES = (
    "input_snapshot_hash", "method_json_hash", "source_index_hash",
    "fixture_set_hash", "replay_receipt_hash",
    "assumption_gap_inventory_hash", "reviewer_receipt_hash",
)


def _typed_items(
    field: str,
    values: tuple[Any, ...],
    item_type: type[Any],
    identity: str,
) -> tuple[Any, ...]:
    identities = tuple(
        getattr(item, identity)
        for item in values
        if type(item) is item_type
    )
    if (
        type(values) is not tuple
        or any(type(item) is not item_type for item in values)
        or any(not isinstance(value, str) for value in identities)
        or identities != tuple(sorted(set(identities)))
    ):
        raise MethodValidationError(f"{field} must be ordered typed values")
    for value in identities:
        method_id(str(value))
    return values


def validate_gate_reasons(
    gate_id: GateId,
    passed: bool,
    reasons: tuple[str, ...],
) -> tuple[str, ...]:
    exact_bool(f"{gate_id.value}.passed", passed)
    if type(reasons) is not tuple:
        raise MethodValidationError(f"{gate_id.value}.reasons must be a tuple")
    if reasons != tuple(sorted(set(reasons))):
        raise MethodValidationError(f"{gate_id.value}.reasons must be sorted unique")
    if passed:
        if reasons:
            raise MethodValidationError(f"{gate_id.value} passing gate requires empty reasons")
        return reasons
    if not reasons:
        raise MethodValidationError(f"{gate_id.value} failed gate requires reasons")
    allowed = COMPILER_REASON_CATALOG[gate_id]
    for reason in reasons:
        if not isinstance(reason, str):
            raise MethodValidationError(f"{gate_id.value}.reasons must be strings")
        if reason not in allowed:
            if any(
                reason in gate_reasons
                for other_gate, gate_reasons in COMPILER_REASON_CATALOG.items()
                if other_gate is not gate_id
            ):
                raise MethodValidationError(f"{reason} is not valid for {gate_id.value}")
            raise MethodValidationError(
                f"{gate_id.value}.reasons contains unknown code {reason!r}"
            )
    return reasons


def _validate_receipt_identity(receipt: CompilerReceipt) -> None:
    for value in (receipt.attempt_id, receipt.release_id, receipt.workspace_id):
        method_id(value)
    if (
        isinstance(receipt.release_version, bool)
        or not isinstance(receipt.release_version, int)
        or receipt.release_version < 1
    ):
        raise MethodValidationError("release_version must be positive")
    if receipt.method_schema_version != "method-v1":
        raise MethodValidationError("method_schema_version must be method-v1")
    if receipt.compiler_version != "method-compiler-v1":
        raise MethodValidationError("unsupported compiler_version")
    for field in _RECEIPT_HASHES:
        sha256_hash(field, getattr(receipt, field))


def _validate_receipt_inputs(receipt: CompilerReceipt) -> None:
    policies = _typed_items(
        "policy_snapshots", receipt.policy_snapshots,
        CompilerPolicySnapshot, "snapshot_id",
    )
    objects = _typed_items(
        "accepted_objects", receipt.accepted_objects,
        CompilerAcceptedObject, "object_id",
    )
    for policy in policies:
        if (
            nonempty_text("policy_version", policy.policy_version)
            != policy.policy_version
        ):
            raise MethodValidationError("policy_version must be canonical")
    for accepted in objects:
        for field in ("row_hash", "input_hash"):
            sha256_hash(field, getattr(accepted, field))
    _validate_replay_binding(receipt)


def replay_receipt_hash(
    fixture_set_hash: str,
    fixture_count: int,
    result_count: int,
    kind_counts: tuple[CompilerReplayKindCount, ...],
    results: tuple[CompilerReplayResult, ...],
) -> str:
    payload = {
        "fixture_set_hash": fixture_set_hash,
        "fixture_count": fixture_count,
        "result_count": result_count,
        "kind_counts": kind_counts,
        "results": results,
    }
    return "sha256:" + hashlib.sha256(
        canonical_json(payload).encode()
    ).hexdigest()


def _exact_count(field: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise MethodValidationError(
            f"{field} must be a non-negative exact integer"
        )
    return value


def _validate_replay_binding(receipt: CompilerReceipt) -> None:
    if receipt.reason_catalog_version != COMPILER_REASON_CATALOG_VERSION:
        raise MethodValidationError("receipt reason catalog version is invalid")
    fixture_count = _exact_count(
        "replay_fixture_count",
        receipt.replay_fixture_count,
    )
    result_count = _exact_count(
        "replay_result_count",
        receipt.replay_result_count,
    )
    kind_counts = receipt.replay_kind_counts
    if (
        type(kind_counts) is not tuple
        or any(
            type(row) is not CompilerReplayKindCount
            for row in kind_counts
        )
    ):
        raise MethodValidationError(
            "replay_kind_counts must be ordered typed values"
        )
    results = _typed_items(
        "replay_results",
        receipt.replay_results,
        CompilerReplayResult,
        "fixture_id",
    )
    if tuple(row.kind for row in kind_counts) != COMPILER_REPLAY_KINDS:
        raise MethodValidationError("replay kind counts must be canonical")
    for row in kind_counts:
        count = _exact_count("fixture_count", row.fixture_count)
        passed = _exact_count("passed_count", row.passed_count)
        if passed > count:
            raise MethodValidationError(
                "replay passed count exceeds fixture count"
            )
    for row in results:
        if row.kind not in COMPILER_REPLAY_KINDS:
            raise MethodValidationError("replay result kind is invalid")
        exact_bool("replay result passed", row.passed)
    if (
        result_count != len(results)
        or sum(row.fixture_count for row in kind_counts) != result_count
        or result_count > fixture_count
    ):
        raise MethodValidationError("replay counts do not match results")
    for row in kind_counts:
        matching = tuple(result for result in results if result.kind == row.kind)
        if (
            row.fixture_count != len(matching)
            or row.passed_count != sum(result.passed for result in matching)
        ):
            raise MethodValidationError("replay kind counts do not match results")
    expected = replay_receipt_hash(
        receipt.fixture_set_hash,
        fixture_count,
        result_count,
        kind_counts,
        results,
    )
    if receipt.replay_receipt_hash != expected:
        raise MethodValidationError("replay receipt hash does not match results")


def _validate_receipt_gates(receipt: CompilerReceipt) -> None:
    if (
        type(receipt.gates) is not tuple
        or tuple(getattr(gate, "gate_id", None) for gate in receipt.gates)
        != tuple(GateId)
        or any(type(gate) is not CompilationGateResult for gate in receipt.gates)
    ):
        raise MethodValidationError("receipt must contain ordered exact G0-G8")
    for gate in receipt.gates:
        validate_gate_reasons(gate.gate_id, gate.passed, gate.reasons)


def _validate_receipt_outcome(
    receipt: CompilerReceipt,
    *,
    require_content_hash: bool,
) -> None:
    passed = exact_bool("passed", receipt.passed)
    if passed != all(gate.passed for gate in receipt.gates):
        raise MethodValidationError("passed must equal non-compensatory G0-G8")
    if receipt.content_hash is not None:
        sha256_hash("content_hash", receipt.content_hash)
    if require_content_hash and passed and receipt.content_hash is None:
        raise MethodValidationError("passed receipt must bind content_hash")
    if not passed and receipt.content_hash is not None:
        raise MethodValidationError("failed receipt cannot bind content_hash")


def validate_compiler_receipt(
    receipt: CompilerReceipt,
    *,
    require_content_hash: bool,
) -> CompilerReceipt:
    if type(receipt) is not CompilerReceipt:
        raise MethodValidationError("compiler receipt must be a CompilerReceipt")
    _validate_receipt_identity(receipt)
    _validate_receipt_inputs(receipt)
    _validate_receipt_gates(receipt)
    _validate_receipt_outcome(
        receipt,
        require_content_hash=require_content_hash,
    )
    return receipt


def gate_reasons_json_valid(
    gate_id: str,
    passed: int,
    value: str,
) -> int:
    try:
        reasons = json.loads(value)
        gate = GateId(gate_id)
        if (
            type(passed) is not int
            or passed not in (0, 1)
            or type(reasons) is not list
            or canonical_json(reasons) != value
        ):
            return 0
        validate_gate_reasons(gate, bool(passed), tuple(reasons))
        return 1
    except (TypeError, ValueError, MethodValidationError):
        return 0
