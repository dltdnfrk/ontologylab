from __future__ import annotations

import hashlib
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from release.candidate_package import (
    PackageRequest,
    package_candidate,
    stage_writable_copy,
    write_artifact_receipt,
)
from scripts.internal_deployment_fs import tree_sha256

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="codesign and hdiutil are macOS tools"
)

_INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Probe</string>
<key>CFBundleIdentifier</key><string>town.neobio.ontologylab.probe</string>
<key>CFBundleVersion</key><string>0.1.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>probe-tool</string>
</dict></plist>
"""


def _machine_code_bundle(root: Path) -> Path:
    app = root / "Probe.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    runtime = app / "Contents" / "Resources" / "runtime"
    runtime.mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(_INFO_PLIST, encoding="utf-8")
    machine_code = Path("/bin/echo").read_bytes()
    for executable in (app / "Contents" / "MacOS" / "probe-tool", runtime / "probe-native"):
        executable.write_bytes(machine_code)
        executable.chmod(0o755)
    (runtime / "data.json").write_text('{"kind": "payload"}\n', encoding="utf-8")
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(app)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return app


def _recording_manifest_writer(path: Path, record: Path) -> Path:
    path.write_text(
        "import hashlib, json, pathlib, sys\n"
        "runtime = pathlib.Path(sys.argv[1])\n"
        "manifest = runtime / 'runtime-manifest.json'\n"
        "manifest.write_text(json.dumps({'version': sys.argv[2]}) + '\\n')\n"
        "seen = {\n"
        "    p.relative_to(runtime).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()\n"
        "    for p in sorted(runtime.rglob('*'))\n"
        "    if p.is_file() and p.name != 'runtime-manifest.json'\n"
        "}\n"
        f"pathlib.Path({str(record)!r}).write_text(json.dumps(seen, sort_keys=True))\n",
        encoding="utf-8",
    )
    return path


def test_the_shipped_receipt_carries_the_hash_the_installer_recomputes(
    tmp_path: Path,
) -> None:
    tree = tmp_path / "OntologyLab.app"
    (tree / "Contents").mkdir(parents=True)
    (tree / "Contents" / "payload.bin").write_bytes(b"payload")

    signed_tree, receipt_sha = write_artifact_receipt(tree, tmp_path / "receipt.json")

    assert signed_tree == tree_sha256(tree)
    payload = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert payload["app_tree_sha256"] == tree_sha256(tree)
    assert len(receipt_sha) == 64


def test_the_staged_bundle_stays_writable_so_installer_cleanup_can_remove_it(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sealed.app"
    (source / "Contents" / "Resources").mkdir(parents=True)
    (source / "Contents" / "Resources" / "leaf.bin").write_bytes(b"leaf")
    for path in sorted(source.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    source.chmod(0o555)

    destination = tmp_path / "staged.app"
    stage_writable_copy(source, destination)

    unwritable = [
        path
        for path in (destination, *destination.rglob("*"))
        if not stat.S_IMODE(path.stat().st_mode) & stat.S_IWUSR
    ]
    assert unwritable == []
    shutil.rmtree(destination)
    assert not destination.exists()


def test_the_runtime_manifest_describes_the_bytes_that_actually_ship(
    tmp_path: Path,
) -> None:
    candidate = _machine_code_bundle(tmp_path / "candidate")
    inventory = tmp_path / "native-inventory.json"
    inventory.write_text(
        json.dumps({"files": [{"path": "Contents/Resources/runtime/probe-native"}]}),
        encoding="utf-8",
    )
    record = tmp_path / "hashes-at-manifest-time.json"
    writer = _recording_manifest_writer(tmp_path / "writer.py", record)
    contract = tmp_path / "runtime-build.json"
    contract.write_text(json.dumps({"pyinstaller": "6.16.0"}), encoding="utf-8")
    release_receipt = tmp_path / "release-receipt.json"
    release_receipt.write_text(
        json.dumps({"source_snapshot_sha256": "a" * 64}), encoding="utf-8"
    )

    result = package_candidate(
        PackageRequest(
            candidate_app=candidate,
            native_inventory=inventory,
            output=tmp_path / "out",
            version="0.1.0",
            runtime_contract=contract,
            manifest_writer=writer,
            release_receipt=release_receipt,
        )
    )

    shipped = tmp_path / "out" / "scratch" / "Probe.app" / "Contents" / "Resources" / "runtime"
    at_manifest_time = json.loads(record.read_text(encoding="utf-8"))
    assert at_manifest_time == {
        path.relative_to(shipped).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(shipped.rglob("*"))
        if path.is_file() and path.name != "runtime-manifest.json"
    }
    assert result.operations.index("write_manifest") > result.operations.index("sign_outer")
    assert result.operations.index("reseal") > result.operations.index("write_manifest")
    shipped_app = tmp_path / "out" / "scratch" / "Probe.app"
    assert [
        path
        for path in (shipped_app, *shipped_app.rglob("*"))
        if not stat.S_IMODE(path.stat().st_mode) & stat.S_IWUSR
    ] == []
    assert result.app_tree_sha256 == tree_sha256(shipped_app)
    assert result.source_snapshot_sha256 == "a" * 64
    assert result.natives_signed == 1
