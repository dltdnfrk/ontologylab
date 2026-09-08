"""Exact manifest-derived source closure for Task 11 fixtures and staging."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ontologylab.release_policy import load_policy
from ontologylab.release_policy_types import POLICY_PATH
from ontologylab.release_snapshot import read_manifest, verify_manifest_identity
from ontologylab.release_source_exclusions import source_exclusion_reason

from .candidate_tree import sha256_file
from .candidate_types import CandidateRefused

_SKIP_DIRS: Final = frozenset({"__pycache__"})
_SKIP_FILES: Final = frozenset({".DS_Store"})
_SKIP_SUFFIXES: Final = (".pyc", ".pyo")


@dataclass(frozen=True, slots=True)
class ClosureEntry:
    """One exact file required by policy, manifest, or manifest retention."""

    path: str
    bytes: int
    sha256: str


def _declared(path: str, declared: tuple[str, ...]) -> bool:
    return any(path == item or path.startswith(f"{item}/") for item in declared)


def source_closure(root: Path) -> tuple[ClosureEntry, ...]:
    """Derive every exact input file from Task 1 policy and retained manifest."""
    policy = load_policy(root)
    manifest = read_manifest(root, policy)
    verify_manifest_identity(manifest)
    entries = {
        entry.path: ClosureEntry(entry.path, entry.bytes, entry.sha256)
        for entry in (manifest.uv_lock, *manifest.files)
    }
    policy_path = root / POLICY_PATH
    entries[POLICY_PATH] = ClosureEntry(
        POLICY_PATH, policy_path.stat().st_size, manifest.policy_sha256
    )
    manifest_path = root / policy.snapshot_manifest_path
    entries[policy.snapshot_manifest_path] = ClosureEntry(
        policy.snapshot_manifest_path,
        manifest_path.stat().st_size,
        sha256_file(manifest_path),
    )
    declared = policy.source_inputs
    for rel, entry in entries.items():
        if rel == policy.snapshot_manifest_path:
            continue
        if not _declared(rel, declared):
            raise CandidateRefused("source_closure_undeclared", entry.path)
    for item in declared:
        source = root / item
        if source.is_symlink() or not source.exists():
            raise CandidateRefused("source_closure_missing", item)
        if source.is_file() and item not in entries:
            raise CandidateRefused("source_closure_unbound", item)
        if source.is_dir() and not any(path.startswith(f"{item}/") for path in entries):
            raise CandidateRefused("source_closure_unbound", item)
    return tuple(entries[path] for path in sorted(entries))


def verify_source_closure(authority: Path, destination: Path) -> None:
    """Refuse missing, changed, or extra files in one disposable source closure."""
    expected = {entry.path: entry for entry in source_closure(authority)}
    actual = {
        path.relative_to(destination).as_posix(): path
        for path in destination.rglob("*")
        if path.is_file()
    }
    for rel in sorted(expected.keys() | actual.keys()):
        wanted = expected.get(rel)
        found = actual.get(rel)
        if wanted is None:
            raise CandidateRefused("source_closure_extra", rel)
        if found is None:
            raise CandidateRefused("source_closure_missing", rel)
        if found.is_symlink():
            raise CandidateRefused("source_closure_indirection", rel)
        if found.stat().st_size != wanted.bytes or sha256_file(found) != wanted.sha256:
            raise CandidateRefused("source_closure_changed", rel)


def copy_policy_inputs(authority: Path, destination: Path) -> None:
    """Materialize only policy-declared files so a disposable snapshot can mint."""
    if destination.exists() and any(destination.iterdir()):
        raise CandidateRefused("source_closure_destination", str(destination))
    destination.mkdir(parents=True, exist_ok=True)
    policy = load_policy(authority)
    files: set[Path] = set()
    for declared in policy.source_inputs:
        source = authority / declared
        if source.is_symlink() or not source.exists():
            raise CandidateRefused("source_closure_missing", declared)
        if source.is_file():
            files.add(source)
        else:
            for dirpath, dirnames, filenames in os.walk(source):
                dirnames[:] = sorted(
                    name
                    for name in dirnames
                    if name not in _SKIP_DIRS
                    and source_exclusion_reason(
                        (Path(dirpath) / name).relative_to(authority).as_posix()
                    )
                    is None
                )
                for name in sorted(filenames):
                    path = Path(dirpath) / name
                    relative = path.relative_to(authority).as_posix()
                    if (
                        name in _SKIP_FILES
                        or name.endswith(_SKIP_SUFFIXES)
                        or source_exclusion_reason(relative) is not None
                    ):
                        continue
                    if path.is_symlink():
                        raise CandidateRefused(
                            "source_closure_indirection",
                            path.relative_to(authority).as_posix(),
                        )
                    files.add(path)
    for source in sorted(files):
        target = destination / source.relative_to(authority)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def copy_source_closure(authority: Path, destination: Path) -> None:
    """Copy only manifest-bound files, then verify the exact closed set."""
    if destination.exists() and any(destination.iterdir()):
        raise CandidateRefused("source_closure_destination", str(destination))
    destination.mkdir(parents=True, exist_ok=True)
    for entry in source_closure(authority):
        source = authority / entry.path
        target = destination / entry.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    verify_source_closure(authority, destination)
