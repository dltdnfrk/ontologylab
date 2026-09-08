"""Bounded subprocess execution values for Task 11 candidate builds."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BuildRequest:
    """One bounded local candidate build request."""

    root: Path
    output: Path
    timeout_seconds: int
    compare: Path | None


@dataclass(frozen=True, slots=True)
class PayloadRun:
    """One exact staged payload compiler invocation."""

    command: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    timeout_seconds: int


def sign_payload(app: Path) -> None:
    """Ad-hoc sign the fully assembled app, then verify every nested code object."""
    for command in (
        (
            "/usr/bin/codesign",
            "--force",
            "--sign",
            "-",
            "--timestamp=none",
            str(app),
        ),
        ("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)),
    ):
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)


def run_payload(request: PayloadRun) -> subprocess.CompletedProcess[str]:
    """Run the payload compiler with captured output and one hard timeout."""
    return subprocess.run(
        request.command,
        cwd=request.cwd,
        env=request.environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=request.timeout_seconds,
    )
