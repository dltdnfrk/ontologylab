"""Canonical policy and verifier checks for independently confirmed Task10 authority."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ontologylab.release_policy_types import (
    SHA256_RE,
    TASK10_AUTHORITY_PATH,
    TASK10_AUTHORITY_PLAN,
    TASK10_AUTHORITY_SHA256,
    TASK10_AUTHORITY_TASK_ID,
    JsonValue,
    ReleasePolicyCode,
    Task10Authority,
    as_object,
    as_str,
    read_json,
    refuse,
)


def parse_task10_authority(
    value: JsonValue,
    *,
    code: ReleasePolicyCode,
    member: str,
) -> Task10Authority:
    """Parse one exact Task10 authority object at a JSON trust boundary."""
    obj = as_object(value, member, code)
    keys = {"report_path", "report_sha256", "task", "plan", "task_id", "verdict"}
    if set(obj) != keys:
        refuse(code, member)
    report_path = as_str(obj, "report_path", f"{member}.report_path", code)
    report_sha256 = as_str(obj, "report_sha256", f"{member}.report_sha256", code)
    task = obj.get("task")
    plan = as_str(obj, "plan", f"{member}.plan", code)
    task_id = as_str(obj, "task_id", f"{member}.task_id", code)
    verdict = as_str(obj, "verdict", f"{member}.verdict", code)
    if type(task) is not int or not SHA256_RE.match(report_sha256):
        refuse(code, member)
    return Task10Authority(report_path, report_sha256, task, plan, task_id, verdict)


def parse_task10_policy(value: JsonValue) -> Task10Authority:
    """Parse and freeze the independently confirmed Task10 policy identity."""
    authority = parse_task10_authority(
        value,
        code=ReleasePolicyCode.POLICY_INVALID,
        member="task10_authority",
    )
    expected = Task10Authority(
        TASK10_AUTHORITY_PATH,
        TASK10_AUTHORITY_SHA256,
        10,
        TASK10_AUTHORITY_PLAN,
        TASK10_AUTHORITY_TASK_ID,
        "confirmed",
    )
    if authority != expected:
        refuse(ReleasePolicyCode.POLICY_INVALID, "task10_authority")
    return authority


def verify_task10_authority(
    root: Path,
    expected: Task10Authority,
    claimed: Task10Authority,
) -> None:
    """Rehash and validate the exact external Task10 verifier report."""
    if claimed != expected:
        refuse(ReleasePolicyCode.TASK10_AUTHORITY_STALE, "task10_authority")
    report = root / expected.report_path
    raw = read_json(
        root,
        expected.report_path,
        ReleasePolicyCode.TASK10_AUTHORITY_MISSING,
        ReleasePolicyCode.TASK10_AUTHORITY_MALFORMED,
    )
    obj = as_object(raw, expected.report_path, ReleasePolicyCode.TASK10_AUTHORITY_MALFORMED)
    task = obj.get("task")
    task_id = obj.get("task_id")
    schema = obj.get("schema")
    verdict = obj.get("verdict")
    path_parts = Path(expected.report_path).parts
    if (
        schema != "OntologyLab.AdversarialVerify.v1"
        or type(task) is not int
        or task != expected.task
        or task_id != expected.task_id
        or expected.plan not in path_parts
        or "task-10" not in path_parts
        or expected.task_id not in expected.report_path
    ):
        refuse(ReleasePolicyCode.TASK10_AUTHORITY_MALFORMED, "task10_authority")
    if verdict != expected.verdict:
        refuse(ReleasePolicyCode.TASK10_AUTHORITY_UNCONFIRMED, "task10_authority.verdict")
    actual_sha256 = hashlib.sha256(report.read_bytes()).hexdigest()
    if actual_sha256 != expected.report_sha256:
        refuse(ReleasePolicyCode.TASK10_AUTHORITY_HASH_DRIFT, "task10_authority.report_sha256")
