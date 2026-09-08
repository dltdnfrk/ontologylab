"""Same-filesystem staged desktop backup, migration, activation, and recovery."""

from __future__ import annotations

import errno
import shutil
from collections.abc import Callable
from pathlib import Path

from ontologylab.server.session import install_session
from ontologylab.storage_compatibility import preflight_database
from ontologylab.storage_quiescence import validate_quiescence
from ontologylab.storage_types import CompatibilityState
from ontologylab.storage_upgrade_io import (
    available_bytes,
    checkpoint_database,
    logical_snapshot,
    pack_hashes,
    registry_hashes,
    required_space,
    tree_hashes,
)
from ontologylab.storage_upgrade_journal import (
    JOURNAL_NAME,
    fsync_directory,
    read_journal,
    upgrade_lock,
    write_journal,
)
from ontologylab.storage_upgrade_steps import (
    STAGING_NAME,
    activate_transition,
    backup_transition,
    migrate_transition,
    upgrade_paths,
    validate_transition,
)
from ontologylab.storage_upgrade_types import (
    JOURNAL_SCHEMA,
    QuiescenceProof,
    UpgradeFailpoint,
    UpgradeInterrupted,
    UpgradeJournal,
    UpgradeJournalRefused,
    UpgradePhase,
    UpgradeRefused,
    UpgradeRequest,
    UpgradeResult,
)
from ontologylab.storage_upgrade_validation import validate_retained_backup

__all__ = [
    "QuiescenceProof",
    "UpgradeFailpoint",
    "UpgradeInterrupted",
    "UpgradeJournalRefused",
    "UpgradeRefused",
    "UpgradeRequest",
    "UpgradeResult",
    "recover_staged_upgrade",
    "rollback_pre_activation",
    "run_staged_upgrade",
]


def _require_canonical(request: UpgradeRequest) -> None:
    root = request.application_support_dir
    expected = (root / "data", root / "packs", root / "backups")
    if (request.data_dir, request.packs_dir, request.backups_dir) != expected:
        raise UpgradeRefused("noncanonical-path")
    for path in (root, *expected):
        if path.is_symlink():
            raise UpgradeRefused("symlink")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if request.backups_dir.stat().st_dev != root.stat().st_dev:
        raise UpgradeRefused("cross-filesystem")


def _checkpoint_sources(data_dir: Path) -> None:
    for name in ("kg.sqlite", "chat.sqlite"):
        path = data_dir / name
        if path.is_file():
            checkpoint_database(path)


def _new_journal(request: UpgradeRequest) -> UpgradeJournal:
    report = preflight_database(request.data_dir / "kg.sqlite", request.packs_dir)
    if report.state is CompatibilityState.CORRUPT:
        raise UpgradeRefused("source-corrupt")
    if report.state is not CompatibilityState.SUPPORTED_OLDER:
        raise UpgradeRefused(f"storage-{report.state.value}")
    if available_bytes(request.application_support_dir) < required_space(request.data_dir):
        raise UpgradeRefused("insufficient-space")
    source_digest, source_counts = logical_snapshot(request.data_dir)
    if report.storage_version is None:
        raise UpgradeRefused("source-version-missing")
    quiescence_hash = validate_quiescence(
        request.quiescence,
        data_dir=request.data_dir,
    )
    owner = request.quiescence.verified_owner
    return UpgradeJournal(
        schema_name=JOURNAL_SCHEMA,
        upgrade_id=f"v{report.storage_version}-v1-{source_digest[:16]}",
        phase=UpgradePhase.PREPARED,
        source_version=int(report.storage_version),
        source_digest=source_digest,
        source_counts=source_counts,
        source_registry_hashes=registry_hashes(request.data_dir),
        raw_hashes=tree_hashes(request.data_dir / "documents"),
        pack_hashes=pack_hashes(request.packs_dir),
        quiescence_receipt_hash=quiescence_hash,
        quiescence_proof_kind=request.quiescence.proof_kind,
        quiescence_inspected_paths=tuple(
            str(path) for path in request.quiescence.inspected_paths
        ),
        quiescence_inspected_at_ns=request.quiescence.inspected_at_ns,
        quiescence_initial_holder_pids=request.quiescence.initial_holder_pids,
        quiescence_final_holder_pids=request.quiescence.final_holder_pids,
        quiescence_verified_backend_pid=None if owner is None else owner.pid,
        quiescence_verified_backend_version=(
            None if owner is None else owner.version
        ),
        quiescence_verified_bundle_identifier=(
            None if owner is None else owner.bundle_identifier
        ),
        quiescence_verified_executable_path=(
            None if owner is None else owner.executable_path
        ),
        quiescence_verified_start_marker=(
            None
            if owner is None
            else f"{owner.start_seconds}.{owner.start_microseconds}"
        ),
        quiescence_verified_uid=None if owner is None else owner.uid,
        quiescence_signals=request.quiescence.signals,
        quiescence_exit_observed=request.quiescence.exit_observed,
    )


