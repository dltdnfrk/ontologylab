"""Strict dynamic pack inventory and standalone verifier contracts."""
# noqa: SIZE_OK — single SUT contract matrix; Task 9 owns only this test file

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from ontologylab.pack_verifier import (
    JsonValue,
    ManifestV1,
    PackSchemaVersion,
    PackVerifyCode,
    PackVerifyRefused,
    parse_manifest,
    verify_pack,
)

_V1_TREE: Final = ("pack.sqlite", "schema.json", "provenance.jsonl")
_COUNT_KEYS: Final = (
    "works",
    "representations",
    "observations",
    "identifiers",
    "citations",
    "review_decisions",
    "extraction_runs",
    "extraction_chunks",
    "nodes",
    "edges",
    "nodes_verified",
    "edges_verified",
)
_TABLES: Final = (
    ("works", "works"),
    ("documents", "representations"),
    ("observations", "observations"),
    ("work_identifiers", "identifiers"),
    ("citations", "citations"),
    ("review_decisions", "review_decisions"),
    ("extraction_runs", "extraction_runs"),
    ("extraction_chunks", "extraction_chunks"),
    ("nodes", "nodes"),
    ("edges", "edges"),
)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_inventory(entries: list[dict[str, int | str]]) -> str:
    return json.dumps(entries, sort_keys=True, separators=(",", ":"))


def _v1_tree_hash(pack_dir: Path) -> str:
    hasher = hashlib.sha256()
    for name in _V1_TREE:
        path = pack_dir / name
        data = path.read_bytes() if path.is_file() else b""
        hasher.update(name.encode())
        hasher.update(b"\0")
        hasher.update(hashlib.sha256(data).hexdigest().encode())
        hasher.update(b"\n")
    return "sha256:" + hasher.hexdigest()


def _write_ro(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o444)


def _write_v1(root: Path, pack_id: str, *, tree_hash: bool) -> Path:
    pack_dir = root / pack_id
    pack_dir.mkdir()
    sqlite_bytes = b"v1-sqlite-payload"
    (pack_dir / "pack.sqlite").write_bytes(sqlite_bytes)
    (pack_dir / "schema.json").write_text("{}", encoding="utf-8")
    (pack_dir / "provenance.jsonl").write_text("{}\n", encoding="utf-8")
    manifest: dict[str, object] = {  # noqa: OBJECT_OK
        "pack_id": pack_id,
        "capabilities": ["knowledge-graph-v1"],
        "content_hash": _digest(sqlite_bytes),
        "counts": {"nodes": 0},
    }
    if tree_hash:
        manifest["tree_hash"] = _v1_tree_hash(pack_dir)
    (pack_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return pack_dir


def _seed_sqlite(path: Path, *, nodes: int) -> None:
    connection = sqlite3.connect(str(path))
    try:
        for table, _key in _TABLES:
            connection.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)")
        for index in range(nodes):
            connection.execute("INSERT INTO nodes VALUES (?)", (f"n{index}",))
        connection.commit()
    finally:
        connection.close()


def _inventory_entry(rel: str, data: bytes, mode: int) -> dict[str, int | str]:
    return {
        "file_type": "regular",
        "mode": mode,
        "path": rel,
        "sha256": _digest(data),
        "size": len(data),
    }


