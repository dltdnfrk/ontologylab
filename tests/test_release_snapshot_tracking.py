"""The source snapshot may only pin files that are actually in the repository.

The gate once pinned three untracked `AGENTS.md` files. Every hash matched on
the machine that wrote them and the refusal it produced elsewhere named a
source change, so the failure read as tampering rather than as a file that
was never committed. On a clean clone the gate could not pass at all.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tracked_files() -> set[str]:
    listing = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(listing.stdout.splitlines())


def test_every_snapshot_member_is_tracked_by_git():
    # Given: the checked-in snapshot and git's own idea of the repository.
    snapshot = json.loads(
        (ROOT / "release" / "source-snapshot.json").read_text(encoding="utf-8")
    )
    tracked = _tracked_files()

    # When: each pinned member is looked up in the index.
    members = [entry["path"] for entry in snapshot["files"]]
    untracked = sorted(member for member in members if member not in tracked)

    # Then: nothing is pinned that a fresh clone would not receive.
    assert members, "snapshot pins no files at all"
    assert untracked == []
