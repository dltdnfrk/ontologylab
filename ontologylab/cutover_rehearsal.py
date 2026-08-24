"""Disposable cutover rehearsal (Step 9A). SAVEPOINT-scoped; never COMMIT."""
# noqa: SIZE_OK — state machine plus sealed reader-proof and flip-bundle gates

from __future__ import annotations

import hashlib, json, sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, NoReturn, assert_never

from ontologylab.migration import fence_writes

_SP: Final = "cutover_rehearsal"


@unique
class CutoverPhase(StrEnum):
    EXPAND = "expand"
    SHADOW_WRITE = "shadow_write"
    BACKFILL = "backfill"
    CATCH_UP = "catch_up"
    DRAINED = "drained"
    FENCED = "fenced"
    CONSTRAINTS_REBUILT = "constraints_rebuilt"
    FULL_V2 = "full_v2"
    AUTHORITY_FLIPPED = "authority_flipped"


@unique
class CutoverCode(StrEnum):
    INVALID_TRANSITION = "invalid_transition"
    DUPLICATE_TRANSITION = "duplicate_transition"
    DRIFT_REQUIRED = "drift_required"
    WRITERS_LIVE = "writers_live"
    UNMIGRATED = "unmigrated"
    COLLISION = "collision"
    FK_ERROR = "fk_error"
    CITATION_ERROR = "citation_error"
    OUTBOX_GAP = "outbox_gap"
    OUTBOX_OPEN = "outbox_open"
    VERIFIER_FAILED = "verifier_failed"
    HASH_CHANGED = "hash_changed"
    ALREADY_INSTALLED = "already_installed"
    EMPTY_BIND = "empty_bind"
    WRONG_PHASE = "wrong_phase"
    READER_SET = "reader_set"
    READER_BINDING = "reader_binding"
    READER_HASH = "reader_hash"
    READER_UNAVAILABLE = "reader_unavailable"
    READER_FAILED = "reader_failed"


@dataclass(frozen=True, slots=True)
class CutoverRefused(Exception):
    code: CutoverCode
    detail: str

    def __str__(self) -> str:
        return f"{self.code.value}:{self.detail}"


@dataclass(frozen=True, slots=True)
class CutoverBind:
    generation: int; high_water: int
    source_fingerprint: str; backup_receipt: str


@dataclass(frozen=True, slots=True)
class DriftObservation:
    generation: int; high_water: int; drift: int


@dataclass(frozen=True, slots=True)
class CutoverChecks:
    old_writer_count: int = 0; unmigrated_rows: int = 0
    blocking_collisions: int = 0; fk_errors: int = 0
    citation_errors: int = 0; outbox_gap: int = 0
    open_outbox: int = 0; pack_verified: bool = False; reader_bundle_hash: str = ""


@dataclass(frozen=True, slots=True)
class CutoverState:
    phase: CutoverPhase; generation: int; high_water: int
    source_fingerprint: str; backup_receipt: str
    zero_drift_streak: int; bundle_hash: str


@dataclass(frozen=True, slots=True)
class CutoverReceipt:
    seq: int; kind: str; phase: str; detail: str


_CONSTRAINTS: Final = (
    ("unmigrated_rows", CutoverCode.UNMIGRATED), ("blocking_collisions", CutoverCode.COLLISION),
    ("fk_errors", CutoverCode.FK_ERROR), ("citation_errors", CutoverCode.CITATION_ERROR),
    ("outbox_gap", CutoverCode.OUTBOX_GAP),
)
_AFTER_CATCH_UP: Final = frozenset({
    CutoverPhase.DRAINED, CutoverPhase.FENCED, CutoverPhase.CONSTRAINTS_REBUILT,
    CutoverPhase.FULL_V2, CutoverPhase.AUTHORITY_FLIPPED,
})


def _refuse(code: CutoverCode, detail: str) -> NoReturn:
    raise CutoverRefused(code, detail)