def _write_v2(
    root: Path,
    pack_id: str,
    *,
    nodes: int = 1,
    extra_files: dict[str, bytes] | None = None,
    counts: dict[str, int] | None = None,
    pack_content_hash: str | None = None,
    sqlite_hash: str | None = None,
    inventory: list[dict[str, int | str]] | None = None,
    include_manifest_in_inventory: bool = False,
) -> Path:
    pack_dir = root / pack_id
    pack_dir.mkdir()
    sqlite_path = pack_dir / "pack.sqlite"
    _seed_sqlite(sqlite_path, nodes=nodes)
    files: dict[str, bytes] = {
        "schema.json": b'{"schema_version_id":1}',
        "provenance.jsonl": b'{"step":"build"}\n',
        "evidence/rep-1/full.txt": b"FULL-TEXT-REP-1\n",
    }
    if extra_files:
        files.update(extra_files)
    for rel, data in files.items():
        _write_ro(pack_dir / rel, data)
    sqlite_path.chmod(0o444)
    sqlite_bytes = sqlite_path.read_bytes()
    files_with_sqlite = {"pack.sqlite": sqlite_bytes, **files}
    derived: list[dict[str, int | str]] = []
    for rel in sorted(files_with_sqlite):
        mode = stat.S_IMODE((pack_dir / rel).stat().st_mode)
        derived.append(_inventory_entry(rel, files_with_sqlite[rel], mode))
    claimed = list(inventory) if inventory is not None else derived
    if include_manifest_in_inventory:
        claimed.append(_inventory_entry("manifest.json", b"{}", 0o444))
    derived_counts = {key: 0 for key in _COUNT_KEYS}
    derived_counts["nodes"] = nodes
    manifest = {
        "pack_id": pack_id,
        "pack_schema_version": 2,
        "capabilities": ["knowledge-graph-v2", "evidence-self-contained-v2"],
        "integrity_model": "sha256-receipt-not-signature",
        "sqlite_hash": sqlite_hash or _digest(sqlite_bytes),
        "artifact_inventory": claimed,
        "pack_content_hash": pack_content_hash
        or _digest(_canonical_inventory(claimed).encode()),
        "counts": counts or derived_counts,
        "exclusions": {
            "ungrounded": 0,
            "waived": 0,
            "invalid_legacy_evidence": 0,
            "identity_conflicts": 0,
        },
    }
    manifest_path = pack_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    manifest_path.chmod(0o444)
    return pack_dir


def _refuse_code(pack_dir: Path, **kwargs: Path | None) -> PackVerifyCode:
    working = kwargs.get("working")
    with pytest.raises(PackVerifyRefused) as raised:
        verify_pack(pack_dir, working=working)
    return raised.value.code


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ontologylab.pack_verifier", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_v2_rejects_sqlite_uri_metacharacters_in_pack_id(
    tmp_path: Path,
) -> None:
    # Given a pack whose name can alter a raw SQLite file: URI
    claimed_counts = {key: 0 for key in _COUNT_KEYS}
    claimed_counts["nodes"] = 1
    pack_dir = _write_v2(
        tmp_path,
        "evil?immutable=1",
        nodes=2,
        counts=claimed_counts,
    )
    _seed_sqlite(tmp_path / "evil", nodes=1)

    # When the standalone boundary verifies the pack
    code = _refuse_code(pack_dir)

    # Then the unsafe pack id is rejected before SQLite opens any database
    assert code is PackVerifyCode.INVALID_MANIFEST


def test_v2_encodes_sqlite_uri_when_parent_path_contains_query_marker(
    tmp_path: Path,
) -> None:
    # Given a safe pack id below an unsafe-looking parent and a sibling decoy DB
    claimed_counts = {key: 0 for key in _COUNT_KEYS}
    claimed_counts["nodes"] = 1
    _seed_sqlite(tmp_path / "parent", nodes=1)
    root = tmp_path / "parent?immutable=1"
    root.mkdir()
    pack_dir = _write_v2(
        root,
        "safe-pack",
        nodes=2,
        counts=claimed_counts,
    )

    # When the verifier derives counts
    code = _refuse_code(pack_dir)

    # Then it reads the physical pack.sqlite, not the sibling decoy
    assert code is PackVerifyCode.FORGED_COUNTS


def test_legacy_v1_with_tree_hash_verifies(tmp_path: Path) -> None:
    # Given a current-style v1 pack with tree_hash
    pack_dir = _write_v1(tmp_path, "legacy-tree", tree_hash=True)
    # When the standalone verifier runs
    receipt = verify_pack(pack_dir)
    # Then v1 compatibility admits it as legacy-graph-only
    assert receipt.pack_schema_version is PackSchemaVersion.V1
    assert receipt.integrity_level == "legacy-graph-only"
    assert receipt.pack_content_hash == _digest((pack_dir / "pack.sqlite").read_bytes())


def test_legacy_v1_without_tree_hash_verifies(tmp_path: Path) -> None:
    pack_dir = _write_v1(tmp_path, "legacy-plain", tree_hash=False)
    receipt = verify_pack(pack_dir)
    assert receipt.pack_schema_version is PackSchemaVersion.V1
    assert receipt.integrity_level == "legacy-graph-only"


