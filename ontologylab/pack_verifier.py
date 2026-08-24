"""Standalone pack inventory verifier: v2 strict, v1 compatible."""
# noqa: SIZE_OK — Task 9 owns only this module; parse/inventory/CLI cannot be split

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum, unique
from pathlib import Path
from types import MappingProxyType
from typing import Final, TypeAlias, assert_never, NoReturn

_MANIFEST: Final = "manifest.json"
_INTEGRITY: Final = "sha256-receipt-not-signature"
_TREE: Final = ("pack.sqlite", "schema.json", "provenance.jsonl")
_WRITE: Final = 0o222
_V2_CAP: Final = "knowledge-graph-v2"
_V2_EV: Final = "evidence-self-contained-v2"
_COUNTS: Final = {
    "works": "works",
    "representations": "documents",
    "observations": "observations",
    "identifiers": "work_identifiers",
    "citations": "citations",
    "review_decisions": "review_decisions",
    "extraction_runs": "extraction_runs",
    "extraction_chunks": "extraction_chunks",
    "nodes": "nodes",
    "edges": "edges",
}

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


@unique
class PackSchemaVersion(IntEnum):
    V1 = 1
    V2 = 2


@unique
class PackVerifyCode(StrEnum):
    MISSING_ARTIFACT = "missing_artifact"
    EXTRA_ARTIFACT = "extra_artifact"
    TAMPERED_ARTIFACT = "tampered_artifact"
    PATH_MISMATCH = "path_mismatch"
    SYMLINK = "symlink"
    HARDLINK = "hardlink"
    WRITABLE = "writable"
    ORIGINAL_INODE = "original_inode"
    FORGED_HASH = "forged_hash"
    FORGED_COUNTS = "forged_counts"
    SELF_REFERENCE = "self_reference"
    INVALID_MANIFEST = "invalid_manifest"


@dataclass(frozen=True, slots=True)
class PackVerifyRefused(Exception):
    code: PackVerifyCode
    path: str | None = None

    def __str__(self) -> str:
        return self.code.value if self.path is None else f"{self.code.value}:{self.path}"


@dataclass(frozen=True, slots=True)
class ClaimedEntry:
    path: str
    size: int
    sha256: str
    file_type: str
    mode: int


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    path: str
    size: int
    sha256: str
    file_type: str
    mode: int
    uid: int
    gid: int
    nlink: int
    dev: int
    ino: int


@dataclass(frozen=True, slots=True)
class ManifestV1:
    pack_id: str
    content_hash: str
    tree_hash: str | None


@dataclass(frozen=True, slots=True)
class ManifestV2:
    pack_id: str
    inventory: tuple[ClaimedEntry, ...]
    pack_content_hash: str
    sqlite_hash: str
    counts: Mapping[str, int]
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PackVerifyReceipt:
    pack_id: str
    pack_schema_version: PackSchemaVersion
    pack_content_hash: str
    integrity_level: str
    inventory: tuple[InventoryRecord, ...]
    counts: Mapping[str, int]
    sqlite_hash: str | None


