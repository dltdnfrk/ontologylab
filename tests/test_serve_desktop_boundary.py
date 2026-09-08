from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from ontologylab.serve_desktop import DesktopEnvironment, main
from ontologylab.storage_types import StorageHandshakeRefused


@dataclass(frozen=True, slots=True)
class InvalidFDCase:
    name: str
    value: str


def _set_desktop_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = home / "Library/Application Support/ontologylab"
    values = {
        "HOME": str(home),
        "ONTOLOGYLAB_LISTENER_FD": "0",
        "ONTOLOGYLAB_READY_FD": "1",
        "ONTOLOGYLAB_NONCE": "0123456789abcdef0123456789abcdef",
        "ONTOLOGYLAB_APP_VERSION": "0.1.0",
        "ONTOLOGYLAB_STORAGE_VERSION": "1",
        "ONTOLOGYLAB_SUPERVISOR_PID": str(os.getppid()),
        "ONTOLOGYLAB_QUIESCENCE_RECEIPT": str(tmp_path / "quiescence.json"),
        "ONTOLOGYLAB_RESOURCES_DIR": str(tmp_path / "OntologyLab.app/Contents/Resources"),
        "ONTOLOGYLAB_DATA_DIR": str(state / "data"),
        "ONTOLOGYLAB_PACKS_DIR": str(state / "packs"),
        "ONTOLOGYLAB_LOG_DIR": str(home / "Library/Logs/ontologylab"),
        "ONTOLOGYLAB_RUNTIME_DIR": str(home / "Library/Caches/ontologylab/runtime"),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_desktop_startup_refuses_stale_supervisor_storage_version_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given canonical paths but a stale supervisor storage handshake.
    _set_desktop_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("ONTOLOGYLAB_STORAGE_VERSION", "999")

    # When desktop startup begins, then it refuses before touching inherited fds.
    with pytest.raises(StorageHandshakeRefused) as raised:
        main()
    assert (raised.value.expected, raised.value.received) == (1, "999")


def test_desktop_environment_accepts_supervisor_fd_zero_and_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given the exact standard descriptors owned by the Swift supervisor.
    _set_desktop_environment(monkeypatch, tmp_path)
    # When the desktop process boundary is parsed.
    environment = DesktopEnvironment.from_process()
    # Then listener fd 0 and readiness fd 1 remain valid typed descriptors.
    assert (environment.listener_fd, environment.ready_fd) == (0, 1)


@pytest.mark.parametrize(
    "case",
    [
        InvalidFDCase("ONTOLOGYLAB_LISTENER_FD", "-1"),
        InvalidFDCase("ONTOLOGYLAB_READY_FD", "-1"),
        InvalidFDCase("ONTOLOGYLAB_LISTENER_FD", "malformed"),
        InvalidFDCase("ONTOLOGYLAB_READY_FD", "malformed"),
    ],
)
def test_desktop_environment_refuses_invalid_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: InvalidFDCase,
) -> None:
    # Given one negative or malformed inherited descriptor.
    _set_desktop_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(case.name, case.value)
    # When the desktop process boundary is parsed, then it refuses the field.
    with pytest.raises(ValidationError):
        DesktopEnvironment.from_process()
