"""Finalize a v2 pack manifest after every payload artifact exists."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Final, TypeAlias

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)

from ontologylab.pack_verifier import ClaimedEntry

_MANIFEST: Final = "manifest.json"
_INTEGRITY: Final = "sha256-receipt-not-signature"
_READONLY: Final = 0o444
_COUNT_TABLES: Final = {
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


def finalize_v2_manifest(pack_dir: Path, fields: dict[str, JsonValue]) -> None:
    """Inventory payloads, bind hashes, write owner-read-only manifest."""
    root = Path(pack_dir)
    _chmod_payloads(root)
    entries = _inventory(root)
    sqlite_hash = _digest((root / "pack.sqlite").read_bytes())
    pack_hash = _digest(_canonical(entries).encode("utf-8"))
    payload: dict[str, JsonValue] = dict(fields)
    inventory: list[JsonValue] = [_claimed(entry) for entry in entries]
    payload["artifact_inventory"] = inventory
    payload["sqlite_hash"] = sqlite_hash
    payload["pack_content_hash"] = pack_hash
    payload["integrity_model"] = _INTEGRITY
    payload["counts"] = dict(_rederive_counts(root / "pack.sqlite"))
    dest = root / _MANIFEST
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    dest.chmod(_READONLY)


def _inventory(root: Path) -> tuple[ClaimedEntry, ...]:
    found: list[ClaimedEntry] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for name in filenames:
            child = base / name
            rel = child.relative_to(root).as_posix()
            if rel == _MANIFEST:
                continue
            info = child.lstat()
            data = child.read_bytes()
            found.append(
                ClaimedEntry(
                    rel, len(data), _digest(data), "regular", stat.S_IMODE(info.st_mode),
                )
            )
    found.sort(key=lambda item: item.path)
    return tuple(found)


def _claimed(entry: ClaimedEntry) -> dict[str, JsonValue]:
    claimed: dict[str, JsonValue] = {
        "path": entry.path,
        "size": entry.size,
        "sha256": entry.sha256,
        "file_type": entry.file_type,
        "mode": entry.mode,
    }
    claimed.update(_ownership(entry.path))
    return claimed


def _ownership(path: str) -> dict[str, str]:
    if path.startswith("evidence/") and path.endswith("/full.txt"):
        return {
            "owner": path.split("/")[1],
            "media_type": "text/plain",
            "redistribution": "full",
        }
    if path.startswith("evidence/") and path.endswith("/window.txt"):
        return {
            "owner": path.split("/")[1],
            "media_type": "text/plain",
            "redistribution": "excerpt",
        }
    if path == "pack.sqlite":
        return {"media_type": "application/vnd.sqlite3", "redistribution": "pack"}
    if path.endswith(".json") or path.endswith(".jsonl"):
        return {"media_type": "application/json", "redistribution": "pack"}
    return {}


def _chmod_payloads(root: Path) -> None:
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            child = Path(dirpath) / name
            if child.relative_to(root).as_posix() != _MANIFEST:
                child.chmod(_READONLY)


def _rederive_counts(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        present = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
        derived: dict[str, int] = {}
        for key, table in _COUNT_TABLES.items():
            if table in present:
                row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                derived[key] = 0 if row is None else int(row[0])
            else:
                derived[key] = 0
        return derived
    finally:
        connection.close()


def _canonical(entries: tuple[ClaimedEntry, ...]) -> str:
    rows = [
        {
            "file_type": entry.file_type,
            "mode": entry.mode,
            "path": entry.path,
            "sha256": entry.sha256,
            "size": entry.size,
        }
        for entry in entries
    ]
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()
