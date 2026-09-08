"""Vocabulary of the release-policy domain: types, refusal codes, JSON boundary parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, NoReturn, TypeAlias, assert_never

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
POLICY_PATH: Final = "release/release-policy.json"
LOCK_PATH: Final = "uv.lock"
VERSION_FILE: Final = "pyproject.toml"
TASK10_AUTHORITY_PATH: Final = (
    ".omo/evidence/mac-desktop-deployment-roadmap/task-10/"
    "verifier-st_01a061f5-20260902T115339Z/AdversarialVerify.json"
)
TASK10_AUTHORITY_SHA256: Final = (
    "948e5549beee5fea9a383c22b2af8a001935af013d34634e3cb0c75257568886"
)
TASK10_AUTHORITY_TASK_ID: Final = "st_01a061f5"
TASK10_AUTHORITY_PLAN: Final = "mac-desktop-deployment-roadmap"
ARCH: Final = "arm64"
ALIAS_RE: Final = re.compile(r"^[A-Z][A-Z0-9_]*$")
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
FROZEN_TEXT: Final = {
    "schema": "ontologylab.release-policy.v1",
    "product": "ontologylab",
    "distribution.channel": "internal-only",
    "distribution.delivery": "sha256-controlled-transfer",
    "platform.arch": ARCH,
    "platform.min_macos": "15.0",
    "signing.identity": "ad-hoc",
    "signing.direction": "inside-out",
    "updates.mechanism": "manual-immutable-replacement",
    "browser.preferred": "aside",
    "browser.fallback": "default-browser",
    "migration.scope": "canonical-application-support-only",
    "version_source.file": VERSION_FILE,
    "version_source.format": "semver",
}
FROZEN_FLAG: Final = {
    "distribution.public_release": False,
    "platform.intel": False,
    "platform.universal2": False,
    "signing.developer_id": False,
    "signing.notarization": False,
    "updates.automatic": False,
    "mcp.bundled": True,
    "mcp.external_python": False,
    "migration.auto_discovery": False,
}


@unique
class ReleasePolicyCode(StrEnum):
    """Typed refusal codes for the release eligibility gate."""

    POLICY_MISSING = "policy_missing"
    POLICY_MALFORMED = "policy_malformed"
    POLICY_INVALID = "policy_invalid"
    VERSION_SOURCE_MISSING = "version_source_missing"
    VERSION_INVALID = "version_invalid"
    QA_TARGET_MISSING = "qa_target_missing"
    QA_TARGET_INVALID = "qa_target_invalid"
    LOCK_MISSING = "lock_missing"
    LOCK_CHANGED = "lock_changed_after_snapshot"
    SOURCE_INPUT_MISSING = "source_input_missing"
    SOURCE_INPUT_UNSUPPORTED = "source_input_unsupported"
    SNAPSHOT_MISSING = "snapshot_missing"
    SNAPSHOT_MALFORMED = "snapshot_malformed"
    SOURCE_CHANGED = "source_changed_after_snapshot"
    POLICY_CHANGED = "policy_changed_after_snapshot"
    RECEIPT_MISSING = "eligibility_receipt_missing"
    RECEIPT_MALFORMED = "eligibility_receipt_malformed"
    RELEASE_NO_GO = "release_no_go"
    PRODUCTION_NOT_AUTHORIZED = "production_not_authorized"
    PRODUCTION_FLAG_NULL = "production_flag_null"
    STALE_SNAPSHOT_EVIDENCE = "stale_snapshot_evidence"
    VERSION_DRIFT = "version_drift"
    STAGED_CHANGES = "staged_changes"
    ELIGIBILITY_FIELD_DRIFT = "eligibility_field_drift"
    FIXTURE_DRIFT = "fixture_contract_drift"
    PROTOCOL_DRIFT = "benchmark_protocol_drift"
    TOOLCHAIN_DRIFT = "toolchain_identity_drift"
    PERFORMANCE_EVIDENCE_INVALID = "performance_evidence_invalid"
    MUTATION_RECEIPT_INVALID = "mutation_receipt_invalid"
    TASK10_AUTHORITY_MISSING = "task10_authority_missing"
    TASK10_AUTHORITY_MALFORMED = "task10_authority_malformed"
    TASK10_AUTHORITY_HASH_DRIFT = "task10_authority_hash_drift"
    TASK10_AUTHORITY_STALE = "task10_authority_stale"
    TASK10_AUTHORITY_UNCONFIRMED = "task10_authority_unconfirmed"


@dataclass(frozen=True, slots=True)
class ReleasePolicyRefused(Exception):
    """Typed refusal: a machine code plus the member that caused it."""

    code: ReleasePolicyCode
    member: str

    def __str__(self) -> str:
        return f"{self.code}:{self.member}"


@unique
class QaRole(StrEnum):
    """The two policy-required Apple Silicon QA target roles."""

    MACOS_15 = "macos-15"
    CURRENT_MAJOR = "current-major"


@dataclass(frozen=True, slots=True)
class QaTarget:
    """One policy-bound QA target reachable through a controlled alias."""

    role: QaRole
    arch: str
    alias: str
    os_major: int | str


@dataclass(frozen=True, slots=True)
class Task10Authority:
    """Exact independently confirmed Task10 verifier authority."""

    report_path: str
    report_sha256: str
    task: int
    plan: str
    task_id: str
    verdict: str


@dataclass(frozen=True, slots=True)
class ReleasePolicy:
    """Parsed release policy with every owner-approved decision frozen."""

    channel: str
    public_release: bool
    delivery: str
    arch: str
    min_macos: str
    signing_identity: str
    developer_id: bool
    notarization: bool
    updates_mechanism: str
    updates_automatic: bool
    browser_preferred: str
    browser_fallback: str
    mcp_bundled: bool
    mcp_external_python: bool
    migration_scope: str
    migration_auto_discovery: bool
    approval_owners: int
    approval_roles: tuple[str, ...]
    qa_targets: tuple[QaTarget, ...]
    source_inputs: tuple[str, ...]
    version_source_file: str
    snapshot_manifest_path: str
    eligibility_receipt_path: str
    fixture_manifest_path: str
    benchmark_protocol_path: str
    performance_evidence_path: str
    mutation_receipt_path: str
    task10_authority: Task10Authority


def refuse(code: ReleasePolicyCode, member: str) -> NoReturn:
    """Raise the typed refusal."""
    raise ReleasePolicyRefused(code=code, member=member)


def walk(raw: JsonValue, dotted: str, code: ReleasePolicyCode) -> JsonValue:
    """Descend a dotted object path or refuse with the path as member."""
    node = raw
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            refuse(code, dotted)
        node = node[part]
    return node


def as_object(
    value: JsonValue, member: str, code: ReleasePolicyCode
) -> dict[str, JsonValue]:
    """Narrow a JSON value to an object or refuse."""
    if not isinstance(value, dict):
        refuse(code, member)
    return value


def as_str(
    obj: dict[str, JsonValue],
    key: str,
    member: str,
    code: ReleasePolicyCode,
    *,
    expect: str | None = None,
) -> str:
    """Narrow a field to str, optionally to one expected value."""
    value = obj.get(key)
    if not isinstance(value, str) or (expect is not None and value != expect):
        refuse(code, member)
    return value


def rel_path(value: str, member: str) -> str:
    """Refuse absolute or parent-escaping policy paths."""
    if not value or value.startswith("/") or ".." in Path(value).parts:
        refuse(ReleasePolicyCode.POLICY_INVALID, member)
    return value


def read_json(
    root: Path, rel: str, missing: ReleasePolicyCode, bad: ReleasePolicyCode
) -> JsonValue:
    """Read a JSON file, refusing absence or malformation with typed codes."""
    path = root / rel
    if not path.is_file():
        refuse(missing, rel)
    try:
        parsed: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        refuse(bad, rel)
    return parsed


def path_field(raw: JsonValue, dotted: str) -> str:
    """Parse a dotted field as a root-relative path."""
    value = walk(raw, dotted, ReleasePolicyCode.POLICY_INVALID)
    if not isinstance(value, str):
        refuse(ReleasePolicyCode.POLICY_INVALID, dotted)
    return rel_path(value, dotted)


def str_tuple(raw: JsonValue, dotted: str) -> tuple[str, ...]:
    """Parse a dotted field as a deduplicated sorted string tuple."""
    listed = walk(raw, dotted, ReleasePolicyCode.POLICY_INVALID)
    if not isinstance(listed, list):
        refuse(ReleasePolicyCode.POLICY_INVALID, dotted)
    values: list[str] = []
    for item in listed:
        if not isinstance(item, str):
            refuse(ReleasePolicyCode.POLICY_INVALID, dotted)
        values.append(item)
    return tuple(sorted(set(values)))


def _os_major(obj: dict[str, JsonValue], role: QaRole) -> int | str:
    value = obj.get("os_major")
    match role:
        case QaRole.MACOS_15:
            if type(value) is int and value == 15:
                return value
        case QaRole.CURRENT_MAJOR:
            if isinstance(value, str) and value == "current":
                return value
        case unreachable:
            assert_never(unreachable)
    refuse(ReleasePolicyCode.QA_TARGET_INVALID, f"qa_targets.{role.value}.os_major")


def parse_qa_targets(raw: JsonValue) -> tuple[QaTarget, ...]:
    """Parse exactly one macos-15 and one current-major arm64 QA target."""
    code = ReleasePolicyCode.QA_TARGET_INVALID
    listed = walk(raw, "qa_targets", code)
    if not isinstance(listed, list):
        refuse(code, "qa_targets")
    targets: dict[QaRole, QaTarget] = {}
    for item in listed:
        obj = as_object(item, "qa_targets", code)
        try:
            role = QaRole(as_str(obj, "role", "qa_targets.role", code))
        except ValueError:
            refuse(code, "qa_targets.role")
        if role in targets:
            refuse(code, f"qa_targets.{role.value}")
        alias = as_str(obj, "alias", f"qa_targets.{role.value}.alias", code)
        if not ALIAS_RE.match(alias):
            refuse(code, f"qa_targets.{role.value}.alias")
        arch = as_str(obj, "arch", f"qa_targets.{role.value}.arch", code, expect=ARCH)
        targets[role] = QaTarget(role, arch, alias, _os_major(obj, role))
    for required in QaRole:
        if required not in targets:
            refuse(ReleasePolicyCode.QA_TARGET_MISSING, required.value)
    return tuple(targets[role] for role in QaRole)
