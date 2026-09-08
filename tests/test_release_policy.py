"""Task 1 contract: release policy freeze, version source, snapshot, eligibility."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ontologylab.release_policy import check, load_policy, read_version
from ontologylab.release_policy_types import (
    JsonValue,
    QaRole,
    ReleasePolicyCode,
    ReleasePolicyRefused,
)
from ontologylab.release_snapshot import write_snapshot

REPO = Path(__file__).resolve().parents[1]
C = ReleasePolicyCode
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"
)
POLICY_REL = "release/release-policy.json"
MANIFEST_REL = "release/source-snapshot.json"


def _pyproject_version() -> str:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _policy_payload() -> dict[str, Any]:
    return json.loads((REPO / POLICY_REL).read_text(encoding="utf-8"))


def _receipt_rel() -> str:
    rel = _policy_payload()["eligibility_receipt_path"]
    assert isinstance(rel, str)
    return rel


def _write_json(root: Path, rel: str, payload: JsonValue) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _edit_json(root: Path, rel: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    payload = json.loads((root / rel).read_text(encoding="utf-8"))
    mutate(payload)
    _write_json(root, rel, payload)


def _go_root(tmp_path: Path) -> Path:
    """Build a disposable exact-dirty source-snapshot GO fixture tree."""
    from tests.release_eligibility_fixtures import bound_go_root

    return bound_go_root(tmp_path)


def _refusal(root: Path) -> ReleasePolicyRefused:
    with pytest.raises(ReleasePolicyRefused) as raised:
        check(root)
    return raised.value


def _mutate_source_byte(root: Path) -> None:
    target = root / "ontologylab" / "__init__.py"
    target.write_text(
        target.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8"
    )


def _mutate_added_file(root: Path) -> None:
    (root / "web" / "extra.js").write_text("// added\n", encoding="utf-8")


def _mutate_lock(root: Path) -> None:
    (root / "uv.lock").write_bytes(b"mutated-lock\n")


def _mutate_lock_missing(root: Path) -> None:
    (root / "uv.lock").unlink()


def _mutate_manifest_missing(root: Path) -> None:
    (root / MANIFEST_REL).unlink()


def _mutate_stale_evidence(root: Path) -> None:
    _edit_json(
        root, _receipt_rel(), lambda p: p.update({"source_snapshot_sha256": "0" * 64})
    )


def _launcher_manifest_entry(payload: dict[str, Any]) -> dict[str, Any]:
    return next(
        entry for entry in payload["files"] if entry["path"] == "launcher/README.md"
    )


def _mutate_manifest_entry(root: Path) -> None:
    _edit_json(
        root,
        MANIFEST_REL,
        lambda payload: _launcher_manifest_entry(payload).update({"sha256": "0" * 64}),
    )


def _mutate_receipt_version(root: Path) -> None:
    _edit_json(root, _receipt_rel(), lambda p: p.update({"version": "9.9.9"}))


def _receipt_flag(root: Path, key: str, value: JsonValue) -> None:
    _edit_json(root, _receipt_rel(), lambda p: p["release"].update({key: value}))


def _flag(key: str, value: JsonValue) -> Callable[[Path], None]:
    return lambda root: _receipt_flag(root, key, value)


def _mutate_qa_drop(root: Path) -> None:
    _edit_json(root, POLICY_REL, lambda p: p["qa_targets"].pop())


def _mutate_qa_null_alias(root: Path) -> None:
    _edit_json(root, POLICY_REL, lambda p: p["qa_targets"][0].update({"alias": None}))


def _mutate_policy_json(root: Path) -> None:
    (root / POLICY_REL).write_text("{not-json", encoding="utf-8")


def _mutate_policy_type(root: Path) -> None:
    _edit_json(root, POLICY_REL, lambda p: p["distribution"].update({"channel": 7}))


def _mutate_frozen_decision(root: Path) -> None:
    _edit_json(
        root, POLICY_REL, lambda p: p["signing"].update({"identity": "developer-id"})
    )


def _mutate_manifest_json(root: Path) -> None:
    (root / MANIFEST_REL).write_text("{not-json", encoding="utf-8")


def _mutate_manifest_sha(root: Path) -> None:
    _edit_json(root, MANIFEST_REL, lambda p: p.update({"snapshot_sha256": "xyz"}))


def _mutate_manifest_policy_sha(root: Path) -> None:
    _edit_json(root, MANIFEST_REL, lambda p: p.update({"policy_sha256": "0" * 8}))


def _mutate_manifest_lock(root: Path) -> None:
    _edit_json(root, MANIFEST_REL, lambda p: p.update({"uv_lock": {"path": "uv.lock"}}))


def _mutate_manifest_duplicate(root: Path) -> None:
    _edit_json(
        root,
        MANIFEST_REL,
        lambda payload: payload["files"].append(
            dict(_launcher_manifest_entry(payload))
        ),
    )


def _mutate_manifest_unsafe_path(root: Path) -> None:
    _edit_json(
        root, MANIFEST_REL, lambda p: p["files"][0].update({"path": "../escape"})
    )


@pytest.mark.parametrize(
    ("mutate", "code", "member"),
    [
        (_mutate_source_byte, C.SOURCE_CHANGED, "ontologylab/__init__.py"),
        (_mutate_added_file, C.SOURCE_CHANGED, "web/extra.js"),
        (_mutate_lock, C.LOCK_CHANGED, "uv.lock"),
        (_mutate_lock_missing, C.LOCK_MISSING, "uv.lock"),
        (_mutate_manifest_missing, C.SNAPSHOT_MISSING, MANIFEST_REL),
        (
            _mutate_stale_evidence,
            C.STALE_SNAPSHOT_EVIDENCE,
            "receipt.source_snapshot_sha256",
        ),
        (_mutate_manifest_entry, C.SOURCE_CHANGED, "launcher/README.md"),
        (_mutate_receipt_version, C.VERSION_DRIFT, "receipt.version"),
        (_flag("go", False), C.RELEASE_NO_GO, "release.go=false"),
        (
            _flag("production_authorized", False),
            C.PRODUCTION_NOT_AUTHORIZED,
            "release.production_authorized",
        ),
        (_flag("go", None), C.PRODUCTION_FLAG_NULL, "release.go"),
        (_mutate_qa_drop, C.QA_TARGET_MISSING, "current-major"),
        (_mutate_qa_null_alias, C.QA_TARGET_INVALID, "qa_targets.macos-15.alias"),
        (_mutate_policy_json, C.POLICY_MALFORMED, POLICY_REL),
        (_mutate_policy_type, C.POLICY_INVALID, "distribution.channel"),
        (_mutate_frozen_decision, C.POLICY_INVALID, "signing.identity"),
        (_mutate_manifest_json, C.SNAPSHOT_MALFORMED, MANIFEST_REL),
        (_mutate_manifest_sha, C.SNAPSHOT_MALFORMED, "snapshot_sha256"),
        (_mutate_manifest_policy_sha, C.SNAPSHOT_MALFORMED, "policy_sha256"),
        (_mutate_manifest_lock, C.SNAPSHOT_MALFORMED, "uv_lock"),
        (_mutate_manifest_duplicate, C.SNAPSHOT_MALFORMED, "launcher/README.md"),
        (_mutate_manifest_unsafe_path, C.SNAPSHOT_MALFORMED, "files[0].path"),
    ],
)
def test_check_refusal_matrix(
    tmp_path: Path,
    mutate: Callable[[Path], None],
    code: ReleasePolicyCode,
    member: str,
) -> None:
    root = _go_root(tmp_path)
    mutate(root)
    refusal = _refusal(root)
    assert refusal.code is code
    assert refusal.member == member


def test_shipped_policy_binds_frozen_decisions_and_qa_aliases() -> None:
    policy = load_policy(REPO)
    assert policy.channel == "internal-only" and policy.public_release is False
    assert policy.arch == "arm64" and policy.min_macos == "15.0"
    assert policy.signing_identity == "ad-hoc"
    assert policy.developer_id is False and policy.notarization is False
    assert policy.updates_automatic is False
    assert policy.browser_preferred == "aside"
    assert policy.browser_fallback == "default-browser"
    assert policy.mcp_bundled is True and policy.mcp_external_python is False
    assert policy.migration_scope == "canonical-application-support-only"
    assert policy.migration_auto_discovery is False
    assert policy.approval_owners == 1
    assert policy.delivery == "sha256-controlled-transfer"
    by_alias = {target.alias: target for target in policy.qa_targets}
    assert set(by_alias) == {"MACOS15_QA_HOST", "MACOS_CURRENT_QA_HOST"}
    assert by_alias["MACOS15_QA_HOST"].role is QaRole.MACOS_15
    assert by_alias["MACOS15_QA_HOST"].os_major == 15
    assert by_alias["MACOS_CURRENT_QA_HOST"].role is QaRole.CURRENT_MAJOR
    assert all(target.arch == "arm64" for target in policy.qa_targets)


def test_version_source_is_pyproject_semver() -> None:
    version = read_version(REPO, load_policy(REPO))
    assert version == _pyproject_version()
    assert SEMVER.match(version)


def test_check_accepts_the_checked_in_exact_source_go() -> None:
    acceptance = check(REPO)
    assert acceptance.version == _pyproject_version()
    assert len(acceptance.snapshot_sha256) == 64
    assert len(acceptance.policy_sha256) == 64


def test_snapshot_is_deterministic_and_binds_uv_lock(tmp_path: Path) -> None:
    root = _go_root(tmp_path)
    policy = load_policy(root)
    version = read_version(root, policy)
    first = write_snapshot(root, policy, version)
    second = write_snapshot(root, policy, version)
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert (
        first.uv_lock.sha256
        == hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()
    )
    assert all(entry.path != "uv.lock" for entry in first.files)


def test_check_refuses_status_drift_after_exact_dirty_capture(
    tmp_path: Path,
) -> None:
    root = _go_root(tmp_path)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    target = root / "ontologylab" / "__init__.py"
    target.write_text(target.read_text(encoding="utf-8") + "# staged later\n")
    subprocess.run(
        ["git", "-C", str(root), "add", "ontologylab/__init__.py"],
        check=True,
        env=env,
        capture_output=True,
    )
    assert _refusal(root).code is ReleasePolicyCode.SOURCE_CHANGED