def _refuse(code: PackVerifyCode, path: str | None = None) -> NoReturn:
    raise PackVerifyRefused(code, path)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _same(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _is_sha(value: JsonValue) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    hex_part = value.removeprefix("sha256:")
    try:
        return len(hex_part) == 64 and bytes.fromhex(hex_part) is not None
    except ValueError:
        return False


def _canonical(entries: tuple[ClaimedEntry, ...]) -> str:
    rows = [
        {"file_type": e.file_type, "mode": e.mode, "path": e.path, "sha256": e.sha256, "size": e.size}
        for e in entries
    ]
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def _pack_id(value: JsonValue) -> str:
    if not isinstance(value, str):
        _refuse(PackVerifyCode.INVALID_MANIFEST, "pack_id")
    if not value or "/" in value or "\\" in value or value in {".", ".."} or "\x00" in value:
        _refuse(PackVerifyCode.INVALID_MANIFEST, "pack_id")
    return value


def _relpath(path: str) -> None:
    if path == _MANIFEST:
        _refuse(PackVerifyCode.SELF_REFERENCE, path)
    escaped = path.startswith("/") or path.startswith("\\") or ":" in path or "\\" in path
    parts = path.split("/")
    if escaped or not parts or any(part in {"", ".", ".."} for part in parts):
        _refuse(PackVerifyCode.PATH_MISMATCH, path)


def _entry(raw: JsonValue) -> ClaimedEntry:
    if not isinstance(raw, dict):
        _refuse(PackVerifyCode.INVALID_MANIFEST, "artifact_inventory")
    path, size, digest = raw.get("path"), raw.get("size"), raw.get("sha256")
    file_type, mode = raw.get("file_type"), raw.get("mode")
    if not isinstance(path, str):
        _refuse(PackVerifyCode.PATH_MISMATCH)
    _relpath(path)
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        _refuse(PackVerifyCode.INVALID_MANIFEST, path)
    if not _is_sha(digest) or not isinstance(digest, str):
        _refuse(PackVerifyCode.FORGED_HASH, path)
    if file_type != "regular" or not isinstance(mode, int) or isinstance(mode, bool):
        _refuse(PackVerifyCode.INVALID_MANIFEST, path)
    if mode & _WRITE:
        _refuse(PackVerifyCode.WRITABLE, path)
    return ClaimedEntry(path, size, digest, "regular", mode)


def _ints(raw: JsonValue, code: PackVerifyCode) -> Mapping[str, int]:
    if not isinstance(raw, dict):
        _refuse(PackVerifyCode.INVALID_MANIFEST, "counts")
    out: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(value, int) or isinstance(value, bool):
            _refuse(code, key)
        out[key] = value
    return MappingProxyType(out)


def _parse_v1(raw: dict[str, JsonValue]) -> ManifestV1:
    content, tree = raw.get("content_hash"), raw.get("tree_hash")
    if not _is_sha(content) or not isinstance(content, str):
        _refuse(PackVerifyCode.FORGED_HASH, "pack.sqlite")
    if tree is not None and (not _is_sha(tree) or not isinstance(tree, str)):
        _refuse(PackVerifyCode.FORGED_HASH, "tree_hash")
    return ManifestV1(_pack_id(raw.get("pack_id")), content, tree if isinstance(tree, str) else None)


def _parse_v2(raw: dict[str, JsonValue]) -> ManifestV2:
    inventory_raw = raw.get("artifact_inventory")
    if not isinstance(inventory_raw, list):
        _refuse(PackVerifyCode.INVALID_MANIFEST, "artifact_inventory")
    entries = tuple(_entry(item) for item in inventory_raw)
    paths = [item.path for item in entries]
    if len(paths) != len(set(paths)) or paths != sorted(paths):
        _refuse(PackVerifyCode.INVALID_MANIFEST, "artifact_inventory")
    pack_hash, sqlite_hash = raw.get("pack_content_hash"), raw.get("sqlite_hash")
    if not _is_sha(pack_hash) or not isinstance(pack_hash, str):
        _refuse(PackVerifyCode.FORGED_HASH, "pack_content_hash")
    if not _is_sha(sqlite_hash) or not isinstance(sqlite_hash, str):
        _refuse(PackVerifyCode.FORGED_HASH, "sqlite_hash")
    if not _same(pack_hash, _digest(_canonical(entries).encode())):
        _refuse(PackVerifyCode.FORGED_HASH, "pack_content_hash")
    caps_raw = raw.get("capabilities")
    if not isinstance(caps_raw, list) or not all(isinstance(item, str) for item in caps_raw):
        _refuse(PackVerifyCode.INVALID_MANIFEST, "capabilities")
    capabilities = tuple(str(item) for item in caps_raw)
    if _V2_CAP not in capabilities:
        _refuse(PackVerifyCode.INVALID_MANIFEST, "capabilities")
    if any(item.path.startswith("evidence/") for item in entries) and _V2_EV not in capabilities:
        _refuse(PackVerifyCode.INVALID_MANIFEST, "capabilities")
    if raw.get("integrity_model") != _INTEGRITY:
        _refuse(PackVerifyCode.INVALID_MANIFEST, "integrity_model")
    if not any(item.path == "pack.sqlite" for item in entries):
        _refuse(PackVerifyCode.MISSING_ARTIFACT, "pack.sqlite")
    return ManifestV2(
        _pack_id(raw.get("pack_id")),
        entries,
        pack_hash,
        sqlite_hash,
        _ints(raw.get("counts"), PackVerifyCode.FORGED_COUNTS),
        capabilities,
    )


def parse_manifest(raw: JsonValue) -> ManifestV1 | ManifestV2:
    """Parse untrusted manifest JSON once into a typed v1 or v2 value."""
    if not isinstance(raw, dict):
        _refuse(PackVerifyCode.INVALID_MANIFEST)
    match raw.get("pack_schema_version", 1):  # noqa: MATCH_OK
        case 1 | None:
            return _parse_v1(raw)
        case 2:
            return _parse_v2(raw)
        case _:
            _refuse(PackVerifyCode.INVALID_MANIFEST, "pack_schema_version")


def _tree_hash(pack_dir: Path) -> str:
    hasher = hashlib.sha256()
    for name in _TREE:
        path = pack_dir / name
        data = path.read_bytes() if path.is_file() else b""
        hasher.update(name.encode() + b"\0" + hashlib.sha256(data).hexdigest().encode() + b"\n")
    return "sha256:" + hasher.hexdigest()


def _record(path: Path, rel: str, *, strict_mode: bool) -> InventoryRecord:
    if path.is_symlink() or stat.S_ISLNK(path.lstat().st_mode):
        _refuse(PackVerifyCode.SYMLINK, rel)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        _refuse(PackVerifyCode.PATH_MISMATCH, rel)
    if info.st_nlink != 1:
        _refuse(PackVerifyCode.HARDLINK, rel)
    mode = stat.S_IMODE(info.st_mode)
    if strict_mode and mode & _WRITE:
        _refuse(PackVerifyCode.WRITABLE, rel)
    data = path.read_bytes()
    return InventoryRecord(
        rel, len(data), _digest(data), "regular", mode,
        info.st_uid, info.st_gid, info.st_nlink, info.st_dev, info.st_ino,
    )


def _scan(pack_dir: Path) -> dict[str, InventoryRecord]:
    found: dict[str, InventoryRecord] = {}
    for dirpath, dirnames, filenames in os.walk(pack_dir, followlinks=False):
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            child = base / name
            rel = child.relative_to(pack_dir).as_posix()
            if child.is_symlink():
                _refuse(PackVerifyCode.SYMLINK, rel)
        for name in filenames:
            child = base / name
            rel = child.relative_to(pack_dir).as_posix()
            if rel != _MANIFEST:
                found[rel] = _record(child, rel, strict_mode=True)
    return found


def _working_idents(working: Path | None, pack_root: Path) -> frozenset[tuple[int, int]]:
    if working is None:
        return frozenset()
    if not working.exists():
        _refuse(PackVerifyCode.INVALID_MANIFEST, str(working))
    if working.is_file():
        info = working.lstat()
        return frozenset({(info.st_dev, info.st_ino)})
    idents: set[tuple[int, int]] = set()
    for child in working.rglob("*"):
        if not child.is_file() or child.is_symlink():
            continue
        resolved = child.resolve()
        if resolved == pack_root or pack_root in resolved.parents:
            continue
        info = child.lstat()
        idents.add((info.st_dev, info.st_ino))
    return frozenset(idents)


def _guard_inode(records: Mapping[str, InventoryRecord], idents: frozenset[tuple[int, int]]) -> None:
    for record in records.values():
        if (record.dev, record.ino) in idents:
            _refuse(PackVerifyCode.ORIGINAL_INODE, record.path)


def _rederive_counts(database: Path) -> Mapping[str, int]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        check = connection.execute("PRAGMA integrity_check").fetchone()
        if check is None or check[0] != "ok":
            _refuse(PackVerifyCode.TAMPERED_ARTIFACT, "pack.sqlite")
        present = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        derived: dict[str, int] = {}
        for key, table in _COUNTS.items():
            if table in present:
                row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                derived[key] = 0 if row is None else int(row[0])
            else:
                derived[key] = 0
        return MappingProxyType(derived)
    finally:
        connection.close()


def _verify_v1(pack_dir: Path, manifest: ManifestV1, working: Path | None) -> PackVerifyReceipt:
    sqlite_path, manifest_path = pack_dir / "pack.sqlite", pack_dir / _MANIFEST
    for path, label in ((sqlite_path, "pack.sqlite"), (manifest_path, _MANIFEST)):
        if path.is_symlink():
            _refuse(PackVerifyCode.SYMLINK, label)
        if not path.is_file():
            _refuse(PackVerifyCode.MISSING_ARTIFACT, label)
        if path.stat().st_nlink != 1:
            _refuse(PackVerifyCode.HARDLINK, label)
    record = _record(sqlite_path, "pack.sqlite", strict_mode=False)
    _guard_inode({"pack.sqlite": record}, _working_idents(working, pack_dir.resolve()))
    if not _same(record.sha256, manifest.content_hash):
        _refuse(PackVerifyCode.TAMPERED_ARTIFACT, "pack.sqlite")
    if manifest.tree_hash is not None and not _same(_tree_hash(pack_dir), manifest.tree_hash):
        _refuse(PackVerifyCode.TAMPERED_ARTIFACT, "tree_hash")
    return PackVerifyReceipt(
        manifest.pack_id, PackSchemaVersion.V1, manifest.content_hash,
        "legacy-graph-only", (), MappingProxyType({}), manifest.content_hash,
    )


def _verify_v2(pack_dir: Path, manifest: ManifestV2, working: Path | None) -> PackVerifyReceipt:
    found = _scan(pack_dir)
    _guard_inode(found, _working_idents(working, pack_dir.resolve()))
    claimed_paths, live_paths = {item.path for item in manifest.inventory}, set(found)
    missing, extra = sorted(claimed_paths - live_paths), sorted(live_paths - claimed_paths)
    if missing:
        _refuse(PackVerifyCode.MISSING_ARTIFACT, missing[0])
    if extra:
        _refuse(PackVerifyCode.EXTRA_ARTIFACT, extra[0])
    for item in manifest.inventory:
        record = found[item.path]
        mismatch = (
            record.size != item.size
            or not _same(record.sha256, item.sha256)
            or record.file_type != item.file_type
            or record.mode != item.mode
        )
        if mismatch:
            _refuse(PackVerifyCode.TAMPERED_ARTIFACT, item.path)
    if not _same(found["pack.sqlite"].sha256, manifest.sqlite_hash):
        _refuse(PackVerifyCode.FORGED_HASH, "sqlite_hash")
    derived = _rederive_counts(pack_dir / "pack.sqlite")
    if dict(manifest.counts) != dict(derived):
        _refuse(PackVerifyCode.FORGED_COUNTS)
    level = "evidence-self-contained-v2" if _V2_EV in manifest.capabilities else "knowledge-graph-v2"
    inventory = tuple(found[path] for path in sorted(found))
    return PackVerifyReceipt(
        manifest.pack_id, PackSchemaVersion.V2, manifest.pack_content_hash,
        level, inventory, derived, manifest.sqlite_hash,
    )


def _manifest_lstat(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError:
        _refuse(PackVerifyCode.MISSING_ARTIFACT, _MANIFEST)
    if stat.S_ISLNK(info.st_mode):
        _refuse(PackVerifyCode.SYMLINK, _MANIFEST)
    if not stat.S_ISREG(info.st_mode):
        _refuse(PackVerifyCode.PATH_MISMATCH, _MANIFEST)
    if info.st_nlink != 1:
        _refuse(PackVerifyCode.HARDLINK, _MANIFEST)
    return info


def verify_pack(pack_dir: Path, *, working: Path | None = None) -> PackVerifyReceipt:
    """Verify a pack directory from packed bytes only."""
    root = Path(pack_dir)
    if root.is_symlink():
        _refuse(PackVerifyCode.SYMLINK, ".")
    if not root.is_dir():
        _refuse(PackVerifyCode.INVALID_MANIFEST, str(root))
    manifest_path = root / _MANIFEST
    info = _manifest_lstat(manifest_path)
    try:
        loaded: JsonValue = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _refuse(PackVerifyCode.INVALID_MANIFEST, _MANIFEST)
    parsed = parse_manifest(loaded)
    if root.name != parsed.pack_id:
        _refuse(PackVerifyCode.PATH_MISMATCH, root.name)
    match parsed:
        case ManifestV1():
            return _verify_v1(root, parsed, working)
        case ManifestV2():
            if stat.S_IMODE(info.st_mode) & _WRITE:
                _refuse(PackVerifyCode.WRITABLE, _MANIFEST)
            return _verify_v2(root, parsed, working)
        case unreachable:
            assert_never(unreachable)


def _payload(receipt: PackVerifyReceipt) -> dict[str, JsonValue]:  # noqa: DICT_OK
    return {
        "ok": True,
        "pack_id": receipt.pack_id,
        "pack_schema_version": int(receipt.pack_schema_version),
        "pack_content_hash": receipt.pack_content_hash,
        "integrity_level": receipt.integrity_level,
        "sqlite_hash": receipt.sqlite_hash,
        "counts": dict(receipt.counts),
        "inventory": [
            {
                "path": item.path, "size": item.size, "sha256": item.sha256,
                "file_type": item.file_type, "mode": item.mode,
                "uid": item.uid, "gid": item.gid, "nlink": item.nlink,
            }
            for item in receipt.inventory
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ontologylab.pack_verifier")
    parser.add_argument("pack_dir")
    parser.add_argument("--working", default=None)
    args = parser.parse_args(argv)
    try:
        working = None if args.working is None else Path(args.working)
        receipt = verify_pack(Path(args.pack_dir), working=working)
    except PackVerifyRefused as refused:
        sys.stdout.write(json.dumps({"ok": False, "code": refused.code.value, "path": refused.path}, sort_keys=True, separators=(",", ":")))
        sys.stdout.write("\n")
        return 2
    sys.stdout.write(json.dumps(_payload(receipt), sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
