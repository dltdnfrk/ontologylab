"""Typed collect writer: per-item failures, identity, batching, finalize."""
# noqa: SIZE_OK

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontologylab.connectors.base import RawDocument
from ontologylab.ingestion import IdentityConflict, IngestedDocument
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance

SECRET_PATH = "/secret/ELS-must-never-surface-9f3a/kg.sqlite"


def _store(tmp_path: Path) -> KGStore:
    return KGStore.open(tmp_path / "kg.sqlite")


def _raw(*, uri: str, text: str, title: str, doi: str | None = None) -> RawDocument:
    return RawDocument(
        source_kind="paper_api",
        source_uri=uri,
        title=title,
        raw_text=text,
        doi=doi,
        source="crossref",
    )


def _events(provenance: Provenance) -> list[dict[str, str | dict[str, str]]]:
    return [
        json.loads(line)
        for line in provenance.jsonl_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_per_item_exception_is_typed_failure_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import ontologylab.ingestion as svc

    first = _raw(
        uri="https://doi.org/10.1000/keep.me",
        text="First document body that must persist.",
        title="Keep",
        doi="10.1000/keep.me",
    )
    second = _raw(
        uri="https://doi.org/10.1000/boom.me",
        text="Second document body that must fail.",
        title="Boom",
        doi="10.1000/boom.me",
    )
    real = svc.persist_raw_document

    def boom(
        store: KGStore,
        raw: RawDocument,
        *,
        operation_id: str,
        provenance: Provenance,
    ) -> IngestedDocument | IdentityConflict:
        if raw.source_uri == second.source_uri:
            raise RuntimeError(  # noqa: GENERIC_ERR_OK
                f"disk I/O error in {SECRET_PATH}"
            )
        return real(
            store, raw, operation_id=operation_id, provenance=provenance,
        )

    monkeypatch.setattr(svc, "persist_raw_document", boom)
    store = _store(tmp_path)
    provenance = Provenance(str(tmp_path / "jobs"), seed=1)
    try:
        result = svc.ingest_raw_documents(store, [first, second], provenance)
        persisted = store.list_documents()
    finally:
        store.close()

    assert len(result.entries) == 1
    assert result.entries[0].document.source_uri == first.source_uri
    assert result.entries[0].created is True
    assert len(persisted) == 1
    assert persisted[0].source_uri == first.source_uri
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.error_class == "RuntimeError"
    assert failure.kind == "internal_error"
    assert failure.source_uri == second.source_uri
    assert "/secret/" not in repr(result.failures)
    failed = [
        event for event in _events(provenance) if event["step"] == "collect.failed"
    ]
    assert len(failed) == 1
    assert failed[0]["payload"] == {
        "source_uri": second.source_uri,
        "error_class": "RuntimeError",
    }


def test_same_doi_new_bytes_second_representation(tmp_path: Path) -> None:
    from ontologylab.ingestion import ingest_raw_documents_and_finalize

    store = _store(tmp_path)
    try:
        first = ingest_raw_documents_and_finalize(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/richer",
                    text="short abstract",
                    title="Richer",
                    doi="10.1000/richer",
                )
            ],
            Provenance(str(tmp_path / "richer-1"), seed=1),
        )
        second = ingest_raw_documents_and_finalize(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/richer",
                    text="short abstract plus full text that is richer",
                    title="Richer",
                    doi="10.1000/richer",
                )
            ],
            Provenance(str(tmp_path / "richer-2"), seed=1),
        )
        assert first.created_count == 1
        assert second.created_count == 1
        assert second.document_count == 1
        assert second.entries[0].document.id != first.entries[0].document.id
        assert len(store.list_documents()) == 2
        assert store.document_raw_text(first.entries[0].document.id) == (
            "short abstract"
        )
        assert store.document_raw_text(second.entries[0].document.id) == (
            "short abstract plus full text that is richer"
        )
        work_ids = {
            str(row[0])
            for row in store.conn.execute(
                "SELECT work_id FROM documents ORDER BY id"
            )
        }
        assert len(work_ids) == 1
    finally:
        store.close()


def test_hash_doi_conflict_is_typed(tmp_path: Path) -> None:
    from ontologylab.ingestion import ingest_raw_documents_and_finalize

    store = _store(tmp_path)
    shared = "Identical body shared by two distinct registered works."
    provenance = Provenance(str(tmp_path / "conflict"), seed=1)
    try:
        result = ingest_raw_documents_and_finalize(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/seam.a",
                    text=shared,
                    title="A",
                    doi="10.1000/seam.a",
                ),
                _raw(
                    uri="https://doi.org/10.1000/seam.b",
                    text=shared,
                    title="B",
                    doi="10.1000/seam.b",
                ),
                _raw(
                    uri="https://doi.org/10.1000/seam.c",
                    text="A different body entirely.",
                    title="C",
                    doi="10.1000/seam.c",
                ),
            ],
            provenance,
        )
        persisted_uris = {doc.source_uri for doc in store.list_documents()}
        assert result.document_count == 2
        assert result.created_count == 2
        assert len(result.conflicts) == 1
        assert result.conflicts[0].incoming_doi == "10.1000/seam.b"
        assert result.conflicts[0].existing_doi == "10.1000/seam.a"
        assert result.conflicts[0].source_uri == "https://doi.org/10.1000/seam.b"
        assert persisted_uris == {
            "https://doi.org/10.1000/seam.a",
            "https://doi.org/10.1000/seam.c",
        }
        identity = [
            event
            for event in _events(provenance)
            if event["step"] == "collect.identity_conflict"
        ]
        assert len(identity) == 1
        assert identity[0]["payload"]["incoming_doi"] == "10.1000/seam.b"
    finally:
        store.close()


