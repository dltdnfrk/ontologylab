from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

import scripts.internal_deployment_fs as deployment_fs
import scripts.internal_deployment_quarantine as quarantine
from scripts.internal_deployment import (
    DeploymentRefused,
    InstallRequest,
    PlatformInfo,
    install_app,
    tree_sha256,
)
from tests.test_internal_deployment import _app, _receipt, _request

_QUARANTINE = "com.apple.quarantine"
_QUARANTINE_VALUE = "0081;00000000;OntologyLab;"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _set_quarantine(path: Path) -> None:
    subprocess.run(
        ["/usr/bin/xattr", "-w", _QUARANTINE, _QUARANTINE_VALUE, str(path)],
        check=True,
        capture_output=True,
    )


def _has_quarantine(path: Path) -> bool:
    result = subprocess.run(
        ["/usr/bin/xattr", str(path)], check=True, capture_output=True, text=True
    )
    return _QUARANTINE in result.stdout.splitlines()


def test_install_clears_root_quarantine_without_touching_unattributed_read_only_matrix(
    tmp_path: Path,
) -> None:
    # Given a quarantined bundle root and an unquarantined mode-0444 matrix.
    candidate = _app(tmp_path / "candidate", "new")
    matrix = candidate / "Contents/Resources/storage-compatibility.json"
    matrix.chmod(0o444)
    _set_quarantine(candidate)
    receipt, receipt_hash = _receipt(candidate, tmp_path / "receipt.json")
    request = _request(tmp_path, candidate, receipt, receipt_hash)
    _app(request.destination.parent, "old")

    # When acknowledged installation clears only paths carrying quarantine.
    result = install_app(request, PlatformInfo("arm64", 15))

    # Then exact bytes/modes activate and the root quarantine is absent.
    assert result.operation == "updated"
    assert (
        _mode(request.destination / "Contents/Resources/storage-compatibility.json")
        == 0o444
    )
    assert tree_sha256(request.destination) == tree_sha256(candidate)
    assert not _has_quarantine(request.destination)
    subprocess.run(
        [
            "/usr/bin/codesign",
            "--verify",
            "--deep",
            "--strict",
            str(request.destination),
        ],
        check=True,
        capture_output=True,
    )


def test_no_ack_refuses_quarantined_app_before_mutation(tmp_path: Path) -> None:
    # Given a quarantined, receipt-bound candidate without acknowledgement.
    candidate = _app(tmp_path / "candidate-no-ack")
    _set_quarantine(candidate)
    receipt, receipt_hash = _receipt(candidate, tmp_path / "no-ack-receipt.json")
    acknowledged = _request(tmp_path, candidate, receipt, receipt_hash)
    request = InstallRequest(
        app=acknowledged.app,
        receipt=acknowledged.receipt,
        receipt_sha256=acknowledged.receipt_sha256,
        destination=acknowledged.destination,
        home=acknowledged.home,
        acknowledge_unnotarized=False,
    )

    # When install is attempted without explicit trust acknowledgement.
    with pytest.raises(DeploymentRefused, match="acknowledgement_required"):
        install_app(request, PlatformInfo("arm64", 15))

    # Then no destination or stage exists and the source quarantine is untouched.
    assert not request.destination.exists()
    assert not request.destination.parent.exists()
    assert _has_quarantine(candidate)


def test_selective_clearance_handles_nested_read_only_attribute_and_is_idempotent(
    tmp_path: Path,
) -> None:
    # Given an attributed nested read-only matrix and an unattributed peer.
    app = _app(tmp_path / "nested")
    matrix = app / "Contents/Resources/storage-compatibility.json"
    peer = app / "Contents/Resources/unattributed.json"
    peer.write_text("{}", encoding="utf-8")
    _set_quarantine(matrix)
    matrix.chmod(0o444)
    peer.chmod(0o444)
    before = tree_sha256(app)

    # When selective clearance is repeated.
    deployment_fs.clear_quarantine(app)
    deployment_fs.clear_quarantine(app)

    # Then only the actual attribute is removed and both exact modes remain.
    assert not _has_quarantine(matrix)
    assert _mode(matrix) == _mode(peer) == 0o444
    assert tree_sha256(app) == before


def test_selective_clearance_no_attributes_never_changes_modes(tmp_path: Path) -> None:
    # Given a tree with no quarantine attributes and mixed read-only modes.
    app = _app(tmp_path / "clean")
    matrix = app / "Contents/Resources/storage-compatibility.json"
    matrix.chmod(0o444)
    before = tree_sha256(app)

    # When selective clearance runs.
    deployment_fs.clear_quarantine(app)

    # Then it is a byte/path/mode no-op.
    assert tree_sha256(app) == before
    assert _mode(matrix) == 0o444


def test_selective_clearance_refuses_symlink_without_following_it(
    tmp_path: Path,
) -> None:
    # Given a symlink inside the owned staged tree pointing outside it.
    app = _app(tmp_path / "symlink")
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    link = app / "Contents/Resources/link"
    link.symlink_to(outside)
    _set_quarantine(outside)

    # When selective traversal encounters the symlink.
    with pytest.raises(DeploymentRefused, match="artifact_symlink"):
        deployment_fs.clear_quarantine(app)

    # Then the external target was neither followed nor modified.
    assert _has_quarantine(outside)


def test_selective_clearance_restores_mode_when_removal_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given an attributed read-only matrix whose attribute removal is denied.
    app = _app(tmp_path / "denied")
    matrix = app / "Contents/Resources/storage-compatibility.json"
    _set_quarantine(matrix)
    matrix.chmod(0o444)

    def deny(_path: Path) -> None:
        raise PermissionError

    monkeypatch.setattr(quarantine, "_remove_quarantine", deny)

    destination = _app(tmp_path / "Applications", "old")

    # When staged removal fails after temporary owner-write permission.
    with pytest.raises(DeploymentRefused, match="quarantine_remove_failed"):
        deployment_fs.atomic_copy_app(app, destination, tree_sha256(app))

    # Then the live app is untouched, the stage is gone, and source mode is exact.
    assert (destination / "Contents/MacOS/OntologyLab").read_text() == "old"
    assert not tuple(destination.parent.glob(".OntologyLab.app.install-*"))
    assert _mode(matrix) == 0o444
    assert _has_quarantine(matrix)


def test_selective_clearance_restores_mode_when_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given an attributed read-only matrix interrupted during removal.
    app = _app(tmp_path / "interrupted")
    matrix = app / "Contents/Resources/storage-compatibility.json"
    _set_quarantine(matrix)
    matrix.chmod(0o444)

    def interrupt(_path: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(quarantine, "_remove_quarantine", interrupt)

    destination = _app(tmp_path / "Applications", "old")

    # When the staged operation is interrupted.
    with pytest.raises(KeyboardInterrupt):
        deployment_fs.atomic_copy_app(app, destination, tree_sha256(app))

    # Then live activation never occurs, stage cleanup and mode restoration complete.
    assert (destination / "Contents/MacOS/OntologyLab").read_text() == "old"
    assert not tuple(destination.parent.glob(".OntologyLab.app.install-*"))
    assert _mode(matrix) == 0o444
    assert _has_quarantine(matrix)
