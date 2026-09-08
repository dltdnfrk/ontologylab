from __future__ import annotations

import json
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest

import scripts.internal_deployment_removal_apply as removal
from scripts.internal_deployment_removal_journal import ProgressEvent
from scripts.internal_deployment import DeploymentRefused, uninstall_app
from scripts.internal_deployment_fs import tree_sha256
from tests.test_internal_deployment_retained import _installed, _request


@unique
class ReceiptMutation(StrEnum):
    RETAINED_PATH = "retained_path"
    SOURCE_PATH = "source_path"
    TREE_HASH = "tree_hash"
    INODE = "inode"
    DEVICE = "device"
    MODE = "mode"
    EXECUTABLE = "executable"
    APP_HASH = "app_hash"
    ASSOCIATION = "association"


def _partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path]:
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
    with pytest.raises(
        DeploymentRefused, match="retained_removal_forward_recovery_required"
    ):
        uninstall_app(_request(app, home, retained))
    monkeypatch.setattr(removal, "_rename_exclusive", real_rename)
    return app, home, runtime, retained


def test_completed_repeat_refuses_receipt_substituted_sibling_trees(
    tmp_path: Path,
) -> None:
    # Given a completed receipt rewritten to attacker-controlled sibling trees.
    app, home, _runtime, retained = _installed(tmp_path / "victim")
    receipt_path = uninstall_app(_request(app, home, retained))
    assert receipt_path is not None
    external_app, _external_home, external_runtime, _external_retained = _installed(
        tmp_path / "external"
    )
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["app_tree_sha256"] = "e" * 64
    payload["artifact"]["executable_sha256"] = "f" * 64
    for entry, external in zip(
        payload["paths"], (external_app, external_runtime), strict=True
    ):
        info = external.stat()
        entry.update(
            {
                "source_inode": 1,
                "source_device": 1,
                "source_tree_sha256": "d" * 64,
                "retained_path": str(external),
                "retained_inode": info.st_ino,
                "retained_device": info.st_dev,
                "retained_tree_sha256": tree_sha256(external),
            }
        )
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")
    before = (
        tree_sha256(retained / "OntologyLab.app"),
        tree_sha256(retained / "runtime"),
        tree_sha256(external_app),
        tree_sha256(external_runtime),
    )

    # When the exact request is repeated, then attacker-selected projections refuse.
    with pytest.raises(DeploymentRefused, match="retained_removal_receipt"):
        uninstall_app(_request(app, home, retained))
    assert before == (
        tree_sha256(retained / "OntologyLab.app"),
        tree_sha256(retained / "runtime"),
        tree_sha256(external_app),
        tree_sha256(external_runtime),
    )


@pytest.mark.parametrize("mutation", list(ReceiptMutation))
def test_completed_repeat_refuses_each_receipt_identity_mutation(
    tmp_path: Path, mutation: ReceiptMutation
) -> None:
    # Given one completed receipt with one machine-consumed field changed.
    app, home, _runtime, retained = _installed(tmp_path)
    receipt = uninstall_app(_request(app, home, retained))
    assert receipt is not None
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    match mutation:
        case ReceiptMutation.RETAINED_PATH:
            payload["paths"][0]["retained_path"] = str(tmp_path / "sibling")
        case ReceiptMutation.SOURCE_PATH:
            payload["paths"][0]["source_path"] = str(tmp_path / "other.app")
        case ReceiptMutation.TREE_HASH:
            payload["paths"][0]["retained_tree_sha256"] = "a" * 64
        case ReceiptMutation.INODE:
            payload["paths"][0]["retained_inode"] += 1
        case ReceiptMutation.DEVICE:
            payload["paths"][0]["retained_device"] += 1
        case ReceiptMutation.MODE:
            payload["paths"][0]["retained_mode"] ^= 1
        case ReceiptMutation.EXECUTABLE:
            payload["artifact"]["executable_sha256"] = "b" * 64
        case ReceiptMutation.APP_HASH:
            payload["app_tree_sha256"] = "c" * 64
        case ReceiptMutation.ASSOCIATION:
            payload["paths"].reverse()
        case unreachable:
            assert_never(unreachable)
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    # When replay validates independent journal/request/filesystem authority.
    with pytest.raises(DeploymentRefused, match="retained_removal_receipt"):
        uninstall_app(_request(app, home, retained))
    assert (retained / "OntologyLab.app").is_dir()
    assert (retained / "runtime").is_dir()