def test_doi_spellings_canonicalize(tmp_path: Path) -> None:
    from ontologylab.ingestion import ingest_raw_documents_and_finalize

    store = _store(tmp_path)
    spellings = (
        "10.1000/Foo",
        "10.1000/foo",
        "https://doi.org/10.1000/foo",
        "10.1000/foo ",
        " 10.1000/foo",
    )
    try:
        last = None
        for index, spelling in enumerate(spellings):
            last = ingest_raw_documents_and_finalize(
                store,
                [
                    _raw(
                        uri=f"https://example.invalid/{index}",
                        text=f"same paper body {index}",
                        title="Canon",
                        doi=spelling,
                    )
                ],
                Provenance(str(tmp_path / f"canon-{index}"), seed=1),
            )
        assert last is not None
        works = store.conn.execute("SELECT COUNT(*) FROM works").fetchone()
        assert int(works[0]) == 1
        values = [
            row[0]
            for row in store.conn.execute(
                "SELECT normalized_value FROM work_identifiers "
                "WHERE scheme = 'doi'"
            )
        ]
        assert values == ["10.1000/foo"]
        dois = [
            row[0] for row in store.conn.execute("SELECT doi FROM documents")
        ]
        assert dois.count("10.1000/foo") == 1
        assert dois.count(None) == len(spellings) - 1
        docs = store.conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        assert int(docs[0]) == len(spellings)
    finally:
        store.close()


def test_batch_above_100_raises(tmp_path: Path) -> None:
    from ontologylab.ingestion import (
        MAX_INGEST_BATCH,
        IngestBatchBoundError,
        ingest_raw_documents,
    )

    store = _store(tmp_path)
    docs = [
        _raw(
            uri=f"https://example.invalid/{index}",
            text=f"body {index}",
            title=f"Bound {index}",
            doi=f"10.1000/bound.{index}",
        )
        for index in range(MAX_INGEST_BATCH + 1)
    ]
    provenance = Provenance(str(tmp_path / "bound"), seed=1)
    try:
        with pytest.raises(IngestBatchBoundError):
            ingest_raw_documents(store, docs, provenance)
        assert store.list_documents() == []
    finally:
        store.close()


def test_cancel_after_first_chunk_raises_partial(tmp_path: Path) -> None:
    from ontologylab.ingestion import (
        PartialIngestionError,
        ingest_raw_documents_batched,
    )

    store = _store(tmp_path)
    documents = [
        _raw(
            uri=f"https://doi.org/10.1000/batch-{index}",
            text=f"Paper {index}\n\nUnique abstract {index}",
            title=f"Paper {index}",
            doi=f"10.1000/batch-{index}",
        )
        for index in range(101)
    ]
    provenance = Provenance(str(tmp_path / "cancel"), seed=1)

    def should_cancel() -> bool:
        row = store.conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        return int(row[0]) >= 100

    try:
        with pytest.raises(PartialIngestionError) as caught:
            ingest_raw_documents_batched(
                store,
                documents,
                provenance,
                should_cancel=should_cancel,
            )
        assert caught.value.kind == "cancelled"
        assert caught.value.completed_batches == 1
        assert caught.value.created_count == 100
    finally:
        store.close()


def test_finalize_quarantine_is_scoped_to_current_ids(tmp_path: Path) -> None:
    from ontologylab.file_lifecycle import FileIntegrityError, quarantine_representation
    from ontologylab.ingestion import (
        finalize_ingest_writes,
        ingest_raw_documents,
        ingest_raw_documents_and_finalize,
    )

    store = _store(tmp_path)
    try:
        old = ingest_raw_documents_and_finalize(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/old.q",
                    text="Older quarantined representation.",
                    title="Old",
                    doi="10.1000/old.q",
                )
            ],
            Provenance(str(tmp_path / "old-q"), seed=1),
        )
        old_id = old.document_ids[0]
        quarantine_representation(store.conn, old_id)

        current = ingest_raw_documents(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/new.ok",
                    text="New batch member that must finalize.",
                    title="New",
                    doi="10.1000/new.ok",
                )
            ],
            Provenance(str(tmp_path / "new-ok"), seed=1),
        )
        finalize_ingest_writes(store, current.document_ids)
        assert store.document_raw_text(current.document_ids[0]) == (
            "New batch member that must finalize."
        )

        bad = ingest_raw_documents(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/new.bad",
                    text="Current batch member that is quarantined.",
                    title="Bad",
                    doi="10.1000/new.bad",
                )
            ],
            Provenance(str(tmp_path / "new-bad"), seed=1),
        )
        quarantine_representation(store.conn, bad.document_ids[0])
        with pytest.raises(FileIntegrityError):
            finalize_ingest_writes(store, bad.document_ids)
    finally:
        store.close()
