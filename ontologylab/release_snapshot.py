"""Immutable source-snapshot hashing: every build-input byte, including uv.lock."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Final

from ontologylab.release_git_identity import read_git_identity
from ontologylab.release_policy_types import (
    LOCK_PATH,
    POLICY_PATH,
    SHA256_RE,
    JsonValue,
    ReleasePolicy,
    ReleasePolicyCode,
    as_object,
    as_str,
    read_json,
    refuse,
    walk,
)
from ontologylab.release_source_exclusions import source_exclusion_reason

_SNAPSHOT_SCHEMA: Final = "ontologylab.release.source-snapshot.v1"
_SKIP_DIRS: Final = frozenset({"__pycache__"})
_SKIP_FILES: Final = frozenset({".DS_Store"})
_SKIP_SUFFIXES: Final = (".pyc", ".pyo")


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One hashed build-input file."""

    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """Immutable content-derived snapshot of every build input byte."""

    version: str
    policy_sha256: str
    uv_lock: FileEntry
    files: tuple[FileEntry, ...]
    inventory_sha256: str
    git_status_sha256: str
    git_staged_diff_sha256: str
    git_unstaged_diff_sha256: str
    snapshot_sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_inputs(root: Path, policy: ReleasePolicy) -> list[str]:
    rels: set[str] = set()
    for declared in policy.source_inputs:
        base = root / declared
        if base.is_symlink():
            refuse(ReleasePolicyCode.SOURCE_INPUT_UNSUPPORTED, declared)
        if base.is_file():
            rels.add(declared)
            continue
        if base.is_dir():
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(
                    name
                    for name in dirnames
                    if name not in _SKIP_DIRS
                    and source_exclusion_reason(
                        (Path(dirpath) / name).relative_to(root).as_posix()
                    ) is None
                )
                for name in sorted(filenames):
                    relative = (Path(dirpath) / name).relative_to(root).as_posix()
                    if name in _SKIP_FILES or name.endswith(_SKIP_SUFFIXES):
                        continue
                    rels.add(relative)
            continue
        if declared == LOCK_PATH:
            refuse(ReleasePolicyCode.LOCK_MISSING, LOCK_PATH)
        refuse(ReleasePolicyCode.SOURCE_INPUT_MISSING, declared)
    return sorted(rels)


def _manifest_payload(manifest: SnapshotManifest) -> dict[str, JsonValue]:
    return {
        "schema": _SNAPSHOT_SCHEMA,
        "version": manifest.version,
        "policy_sha256": manifest.policy_sha256,
        "uv_lock": asdict(manifest.uv_lock),
        "files": [asdict(entry) for entry in manifest.files],
        "inventory_sha256": manifest.inventory_sha256,
        "git_status_sha256": manifest.git_status_sha256,
        "git_staged_diff_sha256": manifest.git_staged_diff_sha256,
        "git_unstaged_diff_sha256": manifest.git_unstaged_diff_sha256,
    }


