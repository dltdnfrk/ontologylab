"""Wave 2.1 Step 4 (4A): audited identity decision operations.

Every decision carries actor/reason/time in the append-only
``identifier_decisions`` audit table; retraction is a write-once status
transition; ambiguous collisions become deterministic PENDING records with
zero accepted owner. No hard delete exists anywhere on this surface.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.authority_repo import attach_identifier, create_work
from ontologylab.identity_decisions import (
    DecisionInputInvalid,
    IdentifierAlreadyRetracted,
    attach_with_decision,
    record_collision,
    retract_identifier,
)
from ontologylab.kgstore import KGStore


@pytest.fixture()
def store(tmp_path: Path):
    s = KGStore.open(tmp_path / "kg.sqlite")
    yield s
    s.close()


def _audit_rows(conn: sqlite3.Connection, action: str | None = None) -> list:
    sql = "SELECT id, identifier_id, action, actor, reason FROM identifier_decisions"
    if action:
        return conn.execute(sql + " WHERE action = ?", (action,)).fetchall()
    return conn.execute(sql).fetchall()


def test_attach_with_decision_writes_the_audit_row(store) -> None:
    create_work(store.conn, "w-a")
    result, receipt = attach_with_decision(
        store.conn, work_id="w-a", scheme="doi",
        normalized_value="10.1000/dec.a", idempotency_key="op-a",
        actor="curator", reason="verified against Crossref record",
    )
    rows = _audit_rows(store.conn, "attach")
    assert len(rows) == 1
    assert rows[0]["identifier_id"] == result.identifier_id
    assert rows[0]["actor"] == "curator"
    assert rows[0]["reason"] == "verified against Crossref record"
    assert receipt.action == "attach"
    ts = store.conn.execute(
        "SELECT created_ts FROM identifier_decisions WHERE id = ?",
        (receipt.decision_id,),
    ).fetchone()[0]
    assert ts > 0


def test_empty_actor_or_reason_is_typed_with_no_rows_written(store) -> None:
    create_work(store.conn, "w-a")
    for actor, reason in (("", "valid reason"), ("curator", ""), ("  ", "x")):
        with pytest.raises(DecisionInputInvalid):
            attach_with_decision(
                store.conn, work_id="w-a", scheme="doi",
                normalized_value="10.1000/dec.gate", idempotency_key="op-g",
                actor=actor, reason=reason,
            )
    assert _audit_rows(store.conn) == []
    assert store.conn.execute(
        "SELECT COUNT(*) FROM work_identifiers"
    ).fetchone()[0] == 0
    assert store.conn.execute(
        "SELECT COUNT(*) FROM document_observations"
    ).fetchone()[0] == 0


def test_retract_is_a_write_once_transition_that_frees_the_slot(store) -> None:
    create_work(store.conn, "w-a")
    create_work(store.conn, "w-b")
    result, _ = attach_with_decision(
        store.conn, work_id="w-a", scheme="doi",
        normalized_value="10.1000/dec.retract", idempotency_key="op-r",
        actor="curator", reason="initial attach",
    )
    receipt = retract_identifier(
        store.conn, identifier_id=result.identifier_id,
        actor="curator", reason="publisher withdrew the DOI",
    )
    assert receipt.action == "retract"
    status = store.conn.execute(
        "SELECT status FROM work_identifiers WHERE id = ?",
        (result.identifier_id,),
    ).fetchone()[0]
    assert status == "retracted"
    # The accepted-owner slot is free again: another Work may own the value.
    fresh = attach_identifier(
        store.conn, work_id="w-b", scheme="doi",
        normalized_value="10.1000/dec.retract", idempotency_key="op-r2",
    )
    assert fresh.identifier_id != result.identifier_id


def test_second_retract_is_typed_and_leaves_one_audit_row(store) -> None:
    create_work(store.conn, "w-a")
    result, _ = attach_with_decision(
        store.conn, work_id="w-a", scheme="doi",
        normalized_value="10.1000/dec.twice", idempotency_key="op-t",
        actor="curator", reason="initial attach",
    )
    retract_identifier(
        store.conn, identifier_id=result.identifier_id,
        actor="curator", reason="first retraction",
    )
    with pytest.raises(IdentifierAlreadyRetracted):
        retract_identifier(
            store.conn, identifier_id=result.identifier_id,
            actor="curator", reason="second retraction attempt",
        )
    assert len(_audit_rows(store.conn, "retract")) == 1


def test_collision_yields_deterministic_pending_records_zero_owner(store) -> None:
    create_work(store.conn, "w-a")
    create_work(store.conn, "w-b")
    first = record_collision(
        store.conn, scheme="doi", normalized_value="10.1000/dec.collide",
        work_ids=("w-a", "w-b"), actor="migration-planner",
        reason="two legacy rows derive the same DOI",
    )
    again = record_collision(
        store.conn, scheme="doi", normalized_value="10.1000/dec.collide",
        work_ids=("w-a", "w-b"), actor="migration-planner",
        reason="two legacy rows derive the same DOI",
    )
    assert first.pending_identifier_ids == again.pending_identifier_ids
    assert len(first.pending_identifier_ids) == 2
    statuses = [
        row[0] for row in store.conn.execute(
            "SELECT status FROM work_identifiers WHERE scheme='doi' "
            "AND normalized_value='10.1000/dec.collide'"
        )
    ]
    assert statuses == ["pending", "pending"]
    accepted = store.conn.execute(
        "SELECT COUNT(*) FROM work_identifiers WHERE scheme='doi' "
        "AND normalized_value='10.1000/dec.collide' AND status='accepted'"
    ).fetchone()[0]
    assert accepted == 0
    # Idempotent rerun adds no duplicate audit rows.
    assert len(_audit_rows(store.conn, "resolve_collision")) == 2


def test_decision_audit_table_is_append_only(store) -> None:
    create_work(store.conn, "w-a")
    _, receipt = attach_with_decision(
        store.conn, work_id="w-a", scheme="doi",
        normalized_value="10.1000/dec.append", idempotency_key="op-ap",
        actor="curator", reason="attach for append-only proof",
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "UPDATE identifier_decisions SET reason='rewritten' WHERE id=?",
            (receipt.decision_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "DELETE FROM identifier_decisions WHERE id=?",
            (receipt.decision_id,),
        )
