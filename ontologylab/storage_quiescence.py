"""Supervisor-bound holder-discovery proof for canonical mutable SQLite."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ontologylab.storage_upgrade_types import (
    QuiescenceKind,
    QuiescenceProof,
    UpgradeRefused,
    VerifiedBackendIdentity,
)

_RECEIPT_SCHEMA: Final = "ontologylab.storage-quiescence.v2"
_RECEIPT_NAME: Final = "quiescence.json"
_NONCE: Final = re.compile(r"^[0-9a-f]{32}$")


class ProcessFingerprintReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    executable_path: str = Field(alias="executablePath")
    start_seconds: int = Field(alias="startSeconds", ge=0)
    start_microseconds: int = Field(alias="startMicroseconds", ge=0)
    uid: int = Field(ge=0)


class VerifiedOwnerReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    pid: int = Field(gt=0)
    version: str = Field(min_length=1)
    bundle_identifier: str = Field(alias="bundleIdentifier", min_length=1)
    fingerprint: ProcessFingerprintReceipt


class QuiescenceReceipt(BaseModel):
    """Strict owner-only evidence emitted while the supervisor holds its lock."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    schema_name: Literal["ontologylab.storage-quiescence.v2"]
    proof_kind: QuiescenceKind
    supervisor_pid: int = Field(gt=0)
    nonce: str
    inspected_paths: tuple[str, ...]
    inspected_at_ns: int = Field(gt=0)
    initial_holder_pids: tuple[int, ...]
    final_holder_pids: tuple[int, ...]
    verified_owner: VerifiedOwnerReceipt | None = None
    signals: tuple[str, ...]
    exit_observed: bool


def inspected_storage_paths(data_dir: Path) -> tuple[Path, ...]:
    """Match Foundation's lexical normalization of macOS private aliases."""
    absolute = str(data_dir.absolute())
    normalized = (
        absolute.removeprefix("/private")
        if absolute.startswith(("/private/var/", "/private/tmp/"))
        else absolute
    )
    root = Path(normalized)
    return tuple(
        path
        for name in ("kg.sqlite", "chat.sqlite")
        for path in (
            root / name,
            root / f"{name}-wal",
            root / f"{name}-shm",
        )
    )


def _read_receipt(path: Path) -> tuple[QuiescenceReceipt, str]:
    try:
        directory = path.parent.lstat()
        receipt_info = path.lstat()
        if (
            path.name != _RECEIPT_NAME
            or stat.S_ISLNK(receipt_info.st_mode)
            or not stat.S_ISREG(receipt_info.st_mode)
            or stat.S_IMODE(receipt_info.st_mode) != 0o600
            or receipt_info.st_uid != os.getuid()
            or not stat.S_ISDIR(directory.st_mode)
            or stat.S_IMODE(directory.st_mode) != 0o700
            or directory.st_uid != os.getuid()
        ):
            raise UpgradeRefused("quiescence-receipt-owner")
        payload = path.read_bytes()
        receipt = QuiescenceReceipt.model_validate_json(payload, strict=True)
    except (OSError, ValidationError) as exc:
        raise UpgradeRefused("quiescence-receipt-invalid") from exc
    return receipt, hashlib.sha256(payload).hexdigest()


def _identity(receipt: VerifiedOwnerReceipt) -> VerifiedBackendIdentity:
    return VerifiedBackendIdentity(
        pid=receipt.pid,
        version=receipt.version,
        bundle_identifier=receipt.bundle_identifier,
        executable_path=receipt.fingerprint.executable_path,
        start_seconds=receipt.fingerprint.start_seconds,
        start_microseconds=receipt.fingerprint.start_microseconds,
        uid=receipt.fingerprint.uid,
    )


def _validate_semantics(receipt: QuiescenceReceipt) -> None:
    if receipt.final_holder_pids:
        raise UpgradeRefused("quiescence-holders-remain")
    match receipt.proof_kind:
        case QuiescenceKind.NO_EXISTING_BACKEND:
            if (
                receipt.initial_holder_pids
                or receipt.verified_owner is not None
                or receipt.signals
                or receipt.exit_observed
            ):
                raise UpgradeRefused("quiescence-proof-incomplete")
        case QuiescenceKind.STOPPED_BACKEND:
            owner = receipt.verified_owner
            if (
                owner is None
                or receipt.initial_holder_pids != (owner.pid,)
                or not receipt.exit_observed
                or not receipt.signals
                or receipt.signals[-1] != "exit-observed"
            ):
                raise UpgradeRefused("quiescence-proof-incomplete")
        case unreachable:
            assert_never(unreachable)


def load_quiescence_proof(
    receipt_path: Path,
    *,
    supervisor_pid: int,
    nonce: str,
    data_dir: Path,
) -> QuiescenceProof:
    """Parse the supervisor receipt into a complete immutable proof."""
    receipt, _digest = _read_receipt(receipt_path)
    proof = QuiescenceProof(
        receipt_path=receipt_path,
        supervisor_pid=supervisor_pid,
        nonce=nonce,
        proof_kind=receipt.proof_kind,
        inspected_paths=tuple(Path(path) for path in receipt.inspected_paths),
        inspected_at_ns=receipt.inspected_at_ns,
        initial_holder_pids=receipt.initial_holder_pids,
        final_holder_pids=receipt.final_holder_pids,
        verified_owner=(
            None if receipt.verified_owner is None else _identity(receipt.verified_owner)
        ),
        signals=receipt.signals,
        exit_observed=receipt.exit_observed,
    )
    validate_quiescence(proof, data_dir=data_dir)
    return proof


def validate_quiescence(proof: QuiescenceProof, *, data_dir: Path) -> str:
    """Re-read and bind complete holder evidence to parent, nonce, and paths."""
    receipt, digest = _read_receipt(proof.receipt_path)
    _validate_semantics(receipt)
    owner = None if receipt.verified_owner is None else _identity(receipt.verified_owner)
    if (
        receipt.schema_name != _RECEIPT_SCHEMA
        or receipt.supervisor_pid != proof.supervisor_pid
        or receipt.nonce != proof.nonce
        or _NONCE.fullmatch(proof.nonce) is None
        or tuple(Path(path) for path in receipt.inspected_paths)
        != inspected_storage_paths(data_dir)
        or proof.inspected_paths != inspected_storage_paths(data_dir)
        or receipt.inspected_at_ns != proof.inspected_at_ns
        or receipt.proof_kind is not proof.proof_kind
        or receipt.initial_holder_pids != proof.initial_holder_pids
        or receipt.final_holder_pids != proof.final_holder_pids
        or owner != proof.verified_owner
        or receipt.signals != proof.signals
        or receipt.exit_observed is not proof.exit_observed
    ):
        raise UpgradeRefused("quiescence-receipt-mismatch")
    if proof.supervisor_pid != os.getppid():
        raise UpgradeRefused("quiescence-supervisor-identity")
    if (proof.receipt_path.parent / "instance.json").exists():
        raise UpgradeRefused("old-backend-instance-live")
    try:
        os.kill(proof.supervisor_pid, 0)
    except OSError as exc:
        raise UpgradeRefused("quiescence-supervisor-exited") from exc
    return digest
