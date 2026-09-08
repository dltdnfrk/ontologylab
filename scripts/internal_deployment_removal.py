"""Exclusive same-volume rename primitive for retained uninstall."""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
from typing import Final

from scripts.internal_deployment_types import DeploymentRefused

_RENAME_EXCL: Final = 0x00000004
_AT_FDCWD: Final = -2
_LIBC: Final = ctypes.CDLL(None, use_errno=True)
_RENAMEATX_NP = getattr(_LIBC, "renameatx_np", None)
if _RENAMEATX_NP is not None:
    _RENAMEATX_NP.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    _RENAMEATX_NP.restype = ctypes.c_int


def _rename_exclusive(source: Path, destination: Path) -> None:
    if _RENAMEATX_NP is None:
        raise DeploymentRefused("retained_removal_unsupported")
    result = _RENAMEATX_NP(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_EXCL,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EXDEV:
        raise DeploymentRefused("retained_removal_cross_device")
    if error == errno.EEXIST:
        raise DeploymentRefused("retained_removal_collision")
    raise DeploymentRefused(f"retained_removal_errno_{error}")
