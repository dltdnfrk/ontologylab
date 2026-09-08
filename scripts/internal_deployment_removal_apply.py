"""Anchor-authenticated forward recovery for retained uninstall."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from scripts.internal_deployment_fs import sha256_file
from scripts.internal_deployment_removal import _rename_exclusive
from scripts.internal_deployment_removal_journal import (
    JournalPhase,
    append_progress,
    load_journal,
    verify_prepared_anchor,
)
from scripts.internal_deployment_removal_receipt import (
    ReceiptFiles,
    RetainedPair,
    RetainedSource,
    finalize_receipt,
    require_canonical_directory,
    validate_source,
)
from scripts.internal_deployment_types import (
    ApplyRetainedUninstallRequest,
    DeploymentRefused,
    JournalPathIdentity,
)

_JOURNAL = "retained-removal-journal.jsonl"
_RECEIPT = "retained-removal-receipt.json"


@dataclass(frozen=True, slots=True)
class RecoveryPaths:
    app: Path
    runtime: Path
    root: Path
    journal: Path
    receipt: Path


def _bound_source(
    identity: JournalPathIdentity, source: Path, retained: Path
) -> RetainedSource:
    if identity.source_path != str(source) or identity.retained_path != str(retained):
        raise DeploymentRefused("retained_removal_journal_projection")
    return RetainedSource(
        source,
        retained,
        identity.inode,
        identity.device,
        identity.mode,
        identity.tree_sha256,
    )


def _finalize(paths: RecoveryPaths, pair: RetainedPair) -> Path:
    return finalize_receipt(
        ReceiptFiles(paths.journal, paths.receipt),
        load_journal(paths.journal),
        pair,
    )


def _finish_runtime(paths: RecoveryPaths, pair: RetainedPair, event_id: str) -> Path:
    try:
        _rename_exclusive(pair.runtime.path, pair.runtime.retained)
    except DeploymentRefused as exc:
        state = load_journal(paths.journal)
        if state.events[-1:] != ("forward_recovery_required",):
            append_progress(paths.journal, "forward_recovery_required", event_id)
        raise DeploymentRefused("retained_removal_forward_recovery_required") from exc
    append_progress(paths.journal, "runtime_retained", event_id)
    return _finalize(paths, pair)


def _recover(paths: RecoveryPaths, pair: RetainedPair) -> Path:
    state = load_journal(paths.journal)
    match state.phase:
        case JournalPhase.PREPARED:
            if paths.receipt.exists():
                raise DeploymentRefused("retained_removal_receipt_state")
            app_active = os.path.lexists(pair.app.path)
            app_retained = os.path.lexists(pair.app.retained)
            validate_source(pair.runtime, retained=False)
            if app_active and not app_retained:
                validate_source(pair.app, retained=False)
                _rename_exclusive(pair.app.path, pair.app.retained)
            elif app_retained and not app_active:
                validate_source(pair.app, retained=True)
            else:
                raise DeploymentRefused("retained_removal_state_mismatch")
            append_progress(paths.journal, "app_retained", state.prepared.event_id)
            return _finish_runtime(paths, pair, state.prepared.event_id)
        case JournalPhase.APP_RETAINED | JournalPhase.APP_RETAIN_FAILED:
            validate_source(pair.app, retained=True)
            if paths.receipt.exists():
                raise DeploymentRefused("retained_removal_receipt_state")
            runtime_active = os.path.lexists(pair.runtime.path)
            runtime_retained = os.path.lexists(pair.runtime.retained)
            if runtime_retained and not runtime_active:
                validate_source(pair.runtime, retained=True)
                append_progress(
                    paths.journal, "runtime_retained", state.prepared.event_id
                )
                return _finalize(paths, pair)
            validate_source(pair.runtime, retained=False)
            return _finish_runtime(paths, pair, state.prepared.event_id)
        case (
            JournalPhase.RUNTIME_RETAINED
            | JournalPhase.RUNTIME_RETAINED_AFTER_FAILURE
        ):
            validate_source(pair.app, retained=True)
            validate_source(pair.runtime, retained=True)
            return _finalize(paths, pair)
        case unreachable:
            assert_never(unreachable)


def apply_retained_uninstall(request: ApplyRetainedUninstallRequest) -> Path:
    """Authenticate the caller anchor, then move or recover only exact bound trees."""
    home = require_canonical_directory(request.home, "retained_home_path_unsafe")
    root = require_canonical_directory(
        request.retained_root, "retained_root_path_unsafe"
    )
    runtime = home / "Library/Caches/ontologylab/runtime"
    app = request.app
    if not app.is_absolute() or app != Path(os.path.normpath(app)):
        raise DeploymentRefused("retained_app_path_unsafe")
    root_info = root.stat()
    if root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
        raise DeploymentRefused("retained_root_permissions")
    if app.name != "OntologyLab.app" or root in app.parents or app in root.parents:
        raise DeploymentRefused("retained_removal_scope")
    paths = RecoveryPaths(
        app, runtime, root, root / _JOURNAL, root / _RECEIPT
    )
    verify_prepared_anchor(paths.journal, request.prepared_anchor)
    state = load_journal(paths.journal)
    try:
        running = request.running_executable.resolve(strict=True)
    except OSError as exc:
        raise DeploymentRefused("running_installer_unreadable") from exc
    if running.is_relative_to(app) or running.is_relative_to(root):
        raise DeploymentRefused("running_installer_scope")
    if (
        sha256_file(running)
        != state.prepared.release_authority.deployment_executable_sha256
    ):
        raise DeploymentRefused("running_installer_sha256_mismatch")
    pair = RetainedPair(
        _bound_source(state.prepared.app, app, root / "OntologyLab.app"),
        _bound_source(state.prepared.runtime, runtime, root / "runtime"),
    )
    allowed = {paths.journal, pair.app.retained, pair.runtime.retained, paths.receipt}
    if any(member not in allowed for member in root.iterdir()):
        raise DeploymentRefused("retained_removal_collision")
    if any(source.device != root_info.st_dev for source in (pair.app, pair.runtime)):
        raise DeploymentRefused("retained_removal_cross_device")
    return _recover(paths, pair)