def _in_savepoint(conn: sqlite3.Connection, body: Callable[[], None]) -> None:
    conn.execute(f"SAVEPOINT {_SP}")
    try:
        body()
        conn.execute(f"RELEASE SAVEPOINT {_SP}")
    except Exception:  # noqa: BROAD_EXCEPT_OK
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SP}")
        conn.execute(f"RELEASE SAVEPOINT {_SP}")
        raise


def read_cutover_state(conn: sqlite3.Connection) -> CutoverState:
    """Return the singleton rehearsal state."""
    row = conn.execute(
        "SELECT phase, generation, high_water, source_fingerprint, "
        "backup_receipt, zero_drift_streak, bundle_hash FROM cutover_state WHERE id = 1"
    ).fetchone()
    if row is None:
        _refuse(CutoverCode.EMPTY_BIND, "not_installed")
    return CutoverState(
        CutoverPhase(str(row[0])), int(row[1]), int(row[2]), str(row[3]), str(row[4]),
        int(row[5]), str(row[6]) if len(row) > 6 else "",
    )


def read_cutover_receipts(conn: sqlite3.Connection) -> tuple[CutoverReceipt, ...]:
    """Return append-only transition and observation receipts."""
    return tuple(
        CutoverReceipt(int(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in conn.execute(
            "SELECT seq, kind, phase, detail FROM cutover_receipts ORDER BY seq"
        )
    )


def canonical_data_hash(conn: sqlite3.Connection) -> str:
    """Hash every non-rehearsal table so an authority flip cannot hide writes."""
    hasher = hashlib.sha256()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'cutover_%' AND name NOT LIKE 'sqlite_%' ORDER BY 1"
    )
    for (name,) in tables:
        rows = [tuple(row) for row in conn.execute(f'SELECT * FROM "{name}"')]
        hasher.update(name.encode())
        hasher.update(json.dumps(rows, default=str, separators=(",", ":")).encode())
    return hasher.hexdigest()


def _persist(
    conn: sqlite3.Connection, state: CutoverState, receipt: tuple[str, str, str],
    failpoint: Callable[[str], None] | None,
) -> None:
    conn.execute(
        "UPDATE cutover_state SET phase = ?, zero_drift_streak = ?, bundle_hash = ? WHERE id = 1",
        (state.phase.value, state.zero_drift_streak, state.bundle_hash),
    )
    if failpoint is not None:
        failpoint("after_state")
    conn.execute("INSERT INTO cutover_receipts (kind, phase, detail) VALUES (?, ?, ?)", receipt)


def install_cutover(conn: sqlite3.Connection, bind: CutoverBind) -> CutoverState:
    """Create singleton state on a disposable copy and bind identities."""
    if not bind.source_fingerprint.strip() or not bind.backup_receipt.strip():
        _refuse(CutoverCode.EMPTY_BIND, "source_fingerprint")
    state = CutoverState(
        CutoverPhase.EXPAND, bind.generation, bind.high_water,
        bind.source_fingerprint, bind.backup_receipt, 0, "",
    )

    def _write() -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cutover_state ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), phase TEXT NOT NULL, "
            "generation INTEGER NOT NULL, high_water INTEGER NOT NULL, "
            "source_fingerprint TEXT NOT NULL, backup_receipt TEXT NOT NULL, "
            "zero_drift_streak INTEGER NOT NULL, bundle_hash TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cutover_receipts ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
            "phase TEXT NOT NULL, detail TEXT NOT NULL)")
        if conn.execute("SELECT 1 FROM cutover_state WHERE id = 1").fetchone():
            _refuse(CutoverCode.ALREADY_INSTALLED, "cutover_state")
        conn.execute(
            "INSERT INTO cutover_state (id, phase, generation, high_water, "
            "source_fingerprint, backup_receipt, zero_drift_streak, bundle_hash) "
            "VALUES (1, ?, ?, ?, ?, ?, 0, '')",
            (state.phase.value, state.generation, state.high_water,
             state.source_fingerprint, state.backup_receipt),
        )
        conn.execute(
            "INSERT INTO cutover_receipts (kind, phase, detail) VALUES (?, ?, ?)",
            ("transition", state.phase.value, "install"),
        )

    _in_savepoint(conn, _write)
    return state