def _result(request: UpgradeRequest, journal: UpgradeJournal) -> UpgradeResult:
    activated_digest, _activated_counts = logical_snapshot(request.data_dir)
    _staging, backup = upgrade_paths(request, journal.upgrade_id)
    return UpgradeResult(
        upgrade_id=journal.upgrade_id,
        backup_dir=backup,
        source_digest=journal.source_digest,
        backup_digest=journal.backup_digest,
        activated_digest=activated_digest,
        source_counts=journal.source_counts,
        backup_counts=journal.backup_counts,
        activated_counts=_activated_counts,
        activated=True,
    )


def _run_staged_upgrade(
    request: UpgradeRequest,
    *,
    failpoint: Callable[[UpgradeFailpoint], None] | None = None,
) -> UpgradeResult:
    _require_canonical(request)
    validate_quiescence(request.quiescence, data_dir=request.data_dir)
    with upgrade_lock(request.application_support_dir):
        validate_quiescence(request.quiescence, data_dir=request.data_dir)
        _checkpoint_sources(request.data_dir)
        journal = read_journal(request.application_support_dir)
        staging_root = request.application_support_dir / STAGING_NAME
        if journal is None:
            report = preflight_database(request.data_dir / "kg.sqlite", request.packs_dir)
            if report.state is CompatibilityState.CURRENT:
                digest, counts = logical_snapshot(request.data_dir)
                return UpgradeResult(
                    "current",
                    None,
                    digest,
                    digest,
                    digest,
                    counts,
                    counts,
                    counts,
                    True,
                )
            if staging_root.exists():
                raise UpgradeJournalRefused("unowned-staging")
            journal = _new_journal(request)
            write_journal(request.application_support_dir, journal)
        if journal.phase is UpgradePhase.COMPLETE:
            return _result(request, journal)
        if journal.phase in {
            UpgradePhase.BACKED_UP,
            UpgradePhase.MIGRATED,
            UpgradePhase.VALIDATED,
            UpgradePhase.ACTIVATING,
        }:
            validate_retained_backup(request, journal)
        if journal.phase is UpgradePhase.PREPARED:
            if failpoint is not None:
                failpoint(UpgradeFailpoint.BEFORE_BACKUP)
            journal = backup_transition(request, journal, failpoint)
            validate_retained_backup(request, journal)
        if journal.phase is UpgradePhase.BACKED_UP:
            if failpoint is not None:
                failpoint(UpgradeFailpoint.STAGED_MIGRATION)
            journal = migrate_transition(request, journal)
        if journal.phase is UpgradePhase.MIGRATED:
            if failpoint is not None:
                failpoint(UpgradeFailpoint.VALIDATION)
            journal = validate_transition(request, journal)
        if journal.phase is UpgradePhase.VALIDATED and failpoint is not None:
            failpoint(UpgradeFailpoint.PRE_ACTIVATION)
        if journal.phase in {UpgradePhase.VALIDATED, UpgradePhase.ACTIVATING}:
            journal = activate_transition(request, journal, failpoint)
        if journal.phase is UpgradePhase.ACTIVATED:
            if failpoint is not None:
                failpoint(UpgradeFailpoint.POST_ACTIVATION)
            install_session(request.data_dir)
            journal = journal.model_copy(update={"phase": UpgradePhase.COMPLETE})
            write_journal(request.application_support_dir, journal)
        return _result(request, journal)


def run_staged_upgrade(
    request: UpgradeRequest,
    *,
    failpoint: Callable[[UpgradeFailpoint], None] | None = None,
) -> UpgradeResult:
    """Run or deterministically resume the one canonical staged upgrade."""
    try:
        return _run_staged_upgrade(request, failpoint=failpoint)
    except OSError as exc:
        reason = (
            "insufficient-space"
            if exc.errno == errno.ENOSPC
            else "filesystem-read-only"
            if exc.errno in {errno.EACCES, errno.EROFS}
            else "filesystem-failure"
        )
        raise UpgradeRefused(reason) from exc


def recover_staged_upgrade(request: UpgradeRequest) -> UpgradeResult:
    """Resume from the durable journal without injecting a new interruption."""
    return run_staged_upgrade(request)


def rollback_pre_activation(request: UpgradeRequest) -> None:
    """Discard only owned pre-activation staging; never overwrite newer writes."""
    _require_canonical(request)
    validate_quiescence(request.quiescence, data_dir=request.data_dir)
    with upgrade_lock(request.application_support_dir):
        journal = read_journal(request.application_support_dir)
        if journal is None:
            raise UpgradeJournalRefused("missing")
        if journal.phase in {
            UpgradePhase.ACTIVATING,
            UpgradePhase.ACTIVATED,
            UpgradePhase.COMPLETE,
        }:
            raise UpgradeRefused("activation-started-forward-recovery-required")
        staging, backup = upgrade_paths(request, journal.upgrade_id)
        shutil.rmtree(staging, ignore_errors=True)
        if journal.phase is UpgradePhase.PREPARED:
            shutil.rmtree(backup, ignore_errors=True)
        (request.application_support_dir / JOURNAL_NAME).unlink()
        staging.parent.rmdir()
        fsync_directory(request.application_support_dir)