def test_partial_retry_refuses_tampered_journal_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a real partial transaction whose prepared retained path is rewritten.
    app, home, runtime, retained = _partial(tmp_path, monkeypatch)
    journal = retained / "retained-removal-journal.jsonl"
    lines = journal.read_text(encoding="utf-8").splitlines()
    prepared = json.loads(lines[0])
    prepared["app"]["retained_path"] = str(tmp_path / "sibling-app")
    lines[0] = json.dumps(prepared)
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before_runtime = tree_sha256(runtime)
    before_app = tree_sha256(retained / "OntologyLab.app")

    # When the exact request repeats, then journal tampering refuses before rename.
    with pytest.raises(DeploymentRefused, match="prepared_anchor_mismatch"):
        uninstall_app(_request(app, home, retained))
    assert tree_sha256(runtime) == before_runtime
    assert tree_sha256(retained / "OntologyLab.app") == before_app
    assert not (retained / "runtime").exists()


def test_partial_retry_refuses_retained_drift_and_extra_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a partial transaction with changed retained bytes and an extra root entry.
    app, home, runtime, retained = _partial(tmp_path, monkeypatch)
    changed = retained / "OntologyLab.app/Contents/Resources/storage-compatibility.json"
    changed.write_text("drift", encoding="utf-8")
    (retained / "foreign-entry").mkdir()
    before_runtime = tree_sha256(runtime)

    # When recovery runs, then collision/drift state refuses without moving runtime.
    with pytest.raises(DeploymentRefused, match="retained_removal_collision"):
        uninstall_app(_request(app, home, retained))
    assert tree_sha256(runtime) == before_runtime
    assert not (retained / "runtime").exists()


def test_exact_retry_completes_after_second_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given the real partial state from a successful app rename and failed runtime rename.
    app, home, runtime, retained = _partial(tmp_path, monkeypatch)

    # When the exact request repeats, then it validates and completes forward.
    receipt = uninstall_app(_request(app, home, retained))
    assert receipt == retained / "retained-removal-receipt.json"
    assert not app.exists()
    assert not runtime.exists()
    assert (retained / "OntologyLab.app").is_dir()
    assert (retained / "runtime").is_dir()


def test_exact_retry_recovers_app_rename_before_journal_advance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given the app rename completed immediately before its journal transition failed.
    app, home, runtime, retained = _installed(tmp_path)
    real_append = removal.append_progress

    def interrupt_app_transition(
        path: Path, event: ProgressEvent, event_id: str
    ) -> None:
        if event == "app_retained":
            raise DeploymentRefused("injected_app_journal_interruption")
        real_append(path, event, event_id)

    monkeypatch.setattr(removal, "append_progress", interrupt_app_transition)
    with pytest.raises(DeploymentRefused, match="injected_app_journal_interruption"):
        uninstall_app(_request(app, home, retained))
    monkeypatch.setattr(removal, "append_progress", real_append)

    # When the exact request repeats, then filesystem identity advances the journal.
    assert uninstall_app(_request(app, home, retained)) is not None
    assert not app.exists()
    assert not runtime.exists()


def test_exact_retry_recovers_runtime_rename_before_journal_advance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given both renames completed immediately before runtime journal advance failed.
    app, home, runtime, retained = _installed(tmp_path)
    real_append = removal.append_progress

    def interrupt_runtime_transition(
        path: Path, event: ProgressEvent, event_id: str
    ) -> None:
        if event == "runtime_retained":
            raise DeploymentRefused("injected_runtime_journal_interruption")
        real_append(path, event, event_id)

    monkeypatch.setattr(removal, "append_progress", interrupt_runtime_transition)
    with pytest.raises(
        DeploymentRefused, match="injected_runtime_journal_interruption"
    ):
        uninstall_app(_request(app, home, retained))
    monkeypatch.setattr(removal, "append_progress", real_append)

    # When the exact request repeats, then it advances and finalizes without renaming.
    assert uninstall_app(_request(app, home, retained)) is not None
    assert not app.exists()
    assert not runtime.exists()


def test_exact_retry_finalizes_after_both_renames_before_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given both exact trees retained but receipt construction interrupted.
    app, home, runtime, retained = _installed(tmp_path)
    real_finalize = removal._finalize

    def interrupt_receipt(
        _paths: removal.RecoveryPaths, _pair: removal.RetainedPair
    ) -> Path:
        raise DeploymentRefused("injected_receipt_interruption")

    monkeypatch.setattr(removal, "_finalize", interrupt_receipt)
    with pytest.raises(DeploymentRefused, match="injected_receipt_interruption"):
        uninstall_app(_request(app, home, retained))
    monkeypatch.setattr(removal, "_finalize", real_finalize)

    # When the exact request repeats, then it finalizes without another rename.
    receipt = uninstall_app(_request(app, home, retained))
    assert receipt == retained / "retained-removal-receipt.json"
    assert not app.exists()
    assert not runtime.exists()
    assert (retained / "OntologyLab.app").is_dir()
    assert (retained / "runtime").is_dir()