def record_drift_observation(
    conn: sqlite3.Connection,
    observation: DriftObservation | None = None,
    **_unused: str,
) -> None:
    """Public low-level streak path is closed. Use record_all_reader_observation."""
    _refuse(CutoverCode.DRIFT_REQUIRED, "reader_proof")


def _refuse_if_bundle_unbound(conn: sqlite3.Connection, bound: str) -> None:
    row = conn.execute(
        "SELECT detail FROM cutover_receipts WHERE kind = 'reader_bundle' "
        "ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    if row is None or not bound:
        _refuse(CutoverCode.HASH_CHANGED, "reader_bundle")
    payload = json.loads(str(row[0]))
    readers = payload.get("readers") if isinstance(payload, dict) else None
    encoded = json.dumps({"readers": readers}, sort_keys=True, separators=(",", ":"))
    recomputed = "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
    stored = str(payload.get("hash", "")) if isinstance(payload, dict) else ""
    if stored != recomputed or recomputed != bound:
        _refuse(CutoverCode.HASH_CHANGED, "reader_bundle")


def _enforce(target: CutoverPhase, checks: CutoverChecks, state: CutoverState) -> None:
    late = target is CutoverPhase.AUTHORITY_FLIPPED
    if target in _AFTER_CATCH_UP and state.zero_drift_streak < 2:
        _refuse(CutoverCode.DRIFT_REQUIRED, "zero_drift_streak")
    if (late or target is CutoverPhase.FENCED) and checks.old_writer_count:
        _refuse(CutoverCode.WRITERS_LIVE, "old_writer_count")
    if late or target is CutoverPhase.CONSTRAINTS_REBUILT:
        for field, code in _CONSTRAINTS:
            if getattr(checks, field):
                _refuse(code, field)
    if (late or target is CutoverPhase.FULL_V2) and not checks.pack_verified:
        _refuse(CutoverCode.VERIFIER_FAILED, "pack_verified")
    if (late or target is CutoverPhase.FULL_V2) and checks.open_outbox:
        _refuse(CutoverCode.OUTBOX_OPEN, "open_outbox")
    match target:
        case (CutoverPhase.EXPAND | CutoverPhase.SHADOW_WRITE | CutoverPhase.BACKFILL
              | CutoverPhase.CATCH_UP | CutoverPhase.DRAINED | CutoverPhase.FENCED
              | CutoverPhase.CONSTRAINTS_REBUILT | CutoverPhase.FULL_V2
              | CutoverPhase.AUTHORITY_FLIPPED):
            return
        case unreachable:
            assert_never(unreachable)


def advance_cutover(
    conn: sqlite3.Connection,
    target: CutoverPhase,
    checks: CutoverChecks,
    *,
    failpoint: Callable[[str], None] | None = None,
) -> CutoverState:
    """Advance exactly one legal phase after its typed gate."""
    current = read_cutover_state(conn)
    if target is current.phase:
        _refuse(CutoverCode.DUPLICATE_TRANSITION, target.value)
    order = tuple(CutoverPhase)
    nxt_phase = order[order.index(current.phase) + 1] if current.phase is not order[-1] else None
    if target is not nxt_phase:
        _refuse(CutoverCode.INVALID_TRANSITION, target.value)
    _enforce(target, checks, current)
    nxt = CutoverState(
        target, current.generation, current.high_water, current.source_fingerprint,
        current.backup_receipt, current.zero_drift_streak, current.bundle_hash,
    )

    def _write() -> None:
        if target is CutoverPhase.FENCED:
            fence_writes(
                conn, generation=current.generation,
                source_fingerprint=current.source_fingerprint,
            )
        before = canonical_data_hash(conn)
        _persist(conn, nxt, ("transition", target.value, current.phase.value), failpoint)
        if target is CutoverPhase.AUTHORITY_FLIPPED:
            _refuse_if_bundle_unbound(conn, current.bundle_hash)
            if canonical_data_hash(conn) != before:
                _refuse(CutoverCode.HASH_CHANGED, "canonical_hash")

    _in_savepoint(conn, _write)
    return nxt
