"""Selective, mode-preserving macOS quarantine clearance boundary."""

from __future__ import annotations

import errno
import os
import stat
import subprocess
from pathlib import Path
from typing import Final

from scripts.internal_deployment_types import DeploymentRefused

_XATTR: Final = Path("/usr/bin/xattr")
_CODESIGN: Final = Path("/usr/bin/codesign")
_QUARANTINE: Final = "com.apple.quarantine"


def _members(root: Path) -> tuple[Path, ...]:
    if not root.is_dir() or root.is_symlink():
        raise DeploymentRefused("artifact_not_directory")
    members = (
        root,
        *sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()),
    )
    for member in members:
        mode = member.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise DeploymentRefused("artifact_symlink")
        if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
            raise DeploymentRefused("artifact_special_file")
    return members


def _attributes(path: Path) -> frozenset[str]:
    try:
        result = subprocess.run(
            [str(_XATTR), str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeploymentRefused("quarantine_inspection_failed") from exc
    if result.returncode != 0:
        raise DeploymentRefused("quarantine_inspection_failed")
    return frozenset(result.stdout.splitlines())


def _remove_quarantine(path: Path) -> None:
    try:
        result = subprocess.run(
            [str(_XATTR), "-d", _QUARANTINE, str(path)],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError(errno.ETIMEDOUT, "quarantine removal timed out") from exc
    if result.returncode != 0:
        raise OSError(errno.EPERM, "quarantine removal refused")


def _clear_member(path: Path) -> None:
    if _QUARANTINE not in _attributes(path):
        return
    original_mode = stat.S_IMODE(path.lstat().st_mode)
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if path.is_dir():
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DeploymentRefused("quarantine_path_open_failed") from exc
    changed_mode = original_mode & stat.S_IWUSR == 0
    try:
        if changed_mode:
            os.fchmod(descriptor, original_mode | stat.S_IWUSR)
        try:
            _remove_quarantine(path)
        except OSError as exc:
            raise DeploymentRefused("quarantine_remove_failed") from exc
    finally:
        try:
            if changed_mode:
                os.fchmod(descriptor, original_mode)
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != original_mode:
                raise DeploymentRefused("quarantine_mode_restore_failed")
        except OSError as exc:
            raise DeploymentRefused("quarantine_mode_restore_failed") from exc
        finally:
            os.close(descriptor)
    if _QUARANTINE in _attributes(path):
        raise DeploymentRefused("quarantine_remove_unverified")


def clear_quarantine(root: Path) -> None:
    """Remove quarantine only where present, without following symlinks."""
    if not _XATTR.is_file():
        raise DeploymentRefused("quarantine_tool_missing")
    for member in _members(root):
        _clear_member(member)


def verify_strict_signature(root: Path) -> None:
    """Require the complete staged bundle's existing strict code signatures."""
    if not _CODESIGN.is_file():
        raise DeploymentRefused("signature_tool_missing")
    try:
        result = subprocess.run(
            [
                str(_CODESIGN),
                "--verify",
                "--deep",
                "--strict",
                "--verbose=4",
                str(root),
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeploymentRefused("signature_verification_failed") from exc
    if result.returncode != 0:
        raise DeploymentRefused("signature_verification_failed")
