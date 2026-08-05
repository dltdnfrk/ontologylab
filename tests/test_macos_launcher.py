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
