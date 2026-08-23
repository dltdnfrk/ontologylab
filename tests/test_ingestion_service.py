"""Wave 2.1 Step 6 (6A): transactional ingestion service v2 core."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ontologylab.file_lifecycle import content_hash_for
from ontologylab.ingestion_service import (
    IngestItem,
    RepresentationInput,
    ingest_item,
    ingest_items,
    ingest_work_items,
)
from ontologylab.kgstore import KGStore


def _open(tmp_path: Path) -> KGStore:
    return KGStore.open(tmp_path / "kg.sqlite")


def _item(
    *,
    operation: str = "op-1",
    doi: str = "10.1000/service.one",
    work_id: str | None = None,
    representation_id: str | None = None,
) -> IngestItem:
    representation = None
    if representation_id is None:
        representation = RepresentationInput(
            source_kind="paper_api",
            source_uri=f"https://doi.org/{doi}",
            title="Transactional ingestion",
            content_hash=f"sha256:{operation}",
            raw_text_path=f"documents/{operation}/raw.txt",
        )
    return IngestItem(
        idempotency_key=operation,
        scheme="doi",
        normalized_value=doi,
        source="crossref",
        evidence_grade="A",
        work_id=work_id,
        representation_id=representation_id,
        representation=representation,
        stage="version_of_record",
        content_kind="abstract",
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _raw_item(
    body: bytes,
    *,
    content_hash: str | None = None,
) -> IngestItem:
    return IngestItem(
        idempotency_key="op-raw",
        scheme="doi",
        normalized_value="10.1000/service.raw",
        source="crossref",
        evidence_grade="A",
        representation=RepresentationInput(
            source_kind="paper_api",
            source_uri="https://doi.org/10.1000/service.raw",
            title="Transactional raw ingestion",
            content_hash=content_hash or content_hash_for(body),
            raw_text=body,
        ),
        stage="version_of_record",
        content_kind="fulltext",
    )


def test_created_receipt_binds_one_family_in_one_unit(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(store.conn, _item())

        assert receipt.status == "created"
        assert receipt.work_id
        assert receipt.representation_id
        assert receipt.observation_id
        assert receipt.identifier_id
        assert receipt.conflict is None
        assert receipt.error is None
        assert receipt.work_created is True
        assert receipt.representation_created is True
        assert receipt.observation_created is True
        linked = store.conn.execute(
            "SELECT wi.work_id, o.representation_id "
            "FROM identifier_assertions ia "
            "JOIN work_identifiers wi ON wi.id = ia.identifier_id "
            "JOIN document_observations o ON o.id = ia.observation_id "
            "WHERE ia.identifier_id = ? AND ia.observation_id = ?",
            (receipt.identifier_id, receipt.observation_id),
        ).fetchone()
        assert tuple(linked) == (receipt.work_id, receipt.representation_id)
        assert _count(store.conn, "works") == 1
        assert _count(store.conn, "documents") == 1
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "identifier_assertions") == 1
    finally:
        store.close()


def test_raw_bytes_report_staged_until_file_finalization(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(store.conn, _raw_item(b"raw body\n"))

        assert receipt.status == "staged"
        assert receipt.representation_id is not None
        row = store.conn.execute(
            "SELECT representation_state FROM documents WHERE id = ?",
            (receipt.representation_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "staged"
    finally:
        store.close()


def test_initial_raw_hash_mismatch_fails_without_partial_state(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(
            store.conn,
            _raw_item(b"raw body\n", content_hash="sha256:not-the-body"),
        )

        assert receipt.status == "failed"
        assert receipt.error is not None
        assert receipt.error.startswith("FileIntegrityError:")
        for table in (
            "works",
            "documents",
            "document_observations",
            "identifier_assertions",
            "provenance_outbox",
        ):
            assert _count(store.conn, table) == 0
    finally:
        store.close()


def test_same_idempotency_key_returns_typed_duplicate(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        first = ingest_item(store.conn, _item())
        second = ingest_item(store.conn, _item())

        assert first.status == "created"
        assert second.status == "duplicate"
        assert second.work_id == first.work_id
        assert second.representation_id == first.representation_id
        assert second.observation_id == first.observation_id
        assert second.identifier_id == first.identifier_id
        assert second.work_created is False
        assert second.representation_created is False
        assert second.observation_created is False
        assert _count(store.conn, "works") == 1
        assert _count(store.conn, "documents") == 1
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "identifier_assertions") == 1
    finally:
        store.close()


def test_second_doi_is_typed_conflict_not_duplicate_or_merge(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        first = ingest_item(store.conn, _item())
        conflict = ingest_item(
            store.conn,
            _item(
                operation="op-2",
                doi="10.1000/service.two",
                work_id=first.work_id,
                representation_id=first.representation_id,
            ),
        )

        assert conflict.status == "conflict"
        assert conflict.conflict is not None
        assert conflict.conflict.kind == "second_doi"
        assert conflict.conflict.work_id == first.work_id
        assert conflict.conflict.existing_value == "10.1000/service.one"
        assert conflict.conflict.incoming_value == "10.1000/service.two"
        assert conflict.work_id == first.work_id
        assert _count(store.conn, "works") == 1
        assert _count(store.conn, "work_identifiers") == 1
        assert _count(store.conn, "document_observations") == 1
    finally:
        store.close()


def test_failpoint_after_authority_write_leaves_zero_partial_rows(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)

    def failpoint(stage: str) -> None:
        if stage == "after_authority":
            raise RuntimeError("armed:after_authority")

    try:
        receipt = ingest_item(store.conn, _item(), failpoint=failpoint)

        assert receipt.status == "failed"
        assert receipt.error == "RuntimeError: armed:after_authority"
        for table in (
            "works",
            "documents",
            "work_identifiers",
            "document_observations",
            "identifier_assertions",
        ):
            assert _count(store.conn, table) == 0
    finally:
        store.close()


def test_failpoint_between_reservation_and_observation_leaves_no_partial_rows(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)

    def failpoint(stage: str) -> None:
        if stage == "after_identifier_reservation":
            raise RuntimeError("armed:after_identifier_reservation")

    try:
        receipt = ingest_item(store.conn, _item(), failpoint=failpoint)

        assert receipt.status == "failed"
        assert receipt.error == (
            "RuntimeError: armed:after_identifier_reservation"
        )
        for table in (
            "works",
            "documents",
            "work_identifiers",
            "document_observations",
            "identifier_assertions",
        ):
            assert _count(store.conn, table) == 0
    finally:
        store.close()


def test_service_never_commits_callers_transaction(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        store.conn.execute("SAVEPOINT caller")
        receipt = ingest_item(store.conn, _item())
        assert receipt.status == "created"
        store.conn.execute("ROLLBACK TO SAVEPOINT caller")
        store.conn.execute("RELEASE SAVEPOINT caller")

        for table in (
            "works",
            "documents",
            "work_identifiers",
            "document_observations",
            "identifier_assertions",
        ):
            assert _count(store.conn, table) == 0
    finally:
        store.close()


def test_batch_has_typed_per_item_failure_without_silent_partial_success(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)

    def fail_second(stage: str, item: IngestItem) -> None:
        if item.idempotency_key == "op-bad" and stage == "after_authority":
            raise RuntimeError("armed:batch")

    try:
        receipts = ingest_work_items(
            store.conn,
            (_item(operation="op-good"), _item(operation="op-bad")),
            failpoint=fail_second,
        )

        assert [receipt.status for receipt in receipts] == ["created", "failed"]
        assert receipts[1].error == "RuntimeError: armed:batch"
        assert _count(store.conn, "works") == 1
        assert _count(store.conn, "documents") == 1
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "identifier_assertions") == 1
    finally:
        store.close()


def test_invalid_identifier_is_typed_failed_while_valid_batch_item_lands(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        invalid = _item(operation="op-invalid")
        invalid = IngestItem(
            idempotency_key=invalid.idempotency_key,
            scheme="unknown",
            normalized_value="",
        )
        receipts = ingest_items(
            store.conn,
            (_item(operation="op-valid"), invalid),
        )

        assert [receipt.status for receipt in receipts] == ["created", "failed"]
        assert receipts[1].error is not None
        assert receipts[1].error.startswith("InvalidIngestItem:")
        assert _count(store.conn, "works") == 1
        assert _count(store.conn, "document_observations") == 1
    finally:
        store.close()
