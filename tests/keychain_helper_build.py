"""Shared builder for the real Swift Keychain helper used by tests.

Each test module used to compile ``launcher/keychain-helper.swift`` into a
fresh ``mkdtemp`` path and sign it adhoc (or not at all). An adhoc-signed
binary is rejected by amfid ("adhoc signed or signed by an unknown
certificate chain"), and when the executing process is GUI-attributed —
the Aside CLI runtime is — syspolicyd answers with a Gatekeeper prompt.
Because the path is a fresh temp directory every run, no approval can ever
stick, so the prompt repeats for every test module and every run.

Signing with the first available codesigning identity (the same lookup
``launcher/build-macos-app.sh`` performs) gives the binary a known
certificate chain, which amfid accepts and syspolicyd does not prompt on.
Machines without any identity fall back to adhoc, preserving the old
behavior.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HELPER_SRC = Path(__file__).resolve().parents[1] / "launcher" / "keychain-helper.swift"


def _codesigning_identity() -> str:
    """First codesigning identity, or "-" (adhoc) when none exists."""
    try:
        out = subprocess.run(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "-"
    for line in out.splitlines():
        line = line.strip()
        if ")" in line and '"' in line:
            return line.split('"')[1]
    return "-"


def build_signed_helper(work_dir: str) -> str | None:
    """Compile and sign the helper into ``work_dir``; None when unavailable."""
    if sys.platform != "darwin" or shutil.which("swiftc") is None:
        return None
    if not HELPER_SRC.is_file():
        return None
    binary = str(Path(work_dir) / "keychain-helper")
    try:
        sdk = subprocess.check_output(
            ["xcrun", "--show-sdk-path"], text=True, timeout=30
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    compiled = subprocess.run(
        [
            "swiftc", "-O",
            "-sdk", sdk,
            "-framework", "Security",
            "-framework", "Foundation",
            "-o", binary,
            str(HELPER_SRC),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if compiled.returncode != 0:
        return None
    signed = subprocess.run(
        [
            "codesign", "--force",
            "--sign", _codesigning_identity(),
            "--identifier", "town.neobio.ontologylab.keychain-helper",
            binary,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if signed.returncode != 0:
        return None
    return binary
