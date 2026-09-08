from __future__ import annotations

import json
import os
import plistlib
import select
import signal
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "macos_supervisor"


@dataclass(frozen=True, slots=True)
class AppFixture:
    executable: Path
    environment: dict[str, str]
    state_root: Path


def build_supervisor(tmp_path: Path) -> AppFixture:
    sources = sorted(
        path
        for path in (ROOT / "launcher" / "supervisor").glob("*.swift")
        if path.name != "Package.swift"
    )
    if not sources:
        pytest.fail("missing Swift supervisor sources")
    contents = tmp_path / "Randomized.app" / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir()
    executable = macos / "ontologylab-supervisor"
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-framework",
            "Foundation",
            "-framework",
            "Security",
            "-o",
            str(executable),
            *(str(source) for source in sources),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    (resources / "ontologylab-serve-desktop").symlink_to(FIXTURES / "fake_backend.py")
    (resources / "storage-compatibility.json").write_bytes(
        (ROOT / "ontologylab" / "storage-compatibility.json").read_bytes()
    )
    plist = {
        "CFBundleExecutable": executable.name,
        "CFBundleIdentifier": "test.ontologylab.supervisor",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(plist))
    state_root = tmp_path / "Library/Caches/ontologylab/runtime"
    environment = os.environ | {
        "HOME": str(tmp_path),
        "ONTOLOGYLAB_OPEN_EXECUTABLE": str(FIXTURES / "fake_open.py"),
        "ONTOLOGYLAB_APP_SUPPORT_ROOT": str(
            tmp_path / "Library/Application Support/ontologylab"
        ),
        "ONTOLOGYLAB_LOG_ROOT": str(tmp_path / "Library/Logs/ontologylab"),
        "ONTOLOGYLAB_STATE_ROOT": str(state_root),
        "ONTOLOGYLAB_READY_TIMEOUT_MS": "250",
        "ONTOLOGYLAB_SHUTDOWN_TIMEOUT_MS": "250",
        "ONTOLOGYLAB_STORAGE_VERSION": "1",
    }
    return AppFixture(executable, environment, state_root)


def launch(app: AppFixture, mode: str, **environment: str) -> subprocess.Popen[str]:
    env = app.environment | {"FAKE_BACKEND_MODE": mode} | environment
    return subprocess.Popen(
        [str(app.executable)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run(
    app: AppFixture, mode: str, **environment: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(app.executable)],
        env=app.environment | {"FAKE_BACKEND_MODE": mode} | environment,
        capture_output=True,
        text=True,
        timeout=4,
        check=False,
    )


def read_event(process: subprocess.Popen[str], prefix: str, timeout: float = 3) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(f"event {prefix!r} not received")
        readable, _, _ = select.select([process.stdout], [], [], remaining)
        if not readable:
            pytest.fail(f"event {prefix!r} not received")
        line = process.stdout.readline().rstrip("\n")
        if line.startswith(prefix):
            return line


def open_arguments(output: str) -> list[list[str]]:
    return [
        json.loads(line.removeprefix("OPEN:"))
        for line in output.splitlines()
        if line.startswith("OPEN:")
    ]


@contextmanager
def managed_process(process: subprocess.Popen[str]) -> Iterator[subprocess.Popen[str]]:
    try:
        yield process
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=4)


def stop(process: subprocess.Popen[str]) -> tuple[str, str]:
    process.send_signal(signal.SIGTERM)
    return process.communicate(timeout=4)
