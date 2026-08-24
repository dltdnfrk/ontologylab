"""Append-only SQLite storage for the Step 9 rollback contract."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ontologylab.cutover_rehearsal import _in_savepoint
from ontologylab.cutover_rollback_types import (
    MutationKind,
    RollbackCode,
    RollbackReceipt,
    RollbackState,
    refuse,
)


def file_inventory_hash(root: Path) -> str:
    """Hash path and bytes of every regular file under one inventory root."""
    hasher = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        hasher.update(path.relative_to(root).as_posix().encode("utf-8"))
        hasher.update(path.read_bytes())
    return "sha256:" + hasher.hexdigest()


def marker_row(conn: sqlite3.Connection) -> sqlite3.Row | tuple | None:
    return conn.execute(
        "SELECT generation, source_fingerprint FROM v2_migration_ledger "
        "WHERE phase = 'post_cutover_write' ORDER BY seq LIMIT 1"
    ).fetchone()


def append_receipt(
    conn: sqlite3.Connection,
    action: str,
    *,
    kind: MutationKind | None,
    actor: str,
    reason: str,
    detail: dict[str, str],
) -> None:
    conn.execute(
        "INSERT INTO cutover_rollback_receipts "
        "(action, mutation_kind, actor, reason, detail) VALUES (?, ?, ?, ?, ?)",
        (
            action,
            None if kind is None else kind.value,
            actor,
            reason,
            json.dumps(detail, sort_keys=True, separators=(",", ":")),
        ),
    )


def install_rollback_contract(
    conn: sqlite3.Connection,
    *,
    generation: int,
    inventory_root: Path,
) -> RollbackState:
    if generation < 1:
        refuse(RollbackCode.INVALID_INPUT, "generation")
    inventory = file_inventory_hash(inventory_root)

    def _write() -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cutover_rollback_state ("
            "id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL, "
            "forward_only INTEGER NOT NULL, v2_writes_enabled INTEGER NOT NULL, "
            "preferred_selection_enabled INTEGER NOT NULL, "
            "publication_enabled INTEGER NOT NULL, inventory_hash TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cutover_rollback_receipts ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, "
            "mutation_kind TEXT, actor TEXT NOT NULL, reason TEXT NOT NULL, "
            "detail TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS cutover_rollback_receipts_no_update "
            "BEFORE UPDATE ON cutover_rollback_receipts BEGIN "
            "SELECT RAISE(ABORT, 'cutover rollback receipts are append-only'); END"
        )
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS cutover_rollback_receipts_no_delete "
            "BEFORE DELETE ON cutover_rollback_receipts BEGIN "
            "SELECT RAISE(ABORT, 'cutover rollback receipts are append-only'); END"
        )
        if conn.execute(
            "SELECT 1 FROM cutover_rollback_state WHERE id=1"
        ).fetchone() is not None:
            refuse(RollbackCode.INVALID_INPUT, "already_installed")
        conn.execute(
            "INSERT INTO cutover_rollback_state VALUES (1, ?, 0, 1, 1, 1, ?)",
            (generation, inventory),
        )
        append_receipt(
            conn, "install", kind=None, actor="system",
            reason="bind pre-cutover inventory",
            detail={"inventory_hash": inventory},
        )

    _in_savepoint(conn, _write)
    return read_rollback_state(conn)


def read_rollback_state(conn: sqlite3.Connection) -> RollbackState:
    row = conn.execute(
        "SELECT generation, forward_only, v2_writes_enabled, "
        "preferred_selection_enabled, publication_enabled, inventory_hash "
        "FROM cutover_rollback_state WHERE id=1"
    ).fetchone()
    if row is None:
        refuse(RollbackCode.NOT_INSTALLED, "state")
    return RollbackState(
        int(row[0]), bool(row[1]), bool(row[2]), bool(row[3]), bool(row[4]), str(row[5]),
    )


def read_rollback_receipts(
    conn: sqlite3.Connection,
) -> tuple[RollbackReceipt, ...]:
    rows = conn.execute(
        "SELECT seq, action, mutation_kind, actor, reason, detail "
        "FROM cutover_rollback_receipts ORDER BY seq"
    )
    return tuple(
        RollbackReceipt(
            int(row[0]),
            str(row[1]),
            None if row[2] is None else MutationKind(str(row[2])),
            str(row[3]),
            str(row[4]),
            str(row[5]),
        )
        for row in rows
    )
