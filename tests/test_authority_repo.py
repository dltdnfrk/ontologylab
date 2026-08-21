"""Wave 2.1 Step 3 (3B): typed authority repository semantics.

Reserve-then-observe-then-assert in one caller-owned transaction; typed
conflicts for an owned identifier, a second DOI on one Work, and the
concurrent reservation loser; append-only assertion/decision tables; and
acyclic redirect projection where compensation supersedes without rewriting
FKs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.authority_repo import (
    IdentifierOwnedConflict,
    SecondDoiAttachConflict,
    attach_identifier,
    create_work,
    map_identifier_integrity_error,
)
from ontologylab.work_redirects import RedirectCycleError, record_redirect
from ontologylab.kgstore import KGStore


def _open(tmp_path: Path, name: str = "kg.sqlite") -> KGStore:
    return KGStore.open(tmp_path / name)


def test_attach_reserves_observes_and_asserts_in_one_transaction(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        work = create_work(store.conn, "w-a")
        result = attach_identifier(
            store.conn,
            work_id=work,
            scheme="doi",
            normalized_value="10.1000/repo.a",
            idempotency_key="op-attach-a",
            source="paper_api",
            evidence_grade="A",
        )
        assert result.created is True
        identifier, observation, assertion = store.conn.execute(
            "SELECT wi.id, o.id, ia.identifier_id FROM work_identifiers wi "
            "JOIN identifier_assertions ia ON ia.identifier_id = wi.id "
            "JOIN document_observations o ON o.id = ia.observation_id "
            "WHERE wi.id = ?",
            (result.identifier_id,),
        ).fetchone()
        assert identifier == result.identifier_id
        assert observation == result.observation_id
        assert assertion == result.identifier_id
        store.conn.execute("COMMIT")
        rows = store.conn.execute(
            "SELECT COUNT(*) FROM identifier_assertions"
        ).fetchone()[0]
        assert rows == 1
    finally:
        store.close()


def test_attach_retry_is_idempotent_on_idempotency_key(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        work = create_work(store.conn, "w-a")
        first = attach_identifier(
            store.conn, work_id=work, scheme="doi",
            normalized_value="10.1000/repo.retry", idempotency_key="op-x",
        )
        second = attach_identifier(
            store.conn, work_id=work, scheme="doi",
            normalized_value="10.1000/repo.retry", idempotency_key="op-x",
        )
        assert second.created is False
        assert second.observation_id == first.observation_id
        assert second.identifier_id == first.identifier_id
        assert store.conn.execute(
            "SELECT COUNT(*) FROM document_observations"
        ).fetchone()[0] == 1
    finally:
        store.close()


def test_owned_identifier_raises_typed_conflict_with_no_partial_rows(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        create_work(store.conn, "w-a")
        create_work(store.conn, "w-b")
        attach_identifier(
            store.conn, work_id="w-a", scheme="doi",
            normalized_value="10.1000/repo.owned", idempotency_key="op-1",
        )
        with pytest.raises(IdentifierOwnedConflict) as raised:
            attach_identifier(
                store.conn, work_id="w-b", scheme="doi",
                normalized_value="10.1000/repo.owned",
                idempotency_key="op-2", representation_id="doc-ghost",
            )
        assert raised.value.existing_work_id == "w-a"
        assert raised.value.normalized_value == "10.1000/repo.owned"
        # No partial Observation/assertion survived the refused attach.
        assert store.conn.execute(
            "SELECT COUNT(*) FROM document_observations WHERE idempotency_key='op-2'"
        ).fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM work_identifiers WHERE normalized_value='10.1000/repo.owned'"
        ).fetchone()[0] == 1
    finally:
        store.close()


def test_second_accepted_doi_on_one_work_is_typed_conflict(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        create_work(store.conn, "w-a")
        attach_identifier(
            store.conn, work_id="w-a", scheme="doi",
            normalized_value="10.1000/repo.first", idempotency_key="op-a",
        )
        with pytest.raises(SecondDoiAttachConflict) as raised:
            attach_identifier(
                store.conn, work_id="w-a", scheme="doi",
                normalized_value="10.1000/repo.second", idempotency_key="op-b",
            )
        assert raised.value.work_id == "w-a"
        assert raised.value.existing_doi == "10.1000/repo.first"
        assert raised.value.incoming_doi == "10.1000/repo.second"
    finally:
        store.close()


def test_concurrent_reservation_loser_gets_typed_conflict(tmp_path: Path) -> None:
    """The loser's INSERT hits the committed winner's partial index; the
    typed conflict is produced from the race path, not the pre-check."""
    db = tmp_path / "kg.sqlite"
    loser = KGStore.open(db)
    try:
        create_work(loser.conn, "w-lose")
        loser.conn.execute("COMMIT")
    finally:
        loser.close()

    winner = KGStore.open(db)
    try:
        create_work(winner.conn, "w-win")
        attach_identifier(
            winner.conn, work_id="w-win", scheme="doi",
            normalized_value="10.1000/repo.race", idempotency_key="op-win",
        )
        winner.conn.execute("COMMIT")
    finally:
        winner.close()

    loser = KGStore.open(db)
    try:
        with pytest.raises(IdentifierOwnedConflict):
            attach_identifier(
                loser.conn, work_id="w-lose", scheme="doi",
                normalized_value="10.1000/repo.race", idempotency_key="op-lose",
                begin_before_check=False,
            )
    finally:
        loser.close()


def test_mapper_distinguishes_the_two_conflicts(tmp_path: Path) -> None:
    """The mapper re-queries authoritative state: an IntegrityError caused by
    a foreign owner maps to IdentifierOwnedConflict; one caused by a second
    accepted DOI on the same Work maps to SecondDoiAttachConflict."""
    store = _open(tmp_path)
    try:
        create_work(store.conn, "w-x")
        create_work(store.conn, "w-y")
        attach_identifier(
            store.conn, work_id="w-x", scheme="doi",
            normalized_value="10.1000/m", idempotency_key="op-map",
        )
        with pytest.raises(sqlite3.IntegrityError) as owner_err:
            store.conn.execute(
                "INSERT INTO work_identifiers (id, work_id, scheme, "
                "normalized_value, status, created_ts) "
                "VALUES ('wi-ghost', 'w-y', 'doi', '10.1000/m', 'accepted', 0)"
            )
        owner = map_identifier_integrity_error(
            store.conn, owner_err.value, work_id="w-y", scheme="doi",
            normalized_value="10.1000/m",
        )
        assert isinstance(owner, IdentifierOwnedConflict)
        assert owner.existing_work_id == "w-x"

        with pytest.raises(sqlite3.IntegrityError) as second_err:
            store.conn.execute(
                "INSERT INTO work_identifiers (id, work_id, scheme, "
                "normalized_value, status, created_ts) "
                "VALUES ('wi-ghost2', 'w-x', 'doi', '10.1000/other', 'accepted', 0)"
            )
        second = map_identifier_integrity_error(
            store.conn, second_err.value, work_id="w-x", scheme="doi",
            normalized_value="10.1000/other",
        )
        assert isinstance(second, SecondDoiAttachConflict)
        assert second.existing_doi == "10.1000/m"
    finally:
        store.close()


def test_assertions_and_redirect_decisions_are_append_only(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        create_work(store.conn, "w-a")
        result = attach_identifier(
            store.conn, work_id="w-a", scheme="doi",
            normalized_value="10.1000/repo.append", idempotency_key="op-ap",
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.conn.execute(
                "UPDATE identifier_assertions SET observation_id='ghost' "
                "WHERE identifier_id=?",
                (result.identifier_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.conn.execute(
                "DELETE FROM identifier_assertions WHERE identifier_id=?",
                (result.identifier_id,),
            )
    finally:
        store.close()


def test_redirect_cycle_refused_and_compensation_supersedes(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        create_work(store.conn, "w-a")
        create_work(store.conn, "w-b")
        first = record_redirect(
            store.conn, source_work_id="w-a", target_work_id="w-b",
            action="merge", actor="qa", reason="dedupe a into b",
        )
        with pytest.raises(RedirectCycleError):
            record_redirect(
                store.conn, source_work_id="w-b", target_work_id="w-a",
                action="merge", actor="qa", reason="would cycle",
            )
        # Compensation supersedes the merge: the active projection drops it,
        # so the reverse direction is recordable without rewriting any FK.
        record_redirect(
            store.conn, source_work_id="w-a", target_work_id="w-b",
            action="compensate", actor="qa", reason="undo the merge",
            supersedes_id=first.decision_id,
        )
        active = store.conn.execute(
            "SELECT action FROM work_redirect_decisions ORDER BY created_ts"
        ).fetchall()
        assert [row[0] for row in active] == ["merge", "compensate"]
        reverse = record_redirect(
            store.conn, source_work_id="w-b", target_work_id="w-a",
            action="merge", actor="qa", reason="now acyclic",
        )
        assert reverse.decision_id
    finally:
        store.close()
