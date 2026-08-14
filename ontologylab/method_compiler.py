"""Pure deterministic Method compiler and typed persistence caller."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable, Mapping, Protocol, Sequence

from ontologylab.method_compiler_artifacts import (
    ArtifactSelection,
    CompilerArtifacts,
    assemble_artifacts,
    build_method,
    normalized_snapshot_hash,
)
from ontologylab.method_compiler_contract import (
    CompilationGateResult,
    CompilerReceipt,
)
from ontologylab.method_compiler_gates import (
    evaluate_source_gates,
    gate_result,
    snapshot_data,
)
from ontologylab.method_compiler_contract import GateId
from ontologylab.method_ir import canonical_json_bytes
from ontologylab.method_compiler_replay import (
    ReplayReceipt,
    evaluate_replay,
)
from ontologylab.method_snapshot import MethodSnapshot
from ontologylab.method_validation import MethodValidationError


@dataclass(frozen=True, slots=True)
class CompileSelection:
    attempt_id: str
    release_id: str
    method_id: str
    release_version: int


@dataclass(frozen=True, slots=True)
class CompilationResult:
    passed: bool
    release_id: str | None
    method_json: Mapping[str, Any]
    source_index: Sequence[Mapping[str, Any]]
    gates: tuple[CompilationGateResult, ...]
    replay_receipt: ReplayReceipt
    receipt: CompilerReceipt | None
    method_json_bytes: bytes
    source_index_bytes: bytes
    canonical_envelope: bytes
    content_hash: str | None


class CompilerPersistence(Protocol):
    def record_compilation_attempt(
        self,
        receipt: CompilerReceipt,
    ) -> None:
        ...

    def insert_release(
        self,
        *,
        method_id: str,
        method_json: Mapping[str, Any],
        source_index: Sequence[Mapping[str, Any]],
        compiler_receipt: CompilerReceipt,
        review_receipt: Mapping[str, Any],
    ) -> None:
        ...


def _result(
    selection: CompileSelection | None,
    artifacts: CompilerArtifacts,
    gates: tuple[CompilationGateResult, ...],
    replay: ReplayReceipt,
) -> CompilationResult:
    return CompilationResult(
        passed=all(gate.passed for gate in gates),
        release_id=(
            selection.release_id
            if selection is not None
            else None
        ),
        method_json=artifacts.method,
        source_index=artifacts.source_index,
        gates=gates,
        replay_receipt=replay,
        receipt=artifacts.receipt,
        method_json_bytes=artifacts.method_json,
        source_index_bytes=artifacts.source_index_json,
        canonical_envelope=artifacts.canonical_envelope,
        content_hash=artifacts.content_hash,
    )


def validate_final_artifacts(
    result: CompilationResult,
    snapshot: MethodSnapshot,
    selection: CompileSelection,
    *,
    immutable: bool,
) -> CompilationGateResult:
    reasons: list[str] = []
    receipt = result.receipt
    if not immutable:
        reasons.append("release-not-immutable")
    if receipt is None:
        reasons.append("receipt-binding-mismatch")
        return gate_result(GateId.G8, reasons)
    data = snapshot_data(MethodSnapshot(
        snapshot.workspace_id,
        snapshot.canonical_json,
        "sha256:" + hashlib.sha256(snapshot.canonical_json).hexdigest(),
    ))
    normalized = MethodSnapshot(
        snapshot.workspace_id,
        snapshot.canonical_json,
        normalized_snapshot_hash(data),
    )
    try:
        rebuilt = assemble_artifacts(
            data,
            normalized,
            _artifact_selection(selection),
            result.gates,
            result.replay_receipt,
        )
    except MethodValidationError:
        return gate_result(
            GateId.G8,
            ("receipt-binding-mismatch",),
        )
    expected = (
        receipt.release_id == selection.release_id
        and receipt.release_version == selection.release_version
        and receipt.input_snapshot_hash == normalized.content_hash
        and receipt.fixture_set_hash
        == result.replay_receipt.fixture_set_hash
        and receipt.replay_fixture_count
        == result.replay_receipt.fixture_count
        and receipt.replay_result_count
        == result.replay_receipt.result_count
        and receipt.replay_kind_counts
        == result.replay_receipt.kind_counts
        and receipt.replay_results == result.replay_receipt.results
        and receipt.replay_receipt_hash
        == result.replay_receipt.receipt_hash
        and rebuilt.receipt == receipt
    )
    if not expected:
        reasons.append("receipt-binding-mismatch")
    method_bytes = canonical_json_bytes(result.method_json)
    source_bytes = canonical_json_bytes(result.source_index)
    if (
        receipt.method_json_hash
        != "sha256:" + hashlib.sha256(method_bytes).hexdigest()
        or receipt.source_index_hash
        != "sha256:" + hashlib.sha256(source_bytes).hexdigest()
        or method_bytes != result.method_json_bytes
        or source_bytes != result.source_index_bytes
        or receipt.content_hash != result.content_hash
        or rebuilt.method != result.method_json
        or rebuilt.source_index != result.source_index
        or rebuilt.canonical_envelope != result.canonical_envelope
    ):
        reasons.append("canonical-artifact-hash-mismatch")
    return gate_result(GateId.G8, reasons)


def _artifact_selection(
    selection: CompileSelection | None,
) -> ArtifactSelection | None:
    if selection is None:
        return None
    return ArtifactSelection(
        selection.attempt_id,
        selection.release_id,
        selection.method_id,
        selection.release_version,
    )


def compile_method(
    snapshot: MethodSnapshot,
    selection: CompileSelection | None,
    fixtures: Iterable[Mapping[str, Any]],
) -> CompilationResult:
    data = snapshot_data(snapshot)
    normalized_snapshot = MethodSnapshot(
        snapshot.workspace_id,
        snapshot.canonical_json,
        normalized_snapshot_hash(data),
    )
    source_gates = evaluate_source_gates(data)
    artifact_selection = _artifact_selection(selection)
    preview = build_method(
        data,
        artifact_selection,
        source_gates,
    )
    replay, replay_gate = evaluate_replay(
        preview.method,
        fixtures,
    )
    preview_gates = (*source_gates, replay_gate)
    provisional_g8 = gate_result(GateId.G8, ())
    gates = (*preview_gates, provisional_g8)
    artifacts = assemble_artifacts(
        data,
        normalized_snapshot,
        artifact_selection,
        gates,
        replay,
    )
    provisional = _result(selection, artifacts, gates, replay)
    if selection is None:
        return provisional
    final_g8 = validate_final_artifacts(
        provisional,
        normalized_snapshot,
        selection,
        immutable=True,
    )
    if final_g8.passed:
        return provisional
    final_gates = (*preview_gates, final_g8)
    final_artifacts = assemble_artifacts(
        data,
        normalized_snapshot,
        artifact_selection,
        final_gates,
        replay,
    )
    return _result(selection, final_artifacts, final_gates, replay)


def compile_and_persist(
    store: CompilerPersistence,
    snapshot: MethodSnapshot,
    selection: CompileSelection,
    fixtures: Iterable[Mapping[str, Any]],
    *,
    inject_failure: str | None = None,
) -> CompilationResult:
    result = compile_method(
        snapshot,
        selection,
        fixtures,
    )
    if result.receipt is None:
        raise MethodValidationError(
            "selected compile requires receipt"
        )
    if inject_failure == "attempt":
        raise RuntimeError("attempt")
    store.record_compilation_attempt(result.receipt)
    if inject_failure == "middle-gate":
        raise RuntimeError("middle-gate")
    if result.passed:
        if inject_failure == "release":
            raise RuntimeError("release")
        store.insert_release(
            method_id=selection.method_id,
            method_json=result.method_json,
            source_index=result.source_index,
            compiler_receipt=result.receipt,
            review_receipt={
                "decisions": result.method_json[
                    "review_receipts"
                ],
                "workspace_id": snapshot.workspace_id,
            },
        )
    return result
