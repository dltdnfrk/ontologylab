"""Task 14 contracts for the clean-Mac internal deployment executable."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, assert_never

import pytest

from release import candidate_build as candidate
from release.candidate_stage import derive_build_work, patched_builder, prepare_stage
from release.pyinstaller import internal_deployment_entry
from tests import macos_candidate_deployment_support as deployment_support
from tests.macos_candidate_deployment_support import build_standalone_pair
from tests.macos_candidate_test_support import (
    add_license_fixture,
    metadata,
    source_fixture,
)

ROOT: Final = Path(__file__).resolve().parents[1]
_EXECUTABLE: Final = "Contents/MacOS/ontologylab-internal-deploy"


def _deployment_payload(candidate_root: Path, version: str = "0.1.0") -> Path:
    app = candidate_root / "payload" / "OntologyLab.app"
    executable = app / _EXECUTABLE
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"\xcf\xfa\xed\xfe" + b"standalone-arm64")
    executable.chmod(0o755)
    resources = app / "Contents" / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    matrix = (ROOT / "ontologylab" / "storage-compatibility.json").read_bytes()
    (resources / "storage-compatibility.json").write_bytes(matrix)
    (resources / "internal-deployment.json").write_text(
        json.dumps(
            {
                "architecture": "arm64",
                "executable_path": _EXECUTABLE,
                "executable_sha256": hashlib.sha256(
                    executable.read_bytes()
                ).hexdigest(),
                "schema": "ontologylab.internal-deployment-build.v1",
                "version": version,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (resources / "native-inventory.json").write_text(
        json.dumps(
            {
                "architecture": "arm64",
                "files": [
                    {
                        "architecture": "arm64",
                        "dependencies": ["/usr/lib/libSystem.B.dylib"],
                        "path": _EXECUTABLE,
                    }
                ],
                "schema": "ontologylab.runtime-native-inventory.v1",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    add_license_fixture(
        app,
        include_storage_matrix=False,
        include_internal_deployment=False,
    )
    bundled = resources / "runtime/_internal/ontologylab/storage-compatibility.json"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(matrix)
    return app


def test_independent_standalone_builds_are_byte_identical(tmp_path: Path) -> None:
    # Given the immutable Task 11 inputs and two independently derived build roots.
    authority = source_fixture(tmp_path / "authority")
    first = prepare_stage(authority, tmp_path / "stage-a")
    second = derive_build_work(authority, first.source_root, tmp_path / "stage-b")
    builder = patched_builder(authority).decode()
    assert "ontologylab-internal-deployment.spec" in builder
    assert "Contents/MacOS/ontologylab-internal-deploy" in builder
    assert 'codesign --force --sign - --timestamp=none "$APP"' in builder
    assert "--onefile" not in builder

    # When both final executable/hash/resource builds finish, then they are equal.
    first_result, second_result = build_standalone_pair(first, second, tmp_path)
    assert first_result == second_result


def test_standalone_build_failure_reports_bounded_subprocess_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a standalone build whose offline tool invocation fails with large output.
    authority = source_fixture(tmp_path / "authority")
    layout = prepare_stage(authority, tmp_path / "stage")
    secret = "standalone-test-secret"
    monkeypatch.setenv("STANDALONE_TEST_SECRET", secret)

    def fail(*args, **_kwargs) -> None:
        command = args[0]
        raise subprocess.CalledProcessError(
            17,
            command,
            output="stdout-marker-" + "x" * 10_000,
            stderr="stderr-marker-" + "y" * 10_000,
        )

    monkeypatch.setattr(deployment_support.subprocess, "run", fail)
    run_root = tmp_path / "run"
    run_root.mkdir()

    # When the helper observes the failed child process.
    with pytest.raises(AssertionError) as captured:
        build_standalone_pair(layout, layout, run_root)

    # Then the failure identifies the command and bounded streams without environment.
    diagnostic = str(captured.value)
    assert "returncode=17" in diagnostic
    assert "uv run --frozen --offline" in diagnostic
    assert "stdout-marker-" in diagnostic
    assert "stderr-marker-" in diagnostic
    assert len(diagnostic) < 10_000
    assert secret not in diagnostic


def test_standalone_build_timeout_reports_bounded_subprocess_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a standalone build whose offline tool invocation exceeds its deadline.
    authority = source_fixture(tmp_path / "authority")
    layout = prepare_stage(authority, tmp_path / "stage")

    def time_out(*args, **_kwargs) -> None:
        raise subprocess.TimeoutExpired(
            args[0], 300, output=b"timeout-stdout", stderr=b"timeout-stderr"
        )

    monkeypatch.setattr(deployment_support.subprocess, "run", time_out)
    run_root = tmp_path / "run"
    run_root.mkdir()

    # When the helper observes the timed-out child process.
    with pytest.raises(AssertionError) as captured:
        build_standalone_pair(layout, layout, run_root)

    # Then the timeout and captured byte streams remain visible.
    diagnostic = str(captured.value)
    assert "timeout=300" in diagnostic
    assert "timeout-stdout" in diagnostic
    assert "timeout-stderr" in diagnostic


def test_standalone_uninstall_prepares_frozen_app_for_task10_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a Task 11 installed tree whose directories are immutable.
    app = tmp_path / "Applications/OntologyLab.app"
    nested = app / "Contents/Resources"
    nested.mkdir(parents=True)
    for path in (nested, nested.parent, app):
        path.chmod(0o555)

    def observe(_argv: list[str] | None = None) -> int:
        assert all(path.stat().st_mode & stat.S_IWUSR for path in (app, nested))
        return 0

    monkeypatch.setattr(internal_deployment_entry, "deployment_main", observe)

    # When the standalone boundary delegates uninstall, then Task 10 can remove it.
    assert internal_deployment_entry.main(["uninstall", "--app", str(app)]) == 0


def test_candidate_refuses_missing_standalone_executable(tmp_path: Path) -> None:
    # Given an otherwise sealable payload without the clean-Mac deployment surface.
    root = source_fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    app = candidate_root / "payload" / "OntologyLab.app"
    app.mkdir(parents=True)
    add_license_fixture(app, include_internal_deployment=False)

    # When sealing runs, then absence refuses before a receipt is emitted.
    with pytest.raises(candidate.CandidateRefused, match="internal_deployment_missing"):
        candidate.seal_candidate(
            candidate_root, candidate.verify_source(root), metadata()
        )


def test_candidate_binds_standalone_into_resources_receipt_and_frozen_tree(
    tmp_path: Path,
) -> None:
    # Given one thin-arm64 deployment executable with exact generated identity.
    root = source_fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    app = _deployment_payload(candidate_root)

    # When the candidate seals.
    receipt_path = candidate.seal_candidate(
        candidate_root, candidate.verify_source(root), metadata()
    )

    # Then resource, receipt, payload, native, and static inventories bind it.
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    resources = json.loads(
        (candidate_root / "inventories" / "resources.json").read_text(encoding="utf-8")
    )
    payload = json.loads(
        (candidate_root / "inventories" / "payload-tree.json").read_text(
            encoding="utf-8"
        )
    )
    deployment = resources["internal_deployment"]
    assert receipt["resources"]["internal_deployment"] == deployment
    assert deployment["executable_path"] == _EXECUTABLE
    assert deployment["architecture"] == "arm64"
    assert deployment["version"] == "0.1.0"
    entry = next(item for item in payload["entries"] if item["path"] == _EXECUTABLE)
    assert entry["sha256"] == deployment["executable_sha256"]
    assert stat.S_IMODE((app / _EXECUTABLE).stat().st_mode) == 0o555
    assert (
        stat.S_IMODE(
            (app / "Contents/Resources/storage-compatibility.json").stat().st_mode
        )
        == 0o444
    )
    bundled_matrix = (
        app
        / "Contents/Resources/runtime/_internal/ontologylab/storage-compatibility.json"
    )
    assert stat.S_IMODE(bundled_matrix.stat().st_mode) == 0o444


@unique
class DeploymentMutation(StrEnum):
    HASH = "hash"
    VERSION = "version"
    ARCHITECTURE = "architecture"


@pytest.mark.parametrize("mutation", list(DeploymentMutation))
def test_candidate_refuses_standalone_identity_drift(
    tmp_path: Path, mutation: DeploymentMutation
) -> None:
    # Given one standalone payload with one identity field changed after assembly.
    root = source_fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    app = _deployment_payload(candidate_root)
    manifest = app / "Contents/Resources/internal-deployment.json"
    native = app / "Contents/Resources/native-inventory.json"
    match mutation:
        case DeploymentMutation.HASH:
            (app / _EXECUTABLE).write_bytes(b"\xcf\xfa\xed\xfetampered")
        case DeploymentMutation.VERSION:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["version"] = "9.9.9"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
        case DeploymentMutation.ARCHITECTURE:
            payload = json.loads(native.read_text(encoding="utf-8"))
            payload["files"][0]["architecture"] = "x86_64"
            native.write_text(json.dumps(payload), encoding="utf-8")
        case unreachable:
            assert_never(unreachable)

    # When sealing runs, then tamper, version drift, and wrong arch all fail closed.
    with pytest.raises(candidate.CandidateRefused, match="internal_deployment"):
        candidate.seal_candidate(
            candidate_root, candidate.verify_source(root), metadata()
        )
