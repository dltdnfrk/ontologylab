from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.internal_deployment import (
    DeploymentRefused,
    InstallRequest,
    PlatformInfo,
    install_app,
    tree_sha256,
)


def _app(root: Path, version: str = "1") -> Path:
    app = root / "OntologyLab.app"
    resources = app / "Contents/Resources"
    resources.mkdir(parents=True)
    (app / "Contents/MacOS").mkdir()
    executable = app / "Contents/MacOS/OntologyLab"
    executable.write_text(version, encoding="utf-8")
    executable.chmod(0o755)
    (resources / "storage-compatibility.json").write_text("{}", encoding="utf-8")
    (app / "Contents/Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<plist version="1.0"><dict>'
        "<key>CFBundleIdentifier</key><string>test.ontologylab</string>"
        "<key>CFBundleExecutable</key><string>OntologyLab</string>"
        "</dict></plist>",
        encoding="utf-8",
    )
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(app)],
        check=True,
        capture_output=True,
    )
    return app


def _receipt(app: Path, path: Path) -> tuple[Path, str]:
    path.write_text(
        json.dumps(
            {
                "schema": "ontologylab.internal-artifact-receipt.v1",
                "artifact_name": "OntologyLab.app",
                "app_tree_sha256": tree_sha256(app),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _request(
    tmp_path: Path, app: Path, receipt: Path, receipt_hash: str
) -> InstallRequest:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return InstallRequest(
        app=app,
        receipt=receipt,
        receipt_sha256=receipt_hash,
        destination=tmp_path / "Applications/OntologyLab.app",
        home=home,
        acknowledge_unnotarized=True,
    )


def test_install_replaces_exact_app_after_preflight_when_receipt_matches(
    tmp_path: Path,
) -> None:
    # Given a valid receipt, bootstrap storage, and an existing older app.
    app = _app(tmp_path / "candidate", "new")
    receipt, receipt_hash = _receipt(app, tmp_path / "receipt.json")
    request = _request(tmp_path, app, receipt, receipt_hash)
    old = _app(request.destination.parent, "old")
    before_data = request.home / "Library/Application Support/ontologylab/data"

    # When the internal installer performs its controlled replacement.
    result = install_app(request, PlatformInfo("arm64", 15))

    # Then the exact candidate tree is installed and preflight did not create data.
    assert result.operation == "updated"
    assert tree_sha256(request.destination) == tree_sha256(app)
    assert old == request.destination
    assert not before_data.exists()


@pytest.mark.parametrize(
    ("acknowledged", "receipt_hash", "platform_info", "reason"),
    [
        (False, "valid", PlatformInfo("arm64", 15), "acknowledgement_required"),
        (True, "0" * 64, PlatformInfo("arm64", 15), "receipt_sha256_mismatch"),
        (True, "valid", PlatformInfo("x86_64", 15), "architecture"),
        (True, "valid", PlatformInfo("arm64", 14), "macos_version"),
    ],
)
def test_install_refuses_invalid_boundary_before_mutation(
    tmp_path: Path,
    acknowledged: bool,
    receipt_hash: str,
    platform_info: PlatformInfo,
    reason: str,
) -> None:
    # Given one invalid install boundary and a sentinel destination.
    app = _app(tmp_path / "candidate")
    receipt, valid_hash = _receipt(app, tmp_path / "receipt.json")
    request = _request(
        tmp_path, app, receipt, valid_hash if receipt_hash == "valid" else receipt_hash
    )
    request = InstallRequest(
        app=request.app,
        receipt=request.receipt,
        receipt_sha256=request.receipt_sha256,
        destination=request.destination,
        home=request.home,
        acknowledge_unnotarized=acknowledged,
    )
    request.destination.parent.mkdir(parents=True)
    sentinel = request.destination.parent / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")

    # When installation is attempted.
    with pytest.raises(DeploymentRefused, match=reason):
        install_app(request, platform_info)

    # Then no destination or canonical data is mutated.
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert not request.destination.exists()
    assert not (request.home / "Library/Application Support/ontologylab").exists()


def test_install_refuses_malformed_receipt_and_stale_artifact(tmp_path: Path) -> None:
    # Given a receipt that is malformed, then one whose candidate changed afterward.
    app = _app(tmp_path / "candidate")
    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    malformed_hash = hashlib.sha256(malformed.read_bytes()).hexdigest()
    malformed_request = _request(tmp_path, app, malformed, malformed_hash)

    # When each candidate is checked.
    with pytest.raises(DeploymentRefused, match="receipt_malformed"):
        install_app(malformed_request, PlatformInfo("arm64", 15))
    receipt, receipt_hash = _receipt(app, tmp_path / "receipt.json")
    (app / "Contents/MacOS/OntologyLab").write_text("stale", encoding="utf-8")
    with pytest.raises(DeploymentRefused, match="artifact_sha256_mismatch"):
        install_app(
            _request(tmp_path, app, receipt, receipt_hash), PlatformInfo("arm64", 15)
        )

    # Then neither refusal reports success or creates the destination.
    assert not malformed_request.destination.exists()


def test_install_refuses_active_backend_lock(tmp_path: Path) -> None:
    # Given Task 7's canonical supervisor lock held by another process.
    app = _app(tmp_path / "candidate")
    receipt, receipt_hash = _receipt(app, tmp_path / "receipt.json")
    request = _request(tmp_path, app, receipt, receipt_hash)
    runtime = request.home / "Library/Caches/ontologylab/runtime"
    runtime.mkdir(parents=True)
    lock = runtime / "supervisor.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl,sys; f=open(sys.argv[1],'w'); fcntl.lockf(f,fcntl.LOCK_EX); print('READY',flush=True); sys.stdin.read()",
            str(lock),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "READY"

    # When installation checks quiescence.
    try:
        with pytest.raises(DeploymentRefused, match="active_backend"):
            install_app(request, PlatformInfo("arm64", 15))
    finally:
        assert holder.stdin is not None
        holder.stdin.close()
        holder.wait(timeout=5)

    # Then the candidate was not copied.
    assert not request.destination.exists()
