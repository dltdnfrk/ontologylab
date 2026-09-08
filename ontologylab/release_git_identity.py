"""Exact staged, unstaged, and status identity for dirty direct delivery."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ontologylab.release_policy_types import ReleasePolicyCode, refuse


@dataclass(frozen=True, slots=True)
class GitIdentity:
    """Content identity of git-visible state restricted to source inputs."""

    status_sha256: str
    staged_diff_sha256: str
    unstaged_diff_sha256: str


def _git(root: Path, args: tuple[str, ...], paths: tuple[str, ...]) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args, "--", *paths],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        refuse(ReleasePolicyCode.SOURCE_INPUT_UNSUPPORTED, "git-worktree")
    return result.stdout


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_git_identity(root: Path, source_inputs: tuple[str, ...]) -> GitIdentity:
    """Hash exact dirty status plus staged and unstaged binary diffs."""
    paths = tuple(sorted(source_inputs))
    return GitIdentity(
        status_sha256=_sha(
            _git(
                root,
                ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
                paths,
            )
        ),
        staged_diff_sha256=_sha(
            _git(root, ("diff", "--cached", "--binary", "--no-ext-diff"), paths)
        ),
        unstaged_diff_sha256=_sha(
            _git(root, ("diff", "--binary", "--no-ext-diff"), paths)
        ),
    )
