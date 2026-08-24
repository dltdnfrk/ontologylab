"""Privileged additive recovery operations after forward rollback."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ontologylab.cutover_rehearsal import _in_savepoint
from ontologylab.cutover_rollback_store import (
    append_receipt,
    marker_row,
    read_rollback_state,
)
from ontologylab.cutover_rollback_types import (
    FactRetraction,
    MutationKind,
    RedirectCompensation,
    RollbackCode,
    refuse,
    require_text,
)
from ontologylab.grounded_review import apply_review
from ontologylab.grounded_review_types import (
    ReviewAction,
    ReviewBatchResult,
    ReviewRequest,
)
from ontologylab.pack_verifier import verify_pack
from ontologylab.work_redirects import RedirectResult, record_redirect


def _require_forward(conn: sqlite3.Connection) -> None:
    if marker_row(conn) is None:
        refuse(RollbackCode.MARKER_REQUIRED, "post_cutover_write")
    if not read_rollback_state(conn).forward_only:
        refuse(RollbackCode.MARKER_REQUIRED, "forward_rollback")


def record_redirect_compensation(
    conn: sqlite3.Connection,
    *,
    merge_decision_id: str,
    actor: str,
    reason: str,
) -> RedirectCompensation:
    _require_forward(conn)
    clean_actor = require_text(actor, "actor")
    clean_reason = require_text(reason, "reason")
    row = conn.execute(
        "SELECT source_work_id, target_work_id, action "
        "FROM work_redirect_decisions WHERE id=?",
        (merge_decision_id,),
    ).fetchone()
    if row is None or str(row[2]) != "merge":
        refuse(RollbackCode.INVALID_INPUT, "merge_decision_id")
    if conn.execute(
        "SELECT 1 FROM work_redirect_decisions "
        "WHERE action='compensate' AND supersedes_id=?",
        (merge_decision_id,),
    ).fetchone() is not None:
        refuse(RollbackCode.INVALID_INPUT, "already_compensated")
    result: RedirectResult | None = None

    def _write() -> None:
        nonlocal result
        result = record_redirect(
            conn,
            source_work_id=str(row[0]),
            target_work_id=str(row[1]),
            action="compensate",
            actor=clean_actor,
            reason=clean_reason,
            supersedes_id=merge_decision_id,
        )
        append_receipt(
            conn, "redirect_compensation", kind=MutationKind.IDENTITY,
            actor=clean_actor, reason=clean_reason,
            detail={"supersedes_id": merge_decision_id},
        )

    _in_savepoint(conn, _write)
    assert result is not None
    return RedirectCompensation(result.decision_id, merge_decision_id)


def record_fact_retraction(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    actor: str,
    reason: str,
) -> FactRetraction:
    _require_forward(conn)
    clean_actor = require_text(actor, "actor")
    clean_reason = require_text(reason, "reason")
    result: ReviewBatchResult | None = None

    def _write() -> None:
        nonlocal result
        result = apply_review(
            conn,
            ReviewRequest(
                item_id=item_id,
                actor=clean_actor,
                reason=clean_reason,
                action=ReviewAction.RETRACT,
                require_citations=True,
            ),
        )
        append_receipt(
            conn, "fact_retraction", kind=MutationKind.EXTRACTION_REVIEW,
            actor=clean_actor, reason=clean_reason,
            detail={"item_id": item_id},
        )

    _in_savepoint(conn, _write)
    assert result is not None
    citation_ids = tuple(
        str(row[0]) for row in conn.execute(
            "SELECT receipt_id FROM citation_receipts "
            "WHERE fact_kind=? AND fact_id=? ORDER BY receipt_id",
            (result.kind, item_id),
        )
    )
    return FactRetraction(
        tuple(decision.receipt_id for decision in result.decisions),
        citation_ids,
    )


def record_recovery_pack(
    conn: sqlite3.Connection,
    *,
    old_pack_path: Path,
    new_pack_path: Path,
    actor: str,
    reason: str,
) -> None:
    _require_forward(conn)
    old_pack_hash = verify_pack(old_pack_path).pack_content_hash
    new_pack_hash = verify_pack(new_pack_path).pack_content_hash
    if old_pack_hash == new_pack_hash:
        refuse(RollbackCode.PACK_UNCHANGED, "pack_content_hash")
    clean_actor = require_text(actor, "actor")
    clean_reason = require_text(reason, "reason")

    def _write() -> None:
        append_receipt(
            conn, "recovery_pack", kind=MutationKind.PUBLICATION,
            actor=clean_actor, reason=clean_reason,
            detail={
                "old_pack_hash": old_pack_hash,
                "new_pack_hash": new_pack_hash,
            },
        )

    _in_savepoint(conn, _write)
