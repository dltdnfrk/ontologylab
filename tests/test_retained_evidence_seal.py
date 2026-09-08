from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

_DOMAIN = b"ontologylab.retained-evidence-node.v1\0"


def _independent_lstat_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *files):
            path = current_path / name
            paths.add(path.relative_to(root).as_posix())
    return paths


def test_retained_evidence_seal_covers_independent_lstat_inventory_and_symlinks(
    tmp_path: Path,
) -> None:
    # Given files, directories, and internal/absolute/escaping symlink nodes.
    root = tmp_path / "retained"
    data = root / "directory/data.txt"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"retained-data")
    (root / "relative-file-link").symlink_to("directory/data.txt")
    (root / "relative-directory-link").symlink_to("directory", target_is_directory=True)
    (root / "escaping-link").symlink_to("../outside")
    (root / "absolute-link").symlink_to("/nonexistent/security-fixture")
    manifest = tmp_path / "retained-node-manifest.jsonl"

    # When the production node-seal CLI walks with lstat semantics.
    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "scripts.retained_evidence_seal",
            "--root",
            str(root),
            "--output",
            str(manifest),
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
    )

    # Then every independently enumerated node is sealed without dereferencing links.
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    indexed = {record["path"]: record for record in records}
    assert set(indexed) == _independent_lstat_paths(root)
    assert len(indexed) == 6
    assert sum(record["node_type"] == "symlink" for record in records) == 4
    assert indexed["relative-file-link"]["target_scope"] == "internal"
    assert indexed["relative-directory-link"]["target_scope"] == "internal"
    assert indexed["escaping-link"]["target_scope"] == "escaping"
    assert indexed["absolute-link"]["target_scope"] == "absolute"
    for name in (
        "relative-file-link",
        "relative-directory-link",
        "escaping-link",
        "absolute-link",
    ):
        record = indexed[name]
        target = os.fsencode(os.readlink(root / name))
        assert base64.b64decode(record["link_target_base64"]) == target
        assert stat.S_ISLNK(os.lstat(root / name).st_mode)
    for record in records:
        node_sha256 = record.pop("node_sha256")
        canonical = json.dumps(
            record, sort_keys=True, separators=(",", ":")
        ).encode()
        assert node_sha256 == hashlib.sha256(_DOMAIN + canonical).hexdigest()
