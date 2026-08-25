from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path


def _build_app(tmp_path: Path) -> tuple[Path, Path]:
    repo = Path(__file__).resolve().parents[1]
    output_dir = tmp_path / "Applications"

    subprocess.run(
        [
            "bash",
            str(repo / "launcher" / "build-macos-app.sh"),
            "--out",
            str(output_dir),
            "--repo",
            str(repo),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    return repo, output_dir / "ontologylab.app"


def test_unhealthy_launchd_service_is_force_restarted(tmp_path: Path) -> None:
    _, app = _build_app(tmp_path)
    launcher = (app / "Contents" / "MacOS" / "launch").read_text()

    assert (
        '/bin/launchctl kickstart -k "gui/$(id -u)/at.ontologylab.server"'
        in launcher
    )
    assert '/bin/launchctl kickstart -k "gui/$(id -u)/$AGENT"' in launcher


def test_app_opens_default_browser_without_native_webview(tmp_path: Path) -> None:
    _, app = _build_app(tmp_path)
    contents = app / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    executable = contents / "MacOS" / info["CFBundleExecutable"]
    launcher = executable.read_text()

    assert info["CFBundleExecutable"] == "launch"
    assert executable.is_file()
    assert os.access(executable, os.X_OK)
    assert 'ASIDE_BUNDLE_ID="at.studio.AsideBrowser"' in launcher
    assert '/usr/bin/open -b "$ASIDE_BUNDLE_ID" "$URL"' in launcher
    assert "open -a" not in launcher
    assert 'export PATH="$HOME/.npm-global/bin:' in launcher
    assert not (contents / "MacOS" / "ontologylab").exists()
    assert not (contents / "Resources" / "start-server").exists()


def test_build_script_packages_signed_helper_and_probes_healthz() -> None:
    repo = Path(__file__).resolve().parents[1]
    script = repo / "launcher" / "build-macos-app.sh"
    text = script.read_text(encoding="utf-8")

    assert "keychain-helper.swift" in text
    assert "codesign" in text
    assert "ONTOLOGYLAB_KEYCHAIN_HELPER" in text
    assert "/healthz" in text
    assert "/api/engines" not in text

    move_data = (repo / "launcher" / "move-data-out-of-icloud.sh").read_text(
        encoding="utf-8"
    )
    assert "/healthz" in move_data
    assert "/api/engines" not in move_data


def test_app_bundles_signed_keychain_helper_and_probes_healthz(tmp_path: Path) -> None:
    _, app = _build_app(tmp_path)
    contents = app / "Contents"
    launcher = (contents / "MacOS" / "launch").read_text(encoding="utf-8")
    helper = contents / "Resources" / "keychain-helper"

    assert "/healthz" in launcher
    assert "/api/engines" not in launcher
    assert "ONTOLOGYLAB_KEYCHAIN_HELPER" in launcher
    assert helper.is_file()
    assert os.access(helper, os.X_OK)
    verify = subprocess.run(
        ["codesign", "--verify", str(helper)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr
    assert "CODESIGN_IDENTITY" not in launcher
