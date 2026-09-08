from __future__ import annotations

import hashlib
import json
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest

from ontologylab.release_policy_types import JsonValue
from scripts.internal_deployment_cli import main as deployment_main
from scripts.internal_deployment_fs import tree_sha256
from scripts.internal_deployment_types import PreparedRemovalJournal
from tests.test_internal_deployment_prepared_anchor import (
    PreparedFixture,
    _apply_arguments,
    _prepare_arguments,
    _prepared_fixture,
)

_DOMAIN = b"ontologylab.retained-uninstall.prepared.v1\0"


def _canonical(payload: dict[str, JsonValue]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _prepare(
    fixture: PreparedFixture, capsys: pytest.CaptureFixture[str]
) -> str:
    assert deployment_main(_prepare_arguments(fixture)) == 0
    return json.loads(capsys.readouterr().out)["prepared_anchor"]


def _forge_completed_state(fixture: PreparedFixture) -> None:
    app = fixture.retained / "OntologyLab.app"
    runtime = fixture.retained / "runtime"
    manifest = app / "Contents/Resources/internal-deployment.json"
    identity = json.loads(manifest.read_text(encoding="utf-8"))
    identity["version"] = "9.9.9"
    manifest.write_text(json.dumps(identity, sort_keys=True) + "\n", encoding="utf-8")
    (app / "Contents/Resources/forged").write_text("forged-app", encoding="utf-8")
    (runtime / "state").write_text("forged-runtime", encoding="utf-8")
    journal = fixture.retained / "retained-removal-journal.jsonl"
    prepared = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
    prepared["event_id"] = "f" * 32
    prepared["timestamp_utc"] = "2099-01-01T00:00:00+00:00"
    prepared["artifact"] = identity
    prepared["release_authority"]["version"] = "9.9.9"
    prepared["release_authority"]["final_app_tree_sha256"] = tree_sha256(app)
    prepared["release_authority_sha256"] = "e" * 64
    for name, tree in (("app", app), ("runtime", runtime)):
        info = tree.stat()
        prepared[name].update(
            {
                "device": info.st_dev,
                "inode": info.st_ino,
                "tree_sha256": tree_sha256(tree),
            }
        )
    prepared_bytes = PreparedRemovalJournal.model_validate(
        prepared, strict=True
    ).model_dump_json(by_alias=True).encode()
    lines = [prepared_bytes + b"\n"]
    for event in ("app_retained", "runtime_retained"):
        progress = {
            "event": event,
            "event_id": prepared["event_id"],
            "previous_sha256": hashlib.sha256(b"".join(lines)).hexdigest(),
            "schema": "ontologylab.retained-removal-journal.v3",
        }
        lines.append(_canonical(progress) + b"\n")
    journal_state_sha256 = hashlib.sha256(b"".join(lines)).hexdigest()
    forged_anchor = hashlib.sha256(_DOMAIN + lines[0][:-1]).hexdigest()
    receipt_path = fixture.retained / "retained-removal-receipt.json"
    receipt = {
        "app_tree_sha256": tree_sha256(app),
        "artifact": identity,
        "event": "retained_uninstall_completed",
        "event_id": prepared["event_id"],
        "journal_state_sha256": journal_state_sha256,
        "paths": [],
        "prepared_anchor": forged_anchor,
        "release_authority_sha256": prepared["release_authority_sha256"],
        "schema": "ontologylab.retained-removal-receipt.v2",
        "timestamp_utc": prepared["timestamp_utc"],
    }
    for name, tree, source in (
        ("app", app, fixture.app),
        ("runtime", runtime, fixture.runtime),
    ):
        bound = prepared[name]
        receipt["paths"].append(
            {
                "active_path_absent": True,
                "retained_device": bound["device"],
                "retained_inode": bound["inode"],
                "retained_mode": bound["mode"],
                "retained_path": bound["retained_path"],
                "retained_tree_sha256": bound["tree_sha256"],
                "source_device": bound["device"],
                "source_inode": bound["inode"],
                "source_mode": bound["mode"],
                "source_path": str(source),
                "source_tree_sha256": bound["tree_sha256"],
            }
        )
    receipt_path.write_bytes(_canonical(receipt) + b"\n")
    completed = {
        "event": "completed",
        "event_id": prepared["event_id"],
        "prepared_anchor": forged_anchor,
        "previous_sha256": journal_state_sha256,
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "release_authority_sha256": prepared["release_authority_sha256"],
        "schema": "ontologylab.retained-removal-journal.v3",
    }
    journal.write_bytes(b"".join(lines) + _canonical(completed) + b"\n")


def test_original_external_anchor_refuses_complete_coherent_local_forgery(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given completed trees and every local authority field coherently rewritten.
    fixture = _prepared_fixture(tmp_path)
    original_anchor = _prepare(fixture, capsys)
    assert deployment_main(_apply_arguments(fixture, original_anchor)) == 0
    capsys.readouterr()
    _forge_completed_state(fixture)
    before = (
        tree_sha256(fixture.retained / "OntologyLab.app"),
        tree_sha256(fixture.retained / "runtime"),
    )

    # When replay supplies the original controller-held value.
    result = deployment_main(_apply_arguments(fixture, original_anchor))

    # Then comparison with exact first-record bytes refuses before mutation.
    assert result == 2
    assert "prepared_anchor_mismatch" in capsys.readouterr().err
    assert before == (
        tree_sha256(fixture.retained / "OntologyLab.app"),
        tree_sha256(fixture.retained / "runtime"),
    )


@unique
class AnchorMutation(StrEnum):
    MISSING = "missing"
    MALFORMED = "malformed"
    WRONG = "wrong"
    SUBSTITUTED = "substituted"


@pytest.mark.parametrize("mutation", list(AnchorMutation))
def test_apply_refuses_untrusted_anchor_before_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutation: AnchorMutation,
) -> None:
    # Given one prepared transaction and one untrusted caller anchor form.
    fixture = _prepared_fixture(tmp_path / "victim")
    original = _prepare(fixture, capsys)
    match mutation:
        case AnchorMutation.MISSING:
            candidate = None
            reason = "prepared_anchor_required"
        case AnchorMutation.MALFORMED:
            candidate = "not-a-digest"
            reason = "prepared_anchor_malformed"
        case AnchorMutation.WRONG:
            candidate = "0" * 64 if original != "0" * 64 else "1" * 64
            reason = "prepared_anchor_mismatch"
        case AnchorMutation.SUBSTITUTED:
            other = _prepared_fixture(tmp_path / "other")
            candidate = _prepare(other, capsys)
            reason = "prepared_anchor_mismatch"
        case unreachable:
            assert_never(unreachable)
    arguments = _apply_arguments(fixture, candidate or "")
    if candidate is None:
        arguments = arguments[:-2]

    # When apply reaches the anchor boundary, then neither source is renamed.
    assert deployment_main(arguments) == 2
    assert reason in capsys.readouterr().err
    assert fixture.app.is_dir()
    assert fixture.runtime.is_dir()
    assert not (fixture.retained / "OntologyLab.app").exists()
