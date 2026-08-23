"""Reader-side ready-only and path-containment view of Representation bytes."""

from __future__ import annotations

from pathlib import Path

import pytest

from ontologylab.file_lifecycle import (
    content_hash_for,
    finalize_representation,
)
from ontologylab.ingestion_service import IngestItem, RepresentationInput, ingest_item
from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.work_view import work_snapshot


BODY = b"document view ready body\n"
SENTINEL = "ELS-must-never-surface-9f3a"


def test_document_view_reads_ready_bytes_only(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        receipt = ingest_item(
            store.conn,
            IngestItem(
                idempotency_key="op-view",
                scheme="doi",
                normalized_value="10.1000/view.ready",
                source="crossref",
                evidence_grade="A",
                representation=RepresentationInput(
                    source_kind="paper_api",
                    source_uri="https://doi.org/10.1000/view.ready",
                    title="View",
                    content_hash=content_hash_for(BODY),
                    raw_text=BODY,
                ),
                stage="published",
                content_kind="fulltext",
            ),
        )
        assert receipt.status == "staged"
        assert receipt.representation_id is not None
        assert receipt.work_id is not None
        store.conn.commit()
        with pytest.raises(KGStoreError):
            store.document_raw_text(receipt.representation_id)
        staged = work_snapshot(store.conn, receipt.work_id)
        assert staged["preferred_representation_id"] is None
        finalize_representation(
            store.conn, tmp_path, receipt.representation_id
        )
        assert store.document_raw_text(receipt.representation_id) == BODY.decode(
            "utf-8"
        )
        ready = work_snapshot(store.conn, receipt.work_id)
        assert ready["preferred_representation_id"] == receipt.representation_id
    finally:
        store.close()


def test_document_view_refuses_planted_store_and_absolute_paths(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        (tmp_path / "sources.json").write_text(SENTINEL, encoding="utf-8")
        store.conn.execute(
            "INSERT INTO documents "
            "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
            "raw_text_path, representation_state) "
            "VALUES ('rep-src', 'upload', 'file:sources.json', 'x', 0.0, "
            "'sha256:src', 'sources.json', 'ready')"
        )
        store.conn.execute(
            "INSERT INTO documents "
            "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
            "raw_text_path, representation_state) "
            "VALUES ('rep-abs', 'upload', 'file:/etc/passwd', 'x', 0.0, "
            "'sha256:abs', '/etc/passwd', 'ready')"
        )
        with pytest.raises(KGStoreError):
            store.document_raw_text("rep-src")
        with pytest.raises(KGStoreError):
            store.document_raw_text("rep-abs")
    finally:
        store.close()


def test_v2_ready_bytes_read_when_work_id_and_hash_match(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        receipt = ingest_item(
            store.conn,
            IngestItem(
                idempotency_key="op-v2-match",
                scheme="doi",
                normalized_value="10.1000/view.match",
                source="crossref",
                evidence_grade="A",
                representation=RepresentationInput(
                    source_kind="paper_api",
                    source_uri="https://doi.org/10.1000/view.match",
                    title="Match",
                    content_hash=content_hash_for(BODY),
                    raw_text=BODY,
                ),
                stage="published",
                content_kind="fulltext",
            ),
        )
        assert receipt.work_id is not None
        assert receipt.representation_id is not None
        store.conn.commit()
        finalize_representation(store.conn, tmp_path, receipt.representation_id)
        row = store.conn.execute(
            "SELECT work_id, content_hash FROM documents WHERE id = ?",
            (receipt.representation_id,),
        ).fetchone()
        assert row["work_id"] == receipt.work_id
        assert row["content_hash"] == content_hash_for(BODY)
        assert store.document_raw_text(receipt.representation_id) == BODY.decode(
            "utf-8"
        )
    finally:
        store.close()


def test_v2_ready_read_fails_typed_when_hash_mismatches(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        receipt = ingest_item(
            store.conn,
            IngestItem(
                idempotency_key="op-v2-tamper",
                scheme="doi",
                normalized_value="10.1000/view.tamper",
                source="crossref",
                evidence_grade="A",
                representation=RepresentationInput(
                    source_kind="paper_api",
                    source_uri="https://doi.org/10.1000/view.tamper",
                    title="Tamper",
                    content_hash=content_hash_for(BODY),
                    raw_text=BODY,
                ),
                stage="published",
                content_kind="fulltext",
            ),
        )
        assert receipt.work_id is not None
        assert receipt.representation_id is not None
        store.conn.commit()
        finalize_representation(store.conn, tmp_path, receipt.representation_id)
        relative = store.conn.execute(
            "SELECT raw_text_path FROM documents WHERE id = ?",
            (receipt.representation_id,),
        ).fetchone()["raw_text_path"]
        (tmp_path / relative).write_bytes(BODY[:-1] + b"X")
        with pytest.raises(KGStoreError, match="hash") as caught:
            store.document_raw_text(receipt.representation_id)
        assert SENTINEL not in str(caught.value)
        assert BODY.decode("utf-8") not in str(caught.value)
    finally:
        store.close()


def test_legacy_read_fails_typed_when_path_leaves_store_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    root.mkdir()
    store = KGStore.open(root / "kg.sqlite")
    try:
        (tmp_path / "secret.txt").write_text(SENTINEL, encoding="utf-8")
        (root / "sources.json").write_text(SENTINEL, encoding="utf-8")
        store.conn.execute(
            "INSERT INTO documents "
            "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
            "raw_text_path, representation_state) VALUES "
            "('rep-trav', 'upload', 'file:trav', 'x', 0.0, 'sha256:trav', "
            "'../secret.txt', 'ready')"
        )
        store.conn.execute(
            "INSERT INTO documents "
            "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
            "raw_text_path, representation_state) VALUES "
            "('rep-abs2', 'upload', 'file:abs', 'x', 0.0, 'sha256:abs2', "
            "'/etc/passwd', 'ready')"
        )
        store.conn.execute(
            "INSERT INTO documents "
            "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
            "raw_text_path, representation_state) VALUES "
            "('rep-sens', 'upload', 'file:sens', 'x', 0.0, 'sha256:sens', "
            "'sources.json', 'ready')"
        )
        for doc_id in ("rep-trav", "rep-abs2", "rep-sens"):
            with pytest.raises(KGStoreError) as caught:
                store.document_raw_text(doc_id)
            assert SENTINEL not in str(caught.value)
    finally:
        store.close()
