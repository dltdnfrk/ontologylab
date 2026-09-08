"""Task 1 source consumption and retained-manifest verification for candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ontologylab.release_policy import load_policy, read_version
from ontologylab.release_policy_types import (
    LOCK_PATH,
    POLICY_PATH,
    JsonValue,
    ReleasePolicyCode,
)
from ontologylab.release_snapshot import (
    SnapshotManifest,
    diff_manifest,
    hash_tree,
    read_manifest,
    verify_manifest_identity,
)

from .candidate_tree import sha256_file
from .candidate_types import CandidateRefused, SourceIdentity

_RETAINED_SOURCE: Final = Path("receipts/source")


def verify_source(root: Path) -> SourceIdentity:
    """Consume and re-hash an immutable Task 1 source snapshot."""
    root = root.resolve()
    policy = load_policy(root)
    manifest_path = root / policy.snapshot_manifest_path
    if manifest_path.is_symlink():
        raise CandidateRefused("snapshot_indirection", policy.snapshot_manifest_path)
    version = read_version(root, policy)
    manifest = read_manifest(root, policy)
    verify_manifest_identity(manifest)
    if manifest.version != version:
        from ontologylab.release_policy_types import refuse

        refuse(ReleasePolicyCode.VERSION_DRIFT, "snapshot.version")
    actual = hash_tree(root, policy, version)
    diff_manifest(manifest, actual)
    lock_path = root / LOCK_PATH
    policy_path = root / POLICY_PATH
    version_path = root / policy.version_source_file
    return SourceIdentity(
        version=version,
        snapshot_sha256=actual.snapshot_sha256,
        manifest_sha256=sha256_file(manifest_path),
        uv_lock_sha256=actual.uv_lock.sha256,
        policy_sha256=actual.policy_sha256,
        manifest_bytes=manifest_path.read_bytes(),
        uv_lock_bytes=lock_path.read_bytes(),
        policy_bytes=policy_path.read_bytes(),
        version_source_bytes=version_path.read_bytes(),
    )


def retain_source(candidate_root: Path, source: SourceIdentity) -> Path:
    """Retain exact Task 1 authority bytes under a standalone mirror root."""
    root = candidate_root / _RETAINED_SOURCE
    files = {
        Path("release/source-snapshot.json"): source.manifest_bytes,
        Path(POLICY_PATH): source.policy_bytes,
        Path(LOCK_PATH): source.uv_lock_bytes,
        Path("pyproject.toml"): source.version_source_bytes,
    }
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def _receipt_string(obj: dict[str, JsonValue], key: str, member: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise CandidateRefused("retained_receipt", member)
    return value


def _receipt_source(candidate_root: Path) -> tuple[str, str, str, str, str]:
    raw: JsonValue = json.loads(
        (candidate_root / "candidate-receipt.json").read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        raise CandidateRefused("retained_receipt", "root")
    source_value = raw.get("source")
    if not isinstance(source_value, dict):
        raise CandidateRefused("retained_receipt", "source")
    return (
        _receipt_string(raw, "version", "version"),
        _receipt_string(source_value, "snapshot_sha256", "source.snapshot_sha256"),
        _receipt_string(source_value, "manifest_sha256", "source.manifest_sha256"),
        _receipt_string(source_value, "uv_lock_sha256", "source.uv_lock_sha256"),
        _receipt_string(source_value, "policy_sha256", "source.policy_sha256"),
    )


def verify_retained_snapshot(
    candidate_root: Path, expected: SourceIdentity | None = None
) -> SnapshotManifest:
    """Use Task 1 parsing and canonical identity to verify retained authority bytes."""
    root = candidate_root / _RETAINED_SOURCE
    policy = load_policy(root)
    version = read_version(root, policy)
    manifest = read_manifest(root, policy)
    snapshot_sha256 = verify_manifest_identity(manifest)
    wanted = (
        (
            expected.version,
            expected.snapshot_sha256,
            expected.manifest_sha256,
            expected.uv_lock_sha256,
            expected.policy_sha256,
        )
        if expected is not None
        else _receipt_source(candidate_root)
    )
    actual = (
        version,
        snapshot_sha256,
        sha256_file(root / policy.snapshot_manifest_path),
        sha256_file(root / LOCK_PATH),
        sha256_file(root / POLICY_PATH),
    )
    members = (
        "version",
        "snapshot_sha256",
        "manifest_sha256",
        "uv_lock_sha256",
        "policy_sha256",
    )
    for member, actual_value, wanted_value in zip(members, actual, wanted, strict=True):
        if actual_value != wanted_value:
            raise CandidateRefused(f"retained_{member}", actual_value)
    return manifest
