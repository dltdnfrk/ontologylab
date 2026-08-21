"""Shared reconciliation seam (Wave 2.1 Step 4).

One typed surface for the CLI and HTTP reconciliation endpoints so both
return the same state and conflict ids. Reads are pure; writes go through
the typed domain layers (identity_decisions, work_redirects) and commit at
the caller's boundary, never here.
"""

from __future__ import annotations

import sqlite3

from ontologylab.identity_decisions import (
    attach_with_decision,
    record_collision,
    retract_identifier,
)
from ontologylab.work_redirects import record_redirect
from ontologylab.work_view import work_snapshot


def list_state(conn: sqlite3.Connection) -> dict:
    """The whole reconciliation state as plain dicts (pure read)."""
    identifiers = [
        dict(row)
        for row in conn.execute(
            "SELECT id, work_id, scheme, normalized_value, status "
            "FROM work_identifiers ORDER BY created_ts"
        )
    ]
    return {
        "works": conn.execute("SELECT COUNT(*) FROM works").fetchone()[0],
        "identifiers": identifiers,
        "pending_identifiers": [
            row for row in identifiers if row["status"] == "pending"
        ],
        "identifier_decisions": conn.execute(
            "SELECT COUNT(*) FROM identifier_decisions"
        ).fetchone()[0],
        "redirect_decisions": conn.execute(
            "SELECT COUNT(*) FROM work_redirect_decisions"
        ).fetchone()[0],
        "pending_merge_candidates": conn.execute(
            "SELECT COUNT(*) FROM merge_candidates WHERE status = 'proposed'"
        ).fetchone()[0],
    }


def inspect_work(conn: sqlite3.Connection, work_id: str) -> dict:
    """work_snapshot plus the audit rows for that Work's identifiers."""
    snapshot = work_snapshot(conn, work_id)  # typed WorkNotFound
    identifier_ids = [row["id"] for row in snapshot["identifiers"]]
    decisions: list[dict] = []
    if identifier_ids:
        marks = ",".join("?" for _ in identifier_ids)
        decisions = [
            dict(row)
            for row in conn.execute(
                "SELECT id, identifier_id, action, actor, reason, created_ts "
                f"FROM identifier_decisions WHERE identifier_id IN ({marks}) "
                "ORDER BY created_ts",
                identifier_ids,
            )
        ]
    return {**snapshot, "decisions": decisions}


def attach(
    conn: sqlite3.Connection,
    *,
    work_id: str,
    scheme: str,
    normalized_value: str,
    idempotency_key: str,
    actor: str,
    reason: str,
    **attach_kwargs,
) -> dict:
    result, receipt = attach_with_decision(
        conn, work_id=work_id, scheme=scheme,
        normalized_value=normalized_value, idempotency_key=idempotency_key,
        actor=actor, reason=reason, **attach_kwargs,
    )
    return {
        "ok": True,
        "identifier_id": result.identifier_id,
        "observation_id": result.observation_id,
        "decision_id": receipt.decision_id,
    }


def retract(
    conn: sqlite3.Connection, *, identifier_id: str, actor: str, reason: str
) -> dict:
    receipt = retract_identifier(
        conn, identifier_id=identifier_id, actor=actor, reason=reason
    )
    return {
        "ok": True,
        "identifier_id": receipt.identifier_id,
        "decision_id": receipt.decision_id,
    }


def compensate(
    conn: sqlite3.Connection,
    *,
    source_work_id: str,
    target_work_id: str,
    supersedes_id: str,
    actor: str,
    reason: str,
    decided_ts: float | None = None,
) -> dict:
    result = record_redirect(
        conn, source_work_id=source_work_id, target_work_id=target_work_id,
        action="compensate", supersedes_id=supersedes_id, actor=actor,
        reason=reason, decided_ts=decided_ts,
    )
    return {"ok": True, "decision_id": result.decision_id}


def resolve_collision(
    conn: sqlite3.Connection,
    *,
    scheme: str,
    normalized_value: str,
    work_ids: list[str],
    actor: str,
    reason: str,
) -> dict:
    receipt = record_collision(
        conn, scheme=scheme, normalized_value=normalized_value,
        work_ids=tuple(work_ids), actor=actor, reason=reason,
    )
    return {
        "ok": True,
        "pending_identifier_ids": list(receipt.pending_identifier_ids),
        "decision_ids": list(receipt.decision_ids),
    }
