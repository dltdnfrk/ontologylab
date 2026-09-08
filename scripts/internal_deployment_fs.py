"""Filesystem integrity and atomic replacement primitives for deployment."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import uuid
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from scripts.internal_deployment_quarantine import (
    clear_quarantine,
    verify_strict_signature,
)
from scripts.internal_deployment_retention import (
    dispose_stage,
    require_fresh_retained_destination,
)
from scripts.internal_deployment_types import ActivationJournal, DeploymentRefused

_MOUNT: Final = Path("/sbin/mount")
_AT_FDCWD: Final = -2
_RENAME_SWAP: Final = 0x00000002
_JOURNAL_NAME: Final = ".OntologyLab.app.activation.json"
_LIBC: Final = ctypes.CDLL(None, use_errno=True)
_RENAMEATX_NP = _LIBC.renameatx_np
_RENAMEATX_NP.argtypes = (
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_uint,
)
_RENAMEATX_NP.restype = ctypes.c_int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise DeploymentRefused("file_unreadable") from exc
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    """Hash names, types, executable modes, and bytes of one symlink-free tree."""
    if not root.is_dir() or root.is_symlink():
        raise DeploymentRefused("artifact_not_directory")
    digest = hashlib.sha256()
    try:
        members = sorted(
            root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()
        )
        for member in members:
            relative = member.relative_to(root).as_posix().encode()
            mode = member.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise DeploymentRefused("artifact_symlink")
            kind = b"d" if stat.S_ISDIR(mode) else b"f" if stat.S_ISREG(mode) else b"x"
            if kind == b"x":
                raise DeploymentRefused("artifact_special_file")
            digest.update(
                kind
                + b"\0"
                + relative
                + b"\0"
                + oct(stat.S_IMODE(mode)).encode()
                + b"\0"
            )
            if kind == b"f":
                with member.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
    except OSError as exc:
        raise DeploymentRefused("artifact_unreadable") from exc
    return digest.hexdigest()


def _existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        if current == current.parent:
            raise DeploymentRefused("destination_parent_missing")
        current = current.parent
    return current


def _filesystem_type(path: Path) -> str:
    try:
        result = subprocess.run(
            [str(_MOUNT)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeploymentRefused("atomic_exchange_preflight") from exc
    if result.returncode != 0:
        raise DeploymentRefused("atomic_exchange_preflight")
    resolved = path.resolve()
    matches: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        _device, separator, mount_description = line.partition(" on ")
        mount_name, options_separator, options = mount_description.rpartition(" (")
        if not separator or not options_separator or not options.endswith(")"):
            continue
        mount_point = Path(mount_name.replace("\\040", " "))
        if resolved == mount_point or mount_point in resolved.parents:
            matches.append((len(mount_point.parts), options[:-1].split(",", 1)[0]))
    if not matches:
        raise DeploymentRefused("atomic_exchange_preflight")
    return max(matches)[1]


def require_atomic_exchange(destination: Path) -> None:
    """Refuse unsupported filesystems before creating an install stage."""
    if platform.system() != "Darwin" or not hasattr(_LIBC, "renameatx_np"):
        raise DeploymentRefused("atomic_exchange_unsupported")
    ancestor = _existing_ancestor(destination.parent)
    if _filesystem_type(ancestor) != "apfs":
        raise DeploymentRefused("atomic_exchange_unsupported")
    if destination.exists() and destination.stat().st_dev != ancestor.stat().st_dev:
        raise DeploymentRefused("atomic_exchange_cross_device")


def atomic_exchange(left: Path, right: Path) -> None:
    """Swap two same-volume paths in one macOS renameatx_np transaction."""
    result = _RENAMEATX_NP(
        _AT_FDCWD,
        os.fsencode(left),
        _AT_FDCWD,
        os.fsencode(right),
        _RENAME_SWAP,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EXDEV:
        raise DeploymentRefused("atomic_exchange_cross_device")
    if error in {errno.EINVAL, errno.ENOTSUP, errno.ENOSYS}:
        raise DeploymentRefused("atomic_exchange_unsupported")
    raise DeploymentRefused(f"atomic_exchange_errno_{error}")


def _write_journal(path: Path, stage: Path, expected_hash: str) -> None:
    payload = {
        "schema": "ontologylab.atomic-activation.v1",
        "stage_name": stage.name,
        "expected_sha256": expected_hash,
    }
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.unlink(missing_ok=True)
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DeploymentRefused("activation_journal_write") from exc


def _recover_activation(destination: Path, journal_path: Path) -> None:
    if not journal_path.exists():
        return
    try:
        journal = ActivationJournal.model_validate_json(
            journal_path.read_bytes(), strict=True
        )
    except (OSError, ValidationError) as exc:
        raise DeploymentRefused("activation_journal_malformed") from exc
    if not journal.stage_name.startswith(f".{destination.name}.install-"):
        raise DeploymentRefused("activation_journal_destination")
    stage = destination.parent / journal.stage_name
    destination_is_candidate = (
        destination.is_dir() and tree_sha256(destination) == journal.expected_sha256
    )
    stage_is_candidate = (
        stage.is_dir() and tree_sha256(stage) == journal.expected_sha256
    )
    if destination_is_candidate:
        if stage.exists():
            shutil.rmtree(stage)
    elif stage_is_candidate and destination.is_dir():
        shutil.rmtree(stage)
    else:
        raise DeploymentRefused("activation_recovery_ambiguous")
    journal_path.unlink()


def _recover_legacy_previous(destination: Path) -> None:
    matched = tuple(destination.parent.glob(f".{destination.name}.previous-*"))
    previous = tuple(
        item for item in matched if item.is_dir() and not item.is_symlink()
    )
    if len(matched) != len(previous):
        raise DeploymentRefused("legacy_activation_recovery_ambiguous")
    if not previous:
        return
    if destination.is_dir() and not destination.is_symlink():
        for item in previous:
            shutil.rmtree(item)
        return
    if len(previous) == 1 and not destination.exists():
        os.replace(previous[0], destination)
        return
    raise DeploymentRefused("legacy_activation_recovery_ambiguous")


def atomic_copy_app(source: Path, destination: Path, expected_hash: str) -> bool:
    """Copy, verify, and activate through one recoverable atomic exchange."""
    parent = destination.parent
    journal = parent / _JOURNAL_NAME
    require_atomic_exchange(destination)
    require_fresh_retained_destination(destination, journal)
    _recover_legacy_previous(destination)
    _recover_activation(destination, journal)
    stage = parent / f".{destination.name}.install-{uuid.uuid4().hex}"
    existed = destination.exists()
    try:
        parent.mkdir(parents=True, exist_ok=True)
        for stale in parent.glob(f".{destination.name}.install-*"):
            if stale.is_symlink() or not stale.is_dir():
                raise DeploymentRefused("activation_stage_unsafe")
            shutil.rmtree(stale)
        shutil.copytree(source, stage, copy_function=shutil.copy2)
        if tree_sha256(stage) != expected_hash:
            raise DeploymentRefused("partial_copy")
        clear_quarantine(stage)
        if tree_sha256(stage) != expected_hash:
            raise DeploymentRefused("post_quarantine_tree_mismatch")
        verify_strict_signature(stage)
        if existed:
            _write_journal(journal, stage, expected_hash)
            atomic_exchange(destination, stage)
            shutil.rmtree(stage)
            journal.unlink()
        else:
            os.replace(stage, destination)
    except KeyboardInterrupt:
        if stage.exists() and not journal.exists():
            dispose_stage(stage)
        raise
    except DeploymentRefused:
        if stage.exists() and not journal.exists():
            dispose_stage(stage)
        raise
    except (OSError, shutil.Error, subprocess.TimeoutExpired) as exc:
        if stage.exists() and not journal.exists():
            dispose_stage(stage)
        raise DeploymentRefused("atomic_copy_failed") from exc
    return existed
