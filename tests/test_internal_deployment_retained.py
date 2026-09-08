from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest

import scripts.internal_deployment_removal_apply as removal
import scripts.internal_deployment_removal_prepare as preparation
from release.pyinstaller import internal_deployment_entry
from scripts.internal_deployment import uninstall_app
from scripts.internal_deployment_types import DeploymentRefused
from scripts.internal_deployment_cli import main as deployment_main
from scripts.internal_deployment_fs import tree_sha256
from tests.internal_deployment_anchor_support import (
    installed as _installed,
    uninstall_request as _request,
)


def test_retained_uninstall_atomically_moves_only_app_and_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given an installed pair, canonical data, and an owner-only retained root.
    app, home, runtime, retained = _installed(tmp_path)
    data = home / "Library/Application Support/ontologylab/data/kg.sqlite"
    app_hash = tree_sha256(app)
    runtime_hash = tree_sha256(runtime)
    monkeypatch.setattr(
        "scripts.internal_deployment.shutil.rmtree",
        lambda _path: pytest.fail("retained mode selected destructive removal"),
    )

    # When explicit retained-removal uninstall runs through product code.
    result = uninstall_app(_request(app, home, retained))

    # Then exact trees are renamed, data stays active, and the receipt binds both.
    assert result is not None
    assert result == retained / "retained-removal-receipt.json"
    assert not app.exists()
    assert not runtime.exists()
    assert data.read_text(encoding="utf-8") == "canonical"
    assert tree_sha256(retained / "OntologyLab.app") == app_hash
    assert tree_sha256(retained / "runtime") == runtime_hash
    receipt = json.loads(result.read_text(encoding="utf-8"))
    assert receipt["schema"] == "ontologylab.retained-removal-receipt.v2"
    assert receipt["artifact"]["version"] == "0.1.0"
    assert [entry["source_path"] for entry in receipt["paths"]] == [
        str(app),
        str(runtime),
    ]
    assert all(entry["active_path_absent"] for entry in receipt["paths"])
    assert all(
        entry["source_inode"] == entry["retained_inode"]
        and entry["source_device"] == entry["retained_device"]
        and entry["source_mode"] == entry["retained_mode"]
        and entry["source_tree_sha256"] == entry["retained_tree_sha256"]
        for entry in receipt["paths"]
    )
    journal = [
        json.loads(line)
        for line in (retained / "retained-removal-journal.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert journal[-1]["previous_sha256"] == receipt["journal_state_sha256"]
    assert journal[-1]["receipt_sha256"] == hashlib.sha256(result.read_bytes()).hexdigest()

    # When the exact request is repeated, then it returns the same receipt unchanged.
    before = result.read_bytes()
    assert uninstall_app(_request(app, home, retained)) == result
    assert result.read_bytes() == before


@unique
class UnsafeMutation(StrEnum):
    PERMISSIONS = "permissions"
    COLLISION = "collision"
    JOURNAL = "journal"
    ARTIFACT_NAME = "artifact_name"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (UnsafeMutation.PERMISSIONS, "retained_root_permissions"),
        (UnsafeMutation.COLLISION, "retained_removal_collision"),
        (UnsafeMutation.JOURNAL, "retained_removal_collision"),
        (UnsafeMutation.ARTIFACT_NAME, "retained_removal_scope"),
    ],
)
def test_retained_uninstall_refuses_unsafe_preexisting_state_before_rename(
    tmp_path: Path, mutation: UnsafeMutation, reason: str
) -> None:
    # Given one unsafe retained-mode boundary.
    app, home, runtime, retained = _installed(tmp_path)
    match mutation:
        case UnsafeMutation.PERMISSIONS:
            retained.chmod(0o755)
        case UnsafeMutation.COLLISION:
            (retained / "runtime").mkdir()
        case UnsafeMutation.JOURNAL:
            (retained / "retained-removal-journal.jsonl").write_text(
                '{"event":"prepared"}\n', encoding="utf-8"
            )
        case UnsafeMutation.ARTIFACT_NAME:
            app.rename(app.with_name("Foreign.app"))
            app = app.with_name("Foreign.app")
        case unreachable:
            assert_never(unreachable)

    # When retained uninstall preflights, then it refuses before either rename.
    with pytest.raises(DeploymentRefused, match=reason):
        uninstall_app(_request(app, home, retained))
    assert app.exists()
    assert runtime.exists()


