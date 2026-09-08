"""Independent filesystem validation and receipts for retained removal."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from scripts.internal_deployment_fs import sha256_file, tree_sha256
from scripts.internal_deployment_removal_journal import (
    RemovalJournalState,
    append_completed,
    canonical_record_bytes,
    prepared_anchor,
)
from scripts.internal_deployment_types import (
    DeploymentRefused,
    InstalledDeploymentIdentity,
    RetainedPathReceipt,
    RetainedRemovalReceipt,
)


@dataclass(frozen=True, slots=True)
class RetainedSource:
    path: Path
    retained: Path
    inode: int
    device: int
    mode: int
    tree_hash: str


@dataclass(frozen=True, slots=True)
class RetainedPair:
    app: RetainedSource
    runtime: RetainedSource


@dataclass(frozen=True, slots=True)
class ReceiptFiles:
    journal: Path
    receipt: Path


def require_canonical_directory(path: Path, reason: str) -> Path:
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise DeploymentRefused(reason)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DeploymentRefused(reason) from exc
    if resolved != path:
        raise DeploymentRefused(reason)
    return resolved


def load_identity(app: Path) -> InstalledDeploymentIdentity:
    manifest = app / "Contents/Resources/internal-deployment.json"
    try:
        identity = InstalledDeploymentIdentity.model_validate_json(
            manifest.read_bytes(), strict=True
        )
    except (OSError, ValidationError) as exc:
        raise DeploymentRefused("retained_artifact_identity") from exc
    if sha256_file(app / identity.executable_path) != identity.executable_sha256:
        raise DeploymentRefused("retained_artifact_identity")
    return identity


def source_identity(path: Path, retained: Path) -> RetainedSource:
    info = path.stat()
    return RetainedSource(
        path,
        retained,
        info.st_ino,
        info.st_dev,
        stat.S_IMODE(info.st_mode),
        tree_sha256(path),
    )


def validate_source(source: RetainedSource, *, retained: bool) -> None:
    current = source.retained if retained else source.path
    absent = source.path if retained else source.retained
    if os.path.lexists(absent):
        raise DeploymentRefused("retained_removal_state_mismatch")
    current = require_canonical_directory(current, "retained_removal_state_mismatch")
    info = current.stat()
    if (
        info.st_ino != source.inode
        or info.st_dev != source.device
        or stat.S_IMODE(info.st_mode) != source.mode
        or tree_sha256(current) != source.tree_hash
    ):
        raise DeploymentRefused("retained_removal_state_mismatch")


def _path_receipt(source: RetainedSource) -> RetainedPathReceipt:
    validate_source(source, retained=True)
    return RetainedPathReceipt(
        source_path=str(source.path),
        source_inode=source.inode,
        source_device=source.device,
        source_tree_sha256=source.tree_hash,
        source_mode=source.mode,
        retained_path=str(source.retained),
        retained_inode=source.inode,
        retained_device=source.device,
        retained_tree_sha256=source.tree_hash,
        retained_mode=source.mode,
        active_path_absent=True,
    )


def _expected_receipt(
    state: RemovalJournalState, pair: RetainedPair
) -> RetainedRemovalReceipt:
    identity = load_identity(pair.app.retained)
    if identity != state.prepared.artifact:
        raise DeploymentRefused("retained_removal_artifact_drift")
    return RetainedRemovalReceipt(
        schema="ontologylab.retained-removal-receipt.v2",
        event="retained_uninstall_completed",
        event_id=state.prepared.event_id,
        timestamp_utc=state.prepared.timestamp_utc,
        artifact=identity,
        app_tree_sha256=pair.app.tree_hash,
        journal_state_sha256=state.state_sha256,
        prepared_anchor=prepared_anchor(canonical_record_bytes(state.prepared)),
        release_authority_sha256=state.prepared.release_authority_sha256,
        paths=(_path_receipt(pair.app), _path_receipt(pair.runtime)),
    )


def _write_receipt(path: Path, receipt: RetainedRemovalReceipt) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(receipt.model_dump_json(by_alias=True).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise DeploymentRefused("retained_removal_receipt_write") from exc


def finalize_receipt(
    files: ReceiptFiles, state: RemovalJournalState, pair: RetainedPair
) -> Path:
    """Validate or create a receipt, then bind its exact bytes in the journal."""
    expected = _expected_receipt(state, pair)
    if files.receipt.exists():
        try:
            actual = RetainedRemovalReceipt.model_validate_json(
                files.receipt.read_bytes(), strict=True
            )
        except (OSError, ValidationError) as exc:
            raise DeploymentRefused("retained_removal_receipt_malformed") from exc
        if actual != expected:
            raise DeploymentRefused("retained_removal_receipt_drift")
    else:
        _write_receipt(files.receipt, expected)
    receipt_hash = sha256_file(files.receipt)
    if state.completed is not None:
        if (
            state.completed.receipt_sha256 != receipt_hash
            or state.completed.prepared_anchor != expected.prepared_anchor
            or state.completed.release_authority_sha256
            != expected.release_authority_sha256
        ):
            raise DeploymentRefused("retained_removal_receipt_drift")
        return files.receipt
    append_completed(files.journal, state, receipt_hash)
    return files.receipt
