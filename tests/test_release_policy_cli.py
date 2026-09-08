"""CLI surface contract for `python -m ontologylab.release_policy`."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from ontologylab.release_policy import main
from ontologylab.release_policy_types import JsonValue, ReleasePolicyCode
from tests.test_release_policy import (
    MANIFEST_REL,
    REPO,
    _go_root,
    _mutate_lock,
    _mutate_policy_json,
    _mutate_source_byte,
    _mutate_stale_evidence,
    _pyproject_version,
    _receipt_flag,
)


def _mutate_no_go(root: Path) -> None:
    _receipt_flag(root, "go", False)


def _cli_refusal(root: Path, capsys) -> dict[str, JsonValue]:
    assert main(["check", "--root", str(root)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(root) not in captured.err
    refusal = json.loads(captured.err)
    assert refusal["schema"] == "ontologylab.release.refusal.v1"
    assert refusal["status"] == "refused"
    return refusal


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (_mutate_no_go, ReleasePolicyCode.RELEASE_NO_GO),
        (_mutate_policy_json, ReleasePolicyCode.POLICY_MALFORMED),
        (_mutate_stale_evidence, ReleasePolicyCode.STALE_SNAPSHOT_EVIDENCE),
        (_mutate_lock, ReleasePolicyCode.LOCK_CHANGED),
        (_mutate_source_byte, ReleasePolicyCode.SOURCE_CHANGED),
    ],
)
def test_cli_refusals_are_typed_silent_and_redacted(
    tmp_path: Path, capsys, mutate: Callable[[Path], None], code: ReleasePolicyCode
) -> None:
    root = _go_root(tmp_path)
    mutate(root)
    assert _cli_refusal(root, capsys)["code"] == code


def test_cli_acceptance_carries_exact_snapshot_policy_version(
    tmp_path: Path, capsys
) -> None:
    root = _go_root(tmp_path)
    assert main(["check", "--root", str(root)]) == 0
    acceptance = json.loads(capsys.readouterr().out)
    manifest = json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))
    assert acceptance["schema"] == "ontologylab.release.acceptance.v1"
    assert acceptance["status"] == "accepted"
    assert acceptance["snapshot_sha256"] == manifest["snapshot_sha256"]
    assert acceptance["policy_sha256"] == manifest["policy_sha256"]
    assert acceptance["version"] == _pyproject_version()
    assert set(acceptance["qa_targets"]) == {
        "MACOS15_QA_HOST",
        "MACOS_CURRENT_QA_HOST",
    }


def test_cli_snapshot_reports_exact_manifest_entry_count(
    tmp_path: Path, capsys
) -> None:
    # Given: one complete disposable release root.
    root = _go_root(tmp_path)

    # When: the production CLI remints its source snapshot.
    assert main(["snapshot", "--root", str(root)]) == 0
    emitted = json.loads(capsys.readouterr().out)
    manifest = json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))

    # Then: files counts every manifest entry exactly once, including uv.lock.
    assert emitted["files"] == len(manifest["files"]) + 1


def test_cli_version_receipt_derives_app_and_build_from_pyproject(capsys) -> None:
    assert main(["version", "--root", str(REPO)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["source"] == "pyproject.toml:project.version"
    assert receipt["app"]["CFBundleShortVersionString"] == _pyproject_version()
    assert receipt["app"]["CFBundleVersion"] == _pyproject_version()
    assert receipt["build"]["package_version"] == _pyproject_version()