def test_retained_uninstall_refuses_symlink_and_cross_device_before_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a symlinked retained root, then a simulated cross-device source pair.
    app, home, runtime, retained = _installed(tmp_path)
    linked = tmp_path / "retained-link"
    linked.symlink_to(retained, target_is_directory=True)
    with pytest.raises(DeploymentRefused, match="retained_root_path_unsafe"):
        uninstall_app(_request(app, home, linked))

    real_source = preparation._source

    def cross_device(path: Path, destination: Path) -> preparation._Source:
        source = real_source(path, destination)
        return replace(source, device=source.device + 1)

    monkeypatch.setattr(preparation, "_source", cross_device)

    # When device preflight runs, then both active paths remain unchanged.
    with pytest.raises(DeploymentRefused, match="retained_removal_cross_device"):
        uninstall_app(_request(app, home, retained))
    assert app.exists()
    assert runtime.exists()
    assert not tuple(retained.iterdir())


def test_retained_uninstall_refuses_source_drift_before_journal_or_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given runtime bytes that drift between source capture and final preflight.
    app, home, runtime, retained = _installed(tmp_path)
    real_require = preparation._require_unchanged
    calls = 0

    def drift_between_sources(source: preparation._Source) -> None:
        nonlocal calls
        calls += 1
        real_require(source)
        if calls == 1:
            (runtime / "state.bin").write_bytes(b"drifted")

    monkeypatch.setattr(preparation, "_require_unchanged", drift_between_sources)

    # When final source identity preflight runs, then no journal or rename occurs.
    with pytest.raises(DeploymentRefused, match="retained_removal_source_drift"):
        uninstall_app(_request(app, home, retained))
    assert app.exists()
    assert runtime.exists()
    assert not tuple(retained.iterdir())


@pytest.mark.parametrize(
    ("path_arguments", "reason"),
    [
        ((), "retained_removal_app_required"),
        (("--app", "/Applications/OntologyLab.app"), "retained_removal_home_required"),
    ],
)
def test_retained_cli_refuses_home_or_app_discovery(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    path_arguments: tuple[str, ...],
    reason: str,
) -> None:
    # Given retained mode without one explicitly required active-path boundary.
    retained = tmp_path / "retained"
    retained.mkdir(mode=0o700)

    # When the real source CLI parses the request, then discovery is refused.
    assert (
        deployment_main(
            ["uninstall", *path_arguments, "--retain-removals-under", str(retained)]
        )
        == 2
    )
    assert reason in capsys.readouterr().err


def test_standalone_retained_uninstall_preserves_frozen_app_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a frozen app and explicit retained-mode arguments.
    app = tmp_path / "Applications/OntologyLab.app"
    nested = app / "Contents/Resources"
    nested.mkdir(parents=True)
    for path in (nested, nested.parent, app):
        path.chmod(0o555)
    home = tmp_path / "home"
    retained = tmp_path / "retained"
    home.mkdir()
    retained.mkdir(mode=0o700)

    def observe(_argv: list[str] | None = None) -> int:
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o555 for path in (app, nested))
        return 0

    monkeypatch.setattr(internal_deployment_entry, "deployment_main", observe)

    # When the bundled entry delegates retained uninstall, then it does not chmod.
    assert (
        internal_deployment_entry.main(
            [
                "uninstall",
                "--app",
                str(app),
                "--home",
                str(home),
                "--retain-removals-under",
                str(retained),
            ]
        )
        == 0
    )


def test_retained_uninstall_records_forward_recovery_if_second_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a preflighted pair whose second atomic rename reports a late failure.
    app, home, runtime, retained = _installed(tmp_path)
    real_rename = removal._rename_exclusive
    calls = 0

    def fail_second(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DeploymentRefused("retained_removal_errno_5")
        real_rename(source, destination)

    monkeypatch.setattr(removal, "_rename_exclusive", fail_second)

    # When the impossible-under-contract second rename fails, then no rollback deletes.
    with pytest.raises(
        DeploymentRefused, match="retained_removal_forward_recovery_required"
    ):
        uninstall_app(_request(app, home, retained))
    assert not app.exists()
    assert (retained / "OntologyLab.app").is_dir()
    assert runtime.is_dir()
    journal = retained / "retained-removal-journal.jsonl"
    assert "forward_recovery_required" in journal.read_text(encoding="utf-8")
    assert not (retained / "retained-removal-receipt.json").exists()
