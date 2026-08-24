"""Forward-only rollback and additive recovery contract (Step 9A Task 15)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from ontologylab.cutover_compensation import (
    record_fact_retraction as record_fact_retraction,
    record_recovery_pack as record_recovery_pack,
    record_redirect_compensation as record_redirect_compensation,
)
from ontologylab.cutover_rehearsal import _in_savepoint
from ontologylab.cutover_rollback_store import (
    append_receipt as _append_receipt,
    file_inventory_hash as file_inventory_hash,
    install_rollback_contract as install_rollback_contract,
    marker_row as _marker_row,
    read_rollback_receipts as read_rollback_receipts,
    read_rollback_state as read_rollback_state,
)
from ontologylab.cutover_rollback_types import (
    CompatibilityMode as CompatibilityMode,
    FactRetraction as FactRetraction,
    ForwardRollbackChecks as ForwardRollbackChecks,
    MutationKind as MutationKind,
    RedirectCompensation as RedirectCompensation,
    RestoreChecks as RestoreChecks,
    RestorePermit as RestorePermit,
    RollbackCode as RollbackCode,
    RollbackReceipt as RollbackReceipt,
    RollbackRefused as RollbackRefused,
    RollbackState as RollbackState,
    refuse as _refuse,
    require_text as _require_text,
)
from ontologylab.migration import apply_v2_authority_mutation, fence_writes


def authorize_backup_restore(
    conn: sqlite3.Connection,
    checks: RestoreChecks,
    *,
    inventory_root: Path,
) -> RestorePermit:
    state = read_rollback_state(conn)
    if _marker_row(conn) is not None:
        _refuse(RollbackCode.POST_CUTOVER_RESTORE, "post_cutover_write")
    gates = (
        (checks.writes_refused, RollbackCode.WRITES_LIVE, "writes_refused"),
        (checks.writers_drained, RollbackCode.WRITERS_LIVE, "writers_drained"),
        (checks.exclusive_lock, RollbackCode.LOCK_REQUIRED, "exclusive_lock"),
        (checks.zero_drift, RollbackCode.DRIFT_NONZERO, "zero_drift"),
    )
    for passed, code, detail in gates:
        if not passed:
            _refuse(code, detail)
    fresh = file_inventory_hash(inventory_root)
    if (
        checks.fresh_inventory_hash != state.inventory_hash
        or fresh != state.inventory_hash
    ):
        _refuse(RollbackCode.INVENTORY_CHANGED, "file_inventory")

    def _write() -> None:
        _append_receipt(
            conn, "restore_authorized", kind=None, actor="operator",
            reason="all pre-marker restore gates passed",
            detail={"inventory_hash": fresh},
        )

    _in_savepoint(conn, _write)
    return RestorePermit(state.generation, fresh)


def apply_irreversible_mutation(
    conn: sqlite3.Connection,
    *,
    kind: MutationKind,
    mutate: Callable[[sqlite3.Connection], None],
    generation: int,
    source_fingerprint: str,
    actor: str,
    reason: str,
    failpoint: Callable[[str], None] | None = None,
) -> None:
    state = read_rollback_state(conn)
    if not state.v2_writes_enabled:
        _refuse(RollbackCode.V2_WRITES_DISABLED, kind.value)
    if generation != state.generation:
        _refuse(RollbackCode.INVALID_INPUT, "generation")
    clean_actor = _require_text(actor, "actor")
    clean_reason = _require_text(reason, "reason")

    def _mutate(owned: sqlite3.Connection) -> None:
        mutate(owned)
        _append_receipt(
            owned, "irreversible_mutation", kind=kind,
            actor=clean_actor, reason=clean_reason,
            detail={"generation": str(generation)},
        )

    apply_v2_authority_mutation(
        conn,
        _mutate,
        generation=generation,
        source_fingerprint=source_fingerprint,
        failpoint=failpoint,
    )


def enter_forward_rollback(
    conn: sqlite3.Connection,
    *,
    checks: ForwardRollbackChecks,
    actor: str,
    reason: str,
) -> RollbackState:
    state = read_rollback_state(conn)
    marker = _marker_row(conn)
    if marker is None:
        _refuse(RollbackCode.MARKER_REQUIRED, "post_cutover_write")
    if state.forward_only:
        _refuse(RollbackCode.INVALID_INPUT, "already_forward_only")
    if not checks.writers_drained:
        _refuse(RollbackCode.WRITERS_LIVE, "writers_drained")
    if not checks.exclusive_lock:
        _refuse(RollbackCode.LOCK_REQUIRED, "exclusive_lock")
    clean_actor = _require_text(actor, "actor")
    clean_reason = _require_text(reason, "reason")

    def _write() -> None:
        fence_writes(
            conn,
            generation=int(marker[0]),
            source_fingerprint=str(marker[1]),
        )
        conn.execute(
            "UPDATE cutover_rollback_state SET forward_only=1, "
            "v2_writes_enabled=0, preferred_selection_enabled=0, "
            "publication_enabled=0 WHERE id=1"
        )
        _append_receipt(
            conn, "forward_rollback", kind=None,
            actor=clean_actor, reason=clean_reason,
            detail={"inventory_hash": state.inventory_hash},
        )

    _in_savepoint(conn, _write)
    return read_rollback_state(conn)


def authorize_old_writer_reopen(conn: sqlite3.Connection) -> None:
    state = read_rollback_state(conn)
    if state.forward_only or _marker_row(conn) is not None:
        _refuse(RollbackCode.OLD_WRITER_FORBIDDEN, "post_cutover_write")


def compatibility_mode(
    conn: sqlite3.Connection,
    *,
    representable: bool,
) -> CompatibilityMode:
    if not representable:
        return CompatibilityMode.UNAVAILABLE
    return (
        CompatibilityMode.READ_ONLY
        if read_rollback_state(conn).forward_only
        else CompatibilityMode.READ_WRITE
    )
