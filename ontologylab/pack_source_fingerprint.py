"""Inventoried live source-fingerprint witness for packed C-036 binds."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Final

SOURCE_FINGERPRINT_NAME: Final = "source-fingerprint.json"
_FINGERPRINT_SQL: Final = (
    "SELECT id, IFNULL(content_hash, '') FROM documents ORDER BY id"
)


def capture_source_fingerprint_entries(
    conn: sqlite3.Connection,
) -> tuple[tuple[str, str], ...]:
    """Return live document id/hash pairs in canonical id order."""
    rows = conn.execute(_FINGERPRINT_SQL).fetchall()
    return tuple((str(row[0]), str(row[1])) for row in rows)


def fingerprint_from_entries(entries: tuple[tuple[str, str], ...]) -> str:
    """Hash canonical [[id, IFNULL(content_hash, '')], ...] pairs."""
    payload = json.dumps(
        [list(item) for item in entries],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_source_fingerprint(
    pack_dir: Path, entries: tuple[tuple[str, str], ...],
) -> None:
    """Write the live document witness as pack payload."""
    (pack_dir / SOURCE_FINGERPRINT_NAME).write_text(
        json.dumps(
            {"entries": [list(item) for item in entries]},
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def load_source_fingerprint(
    pack_root: Path,
) -> tuple[tuple[str, str], ...] | None:
    """Parse `{entries:[[id,hash],...]}` or return None if absent/invalid."""
    path = pack_root / SOURCE_FINGERPRINT_NAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or set(raw) != {"entries"}:
        return None
    rows = raw["entries"]
    if not isinstance(rows, list):
        return None
    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    previous = ""
    for index, item in enumerate(rows):
        if not isinstance(item, list) or len(item) != 2:
            return None
        doc_id, digest = item[0], item[1]
        if not isinstance(doc_id, str) or not isinstance(digest, str):
            return None
        if not doc_id or doc_id in seen:
            return None
        if index and doc_id <= previous:
            return None
        seen.add(doc_id)
        previous = doc_id
        parsed.append((doc_id, digest))
    return tuple(parsed)


def source_fingerprint_matches(
    conn: sqlite3.Connection,
    pack_root: Path,
    claimed: str,
) -> bool:
    """True when the inventoried witness hashes to claimed and covers packed docs."""
    witness = load_source_fingerprint(pack_root)
    if witness is None:
        return False
    if fingerprint_from_entries(witness) != claimed:
        return False
    try:
        packed = capture_source_fingerprint_entries(conn)
    except sqlite3.OperationalError:
        return False
    return set(packed).issubset(set(witness))
