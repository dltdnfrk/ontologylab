from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Any, Mapping, Protocol, Sequence

from ontologylab.method_compiler_contract import (
    CompilerReceipt,
)
from ontologylab.method_ir import canonical_json_bytes
from ontologylab.method_release_validation import (
    CanonicalReleaseEnvelope,
    canonical_release_envelope,
)
from ontologylab.method_snapshot import canonical_compiler_receipt
from ontologylab.method_validation import (
    MethodConflictError,
    MethodNotFoundError,
    MethodStateError,
    MethodValidationError,
    canonical_json,
    method_id as validate_method_id,
)


@dataclass(frozen=True, slots=True)
class CompilationAttemptWrite:
    attempt_id: str
    workspace_id: str
    release_id: str
    compiler_version: str
    input_snapshot_hash: str
    passed: bool
    gate_receipt_json: str
    compiler_receipt_json: str
    compiler_receipt_hash: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class CompilationGateWrite:
    attempt_id: str
    workspace_id: str
    gate_id: str
    passed: bool
    reasons_json: str
    compiler_receipt_hash: str
    compiler_receipt_json: str


@dataclass(frozen=True, slots=True)
class CompilationAttemptRecord:
    passed: int
    release_id: str
    workspace_id: str
    compiler_version: str
    input_snapshot_hash: str
    gate_receipt_json: str
    compiler_receipt_json: str
    compiler_receipt_hash: str


@dataclass(frozen=True, slots=True)
class ReleaseWrite:
    release_id: str
    workspace_id: str
    method_id: str
    version: int
    canonical_json: str
    source_index_json: str
    content_hash: str
    compiler_version: str
    input_snapshot_hash: str
    gate_receipt_json: str
    review_receipt_json: str
    compiler_receipt_json: str
    compiler_receipt_hash: str
    attempt_id: str
    created_ts: float


class ReleasePersistence(Protocol):
    def insert_compilation_attempt(
        self, row: CompilationAttemptWrite
    ) -> None:
        ...

    def insert_compilation_gate(
        self,
        row: CompilationGateWrite,
    ) -> None:
        ...

    def compilation_attempt(
        self, attempt_id: str
    ) -> CompilationAttemptRecord | None:
        ...

    def compilation_gates(
        self, attempt_id: str
    ) -> tuple[CompilationGateWrite, ...]:
        ...

    def insert_release_row(self, row: ReleaseWrite) -> None:
        ...


class ReleaseCore(Protocol):
    def ensure_active(self) -> None:
        ...

    def workspace_exists(self, workspace_id: str) -> bool:
        ...


def _gate_rows(
    receipt: CompilerReceipt, receipt_hash: str
) -> tuple[CompilationGateWrite, ...]:
    return tuple(
        CompilationGateWrite(
            receipt.attempt_id,
            receipt.workspace_id,
            gate.gate_id.value,
            gate.passed,
            canonical_json(gate.reasons),
            receipt_hash,
            canonical_compiler_receipt(receipt).json,
        )
        for gate in receipt.gates
    )


class MethodReleaseStore:
    _validation_persistence: ReleaseCore
    _release_persistence: ReleasePersistence
    canonical_envelope = staticmethod(canonical_release_envelope)

    def _workspace(self, workspace_id: str) -> str:
        self._validation_persistence.ensure_active()
        workspace_id = validate_method_id(workspace_id)
        if not self._validation_persistence.workspace_exists(workspace_id):
            raise MethodNotFoundError(f"unknown workspace {workspace_id!r}")
        return workspace_id

    def record_compilation_attempt(self, receipt: CompilerReceipt) -> None:
        """Persist one exact receipt and its nine gate rows in the active UoW."""
        if type(receipt) is not CompilerReceipt:
            raise MethodValidationError(
                "compiler receipt must be a CompilerReceipt"
            )
        workspace_id = self._workspace(receipt.workspace_id)
        canonical = canonical_compiler_receipt(receipt)
        if self._release_persistence.compilation_attempt(
            receipt.attempt_id
        ) is not None:
            raise MethodConflictError(
                "compilation attempt identity already exists"
            )
        gates = _gate_rows(receipt, canonical.receipt_hash)
        for gate in gates:
            self._release_persistence.insert_compilation_gate(gate)
        self._release_persistence.insert_compilation_attempt(
            CompilationAttemptWrite(
                validate_method_id(receipt.attempt_id),
                workspace_id,
                validate_method_id(receipt.release_id),
                receipt.compiler_version,
                receipt.input_snapshot_hash,
                receipt.passed,
                canonical.gate_summary_json,
                canonical.json,
                canonical.receipt_hash,
                time.time(),
            )
        )

    def insert_release(
        self,
        *,
        method_id: str,
        method_json: Mapping[str, Any],
        source_index: Sequence[Mapping[str, Any]],
        compiler_receipt: CompilerReceipt,
        review_receipt: Mapping[str, Any],
    ) -> None:
        """Persist a release only when its stored attempt and gates bind."""
        self._validation_persistence.ensure_active()
        canonical = canonical_compiler_receipt(compiler_receipt)
        receipt = compiler_receipt
        attempt = self._release_persistence.compilation_attempt(
            receipt.attempt_id
        )
        if (
            attempt is None
            or attempt.passed != 1
            or not receipt.passed
            or attempt.release_id != receipt.release_id
            or attempt.workspace_id != receipt.workspace_id
            or attempt.compiler_version != receipt.compiler_version
            or attempt.input_snapshot_hash != receipt.input_snapshot_hash
        ):
            raise MethodStateError(
                "release does not match a passed compilation attempt"
            )
        envelope = canonical_release_envelope(
            method_json, source_index, receipt
        )
        receipt = envelope.receipt
        canonical = canonical_compiler_receipt(receipt)
        expected_gates = _gate_rows(receipt, canonical.receipt_hash)
        stored_gates = self._release_persistence.compilation_gates(
            receipt.attempt_id
        )
        if (
            attempt.gate_receipt_json != canonical.gate_summary_json
            or attempt.compiler_receipt_json != canonical.json
            or attempt.compiler_receipt_hash != canonical.receipt_hash
            or stored_gates != expected_gates
            or len(stored_gates) != 9
            or not all(gate.passed for gate in stored_gates)
        ):
            raise MethodStateError(
                "release does not match a passed hash-bound compilation attempt"
            )
        review_hash = (
            "sha256:"
            + hashlib.sha256(canonical_json_bytes(review_receipt)).hexdigest()
        )
        if receipt.reviewer_receipt_hash != review_hash:
            raise MethodValidationError(
                "reviewer receipt hash does not match compiler receipt"
            )
        self._release_persistence.insert_release_row(
            ReleaseWrite(
                receipt.release_id,
                receipt.workspace_id,
                method_id=validate_method_id(method_id),
                version=receipt.release_version,
                canonical_json=envelope.method_json,
                source_index_json=envelope.source_index,
                content_hash=envelope.content_hash,
                compiler_version=receipt.compiler_version,
                input_snapshot_hash=receipt.input_snapshot_hash,
                gate_receipt_json=canonical.gate_summary_json,
                review_receipt_json=canonical_json(review_receipt),
                compiler_receipt_json=canonical.json,
                compiler_receipt_hash=canonical.receipt_hash,
                attempt_id=receipt.attempt_id,
                created_ts=time.time(),
            )
        )
