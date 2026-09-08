"""Explicit, idempotent retirement of legacy macOS launcher ownership.

The command addresses only the historical launchd label, one explicitly
identified source PID, and the old launcher's runtime files. It never scans
process command lines and never touches application data or Keychain items.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

LEGACY_LAUNCHD_LABEL: Final = "at.ontologylab.server"
_LAUNCHCTL: Final = "/bin/launchctl"


@dataclass(frozen=True, slots=True)
class RetirementPaths:
    """Exact legacy files eligible for removal."""

    launch_agent: Path
    source_runtime_files: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class RetirementRequest:
    """One explicit retirement request."""

    paths: RetirementPaths
    uid: int
    source_pid: int | None = None


@dataclass(frozen=True, slots=True)
class RetirementReceipt:
    """Secret-free machine-readable retirement outcome."""

    launchd: Literal["retired", "absent"]
    source_process: Literal["signaled", "absent"]
    removed_files: tuple[str, ...]

    def as_json(self) -> dict[str, str | list[str]]:
        return {
            "launchd": self.launchd,
            "source_process": self.source_process,
            "removed_files": list(self.removed_files),
        }


@dataclass(frozen=True, slots=True)
class LegacyRetirementError(Exception):
    """Typed refusal that never includes command output or credentials."""

    kind: str

    def __str__(self) -> str:
        return f"legacy retirement refused: {self.kind}"


class RetirementSystem(Protocol):
    """Narrow operating-system seam for deterministic tests."""

    def launchctl(self, arguments: tuple[str, ...]) -> int: ...

    def process_exists(self, pid: int) -> bool: ...

    def terminate(self, pid: int) -> None: ...


class LocalRetirementSystem:
    """Production adapter using only exact launchd service and PID operations."""

    def launchctl(self, arguments: tuple[str, ...]) -> int:
        completed = subprocess.run(
            [_LAUNCHCTL, *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.returncode

    def process_exists(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def terminate(self, pid: int) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return


def retire_legacy_ownership(
    request: RetirementRequest,
    system: RetirementSystem,
) -> RetirementReceipt:
    """Stop exact legacy owners, then remove only allowlisted runtime files."""
    if request.uid < 0:
        raise LegacyRetirementError(kind="invalid_uid")
    if request.source_pid is not None and request.source_pid in (0, 1, os.getpid()):
        raise LegacyRetirementError(kind="invalid_source_pid")

    target = f"gui/{request.uid}/{LEGACY_LAUNCHD_LABEL}"
    loaded = system.launchctl(("print", target)) == 0
    if loaded and system.launchctl(("bootout", target)) != 0:
        raise LegacyRetirementError(kind="launchd_refused")

    source_state: Literal["signaled", "absent"] = "absent"
    if request.source_pid is not None and system.process_exists(request.source_pid):
        try:
            system.terminate(request.source_pid)
        except OSError as error:
            raise LegacyRetirementError(kind="source_pid_refused") from error
        source_state = "signaled"

    removable = (request.paths.launch_agent, *request.paths.source_runtime_files)
    removed: list[str] = []
    for path in removable:
        if path.exists():
            try:
                path.unlink()
            except OSError as error:
                raise LegacyRetirementError(kind="file_cleanup_refused") from error
            removed.append(str(path))

    return RetirementReceipt(
        launchd="retired" if loaded else "absent",
        source_process=source_state,
        removed_files=tuple(removed),
    )


def _default_paths(repo: Path) -> RetirementPaths:
    home = Path.home()
    return RetirementPaths(
        launch_agent=(
            home / "Library" / "LaunchAgents" / f"{LEGACY_LAUNCHD_LABEL}.plist"
        ),
        source_runtime_files=tuple(
            repo / name for name in (".launcher.pid", ".launcher.port", ".launcher.log")
        ),
    )


def main(arguments: list[str] | None = None) -> int:
    """Run the explicit local retirement command and emit one JSON receipt."""
    parser = argparse.ArgumentParser(
        description="Retire exact legacy OntologyLab launcher ownership."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--source-pid", type=int)
    namespace = parser.parse_args(arguments)
    request = RetirementRequest(
        paths=_default_paths(namespace.repo.resolve()),
        uid=os.getuid(),
        source_pid=namespace.source_pid,
    )
    try:
        receipt = retire_legacy_ownership(request, LocalRetirementSystem())
    except LegacyRetirementError as error:
        sys.stdout.write(json.dumps({"ok": False, "error": error.kind}) + "\n")
        return 1
    sys.stdout.write(json.dumps({"ok": True, **receipt.as_json()}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
