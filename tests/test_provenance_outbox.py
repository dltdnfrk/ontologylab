"""Wave 2.1 Step 6C / F5: transactional provenance outbox and projector."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ontologylab.ingestion_service import (
    IngestItem,
    RepresentationInput,
    ingest_item,
)
from ontologylab.kgstore import KGStore
from ontologylab.provenance_outbox import (
    MalformedOutboxPayload,
    canonical_json,
    event_id_for,
    insert_observation_event,
    load_outbox_events,
    project_outbox,
    provenance_jsonl_path,
)


def _open(tmp_path: Path) -> KGStore:
    return KGStore.open(tmp_path / "kg.sqlite")


def _item(
    *,
    operation: str = "op-1",
    doi: str = "10.1000/outbox.one",
) -> IngestItem:
    return IngestItem(
        idempotency_key=operation,
        scheme="doi",
        normalized_value=doi,
        source="crossref",
        evidence_grade="A",
        representation=RepresentationInput(
            source_kind="paper_api",
            source_uri=f"https://doi.org/{doi}",
            title="Transactional outbox",
            content_hash=f"sha256:{operation}",
            raw_text_path=f"documents/{operation}/raw.txt",
        ),
        stage="published",
        content_kind="abstract",
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _mirrored(conn: sqlite3.Connection) -> list[float | None]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT mirrored_ts FROM provenance_outbox ORDER BY seq, event_id"
        )
    ]


def _jsonl_event_ids(path: Path) -> list[str]:
    if not path.is_file():
        return []
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        payload = json.loads(line)
        ids.append(str(payload["event_id"]))
    return ids


def test_successful_observation_writes_one_deterministic_outbox_event(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(store.conn, _item())
        assert receipt.status == "created"
        assert receipt.observation_id is not None
        events = load_outbox_events(store.conn)
        assert len(events) == 1
        event = events[0]
        assert event.step == "observation.recorded"
        assert event.event_id == event_id_for(
            step="observation.recorded",
            observation_id=receipt.observation_id,
        )
        assert event.mirrored_ts is None
        payload = json.loads(event.payload_json)
        assert payload["event_id"] == event.event_id
        assert payload["observation_id"] == receipt.observation_id
        assert payload["work_id"] == receipt.work_id
        assert payload["representation_id"] == receipt.representation_id
        assert payload["identifier_id"] == receipt.identifier_id
        assert payload["idempotency_key"] == "op-1"
        assert event.payload_json == canonical_json(payload)
        again = ingest_item(store.conn, _item())
        assert again.status == "duplicate"
        assert _count(store.conn, "provenance_outbox") == 1
        assert _count(store.conn, "document_observations") == 1
    finally:
        store.close()


def test_outbox_event_shares_caller_savepoint(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        store.conn.execute("SAVEPOINT caller")
        receipt = ingest_item(store.conn, _item())
        assert receipt.status == "created"
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "provenance_outbox") == 1
        store.conn.execute("ROLLBACK TO SAVEPOINT caller")
        store.conn.execute("RELEASE SAVEPOINT caller")
        assert _count(store.conn, "document_observations") == 0
        assert _count(store.conn, "provenance_outbox") == 0
        assert _count(store.conn, "works") == 0
        assert _count(store.conn, "documents") == 0
    finally:
        store.close()


def test_project_outbox_rebuilds_canonical_jsonl_before_mark(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(store.conn, _item())
        assert receipt.status == "created"
        store.conn.commit()
        jsonl = provenance_jsonl_path(tmp_path)
        assert not jsonl.exists()
        assert _mirrored(store.conn) == [None]
        result = project_outbox(store.conn, tmp_path)
        store.conn.commit()
        assert result.written == 1
        assert result.marked == 1
        assert jsonl.is_file()
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["event_id"] == event_id_for(
            step="observation.recorded",
            observation_id=receipt.observation_id or "",
        )
        assert lines[0] == canonical_json(payload)
        assert _mirrored(store.conn) != [None]
        assert all(mark is not None for mark in _mirrored(store.conn))
    finally:
        store.close()


def test_caller_rollback_removes_domain_and_outbox(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        store.conn.execute("SAVEPOINT caller")
        receipt = ingest_item(
            store.conn, _item(operation="op-rollback", doi="10.1000/outbox.rb")
        )
        assert receipt.status == "created"
        store.conn.execute("ROLLBACK TO SAVEPOINT caller")
        store.conn.execute("RELEASE SAVEPOINT caller")
        project_outbox(store.conn, tmp_path)
        store.conn.commit()
        assert _count(store.conn, "provenance_outbox") == 0
        assert _jsonl_event_ids(provenance_jsonl_path(tmp_path)) == []
    finally:
        store.close()


def test_replay_yields_exactly_one_logical_and_physical_event(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        first = ingest_item(store.conn, _item())
        second = ingest_item(
            store.conn, _item(operation="op-2", doi="10.1000/outbox.two")
        )
        assert first.status == "created"
        assert second.status == "created"
        store.conn.commit()
        first_result = project_outbox(store.conn, tmp_path)
        store.conn.commit()
        jsonl = provenance_jsonl_path(tmp_path)
        before = jsonl.read_bytes()
        second_result = project_outbox(store.conn, tmp_path)
        store.conn.commit()
        after = jsonl.read_bytes()
        ids = _jsonl_event_ids(jsonl)
        assert first_result.written == 2
        assert second_result.written == 2
        assert len(ids) == 2
        assert len(set(ids)) == 2
        assert before == after
        assert ids == [event.event_id for event in load_outbox_events(store.conn)]
    finally:
        store.close()


def test_failpoint_after_mirror_before_mark_is_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(store.conn, _item())
        assert receipt.status == "created"
        store.conn.commit()

        def fail_after_mirror(stage: str) -> None:
            if stage == "after_durable_mirror":
                raise RuntimeError("armed:after_durable_mirror")

        with pytest.raises(RuntimeError, match="armed:after_durable_mirror"):
            project_outbox(store.conn, tmp_path, failpoint=fail_after_mirror)
        jsonl = provenance_jsonl_path(tmp_path)
        assert jsonl.is_file()
        first_bytes = jsonl.read_bytes()
        assert _jsonl_event_ids(jsonl) == [
            event_id_for(
                step="observation.recorded",
                observation_id=receipt.observation_id or "",
            )
        ]
        assert _mirrored(store.conn) == [None]

        result = project_outbox(store.conn, tmp_path)
        store.conn.commit()
        assert result.written == 1
        assert result.marked == 1
        assert jsonl.read_bytes() == first_bytes
        assert all(mark is not None for mark in _mirrored(store.conn))
    finally:
        store.close()


def test_failpoint_before_durable_mirror_leaves_projected_unset(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        ingest_item(store.conn, _item())
        store.conn.commit()
        jsonl = provenance_jsonl_path(tmp_path)

        def fail_before_mirror(stage: str) -> None:
            if stage == "before_durable_mirror":
                raise RuntimeError("armed:before_durable_mirror")

        with pytest.raises(RuntimeError, match="armed:before_durable_mirror"):
            project_outbox(store.conn, tmp_path, failpoint=fail_before_mirror)
        assert not jsonl.exists()
        assert _mirrored(store.conn) == [None]
    finally:
        store.close()


def test_malformed_payload_fails_closed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(store.conn, _item())
        assert receipt.status == "created"
        store.conn.commit()
        project_outbox(store.conn, tmp_path)
        store.conn.commit()
        jsonl = provenance_jsonl_path(tmp_path)
        good = jsonl.read_bytes()
        store.conn.execute(
            "INSERT INTO provenance_outbox "
            "(event_id, step, payload_json, created_ts, mirrored_ts) "
            "VALUES ('evt-bad', 'observation.recorded', '{not-json', 1.0, NULL)"
        )
        store.conn.commit()
        with pytest.raises(MalformedOutboxPayload):
            project_outbox(store.conn, tmp_path)
        assert jsonl.read_bytes() == good
        bad_mark = store.conn.execute(
            "SELECT mirrored_ts FROM provenance_outbox WHERE event_id = 'evt-bad'"
        ).fetchone()
        assert bad_mark is not None
        assert bad_mark[0] is None
    finally:
        store.close()


def test_torn_mirror_is_rebuilt_from_outbox(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(store.conn, _item())
        assert receipt.status == "created"
        store.conn.commit()
        jsonl = provenance_jsonl_path(tmp_path)
        jsonl.write_text(
            '{"event_id":"stale"}\n{"event_id":"torn',
            encoding="utf-8",
        )
        result = project_outbox(store.conn, tmp_path)
        store.conn.commit()
        assert result.written == 1
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["event_id"] == event_id_for(
            step="observation.recorded",
            observation_id=receipt.observation_id or "",
        )
        assert "torn" not in jsonl.read_text(encoding="utf-8")
        assert "stale" not in jsonl.read_text(encoding="utf-8")
    finally:
        store.close()


def test_projection_order_follows_seq_not_event_id(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        store.conn.execute(
            "INSERT INTO provenance_outbox "
            "(event_id, step, payload_json, created_ts, mirrored_ts) VALUES "
            "('z-last-lexically', 'observation.recorded', ?, 1.0, NULL)",
            (canonical_json({"event_id": "z-last-lexically", "n": 1}),),
        )
        store.conn.execute(
            "INSERT INTO provenance_outbox "
            "(event_id, step, payload_json, created_ts, mirrored_ts) VALUES "
            "('a-first-lexically', 'observation.recorded', ?, 2.0, NULL)",
            (canonical_json({"event_id": "a-first-lexically", "n": 2}),),
        )
        store.conn.commit()
        project_outbox(store.conn, tmp_path)
        store.conn.commit()
        assert _jsonl_event_ids(provenance_jsonl_path(tmp_path)) == [
            "z-last-lexically",
            "a-first-lexically",
        ]
    finally:
        store.close()


def test_conflict_does_not_write_outbox(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        first = ingest_item(store.conn, _item())
        conflict = ingest_item(
            store.conn,
            IngestItem(
                idempotency_key="op-2",
                scheme="doi",
                normalized_value="10.1000/outbox.two",
                work_id=first.work_id,
                representation_id=first.representation_id,
            ),
        )
        assert first.status == "created"
        assert conflict.status == "conflict"
        assert _count(store.conn, "provenance_outbox") == 1
        assert _count(store.conn, "document_observations") == 1
    finally:
        store.close()


def test_outbox_never_commits_or_rolls_back_caller_transaction(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        store.conn.execute("SAVEPOINT caller")
        receipt = ingest_item(store.conn, _item())
        assert receipt.status == "created"
        assert store.conn.in_transaction
        insert_observation_event(
            store.conn,
            observation_id=receipt.observation_id or "obs-x",
            work_id=receipt.work_id,
            representation_id=receipt.representation_id,
            identifier_id=receipt.identifier_id,
            idempotency_key=receipt.idempotency_key,
        )
        assert store.conn.in_transaction
        store.conn.commit()
        store.conn.execute("SAVEPOINT projector")
        project_outbox(store.conn, tmp_path)
        assert store.conn.in_transaction
        store.conn.execute("ROLLBACK TO SAVEPOINT projector")
        store.conn.execute("RELEASE SAVEPOINT projector")
        assert _mirrored(store.conn) == [None]
        outbox_src = Path("ontologylab/provenance_outbox.py").read_text(
            encoding="utf-8"
        )
        service_src = Path("ontologylab/ingestion_service.py").read_text(
            encoding="utf-8"
        )
        assert "conn.commit(" not in outbox_src
        assert "conn.rollback(" not in outbox_src
        assert "conn.commit(" not in service_src
        assert "conn.rollback(" not in service_src
    finally:
        store.close()


def test_repository_insert_is_idempotent_on_event_id(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        first = insert_observation_event(
            store.conn,
            observation_id="obs-same",
            work_id="work-1",
            representation_id="rep-1",
            identifier_id="wi-1",
            idempotency_key="op-same",
        )
        second = insert_observation_event(
            store.conn,
            observation_id="obs-same",
            work_id="work-1",
            representation_id="rep-1",
            identifier_id="wi-1",
            idempotency_key="op-same",
        )
        assert first.event_id == second.event_id
        assert _count(store.conn, "provenance_outbox") == 1
    finally:
        store.close()


def test_writable_open_projects_unmirrored_outbox(tmp_path: Path) -> None:
    store = _open(tmp_path)
    receipt = ingest_item(store.conn, _item())
    assert receipt.status == "created"
    store.conn.commit()
    event_id = load_outbox_events(store.conn)[0].event_id
    assert _mirrored(store.conn) == [None]
    store.close()

    reopened = _open(tmp_path)
    try:
        assert _mirrored(reopened.conn)[0] is not None
        assert _jsonl_event_ids(provenance_jsonl_path(tmp_path)) == [event_id]
    finally:
        reopened.close()
