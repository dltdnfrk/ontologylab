"""Pre-mutation authority validation for retained uninstall."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from scripts.internal_deployment_fs import sha256_file, tree_sha256
from scripts.internal_deployment_removal_journal import (
    canonical_record_bytes,
    create_journal,
    prepared_anchor,
)
from scripts.internal_deployment_removal_receipt import (
    RetainedSource,
    load_identity,
    require_canonical_directory,
    source_identity,
    validate_source,
)
from scripts.internal_deployment_types import (
    ArtifactReceipt,
    DeploymentRefused,
    JournalPathIdentity,
    PreparedRemovalJournal,
    PreparedRetainedUninstall,
    PrepareRetainedUninstallRequest,
    Task12ReleaseAuthority,
)

_JOURNAL = "retained-removal-journal.jsonl"
_AUTHORITY_NAME = "OntologyLab.task12-release-authority.json"
_AUTHORITY_DIGEST_NAME = "OntologyLab.task12-release-authority.sha256"
_AUTHORITY_MARKER_NAME = "OntologyLab.task12-release-authority.complete"
_AUTHORITY_MARKER = b"ontologylab.task12-release-authority.complete.v1\n"
_Source = RetainedSource
_source = source_identity


def _release_file(path: Path, reason: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise DeploymentRefused(reason)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DeploymentRefused(reason) from exc
    if resolved != path:
        raise DeploymentRefused(reason)
    return resolved


def _load_authority(
    path: Path, expected_sha256: str
) -> tuple[Task12ReleaseAuthority, str]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise DeploymentRefused("release_authority_digest_malformed")
    parent = require_canonical_directory(
        path.parent, "release_authority_directory_unsafe"
    )
    if parent.name.startswith(".") or path.name != _AUTHORITY_NAME:
        raise DeploymentRefused("release_authority_directory_unsafe")
    expected_names = {
        _AUTHORITY_NAME,
        _AUTHORITY_DIGEST_NAME,
        _AUTHORITY_MARKER_NAME,
    }
    try:
        actual_names = {member.name for member in parent.iterdir()}
    except OSError as exc:
        raise DeploymentRefused("release_authority_directory_unreadable") from exc
    if actual_names != expected_names:
        raise DeploymentRefused("release_authority_directory_incomplete")
    authority_path = _release_file(path, "release_authority_unreadable")
    digest_path = _release_file(
        parent / _AUTHORITY_DIGEST_NAME, "release_authority_digest_unreadable"
    )
    marker_path = _release_file(
        parent / _AUTHORITY_MARKER_NAME, "release_authority_marker_unreadable"
    )
    try:
        raw = authority_path.read_bytes()
        digest = digest_path.read_bytes()
        marker = marker_path.read_bytes()
    except OSError as exc:
        raise DeploymentRefused("release_authority_unreadable") from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if marker != _AUTHORITY_MARKER:
        raise DeploymentRefused("release_authority_marker_mismatch")
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise DeploymentRefused("release_authority_digest_mismatch")
    if digest != actual_sha256.encode("ascii") + b"\n":
        raise DeploymentRefused("release_authority_sidecar_digest_mismatch")
    try:
        authority = Task12ReleaseAuthority.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        raise DeploymentRefused("release_authority_malformed") from exc
    return authority, actual_sha256


def _require_unchanged(source: RetainedSource) -> None:
    try:
        validate_source(source, retained=False)
    except DeploymentRefused as exc:
        raise DeploymentRefused("retained_removal_source_drift") from exc


def prepare_retained_uninstall(
    request: PrepareRetainedUninstallRequest,
) -> PreparedRetainedUninstall:
    """Create the sole prepared journal without renaming either source tree."""
    home = require_canonical_directory(request.home, "retained_home_path_unsafe")
    root = require_canonical_directory(
        request.retained_root, "retained_root_path_unsafe"
    )
    app = require_canonical_directory(request.app, "retained_app_path_unsafe")
    runtime = require_canonical_directory(
        home / "Library/Caches/ontologylab/runtime", "retained_runtime_path_unsafe"
    )
    root_info = root.stat()
    if root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
        raise DeploymentRefused("retained_root_permissions")
    if app.name != "OntologyLab.app":
        raise DeploymentRefused("retained_removal_scope")
    if root in app.parents or app in root.parents or root in runtime.parents:
        raise DeploymentRefused("retained_removal_scope")
    if any(root.iterdir()):
        raise DeploymentRefused("retained_removal_collision")
    authority, authority_sha256 = _load_authority(
        request.release_authority, request.release_authority_sha256
    )
    release_dmg = _release_file(
        request.release_dmg, "release_authority_dmg_unreadable"
    )
    release_zip = _release_file(
        request.release_zip, "release_authority_zip_unreadable"
    )
    install_receipt = _release_file(
        request.install_receipt, "release_authority_receipt_unreadable"
    )
    if sha256_file(release_dmg) != authority.final_dmg_sha256:
        raise DeploymentRefused("release_authority_dmg_mismatch")
    if sha256_file(release_zip) != authority.zip_sha256:
        raise DeploymentRefused("release_authority_zip_mismatch")
    if sha256_file(install_receipt) != authority.install_receipt_sha256:
        raise DeploymentRefused("release_authority_receipt_mismatch")
    try:
        receipt = ArtifactReceipt.model_validate_json(
            install_receipt.read_bytes(), strict=True
        )
    except (OSError, ValidationError) as exc:
        raise DeploymentRefused("release_authority_receipt_malformed") from exc
    if receipt.app_tree_sha256 != authority.final_app_tree_sha256:
        raise DeploymentRefused("release_authority_receipt_app_mismatch")
    try:
        running = request.running_executable.resolve(strict=True)
    except OSError as exc:
        raise DeploymentRefused("running_installer_unreadable") from exc
    if running.is_relative_to(app) or running.is_relative_to(root):
        raise DeploymentRefused("running_installer_scope")
    if sha256_file(running) != authority.deployment_executable_sha256:
        raise DeploymentRefused("running_installer_sha256_mismatch")
    if tree_sha256(app) != authority.final_app_tree_sha256:
        raise DeploymentRefused("release_authority_app_mismatch")
    identity = load_identity(app)
    if (
        identity.architecture != authority.architecture
        or identity.version != authority.version
        or identity.executable_path
        != authority.deployment_executable_relative_path
        or identity.executable_sha256
        != authority.deployment_executable_sha256
    ):
        raise DeploymentRefused("release_authority_identity_mismatch")
    app_source = _source(app, root / "OntologyLab.app")
    runtime_source = _source(runtime, root / "runtime")
    app_identity = JournalPathIdentity(
        source_path=str(app_source.path),
        retained_path=str(app_source.retained),
        inode=app_source.inode,
        device=app_source.device,
        mode=app_source.mode,
        tree_sha256=app_source.tree_hash,
    )
    runtime_identity = JournalPathIdentity(
        source_path=str(runtime_source.path),
        retained_path=str(runtime_source.retained),
        inode=runtime_source.inode,
        device=runtime_source.device,
        mode=runtime_source.mode,
        tree_sha256=runtime_source.tree_hash,
    )
    if (
        app_identity.device != root_info.st_dev
        or runtime_identity.device != root_info.st_dev
    ):
        raise DeploymentRefused("retained_removal_cross_device")
    if (app_identity.device, app_identity.inode) == (
        runtime_identity.device,
        runtime_identity.inode,
    ):
        raise DeploymentRefused("retained_removal_identity_collision")
    _require_unchanged(app_source)
    _require_unchanged(runtime_source)
    prepared = PreparedRemovalJournal(
        schema="ontologylab.retained-removal-journal.v3",
        event="prepared",
        event_id=uuid.uuid4().hex,
        timestamp_utc=datetime.now(UTC).isoformat(),
        release_authority=authority,
        release_authority_sha256=authority_sha256,
        artifact=identity,
        app=app_identity,
        runtime=runtime_identity,
    )
    canonical = canonical_record_bytes(prepared)
    journal = root / _JOURNAL
    create_journal(journal, prepared)
    return PreparedRetainedUninstall(
        journal=journal,
        prepared=prepared,
        release_authority_sha256=authority_sha256,
        prepared_anchor=prepared_anchor(canonical),
    )