def test_legacy_v1_writable_and_extra_file_still_verifies(tmp_path: Path) -> None:
    pack_dir = _write_v1(tmp_path, "legacy-loose", tree_hash=True)
    (pack_dir / "notes.txt").write_text("extra", encoding="utf-8")
    (pack_dir / "pack.sqlite").chmod(0o644)
    (pack_dir / "manifest.json").chmod(0o644)
    receipt = verify_pack(pack_dir)
    assert receipt.pack_id == "legacy-loose"


def test_legacy_v1_tampered_sqlite_is_refused(tmp_path: Path) -> None:
    pack_dir = _write_v1(tmp_path, "legacy-tamper", tree_hash=True)
    sqlite_path = pack_dir / "pack.sqlite"
    sqlite_path.write_bytes(sqlite_path.read_bytes() + b"x")
    assert _refuse_code(pack_dir) is PackVerifyCode.TAMPERED_ARTIFACT


def test_legacy_v1_tampered_payload_tree_hash_is_refused(tmp_path: Path) -> None:
    pack_dir = _write_v1(tmp_path, "legacy-schema", tree_hash=True)
    (pack_dir / "schema.json").write_text('{"injected":true}', encoding="utf-8")
    assert _refuse_code(pack_dir) is PackVerifyCode.TAMPERED_ARTIFACT


_V1_SHA: Final = "sha256:" + ("ab" * 32)
_V2_ONLY_FIELDS: Final = (
    "artifact_inventory",
    "pack_content_hash",
    "sqlite_hash",
    "integrity_model",
    "evidence_mode",
    "closure",
    "receipt_inventory",
    "receipt_inventory_root",
    "source_fingerprint",
    "source_fingerprint_entries",
)


def _v1_manifest(**fields: JsonValue) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "pack_id": "legacy-parse",
        "content_hash": _V1_SHA,
    }
    payload.update(fields)
    return payload


def _parse_v1_ok(**fields: JsonValue) -> ManifestV1:
    parsed = parse_manifest(_v1_manifest(**fields))
    assert isinstance(parsed, ManifestV1)
    return parsed


def _parse_v1_path(**fields: JsonValue) -> str | None:
    with pytest.raises(PackVerifyRefused) as raised:
        parse_manifest(_v1_manifest(**fields))
    assert raised.value.code is PackVerifyCode.INVALID_MANIFEST
    return raised.value.path


@pytest.mark.parametrize(
    "fields",
    (
        {},
        {"capabilities": []},
        {"capabilities": ["knowledge-graph-v1"]},
        {"capabilities": ["knowledge-graph-v1", "methodology-v1"]},
        {"pack_schema_version": 1, "capabilities": ["knowledge-graph-v1"]},
    ),
    ids=(
        "historical-absent",
        "empty",
        "graph-only",
        "graph-and-methodology",
        "explicit-schema-1",
    ),
)
def test_parse_v1_accepts_historical_and_builder_capabilities(
    fields: dict[str, JsonValue],
) -> None:
    # Given a legitimate historical or builder v1 capability shape
    # When parse_manifest runs
    # Then the typed v1 manifest is accepted
    assert _parse_v1_ok(**fields).pack_id == "legacy-parse"


@pytest.mark.parametrize(
    "capabilities",
    (
        ["admin-override"],
        ["knowledge-graph-v1", "admin-override"],
        ["reviewed"],
        ["sourced-answer-v2"],
        ["knowledge-graph-v2"],
        ["evidence-self-contained-v2"],
        ["knowledge-graph-v1", "reviewed"],
        ["methodology-v1"],
        ["methodology-v1", "knowledge-graph-v1"],
        ["knowledge-graph-v1", "knowledge-graph-v1"],
        ["knowledge-graph-v1", "methodology-v1", "knowledge-graph-v1"],
        "knowledge-graph-v1",
        {"cap": "knowledge-graph-v1"},
        [1],
    ),
    ids=(
        "unknown",
        "unknown-after-v1",
        "reviewed",
        "sourced",
        "knowledge-graph-v2",
        "evidence-self-contained-v2",
        "reviewed-after-v1",
        "methodology-without-graph",
        "methodology-before-graph",
        "duplicate-graph",
        "duplicate-after-methodology",
        "string-shape",
        "object-shape",
        "non-string-item",
    ),
)
def test_parse_v1_rejects_capability_outside_allowlist(
    capabilities: JsonValue,
) -> None:
    # Given a v1-shaped manifest whose capabilities leave the historical allowlist
    # When parse_manifest runs
    # Then the typed capabilities path is refused
    assert _parse_v1_path(capabilities=capabilities) == "capabilities"


