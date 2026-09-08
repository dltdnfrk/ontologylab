"""Canonical Task10 verifier binding for release eligibility."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ontologylab.release_policy import load_policy
from ontologylab.release_policy_types import JsonValue
from tests.release_eligibility_fixtures import mutate_receipt
from tests.test_release_policy import (
    REPO,
    _go_root,
    _policy_payload,
    _receipt_rel,
    _refusal,
    _write_json,
)


def test_checked_in_eligibility_binds_confirmed_task10_verifier() -> None:
    # Given: the canonical eligibility and independently confirmed Task10 report.
    policy = _policy_payload()
    receipt = json.loads((REPO / _receipt_rel()).read_text(encoding="utf-8"))
    authority = receipt["task10_authority"]
    report = REPO / authority["report_path"]

    # When/Then: eligibility carries the machine-consumed report identity and verdict.
    assert authority == policy["task10_authority"]
    assert hashlib.sha256(report.read_bytes()).hexdigest() == authority["report_sha256"]
    parsed = json.loads(report.read_text(encoding="utf-8"))
    assert parsed["task"] == 10
    assert parsed["task_id"] == authority["task_id"]
    assert parsed["verdict"] == "confirmed"


def test_task10_authority_refuses_missing_report_without_deletion(
    tmp_path: Path,
) -> None:
    # Given: a valid GO whose external report is moved to retained sibling evidence.
    root = _go_root(tmp_path)
    policy = load_policy(root)
    report = root / policy.task10_authority.report_path
    report.rename(report.with_suffix(".retained-missing"))

    # When/Then: canonical eligibility typed-refuses the absent authority.
    refusal = _refusal(root)
    assert str(refusal.code) == "task10_authority_missing"


@pytest.mark.parametrize(
    ("field", "value"),
    [("task", 13), ("task_id", "st_wrong"), ("schema", "wrong")],
)
def test_task10_authority_refuses_wrong_report_identity(
    tmp_path: Path, field: str, value: JsonValue
) -> None:
    root = _go_root(tmp_path)
    policy = load_policy(root)
    report = root / policy.task10_authority.report_path
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload[field] = value
    _write_json(root, policy.task10_authority.report_path, payload)

    refusal = _refusal(root)
    assert str(refusal.code) == "task10_authority_malformed"


def test_task10_authority_refuses_unconfirmed_verdict(tmp_path: Path) -> None:
    root = _go_root(tmp_path)
    policy = load_policy(root)
    report = root / policy.task10_authority.report_path
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["verdict"] = "needs-fix"
    _write_json(root, policy.task10_authority.report_path, payload)

    refusal = _refusal(root)
    assert str(refusal.code) == "task10_authority_unconfirmed"


def test_task10_authority_refuses_report_hash_drift(tmp_path: Path) -> None:
    root = _go_root(tmp_path)
    policy = load_policy(root)
    report = root / policy.task10_authority.report_path
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["unbound_change"] = True
    _write_json(root, policy.task10_authority.report_path, payload)

    refusal = _refusal(root)
    assert str(refusal.code) == "task10_authority_hash_drift"


def test_task10_authority_refuses_stale_claim_plan(tmp_path: Path) -> None:
    root = _go_root(tmp_path)
    mutate_receipt(
        root,
        lambda payload: payload["task10_authority"].update({"plan": "wrong-plan"}),
    )

    refusal = _refusal(root)
    assert str(refusal.code) == "task10_authority_stale"
