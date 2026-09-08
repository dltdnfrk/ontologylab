"""Post-final-DMG Task12 external authority finalization."""

from __future__ import annotations

import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from scripts.internal_deployment_fs import sha256_file, tree_sha256
from scripts.internal_deployment_release_authority import (
    Task12AuthorityRequest,
    generate_task12_release_authority,
)
from scripts.internal_deployment_removal import _rename_exclusive
from scripts.internal_deployment_removal_receipt import load_identity
from scripts.internal_deployment_types import (
    DeploymentRefused,
    Task12ReleaseAuthority,
)

_AUTHORITY_NAME = "OntologyLab.task12-release-authority.json"
_AUTHORITY_DIGEST_NAME = "OntologyLab.task12-release-authority.sha256"
_AUTHORITY_MARKER_NAME = "OntologyLab.task12-release-authority.complete"
_AUTHORITY_MARKER = b"ontologylab.task12-release-authority.complete.v1\n"


@dataclass(frozen=True, slots=True)
class Task12FinalizeRequest:
    final_dmg: Path
    final_zip: Path
    final_app: Path
    install_receipt: Path
    external_receipts_dir: Path


@dataclass(frozen=True, slots=True)
class FinalArtifactHashes:
    dmg_sha256: str
    zip_sha256: str
    app_tree_sha256: str
    install_receipt_sha256: str
    installer_sha256: str


@dataclass(frozen=True, slots=True)
class Task12FinalizeResult:
    authority: Path
    authority_digest: Path
    authority_sha256: str
    final_hashes: FinalArtifactHashes


@dataclass(frozen=True, slots=True)
class FinalArtifactSnapshot:
    hashes: FinalArtifactHashes
    identities: tuple[tuple[Path, int, int, int], ...]