@pytest.mark.parametrize("field", _V2_ONLY_FIELDS)
def test_parse_v1_rejects_v2_contract_field(field: str) -> None:
    # Given a v1-shaped manifest that still carries a v2-only contract field
    # When parse_manifest runs
    # Then that field is refused and is not treated as legacy
    assert _parse_v1_path(**{field: []}) == field


def test_parse_v1_omitted_schema_rejects_v2_capabilities() -> None:
    # Given omitted pack_schema_version and raw v2 authority strings
    raw = _v1_manifest(
        capabilities=[
            "knowledge-graph-v2",
            "evidence-self-contained-v2",
            "reviewed",
            "sourced-answer-v2",
        ],
    )
    assert "pack_schema_version" not in raw
    # When parse_manifest defaults the omitted schema to v1
    with pytest.raises(PackVerifyRefused) as raised:
        parse_manifest(raw)
    # Then the v2 labels cannot enter the typed v1 value
    assert raised.value.code is PackVerifyCode.INVALID_MANIFEST
    assert raised.value.path == "capabilities"


def test_legacy_v1_without_capabilities_verifies(tmp_path: Path) -> None:
    pack_dir = _write_v1(tmp_path, "legacy-nocap", tree_hash=True)
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    del payload["capabilities"]
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    receipt = verify_pack(pack_dir)
    assert receipt.pack_schema_version is PackSchemaVersion.V1
    assert receipt.integrity_level == "legacy-graph-only"


def test_legacy_v1_with_methodology_capability_verifies(tmp_path: Path) -> None:
    pack_dir = _write_v1(tmp_path, "legacy-method", tree_hash=False)
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["capabilities"] = ["knowledge-graph-v1", "methodology-v1"]
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    receipt = verify_pack(pack_dir)
    assert receipt.pack_id == "legacy-method"
    assert receipt.integrity_level == "legacy-graph-only"


def test_legacy_v1_unknown_capability_is_refused(tmp_path: Path) -> None:
    pack_dir = _write_v1(tmp_path, "legacy-unknown", tree_hash=True)
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["capabilities"] = ["knowledge-graph-v1", "admin-override"]
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(PackVerifyRefused) as raised:
        verify_pack(pack_dir)
    assert raised.value.code is PackVerifyCode.INVALID_MANIFEST
    assert raised.value.path == "capabilities"


def test_legacy_v1_reviewed_capability_is_refused(tmp_path: Path) -> None:
    pack_dir = _write_v1(tmp_path, "legacy-reviewed", tree_hash=True)
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["capabilities"] = [
        "knowledge-graph-v2",
        "evidence-self-contained-v2",
        "reviewed",
        "sourced-answer-v2",
    ]
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(PackVerifyRefused) as raised:
        verify_pack(pack_dir)
    assert raised.value.code is PackVerifyCode.INVALID_MANIFEST
    assert raised.value.path == "capabilities"


def test_legacy_v1_v2_contract_field_is_refused(tmp_path: Path) -> None:
    pack_dir = _write_v1(tmp_path, "legacy-inventory", tree_hash=True)
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifact_inventory"] = []
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(PackVerifyRefused) as raised:
        verify_pack(pack_dir)
    assert raised.value.code is PackVerifyCode.INVALID_MANIFEST
    assert raised.value.path == "artifact_inventory"