def _inventory_sha(lock: FileEntry, files: tuple[FileEntry, ...]) -> str:
    canonical = json.dumps(
        {"uv_lock": asdict(lock), "files": [asdict(entry) for entry in files]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _manifest_sha(manifest: SnapshotManifest) -> str:
    canonical = json.dumps(
        _manifest_payload(manifest), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_manifest_identity(manifest: SnapshotManifest) -> str:
    """Recompute and verify the content-derived identity stored by Task 1."""
    recomputed = _manifest_sha(manifest)
    if manifest.snapshot_sha256 != recomputed:
        refuse(ReleasePolicyCode.SNAPSHOT_MALFORMED, "snapshot_sha256")
    return recomputed


def hash_tree(root: Path, policy: ReleasePolicy, version: str) -> SnapshotManifest:
    """Hash every declared build input into a content-derived manifest."""
    entries: list[FileEntry] = []
    lock: FileEntry | None = None
    policy_sha256 = ""
    for rel in _iter_inputs(root, policy):
        path = root / rel
        if path.is_symlink():
            refuse(ReleasePolicyCode.SOURCE_INPUT_UNSUPPORTED, rel)
        entry = FileEntry(rel, _sha256_file(path), path.stat().st_size)
        if rel == LOCK_PATH:
            lock = entry
        elif rel == POLICY_PATH:
            policy_sha256 = entry.sha256
        else:
            entries.append(entry)
    if lock is None:
        refuse(ReleasePolicyCode.LOCK_MISSING, LOCK_PATH)
    files = tuple(entries)
    git = read_git_identity(root, policy.source_inputs)
    manifest = SnapshotManifest(
        version=version,
        policy_sha256=policy_sha256,
        uv_lock=lock,
        files=files,
        inventory_sha256=_inventory_sha(lock, files),
        git_status_sha256=git.status_sha256,
        git_staged_diff_sha256=git.staged_diff_sha256,
        git_unstaged_diff_sha256=git.unstaged_diff_sha256,
        snapshot_sha256="",
    )
    return replace(manifest, snapshot_sha256=_manifest_sha(manifest))


def write_snapshot(root: Path, policy: ReleasePolicy, version: str) -> SnapshotManifest:
    """Write the snapshot manifest; identity is content-only, no commit needed."""
    root = root.resolve()
    manifest = hash_tree(root, policy, version)
    payload = _manifest_payload(manifest)
    payload["snapshot_sha256"] = manifest.snapshot_sha256
    target = root / policy.snapshot_manifest_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _entry(value: JsonValue, member: str) -> FileEntry:
    code = ReleasePolicyCode.SNAPSHOT_MALFORMED
    obj = as_object(value, member, code)
    if set(obj) != {"path", "sha256", "bytes"}:
        refuse(code, member)
    path = as_str(obj, "path", f"{member}.path", code)
    if not path or path.startswith("/") or "\\" in path or ".." in Path(path).parts:
        refuse(code, f"{member}.path")
    sha256 = as_str(obj, "sha256", f"{member}.sha256", code)
    size = obj.get("bytes")
    if not SHA256_RE.match(sha256) or type(size) is not int or size < 0:
        refuse(code, member)
    return FileEntry(path, sha256, size)


def read_manifest(root: Path, policy: ReleasePolicy) -> SnapshotManifest:
    """Parse a written manifest; refuse absence, malformation, or unsafe entries."""
    code = ReleasePolicyCode.SNAPSHOT_MALFORMED
    raw = read_json(
        root, policy.snapshot_manifest_path, ReleasePolicyCode.SNAPSHOT_MISSING, code
    )
    obj = as_object(raw, policy.snapshot_manifest_path, code)
    expected_keys = {
        "schema",
        "version",
        "policy_sha256",
        "uv_lock",
        "files",
        "inventory_sha256",
        "git_status_sha256",
        "git_staged_diff_sha256",
        "git_unstaged_diff_sha256",
        "snapshot_sha256",
    }
    if set(obj) != expected_keys:
        refuse(code, policy.snapshot_manifest_path)
    as_str(obj, "schema", "schema", code, expect=_SNAPSHOT_SCHEMA)
    version = as_str(obj, "version", "version", code)
    policy_sha256 = as_str(obj, "policy_sha256", "policy_sha256", code)
    if not SHA256_RE.match(policy_sha256):
        refuse(code, "policy_sha256")
    lock = _entry(walk(raw, "uv_lock", code), "uv_lock")
    listed = walk(raw, "files", code)
    if not isinstance(listed, list):
        refuse(code, "files")
    files = tuple(_entry(item, f"files[{index}]") for index, item in enumerate(listed))
    hashes = {
        key: as_str(obj, key, key, code)
        for key in (
            "inventory_sha256",
            "git_status_sha256",
            "git_staged_diff_sha256",
            "git_unstaged_diff_sha256",
            "snapshot_sha256",
        )
    }
    for key, value in hashes.items():
        if not SHA256_RE.match(value):
            refuse(code, key)
    seen: set[str] = set()
    for entry in (lock, *files):
        if entry.path in seen:
            refuse(code, entry.path)
        seen.add(entry.path)
    return SnapshotManifest(
        version=version,
        policy_sha256=policy_sha256,
        uv_lock=lock,
        files=files,
        inventory_sha256=hashes["inventory_sha256"],
        git_status_sha256=hashes["git_status_sha256"],
        git_staged_diff_sha256=hashes["git_staged_diff_sha256"],
        git_unstaged_diff_sha256=hashes["git_unstaged_diff_sha256"],
        snapshot_sha256=hashes["snapshot_sha256"],
    )


def diff_manifest(expected: SnapshotManifest, actual: SnapshotManifest) -> None:
    """Refuse with the first typed drift between stored and recomputed manifests."""
    if actual.uv_lock != expected.uv_lock:
        refuse(ReleasePolicyCode.LOCK_CHANGED, LOCK_PATH)
    if actual.policy_sha256 != expected.policy_sha256:
        refuse(ReleasePolicyCode.POLICY_CHANGED, POLICY_PATH)
    wanted = {entry.path: entry for entry in expected.files}
    found = {entry.path: entry for entry in actual.files}
    for rel in sorted(wanted.keys() | found.keys()):
        if wanted.get(rel) != found.get(rel):
            refuse(ReleasePolicyCode.SOURCE_CHANGED, rel)
    if actual.inventory_sha256 != expected.inventory_sha256:
        refuse(ReleasePolicyCode.SOURCE_CHANGED, "source-input-inventory")
    if actual.git_status_sha256 != expected.git_status_sha256:
        refuse(ReleasePolicyCode.SOURCE_CHANGED, "git-status")
    if actual.git_staged_diff_sha256 != expected.git_staged_diff_sha256:
        refuse(ReleasePolicyCode.SOURCE_CHANGED, "git-staged-diff")
    if actual.git_unstaged_diff_sha256 != expected.git_unstaged_diff_sha256:
        refuse(ReleasePolicyCode.SOURCE_CHANGED, "git-unstaged-diff")
    if actual.snapshot_sha256 != expected.snapshot_sha256:
        refuse(ReleasePolicyCode.SNAPSHOT_MALFORMED, "snapshot_sha256")
