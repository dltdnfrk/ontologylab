"""Resumable migration core on SQLite backup-API copies (Wave 2.1 Step 5, 5A).

Operates on caller-owned snapshot copies only: backup-API snapshot, source
fingerprint, phase/generation ledger rows in ``v2_migration_ledger``, atomic
phase+cursor commit, writer fence, ``post_cutover_write`` marker, and a
below-cursor drift scan. Ledger writes are SAVEPOINT-scoped inside the
caller-owned transaction; this module never issues COMMIT.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


MIGRATION_PHASES: tuple[str, ...] = (
    "expand",
    "backfill",
    "validate",
    "enforce",
)
PHASE_COMPLETE = "$complete"
_FENCE_PHASE = "fence"
_POST_CUTOVER_PHASE = "post_cutover_write"
_SP_BEGIN = "migration_begin"
_SP_ADVANCE = "migration_advance"
_SP_COMPLETE = "migration_complete"
_SP_FENCE = "migration_fence"
_SP_V2 = "migration_v2_write"


class MigrationError(Exception):
    """Base class for typed migration failures."""


@dataclass(frozen=True, slots=True)
class SnapshotSourceMissing(MigrationError):
    """The source store path does not exist."""

    source_path: str

    def __str__(self) -> str:
        return f"snapshot source missing: {self.source_path}"


@dataclass(frozen=True, slots=True)
class SnapshotTargetMissing(MigrationError):
    """The caller-owned target directory does not exist."""

    target_dir: str

    def __str__(self) -> str:
        return f"snapshot target directory missing: {self.target_dir}"


@dataclass(frozen=True, slots=True)
class SnapshotFailed(MigrationError):
    """The SQLite backup-API copy failed."""

    source_path: str
    target_dir: str
    reason: str

    def __str__(self) -> str:
        return f"snapshot failed: {self.reason}"


@dataclass(frozen=True, slots=True)
class SourceFingerprintRequired(MigrationError):
    """A ledger write arrived without a source fingerprint."""

    field: str

    def __str__(self) -> str:
        return f"migration requires a non-empty {self.field}"


@dataclass(frozen=True, slots=True)
class WritesFenced(MigrationError):
    """An armed writer fence refused a v2 authority mutation."""

    generation: int

    def __str__(self) -> str:
        return f"v2 authority writes are fenced at generation {self.generation}"


@dataclass(frozen=True, slots=True)
class PhasePlan:
    phases: tuple[str, ...]
    generation: int
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class LedgerRow:
    seq: int
    phase: str
    cursor: str | None
    generation: int
    source_fingerprint: str | None


def snapshot_db(source_path: str | Path, target_dir: str | Path) -> Path:
    """Copy ``source_path`` into ``target_dir`` via the SQLite backup API."""
    source = Path(source_path)
    dest_dir = Path(target_dir)
    if not source.is_file():
        raise SnapshotSourceMissing(source_path=str(source))
    if not dest_dir.is_dir():
        raise SnapshotTargetMissing(target_dir=str(dest_dir))
    dest = dest_dir / source.name
    try:
        src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except MigrationError:
        raise
    except Exception as exc:
        raise SnapshotFailed(
            source_path=str(source),
            target_dir=str(dest_dir),
            reason=str(exc),
        ) from exc
    return dest


def compute_source_fingerprint(conn: sqlite3.Connection) -> str:
    """Stable identity of the source document PK/content-hash set."""
    rows = conn.execute(
        "SELECT id, IFNULL(content_hash, '') FROM documents ORDER BY id"
    ).fetchall()
    payload = json.dumps(
        [[row[0], row[1]] for row in rows],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def plan_phases(
    conn: sqlite3.Connection,
    *,
    generation: int = 0,
) -> PhasePlan:
    return PhasePlan(
        phases=MIGRATION_PHASES,
        generation=generation,
        source_fingerprint=compute_source_fingerprint(conn),
    )


def _require_fingerprint(source_fingerprint: str) -> None:
    if not source_fingerprint or not str(source_fingerprint).strip():
        raise SourceFingerprintRequired(field="source_fingerprint")


def _insert_ledger(
    conn: sqlite3.Connection,
    *,
    phase: str,
    cursor: str | None,
    generation: int,
    source_fingerprint: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO v2_migration_ledger "
        "(phase, cursor, generation, source_fingerprint, created_ts) "
        "VALUES (?, ?, ?, ?, julianday('now'))",
        (phase, cursor, generation, source_fingerprint),
    )
    seq = cur.lastrowid
    if seq is None:
        raise MigrationError("ledger insert produced no seq")
    return int(seq)


def _in_savepoint(conn: sqlite3.Connection, name: str, body: Callable[[], None]) -> None:
    conn.execute(f"SAVEPOINT {name}")
    try:
        body()
        conn.execute(f"RELEASE SAVEPOINT {name}")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise


def begin_phase(
    conn: sqlite3.Connection,
    *,
    phase: str,
    generation: int,
    source_fingerprint: str,
) -> LedgerRow:
    """Record a ledger row carrying phase, generation, and source fingerprint."""
    _require_fingerprint(source_fingerprint)
    seq_box: list[int] = []

    def _write() -> None:
        seq_box.append(
            _insert_ledger(
                conn,
                phase=phase,
                cursor=None,
                generation=generation,
                source_fingerprint=source_fingerprint,
            )
        )

    _in_savepoint(conn, _SP_BEGIN, _write)
    return LedgerRow(
        seq=seq_box[0],
        phase=phase,
        cursor=None,
        generation=generation,
        source_fingerprint=source_fingerprint,
    )


def advance_cursor(
    conn: sqlite3.Connection,
    *,
    phase: str,
    cursor: str,
    generation: int,
    source_fingerprint: str,
    failpoint: Callable[[str], None] | None = None,
) -> None:
    """Write the phase row and cursor row atomically in one SAVEPOINT."""
    _require_fingerprint(source_fingerprint)

    def _write() -> None:
        _insert_ledger(
            conn,
            phase=phase,
            cursor=None,
            generation=generation,
            source_fingerprint=source_fingerprint,
        )
        if failpoint is not None:
            failpoint("after_phase_row")
        _insert_ledger(
            conn,
            phase=phase,
            cursor=cursor,
            generation=generation,
            source_fingerprint=source_fingerprint,
        )

    _in_savepoint(conn, _SP_ADVANCE, _write)


def complete_phase(
    conn: sqlite3.Connection,
    *,
    phase: str,
    generation: int,
    source_fingerprint: str,
) -> None:
    """Finalize a phase with a completion marker row."""
    _require_fingerprint(source_fingerprint)

    def _write() -> None:
        _insert_ledger(
            conn,
            phase=phase,
            cursor=PHASE_COMPLETE,
            generation=generation,
            source_fingerprint=source_fingerprint,
        )

    _in_savepoint(conn, _SP_COMPLETE, _write)


def read_ledger(conn: sqlite3.Connection) -> tuple[LedgerRow, ...]:
    rows = conn.execute(
        "SELECT seq, phase, cursor, generation, source_fingerprint "
        "FROM v2_migration_ledger ORDER BY seq"
    ).fetchall()
    return tuple(
        LedgerRow(
            seq=int(row[0]),
            phase=str(row[1]),
            cursor=row[2],
            generation=int(row[3]),
            source_fingerprint=row[4],
        )
        for row in rows
    )


def phase_is_complete(conn: sqlite3.Connection, phase: str) -> bool:
    row = conn.execute(
        "SELECT cursor FROM v2_migration_ledger WHERE phase = ? "
        "ORDER BY seq DESC LIMIT 1",
        (phase,),
    ).fetchone()
    return row is not None and row[0] == PHASE_COMPLETE


def fence_writes(
    conn: sqlite3.Connection,
    *,
    generation: int,
    source_fingerprint: str,
) -> None:
    """Arm the writer fence as a durable ledger row."""
    _require_fingerprint(source_fingerprint)

    def _write() -> None:
        if _fence_row(conn) is None:
            _insert_ledger(
                conn,
                phase=_FENCE_PHASE,
                cursor=None,
                generation=generation,
                source_fingerprint=source_fingerprint,
            )

    _in_savepoint(conn, _SP_FENCE, _write)


def _fence_row(conn: sqlite3.Connection) -> sqlite3.Row | tuple | None:
    return conn.execute(
        "SELECT generation FROM v2_migration_ledger WHERE phase = ? "
        "ORDER BY seq DESC LIMIT 1",
        (_FENCE_PHASE,),
    ).fetchone()


def _has_post_cutover_write(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM v2_migration_ledger WHERE phase = ? LIMIT 1",
            (_POST_CUTOVER_PHASE,),
        ).fetchone()
        is not None
    )


def apply_v2_authority_mutation(
    conn: sqlite3.Connection,
    mutate: Callable[[sqlite3.Connection], None],
    *,
    generation: int,
    source_fingerprint: str,
    failpoint: Callable[[str], None] | None = None,
) -> None:
    """Run a v2 authority mutation; first one writes ``post_cutover_write``.

    An armed fence raises ``WritesFenced`` and runs nothing. The marker is
    inserted in the same SAVEPOINT as the mutation.
    """
    fence = _fence_row(conn)
    if fence is not None:
        raise WritesFenced(generation=int(fence[0]))
    _require_fingerprint(source_fingerprint)

    def _write() -> None:
        mutate(conn)
        if failpoint is not None:
            failpoint("after_v2_mutation")
        if not _has_post_cutover_write(conn):
            _insert_ledger(
                conn,
                phase=_POST_CUTOVER_PHASE,
                cursor=None,
                generation=generation,
                source_fingerprint=source_fingerprint,
            )

    _in_savepoint(conn, _SP_V2, _write)


def scan_drift(
    source: sqlite3.Connection,
    copy: sqlite3.Connection,
    *,
    cursor: str | None = None,
) -> tuple[str, ...]:
    """Document PKs present on ``source`` but not ``copy``.

    When ``cursor`` is set this is the below-cursor catch-up scan: every
    missing PK at or below the cursor is returned and never dropped.
    """
    source_ids = {
        row[0] for row in source.execute("SELECT id FROM documents")
    }
    copy_ids = {row[0] for row in copy.execute("SELECT id FROM documents")}
    missing = tuple(sorted(source_ids - copy_ids))
    if cursor is None:
        return missing
    return tuple(pk for pk in missing if pk <= cursor)
