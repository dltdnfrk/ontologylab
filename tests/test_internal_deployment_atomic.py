from __future__ import annotations

from pathlib import Path

import pytest

import scripts.internal_deployment_fs as deployment_fs
from scripts.internal_deployment import DeploymentRefused, tree_sha256
from tests.test_internal_deployment import _app


def test_atomic_update_recovers_interruption_after_swap_without_live_app_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a verified update whose process is interrupted immediately after swap.
    candidate = _app(tmp_path / "candidate", "new")
    destination = _app(tmp_path / "Applications", "old")
    real_exchange = deployment_fs.atomic_exchange

    def interrupt_after_swap(left: Path, right: Path) -> None:
        real_exchange(left, right)
        raise KeyboardInterrupt

    monkeypatch.setattr(deployment_fs, "atomic_exchange", interrupt_after_swap)

    # When activation reaches the single atomic exchange and is interrupted.
    with pytest.raises(KeyboardInterrupt):
        deployment_fs.atomic_copy_app(candidate, destination, tree_sha256(candidate))

    # Then one live new app and the recovery journal remain, never an absent app.
    assert (destination / "Contents/MacOS/OntologyLab").read_text() == "new"
    assert len(tuple(destination.parent.glob(".OntologyLab.app.install-*"))) == 1
    assert (destination.parent / ".OntologyLab.app.activation.json").is_file()

    # When the same exact update is retried.
    monkeypatch.setattr(deployment_fs, "atomic_exchange", real_exchange)
    deployment_fs.atomic_copy_app(candidate, destination, tree_sha256(candidate))

    # Then recovery is deterministic with exactly one live app and no orphans.
    assert destination.exists()
    assert not tuple(destination.parent.glob(".OntologyLab.app.previous-*"))
    assert not tuple(destination.parent.glob(".OntologyLab.app.install-*"))
    assert not (destination.parent / ".OntologyLab.app.activation.json").exists()


def test_atomic_exchange_refuses_unsupported_filesystem_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a valid candidate but a destination on a filesystem without swap.
    candidate = _app(tmp_path / "candidate", "new")
    destination = tmp_path / "missing/Applications/OntologyLab.app"
    monkeypatch.setattr(deployment_fs, "_filesystem_type", lambda _path: "exfat")

    # When activation preflights the filesystem.
    with pytest.raises(DeploymentRefused, match="atomic_exchange_unsupported"):
        deployment_fs.atomic_copy_app(candidate, destination, tree_sha256(candidate))

    # Then no destination parent, stage, or journal was created.
    assert not destination.parent.exists()


def test_retry_recovers_legacy_absent_live_app_and_orphan_previous(
    tmp_path: Path,
) -> None:
    # Given the old two-rename failure state captured by the RED characterization.
    candidate = _app(tmp_path / "candidate", "new")
    destination = _app(tmp_path / "Applications", "old")
    previous = destination.parent / ".OntologyLab.app.previous-interrupted"
    deployment_fs.os.replace(destination, previous)

    # When the repaired installer retries the update.
    deployment_fs.atomic_copy_app(candidate, destination, tree_sha256(candidate))

    # Then exactly one new live app exists and the legacy orphan is gone.
    assert (destination / "Contents/MacOS/OntologyLab").read_text() == "new"
    assert not previous.exists()
    assert not tuple(destination.parent.glob(".OntologyLab.app.install-*"))


def test_retained_scratch_mode_refuses_update_before_any_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a valid candidate, an existing app, and the no-delete QA boundary.
    candidate = _app(tmp_path / "candidate", "new")
    destination = _app(tmp_path / "Applications", "old")
    retention_root = tmp_path / "retained"
    monkeypatch.setenv("ONTOLOGYLAB_RETAIN_SCRATCH_ROOT", str(retention_root))

    # When an update would require deleting or replacing existing state.
    with pytest.raises(DeploymentRefused, match="retained_scratch_requires_fresh"):
        deployment_fs.atomic_copy_app(candidate, destination, tree_sha256(candidate))

    # Then the existing app remains exact and no scratch mutation has started.
    assert (destination / "Contents/MacOS/OntologyLab").read_text() == "old"
    assert not retention_root.exists()
    assert not tuple(destination.parent.glob(".OntologyLab.app.install-*"))


def test_reinstall_recovers_deployment_owned_interrupted_stage(
    tmp_path: Path,
) -> None:
    # Given a stale partial stage left before an atomic activation journal existed.
    candidate = _app(tmp_path / "candidate")
    destination = tmp_path / "Applications/OntologyLab.app"
    destination.parent.mkdir(parents=True)
    stale = destination.parent / ".OntologyLab.app.install-interrupted"
    stale.mkdir()
    (stale / "partial").write_text("partial", encoding="utf-8")

    # When the validated copy is retried.
    deployment_fs.atomic_copy_app(candidate, destination, tree_sha256(candidate))

    # Then the stale stage is cleaned and exact activation succeeds.
    assert not stale.exists()
    assert tree_sha256(destination) == tree_sha256(candidate)
