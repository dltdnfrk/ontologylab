from __future__ import annotations

import json
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest

import scripts.internal_deployment_removal_apply as apply
import scripts.internal_deployment_removal_receipt as receipt
from scripts.internal_deployment_cli import main as deployment_main
from scripts.internal_deployment_removal_journal import (
    ProgressEvent,
    RemovalJournalState,
)
from scripts.internal_deployment_types import DeploymentRefused
from tests.test_internal_deployment_prepared_anchor import (
    _apply_arguments,
    _prepare_arguments,
    _prepared_fixture,
)


@unique
class CrashBoundary(StrEnum):
    BEFORE_APP_RENAME = "before_app_rename"
    AFTER_APP_RENAME = "after_app_rename"
    AFTER_APP_PROGRESS = "after_app_progress"
    BEFORE_RUNTIME_RENAME = "before_runtime_rename"
    AFTER_RUNTIME_RENAME = "after_runtime_rename"
    AFTER_RUNTIME_PROGRESS = "after_runtime_progress"
    AFTER_RECEIPT = "after_receipt"


def _inject_crash(
    boundary: CrashBoundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = apply._rename_exclusive
    real_progress = apply.append_progress
    real_completed = receipt.append_completed
    rename_calls = 0

    def crash_rename(source: Path, destination: Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if boundary is CrashBoundary.BEFORE_APP_RENAME and rename_calls == 1:
            raise DeploymentRefused("injected_before_app_rename")
        if boundary is CrashBoundary.BEFORE_RUNTIME_RENAME and rename_calls == 2:
            raise DeploymentRefused("injected_before_runtime_rename")
        real_rename(source, destination)

    def crash_progress(path: Path, event: ProgressEvent, event_id: str) -> None:
        if boundary is CrashBoundary.AFTER_APP_RENAME and event == "app_retained":
            raise DeploymentRefused("injected_after_app_rename")
        if boundary is CrashBoundary.AFTER_RUNTIME_RENAME and event == "runtime_retained":
            raise DeploymentRefused("injected_after_runtime_rename")
        real_progress(path, event, event_id)
        if boundary is CrashBoundary.AFTER_APP_PROGRESS and event == "app_retained":
            raise DeploymentRefused("injected_after_app_progress")
        if boundary is CrashBoundary.AFTER_RUNTIME_PROGRESS and event == "runtime_retained":
            raise DeploymentRefused("injected_after_runtime_progress")

    def crash_completed(
        path: Path, state: RemovalJournalState, receipt_sha256: str
    ) -> None:
        if boundary is CrashBoundary.AFTER_RECEIPT:
            raise DeploymentRefused("injected_after_receipt")
        real_completed(path, state, receipt_sha256)

    match boundary:
        case CrashBoundary.BEFORE_APP_RENAME | CrashBoundary.BEFORE_RUNTIME_RENAME:
            monkeypatch.setattr(apply, "_rename_exclusive", crash_rename)
        case (
            CrashBoundary.AFTER_APP_RENAME
            | CrashBoundary.AFTER_APP_PROGRESS
            | CrashBoundary.AFTER_RUNTIME_RENAME
            | CrashBoundary.AFTER_RUNTIME_PROGRESS
        ):
            monkeypatch.setattr(apply, "append_progress", crash_progress)
        case CrashBoundary.AFTER_RECEIPT:
            monkeypatch.setattr(receipt, "append_completed", crash_completed)
        case unreachable:
            assert_never(unreachable)


@pytest.mark.parametrize("boundary", list(CrashBoundary))
def test_same_controller_anchor_recovers_every_forward_crash_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    boundary: CrashBoundary,
) -> None:
    # Given a prepared transaction and one injected durable crash boundary.
    fixture = _prepared_fixture(tmp_path)
    assert deployment_main(_prepare_arguments(fixture)) == 0
    anchor = json.loads(capsys.readouterr().out)["prepared_anchor"]
    with pytest.MonkeyPatch.context() as injected:
        _inject_crash(boundary, injected)

        # When apply is interrupted at that exact boundary.
        assert deployment_main(_apply_arguments(fixture, anchor)) == 2
        capsys.readouterr()

    # Then replay with the same external anchor completes only forward.
    assert deployment_main(_apply_arguments(fixture, anchor)) == 0
    replay = json.loads(capsys.readouterr().out)
    assert Path(replay["retained_removal_receipt"]).is_file()
    assert not fixture.app.exists()
    assert not fixture.runtime.exists()
    assert (fixture.retained / "OntologyLab.app").is_dir()
    assert (fixture.retained / "runtime").is_dir()


def test_completed_replay_requires_same_anchor_and_returns_same_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given one completed anchored retained uninstall.
    fixture = _prepared_fixture(tmp_path)
    assert deployment_main(_prepare_arguments(fixture)) == 0
    anchor = json.loads(capsys.readouterr().out)["prepared_anchor"]
    assert deployment_main(_apply_arguments(fixture, anchor)) == 0
    first = json.loads(capsys.readouterr().out)["retained_removal_receipt"]
    before = Path(first).read_bytes()

    # When completed replay receives the original anchor.
    assert deployment_main(_apply_arguments(fixture, anchor)) == 0

    # Then the same receipt is returned without local mutation.
    second = json.loads(capsys.readouterr().out)["retained_removal_receipt"]
    assert second == first
    assert Path(second).read_bytes() == before