def _final_hashes(request: Task12FinalizeRequest) -> FinalArtifactHashes:
    identity = load_identity(request.final_app)
    return FinalArtifactHashes(
        dmg_sha256=sha256_file(request.final_dmg),
        zip_sha256=sha256_file(request.final_zip),
        app_tree_sha256=tree_sha256(request.final_app),
        install_receipt_sha256=sha256_file(request.install_receipt),
        installer_sha256=identity.executable_sha256,
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, payload: bytes, reason: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(path.parent)
    except OSError as exc:
        raise DeploymentRefused(reason) from exc


def _write_digest(path: Path, digest: str) -> None:
    _write_exclusive(
        path, digest.encode("ascii") + b"\n", "release_authority_digest_write"
    )


def _resolved_file(path: Path, reason: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DeploymentRefused(reason) from exc
    if path.is_symlink() or not resolved.is_file():
        raise DeploymentRefused(reason)
    return resolved


def _resolved_directory(path: Path, reason: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DeploymentRefused(reason) from exc
    if path.is_symlink() or not resolved.is_dir() or resolved.is_symlink():
        raise DeploymentRefused(reason)
    return resolved


def _normalized_request(request: Task12FinalizeRequest) -> Task12FinalizeRequest:
    final_app = _resolved_directory(request.final_app, "task12_final_app_unreadable")
    try:
        parent = request.external_receipts_dir.parent.resolve(strict=True)
    except OSError as exc:
        raise DeploymentRefused("task12_external_receipts_path") from exc
    external = parent / request.external_receipts_dir.name
    if request.external_receipts_dir.exists() or request.external_receipts_dir.is_symlink():
        raise DeploymentRefused("task12_authority_collision")
    if external == final_app or external.is_relative_to(final_app):
        raise DeploymentRefused("task12_authority_circular_scope")
    return Task12FinalizeRequest(
        _resolved_file(request.final_dmg, "task12_final_dmg_unreadable"),
        _resolved_file(request.final_zip, "task12_final_zip_unreadable"),
        final_app,
        _resolved_file(
            request.install_receipt, "task12_install_receipt_unreadable"
        ),
        external,
    )


def _snapshot(request: Task12FinalizeRequest) -> FinalArtifactSnapshot:
    identity = load_identity(request.final_app)
    paths = (
        request.final_dmg, request.final_zip, request.final_app, request.install_receipt,
        request.final_app / identity.executable_path,
    )
    identities: list[tuple[Path, int, int, int]] = []
    try:
        for path in paths:
            info = path.stat()
            path_identity = (
                path.resolve(strict=True), info.st_dev, info.st_ino,
                stat.S_IMODE(info.st_mode),
            )
            identities.append(path_identity)
    except OSError as exc:
        raise DeploymentRefused("task12_final_artifact_identity") from exc
    return FinalArtifactSnapshot(_final_hashes(request), tuple(identities))


def _validate_staged(
    authority: Path,
    authority_digest: Path,
    expected: FinalArtifactHashes,
) -> Task12ReleaseAuthority:
    try:
        parsed = Task12ReleaseAuthority.model_validate_json(
            authority.read_bytes(), strict=True
        )
        digest = authority_digest.read_text(encoding="ascii")
    except (OSError, UnicodeError, ValidationError) as exc:
        raise DeploymentRefused("task12_authority_staging_incomplete") from exc
    authority_sha256 = sha256_file(authority)
    if digest != f"{authority_sha256}\n":
        raise DeploymentRefused("task12_authority_staging_incomplete")
    if (
        parsed.final_dmg_sha256 != expected.dmg_sha256
        or parsed.zip_sha256 != expected.zip_sha256
        or parsed.final_app_tree_sha256 != expected.app_tree_sha256
        or parsed.install_receipt_sha256 != expected.install_receipt_sha256
        or parsed.deployment_executable_sha256 != expected.installer_sha256
    ):
        raise DeploymentRefused("task12_authority_staging_mismatch")
    return parsed


def _validate_published(
    request: Task12FinalizeRequest,
    expected: FinalArtifactSnapshot,
    authority_sha256: str,
) -> FinalArtifactHashes:
    canonical = _resolved_directory(
        request.external_receipts_dir, "task12_authority_canonical_path"
    )
    authority = _resolved_file(
        canonical / _AUTHORITY_NAME, "task12_authority_canonical_path"
    )
    digest = _resolved_file(
        canonical / _AUTHORITY_DIGEST_NAME, "task12_authority_canonical_path"
    )
    marker = _resolved_file(
        canonical / _AUTHORITY_MARKER_NAME, "task12_authority_canonical_path"
    )
    if marker.read_bytes() != _AUTHORITY_MARKER:
        raise DeploymentRefused("task12_authority_terminal_marker")
    _validate_staged(authority, digest, expected.hashes)
    if sha256_file(authority) != authority_sha256:
        raise DeploymentRefused("task12_authority_published_digest")
    current = _snapshot(request)
    if current != expected:
        raise DeploymentRefused("task12_final_artifact_drift")
    _validate_staged(authority, digest, current.hashes)
    return current.hashes


def _retain_failed_publication(canonical: Path) -> Path:
    while True:
        retained = canonical.parent / (
            f".{canonical.name}.retained-failure-{uuid.uuid4().hex}"
        )
        try:
            _rename_exclusive(canonical, retained)
        except DeploymentRefused as exc:
            if exc.reason == "retained_removal_collision":
                continue
            raise DeploymentRefused("task12_authority_failure_retain") from exc
        try:
            _fsync_directory(canonical.parent)
        except OSError as exc:
            raise DeploymentRefused("task12_authority_failure_retain") from exc
        return retained


def finalize_task12_release(request: Task12FinalizeRequest) -> Task12FinalizeResult:
    """Stage complete authority, revalidate finals, then publish one directory."""
    normalized = _normalized_request(request)
    before = _snapshot(normalized)
    stage = normalized.external_receipts_dir.parent / (
        f".{normalized.external_receipts_dir.name}.retained-stage-{uuid.uuid4().hex}"
    )
    try:
        stage.mkdir(mode=0o700)
    except OSError as exc:
        raise DeploymentRefused("task12_authority_stage_create") from exc
    staged_authority = stage / _AUTHORITY_NAME
    staged_digest = stage / _AUTHORITY_DIGEST_NAME
    generated = generate_task12_release_authority(
        Task12AuthorityRequest(
            normalized.final_dmg,
            normalized.final_zip,
            normalized.install_receipt,
            normalized.final_app,
            staged_authority,
        )
    )
    _write_digest(staged_digest, generated.sha256)
    _validate_staged(staged_authority, staged_digest, before.hashes)
    after = _snapshot(normalized)
    if after != before:
        raise DeploymentRefused("task12_final_artifact_drift")
    try:
        _rename_exclusive(stage, normalized.external_receipts_dir)
    except DeploymentRefused as exc:
        if exc.reason == "retained_removal_collision":
            raise DeploymentRefused("task12_authority_collision") from exc
        raise DeploymentRefused("task12_authority_publish") from exc
    authority = normalized.external_receipts_dir / _AUTHORITY_NAME
    authority_digest = normalized.external_receipts_dir / _AUTHORITY_DIGEST_NAME
    try:
        _fsync_directory(normalized.external_receipts_dir.parent)
        _write_exclusive(
            normalized.external_receipts_dir / _AUTHORITY_MARKER_NAME,
            _AUTHORITY_MARKER,
            "task12_authority_terminal_marker_write",
        )
        final_hashes = _validate_published(normalized, before, generated.sha256)
    except (DeploymentRefused, OSError) as exc:
        _retain_failed_publication(normalized.external_receipts_dir)
        raise DeploymentRefused("task12_postpublication_validation") from exc
    return Task12FinalizeResult(
        authority, authority_digest, generated.sha256, final_hashes
    )

