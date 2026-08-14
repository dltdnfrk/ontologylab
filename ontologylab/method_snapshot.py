"""Canonical compiler receipt helpers and immutable Method snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import time
from typing import Any, Mapping, Protocol

from ontologylab.method_compiler_contract import (
    CompilationGateResult,
    CompilerAcceptedObject,
    CompilerPolicySnapshot,
    CompilerReceipt,
    CompilerReplayKindCount,
    CompilerReplayResult,
    GateId,
    gate_reasons_json_valid,
    validate_compiler_receipt,
)
from ontologylab.method_ir import canonical_json_bytes
from ontologylab.method_snapshot_payload import (
    SnapshotRows as SnapshotRows,
    snapshot_payload,
)
from ontologylab.method_validation import (
    DocumentPolicySnapshotWrite,
    DocumentRecord,
    MethodNotFoundError,
    MethodValidationError,
    WorkspaceWrite,
    canonical_json,
    document_bytes,
    method_id,
    nonempty_text,
    sha256_hash,
)


@dataclass(frozen=True, slots=True)
class MethodSnapshot:
    """Canonical immutable view of one Method workspace."""

    workspace_id: str
    canonical_json: bytes
    content_hash: str


@dataclass(frozen=True, slots=True)
class CanonicalCompilerReceipt:
    json: str
    receipt_hash: str
    gate_summary_json: str


def compiler_receipt_without_content_hash(
    receipt: CompilerReceipt,
) -> CompilerReceipt:
    return replace(
        validate_compiler_receipt(receipt, require_content_hash=False),
        content_hash=None,
    )


def canonical_compiler_receipt(
    receipt: CompilerReceipt,
) -> CanonicalCompilerReceipt:
    payload = canonical_json_bytes(
        validate_compiler_receipt(receipt, require_content_hash=True)
    )
    gates = {gate.gate_id.value: gate.passed for gate in receipt.gates}
    return CanonicalCompilerReceipt(
        payload.decode("utf-8"),
        "sha256:" + hashlib.sha256(payload).hexdigest(),
        canonical_json(gates),
    )


def compiler_receipt_from_json(value: str) -> CompilerReceipt | None:
    """Parse only the exact canonical CompilerReceipt representation."""
    try:
        data = json.loads(value)
        data.setdefault("content_hash", None)
        data["policy_snapshots"] = tuple(
            CompilerPolicySnapshot(**row) for row in data["policy_snapshots"]
        )
        data["accepted_objects"] = tuple(
            CompilerAcceptedObject(**row) for row in data["accepted_objects"]
        )
        data["replay_kind_counts"] = tuple(
            CompilerReplayKindCount(**row)
            for row in data["replay_kind_counts"]
        )
        data["replay_results"] = tuple(
            CompilerReplayResult(**row)
            for row in data["replay_results"]
        )
        data["gates"] = tuple(
            CompilationGateResult(
                GateId(row["gate_id"]), row["passed"], tuple(row["reasons"])
            )
            for row in data["gates"]
        )
        receipt = CompilerReceipt(**data)
        canonical = (
            compiler_receipt_without_content_hash(receipt)
            if not receipt.passed
            else receipt
        )
        if canonical_json_bytes(canonical).decode("utf-8") == value:
            return receipt
        return None
    except (KeyError, TypeError, ValueError, MethodValidationError):
        return None


def compiler_receipt_json_valid(value: str) -> int:
    return int(compiler_receipt_from_json(value) is not None)


def sha256_text(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def canonical_json_text_valid(value: str) -> int:
    try:
        return int(canonical_json_bytes(json.loads(value)).decode() == value)
    except (TypeError, ValueError):
        return 0


def compiler_receipt_field(value: str, field: str) -> str | int | None:
    receipt = compiler_receipt_from_json(value)
    result = None if receipt is None else getattr(receipt, field, None)
    return int(result) if isinstance(result, bool) else result


def compiler_receipt_gate_summary(value: str) -> str | None:
    receipt = compiler_receipt_from_json(value)
    if receipt is None:
        return None
    return canonical_json(
        {gate.gate_id.value: gate.passed for gate in receipt.gates}
    )


def compiler_receipt_gate_matches(
    value: str,
    gate_id: str,
    passed: int,
    reasons_json: str,
) -> int:
    receipt = compiler_receipt_from_json(value)
    if receipt is None:
        return 0
    gate = next(
        (row for row in receipt.gates if row.gate_id.value == gate_id),
        None,
    )
    return int(
        gate is not None
        and int(gate.passed) == passed
        and canonical_json(gate.reasons) == reasons_json
    )


class SnapshotPersistence(Protocol):
    def load_snapshot(self, workspace_id: str) -> SnapshotRows | None:
        ...


class SnapshotCore(Protocol):
    def ensure_active(self) -> None:
        ...

    def document(self, document_id: str) -> DocumentRecord | None:
        ...

    def insert_workspace(self, row: WorkspaceWrite) -> None:
        ...

    def insert_document_policy_snapshot(
        self,
        row: DocumentPolicySnapshotWrite,
    ) -> None:
        ...


class MethodSnapshotStore:
    _validation_persistence: SnapshotCore
    _snapshot_persistence: SnapshotPersistence

    def create_workspace(
        self,
        workspace_id: str,
        *,
        name: str,
        objective: str,
        scope: Mapping[str, Any],
        created_by: str,
        method_schema_version: str = "method-v1",
    ) -> None:
        self._validation_persistence.ensure_active()
        self._validation_persistence.insert_workspace(
            WorkspaceWrite(
                method_id(workspace_id),
                nonempty_text("name", name),
                nonempty_text("objective", objective),
                canonical_json(scope),
                nonempty_text("method_schema_version", method_schema_version),
                "draft",
                nonempty_text("created_by", created_by),
                time.time(),
            )
        )

    def create_document_policy_snapshot(
        self,
        snapshot_id: str,
        *,
        document_id: str,
        document_content_hash: str,
        source_policy_id: str,
        resolution_status: str,
        resolved_by: str,
    ) -> None:
        self._validation_persistence.ensure_active()
        digest = sha256_hash("document_content_hash", document_content_hash)
        if resolution_status not in {
            "resolved",
            "discovery_only",
            "denied",
            "ambiguous",
        }:
            raise MethodValidationError("invalid policy resolution status")
        document_id = method_id(document_id)
        record = self._validation_persistence.document(document_id)
        if record is None:
            raise MethodNotFoundError(f"unknown document {document_id!r}")
        if resolution_status == "resolved":
            document_bytes(record, digest)
        self._validation_persistence.insert_document_policy_snapshot(
            DocumentPolicySnapshotWrite(
                method_id(snapshot_id),
                document_id,
                digest,
                method_id(source_policy_id),
                resolution_status,
                nonempty_text("resolved_by", resolved_by),
                time.time(),
            )
        )

    def _read_snapshot(
        self,
        workspace_id: str,
        *,
        include_compilation_outputs: bool,
    ) -> MethodSnapshot:
        self._validation_persistence.ensure_active()
        rows = self._snapshot_persistence.load_snapshot(workspace_id)
        if rows is None:
            raise MethodNotFoundError(f"unknown workspace {workspace_id!r}")
        canonical = canonical_json_bytes(
            snapshot_payload(
                rows,
                include_compilation_outputs=include_compilation_outputs,
            )
        )
        return MethodSnapshot(
            workspace_id,
            canonical,
            "sha256:" + hashlib.sha256(canonical).hexdigest(),
        )

    def read_snapshot(self, workspace_id: str) -> MethodSnapshot:
        return self._read_snapshot(
            workspace_id,
            include_compilation_outputs=True,
        )

    def read_compilation_snapshot(self, workspace_id: str) -> MethodSnapshot:
        return self._read_snapshot(
            workspace_id,
            include_compilation_outputs=False,
        )
