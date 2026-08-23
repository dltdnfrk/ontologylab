"""F6 interrupt/resume rehearsal driver over the 5A migration core (Wave 2.1 Step 5, 5C).

Drives ``ontologylab.migration``: backup-API copies, phase/cursor ledger,
and below-cursor ``scan_drift``. 5A does not expose a current-cursor
reader, a document row-copy, a per-row effect counter, a canonical dump,
a receipt, or an interrupt/resume loop — those are wrapped here. Ledger
and effect writes are SAVEPOINT-scoped inside the caller-owned
transaction; this module never issues COMMIT.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from ontologylab.migration import (
    MigrationError,
    advance_cursor,
    begin_phase,
    complete_phase,
    phase_is_complete,
    plan_phases,
    read_ledger,
    scan_drift,
)


_DEFAULT_PHASE = "expand"
_EFFECTS_TABLE = "v2_rehearsal_effects"
_SP_CATCHUP = "rehearsal_catchup"
_SP_ROW = "rehearsal_row"
_VOLATILE_COLUMNS = frozenset({"created_ts", "updated_ts"})


@dataclass(frozen=True, slots=True)
class InterruptionInjected(MigrationError):
    """A rehearsal failpoint aborted the current row."""

    row_id: str
    phase: str

    def __str__(self) -> str:
        return f"interruption injected at row {self.row_id} in phase {self.phase}"


@dataclass(frozen=True, slots=True)
class RehearsalReceipt:
    phase: str
    generation: int
    source_fingerprint: str
    cursor: str | None
    complete: bool
    processed_ids: tuple[str, ...]
    effect_counts: tuple[tuple[str, int], ...]
    dump_sha256: str
    receipt_sha256: str


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _in_savepoint(
    conn: sqlite3.Connection, name: str, body: Callable[[], None]
) -> None:
    conn.execute(f"SAVEPOINT {name}")
    try:
        body()
        conn.execute(f"RELEASE SAVEPOINT {name}")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise


def _ensure_effects_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS v2_rehearsal_effects ("
        "row_id TEXT PRIMARY KEY, "
        "apply_count INTEGER NOT NULL"
        ")"
    )


def _apply_effect(conn: sqlite3.Connection, row_id: str) -> None:
    conn.execute(
        "INSERT INTO v2_rehearsal_effects (row_id, apply_count) "
        "VALUES (?, 1) "
        "ON CONFLICT(row_id) DO UPDATE SET apply_count = apply_count + 1",
        (row_id,),
    )


def _copy_document(
    source: sqlite3.Connection,
    dest: sqlite3.Connection,
    doc_id: str,
) -> None:
    if dest.execute(
        "SELECT 1 FROM documents WHERE id = ?", (doc_id,)
    ).fetchone() is not None:
        return
    src_cols = [row[1] for row in source.execute("PRAGMA table_info(documents)")]
    dst_cols = {row[1] for row in dest.execute("PRAGMA table_info(documents)")}
    cols = [col for col in src_cols if col in dst_cols]
    if not cols:
        raise MigrationError("documents has no copyable columns")
    quoted = ", ".join(_ident(col) for col in cols)
    row = source.execute(
        f"SELECT {quoted} FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if row is None:
        raise MigrationError(f"source document missing: {doc_id}")
    placeholders = ", ".join("?" * len(cols))
    dest.execute(
        f"INSERT INTO documents ({quoted}) VALUES ({placeholders})",
        tuple(row),
    )


def _pinned_plan(
    source: sqlite3.Connection,
    copy: sqlite3.Connection,
    *,
    generation: int,
) -> tuple[int, str]:
    for row in read_ledger(copy):
        if row.source_fingerprint:
            return row.generation, row.source_fingerprint
    plan = plan_phases(source, generation=generation)
    return plan.generation, plan.source_fingerprint


def _forward_ids(
    source: sqlite3.Connection, cursor: str | None
) -> tuple[str, ...]:
    ids = tuple(
        row[0] for row in source.execute("SELECT id FROM documents ORDER BY id")
    )
    if cursor is None:
        return ids
    return tuple(doc_id for doc_id in ids if doc_id > cursor)


def _catchup_ids(
    source: sqlite3.Connection,
    copy: sqlite3.Connection,
    cursor: str | None,
) -> tuple[str, ...]:
    if cursor is None:
        return ()
    return scan_drift(source, copy, cursor=cursor)


def current_cursor(conn: sqlite3.Connection, phase: str) -> str | None:
    """Latest durable cursor for ``phase``, or None if none has committed."""
    for row in reversed(read_ledger(conn)):
        if row.phase != phase:
            continue
        if row.cursor is not None:
            return row.cursor
    return None


def effect_counts(conn: sqlite3.Connection) -> tuple[tuple[str, int], ...]:
    """Durable per-row apply counts, ordered by row id."""
    present = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (_EFFECTS_TABLE,),
    ).fetchone()
    if present is None:
        return ()
    rows = conn.execute(
        "SELECT row_id, apply_count FROM v2_rehearsal_effects ORDER BY row_id"
    ).fetchall()
    return tuple((str(row[0]), int(row[1])) for row in rows)


def _cell(value: object) -> object:
    if value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def canonical_db_dump(conn: sqlite3.Connection) -> bytes:
    """sqlite_master plus ordered table contents, minus volatile timestamps."""
    master = [
        {"name": row[1], "sql": row[3], "tbl_name": row[2], "type": row[0]}
        for row in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        )
    ]
    tables: dict[str, list[list[object]]] = {}
    table_names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND sql LIKE 'CREATE TABLE%' "
            "ORDER BY name"
        )
    ]
    for table in table_names:
        cols = [
            row[1]
            for row in conn.execute(f"PRAGMA table_info({_ident(table)})")
            if row[1] not in _VOLATILE_COLUMNS
        ]
        if not cols:
            tables[table] = []
            continue
        quoted = ", ".join(_ident(col) for col in cols)
        rows = conn.execute(
            f"SELECT {quoted} FROM {_ident(table)} ORDER BY {quoted}"
        ).fetchall()
        tables[table] = [[_cell(value) for value in row] for row in rows]
    return json.dumps(
        {"sqlite_master": master, "tables": tables},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_db_hash(conn: sqlite3.Connection) -> str:
    return hashlib.sha256(canonical_db_dump(conn)).hexdigest()


def _build_receipt(
    copy: sqlite3.Connection,
    *,
    phase: str,
    generation: int,
    source_fingerprint: str,
) -> RehearsalReceipt:
    counts = effect_counts(copy)
    payload = {
        "complete": phase_is_complete(copy, phase),
        "cursor": current_cursor(copy, phase),
        "dump_sha256": canonical_db_hash(copy),
        "effect_counts": [list(item) for item in counts],
        "generation": generation,
        "phase": phase,
        "processed_ids": [row_id for row_id, _ in counts],
        "source_fingerprint": source_fingerprint,
    }
    receipt_sha = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return RehearsalReceipt(
        phase=phase,
        generation=generation,
        source_fingerprint=source_fingerprint,
        cursor=payload["cursor"],
        complete=payload["complete"],
        processed_ids=tuple(payload["processed_ids"]),
        effect_counts=counts,
        dump_sha256=payload["dump_sha256"],
        receipt_sha256=receipt_sha,
    )


def _process_row(
    source: sqlite3.Connection,
    copy: sqlite3.Connection,
    *,
    row_id: str,
    phase: str,
    generation: int,
    source_fingerprint: str,
    advance: bool,
    failpoint: Callable[[str], None] | None,
) -> None:
    if failpoint is not None:
        failpoint(row_id)

    def _write() -> None:
        _copy_document(source, copy, row_id)
        _apply_effect(copy, row_id)
        if advance:
            advance_cursor(
                copy,
                phase=phase,
                cursor=row_id,
                generation=generation,
                source_fingerprint=source_fingerprint,
            )

    _in_savepoint(copy, _SP_ROW if advance else _SP_CATCHUP, _write)


def run_rehearsal(
    source: sqlite3.Connection,
    copy: sqlite3.Connection,
    *,
    phase: str = _DEFAULT_PHASE,
    generation: int = 1,
    failpoint: Callable[[str], None] | None = None,
) -> RehearsalReceipt:
    """Walk source document PKs on ``copy``, honoring ledger cursor and failpoint.

    Per-row hook ``failpoint(row_id)`` may raise ``InterruptionInjected``.
    Completed rows keep a durable cursor; resume continues after it.
    Below-cursor rows that landed on ``source`` after the snapshot are
    copied via ``scan_drift`` and never dropped. A completed phase is a
    no-op that returns the same receipt hash.
    """
    _ensure_effects_table(copy)
    generation, source_fingerprint = _pinned_plan(
        source, copy, generation=generation
    )
    if phase_is_complete(copy, phase):
        return _build_receipt(
            copy,
            phase=phase,
            generation=generation,
            source_fingerprint=source_fingerprint,
        )
    if not any(row.phase == phase for row in read_ledger(copy)):
        begin_phase(
            copy,
            phase=phase,
            generation=generation,
            source_fingerprint=source_fingerprint,
        )
    cursor = current_cursor(copy, phase)
    for row_id in _catchup_ids(source, copy, cursor):
        _process_row(
            source,
            copy,
            row_id=row_id,
            phase=phase,
            generation=generation,
            source_fingerprint=source_fingerprint,
            advance=False,
            failpoint=failpoint,
        )
    for row_id in _forward_ids(source, cursor):
        _process_row(
            source,
            copy,
            row_id=row_id,
            phase=phase,
            generation=generation,
            source_fingerprint=source_fingerprint,
            advance=True,
            failpoint=failpoint,
        )
    complete_phase(
        copy,
        phase=phase,
        generation=generation,
        source_fingerprint=source_fingerprint,
    )
    return _build_receipt(
        copy,
        phase=phase,
        generation=generation,
        source_fingerprint=source_fingerprint,
    )