def test_accepts_valid_v2_dynamic_inventory(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-ok")
    receipt = verify_pack(pack_dir)
    assert receipt.pack_id == "pack-ok"
    assert receipt.pack_schema_version is PackSchemaVersion.V2
    assert receipt.integrity_level == "evidence-self-contained-v2"
    assert receipt.counts["nodes"] == 1
    assert receipt.counts["edges"] == 0
    paths = [entry.path for entry in receipt.inventory]
    assert paths == sorted(paths)
    assert "manifest.json" not in paths
    assert "evidence/rep-1/full.txt" in paths
    assert "pack.sqlite" in paths
    for entry in receipt.inventory:
        assert entry.file_type == "regular"
        assert entry.mode == 0o444
        assert entry.nlink == 1


def test_inventory_is_sorted_and_excludes_manifest(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-sort")
    receipt = verify_pack(pack_dir)
    claimed = [
        {
            "file_type": entry.file_type,
            "mode": entry.mode,
            "path": entry.path,
            "sha256": entry.sha256,
            "size": entry.size,
        }
        for entry in receipt.inventory
    ]
    assert receipt.pack_content_hash == _digest(_canonical_inventory(claimed).encode())
    assert receipt.sqlite_hash == _digest((pack_dir / "pack.sqlite").read_bytes())


def test_parse_manifest_v2_is_typed_boundary(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-parse")
    raw = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    parsed = parse_manifest(raw)
    assert parsed.pack_id == "pack-parse"
    raw["artifact_inventory"] = "not-a-list"
    with pytest.raises(PackVerifyRefused) as raised:
        parse_manifest(raw)
    assert raised.value.code is PackVerifyCode.INVALID_MANIFEST


def test_refuses_missing_artifact(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-missing")
    (pack_dir / "schema.json").unlink()
    assert _refuse_code(pack_dir) is PackVerifyCode.MISSING_ARTIFACT


def test_refuses_missing_nested_evidence(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-missing-ev")
    (pack_dir / "evidence" / "rep-1" / "full.txt").unlink()
    assert _refuse_code(pack_dir) is PackVerifyCode.MISSING_ARTIFACT


def test_refuses_extra_payload_artifact(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-extra")
    _write_ro(pack_dir / "notes.txt", b"bonus")
    assert _refuse_code(pack_dir) is PackVerifyCode.EXTRA_ARTIFACT


def test_refuses_tampered_nested_evidence(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-tamper-ev")
    target = pack_dir / "evidence" / "rep-1" / "full.txt"
    target.chmod(0o644)
    target.write_bytes(b"TAMPERED-EVIDENCE\n")
    target.chmod(0o444)
    assert _refuse_code(pack_dir) is PackVerifyCode.TAMPERED_ARTIFACT


def test_refuses_root_only_pack_content_hash(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-root-hash")
    root_only = _digest((pack_dir / "pack.sqlite").read_bytes())
    manifest_path = pack_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pack_content_hash"] = root_only
    manifest_path.chmod(0o644)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o444)
    assert _refuse_code(pack_dir) is PackVerifyCode.FORGED_HASH


def test_refuses_writable_0644(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-mode")
    (pack_dir / "schema.json").chmod(0o644)
    assert _refuse_code(pack_dir) is PackVerifyCode.WRITABLE


def test_refuses_symlink(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-link")
    os.symlink("pack.sqlite", pack_dir / "alias.sqlite")
    assert _refuse_code(pack_dir) is PackVerifyCode.SYMLINK


def test_refuses_hardlink(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-nlink")
    os.link(pack_dir / "pack.sqlite", pack_dir / "dup.sqlite")
    assert _refuse_code(pack_dir) is PackVerifyCode.HARDLINK


def test_refuses_writable_v2_manifest_0644(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-man-mode")
    (pack_dir / "manifest.json").chmod(0o644)
    assert _refuse_code(pack_dir) is PackVerifyCode.WRITABLE


def test_refuses_hardlinked_v2_manifest(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-man-nlink")
    os.link(pack_dir / "manifest.json", tmp_path / "manifest.outside")
    assert _refuse_code(pack_dir) is PackVerifyCode.HARDLINK


def test_refuses_symlinked_v2_manifest_before_bytes(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-man-sym")
    real = pack_dir / "manifest.json"
    outside = tmp_path / "forged-manifest.json"
    outside.write_text(real.read_text(encoding="utf-8"), encoding="utf-8")
    real.unlink()
    os.symlink(outside, real)
    outside.unlink()
    assert _refuse_code(pack_dir) is PackVerifyCode.SYMLINK


def test_refuses_absolute_inventory_path(tmp_path: Path) -> None:
    abs_path = str(tmp_path / "outside.txt")
    inventory = [
        _inventory_entry("pack.sqlite", b"x", 0o444),
        {
            "file_type": "regular",
            "mode": 0o444,
            "path": abs_path,
            "sha256": _digest(b"x"),
            "size": 1,
        },
    ]
    pack_dir = _write_v2(tmp_path, "pack-abs", inventory=inventory)
    assert _refuse_code(pack_dir) is PackVerifyCode.PATH_MISMATCH


def test_refuses_traversal_inventory_path(tmp_path: Path) -> None:
    inventory = [
        {
            "file_type": "regular",
            "mode": 0o444,
            "path": "../escape.txt",
            "sha256": _digest(b"x"),
            "size": 1,
        }
    ]
    pack_dir = _write_v2(tmp_path, "pack-trav", inventory=inventory)
    assert _refuse_code(pack_dir) is PackVerifyCode.PATH_MISMATCH


def test_refuses_path_mismatch_when_pack_dir_disagrees(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-named")
    renamed = tmp_path / "renamed-dir"
    pack_dir.rename(renamed)
    assert _refuse_code(renamed) is PackVerifyCode.PATH_MISMATCH


def test_refuses_original_working_inode(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-inode")
    assert (
        _refuse_code(pack_dir, working=pack_dir / "pack.sqlite")
        is PackVerifyCode.ORIGINAL_INODE
    )


def test_accepts_v2_when_working_store_is_distinct(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-distinct")
    working = tmp_path / "kg.sqlite"
    working.write_bytes(b"live-working-store-bytes")
    receipt = verify_pack(pack_dir, working=working)
    assert receipt.pack_id == "pack-distinct"
    assert receipt.sqlite_hash != _digest(b"live-working-store-bytes")


def test_refuses_forged_manifest_counts(tmp_path: Path) -> None:
    forged = {key: 0 for key in _COUNT_KEYS}
    forged["nodes"] = 7
    pack_dir = _write_v2(tmp_path, "pack-counts", counts=forged)
    assert _refuse_code(pack_dir) is PackVerifyCode.FORGED_COUNTS


def test_refuses_forged_pack_content_hash(tmp_path: Path) -> None:
    pack_dir = _write_v2(
        tmp_path,
        "pack-pch",
        pack_content_hash="sha256:" + ("ab" * 32),
    )
    assert _refuse_code(pack_dir) is PackVerifyCode.FORGED_HASH


def test_refuses_forged_sqlite_hash(tmp_path: Path) -> None:
    pack_dir = _write_v2(
        tmp_path,
        "pack-sqlh",
        sqlite_hash="sha256:" + ("cd" * 32),
    )
    assert _refuse_code(pack_dir) is PackVerifyCode.FORGED_HASH


def test_refuses_manifest_self_reference(tmp_path: Path) -> None:
    pack_dir = _write_v2(
        tmp_path, "pack-self", include_manifest_in_inventory=True
    )
    assert _refuse_code(pack_dir) is PackVerifyCode.SELF_REFERENCE


def test_cli_emits_deterministic_ok_json(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-cli")
    first = _run_cli(str(pack_dir))
    second = _run_cli(str(pack_dir))
    assert first.returncode == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["ok"] is True
    assert payload["pack_id"] == "pack-cli"
    assert payload["pack_schema_version"] == 2
    assert payload["integrity_level"] == "evidence-self-contained-v2"
    assert payload["counts"]["nodes"] == 1
    paths = [entry["path"] for entry in payload["inventory"]]
    assert paths == sorted(paths)
    assert "manifest.json" not in paths


def test_cli_refuses_tamper_with_typed_code(tmp_path: Path) -> None:
    pack_dir = _write_v2(tmp_path, "pack-cli-bad")
    target = pack_dir / "evidence" / "rep-1" / "full.txt"
    target.chmod(0o644)
    target.write_bytes(b"nope")
    target.chmod(0o444)
    result = _run_cli(str(pack_dir))
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["code"] == PackVerifyCode.TAMPERED_ARTIFACT.value


def test_pack_verifier_module_parses_as_python_3_11() -> None:
    import ast

    source_path = (
        Path(__file__).resolve().parents[1] / "ontologylab" / "pack_verifier.py"
    )
    ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
        feature_version=(3, 11),
    )
