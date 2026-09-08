from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

_MACH_O_ARM64 = b"\xcf\xfa\xed\xfe"


def _build_app(tmp_path: Path) -> Path:
    """Build the bundle around a stub backend.

    The shipped backend is a PyInstaller artifact and nothing asserted here
    depends on it, so a stub keeps the bundle contract testable without the
    packaging step.
    """
    repo = Path(__file__).resolve().parents[1]
    backend = tmp_path / "stub" / "ontologylab-serve-desktop"
    backend.parent.mkdir(parents=True)
    backend.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    backend.chmod(0o755)
    output_dir = tmp_path / "Applications"

    subprocess.run(
        [
            "bash",
            str(repo / "launcher" / "build-macos-app.sh"),
            "--out",
            str(output_dir),
            "--backend",
            str(backend),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    return output_dir / "ontologylab.app"


def test_bundle_runs_the_supervisor_and_not_a_launchd_healing_script(
    tmp_path: Path,
) -> None:
    """Instance health is the supervisor's job, so no shell launcher ships.

    The retired bundle put a generated `MacOS/launch` script in front of a
    launchd agent and force-restarted it with `launchctl kickstart -k` whenever
    the service looked unhealthy. The supervisor rewrite owns the exact backend
    child in-process and waits for a structured readiness receipt instead, so
    the requirement — a sick instance must not strand the user — is proven on
    the shipped supervisor rather than on launchd self-healing.
    """
    app = _build_app(tmp_path)
    contents = app / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    executable = contents / "MacOS" / info["CFBundleExecutable"]
    supervisor = executable.read_bytes()

    assert info["CFBundleExecutable"] == "ontologylab-supervisor"
    assert executable.is_file()
    assert os.access(executable, os.X_OK)
    assert supervisor[:4] == _MACH_O_ARM64
    assert b"ontologylab-ready-v1" in supervisor
    assert not (contents / "MacOS" / "launch").exists()
    assert not (contents / "MacOS" / "ontologylab").exists()
    assert not (contents / "Resources" / "start-server").exists()


def test_bundle_opens_the_default_browser_through_aside_without_a_webview(
    tmp_path: Path,
) -> None:
    app = _build_app(tmp_path)
    executable = app / "Contents" / "MacOS" / "ontologylab-supervisor"

    assert b"at.studio.AsideBrowser" in executable.read_bytes()
    linked = subprocess.run(
        ["otool", "-L", str(executable)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "WebKit" not in linked


def test_build_script_compiles_and_signs_the_keychain_helper() -> None:
    repo = Path(__file__).resolve().parents[1]
    text = (repo / "launcher" / "build-macos-app.sh").read_text(encoding="utf-8")

    assert "keychain-helper.swift" in text
    assert "codesign" in text

    move_data = (repo / "launcher" / "move-data-out-of-icloud.sh").read_text(
        encoding="utf-8"
    )
    assert "/healthz" in move_data
    assert "/api/engines" not in move_data


def test_bundle_ships_a_signed_helper_the_supervisor_can_reach(
    tmp_path: Path,
) -> None:
    """The helper ships signed, and the supervisor is what names it to the backend.

    `ONTOLOGYLAB_KEYCHAIN_HELPER` moved out of the generated launcher into the
    supervisor, which exports the helper path and its designated requirement, so
    the environment contract is asserted where it now lives.
    """
    app = _build_app(tmp_path)
    contents = app / "Contents"
    helper = contents / "Resources" / "keychain-helper"
    requirement = contents / "Resources" / "keychain-helper.requirement"
    supervisor = (contents / "MacOS" / "ontologylab-supervisor").read_bytes()

    assert helper.is_file()
    assert os.access(helper, os.X_OK)
    verify = subprocess.run(
        ["codesign", "--verify", str(helper)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr
    assert "keychain-helper" in requirement.read_text(encoding="utf-8")
    assert b"ONTOLOGYLAB_KEYCHAIN_HELPER" in supervisor
    assert b"CODESIGN_IDENTITY" not in supervisor
