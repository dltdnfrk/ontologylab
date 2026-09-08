"""Deterministic Task 11 tree hashing and final mode normalization."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Final

from ontologylab.release_policy_types import JsonValue

from .candidate_types import CandidateRefused, TreeEntry

_NORMALIZED_SCHEMA: Final = "ontologylab.macos-candidate.normalized-tree.v1"
_SKIP_NAMES: Final = frozenset({".DS_Store", "__pycache__"})


def sha256_file(path: Path) -> str:
    """Hash one file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha(payload: JsonValue | dict[str, str | list[TreeEntry]]) -> str:
    """Hash one canonical JSON-compatible payload."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def write_json(
    path: Path, payload: JsonValue | dict[str, str | list[TreeEntry]]
) -> None:
    """Write stable pretty JSON for retained evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def tree_manifest(root: Path) -> list[TreeEntry]:
    """Hash payload bytes, relative paths, kinds, and delivered POSIX modes."""
    records: list[TreeEntry] = [
        {
            "path": ".",
            "kind": "directory",
            "bytes": 0,
            "mode": oct(stat.S_IMODE(root.stat().st_mode)),
            "sha256": "directory",
        }
    ]
    for path in sorted(root.rglob("*")):
        if any(part in _SKIP_NAMES for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            records.append(
                {
                    "path": rel,
                    "kind": "directory",
                    "bytes": 0,
                    "mode": oct(stat.S_IMODE(path.stat().st_mode)),
                    "sha256": "directory",
                }
            )
        elif path.is_file():
            records.append(
                {
                    "path": rel,
                    "kind": "file",
                    "bytes": path.stat().st_size,
                    "mode": oct(stat.S_IMODE(path.stat().st_mode)),
                    "sha256": sha256_file(path),
                }
            )
    return records


def normalized_tree_manifest(
    root: Path, variable_paths: frozenset[str]
) -> dict[str, str | list[TreeEntry]]:
    """Normalize native and ad-hoc-derived bytes while pinning every other byte."""
    files: list[TreeEntry] = []
    for record in tree_manifest(root):
        if record["path"] in variable_paths:
            files.append(
                {
                    "path": record["path"],
                    "kind": record["kind"],
                    "bytes": 0,
                    "mode": record["mode"],
                    "sha256": "unsigned-mach-o",
                }
            )
        else:
            files.append(record)
    return {"schema": _NORMALIZED_SCHEMA, "entries": files}


def verify_normalized_match(actual: Path, expected: Path) -> None:
    """Refuse any normalized payload drift, including one static asset byte."""
    if actual.read_bytes() != expected.read_bytes():
        raise CandidateRefused("normalized_manifest_drift", str(expected))


def freeze_tree(root: Path) -> None:
    """Set deterministic final read/execute modes without changing bytes."""
    for path in sorted(root.rglob("*"), reverse=True):
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir() or mode & 0o111:
            path.chmod(0o555)
        else:
            path.chmod(0o444)
    root.chmod(0o555)
