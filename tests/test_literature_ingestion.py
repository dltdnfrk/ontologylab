"""Large literature corpora cross the bounded ingest seam safely."""

from __future__ import annotations

import pytest

from ontologylab import ingestion as ingestion_module
from ontologylab.connectors.base import RawDocument
from ontologylab.ingestion import (
    IngestionResult,
    PartialIngestionError,
    ingest_raw_documents_batched,
)
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance


def test_a_large_harvest_is_persisted_in_bounded_batches(tmp_path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    documents = [
        RawDocument(
            source_kind="paper_api",
            source_uri=f"https://doi.org/10.1000/batch-{index}",
            title=f"Paper {index}",
            raw_text=f"Paper {index}\n\nUnique abstract {index}",
            doi=f"10.1000/batch-{index}",
            source="crossref",
        )
        for index in range(125)
    ]
    provenance = Provenance(str(tmp_path / "run"), seed=0)

    try:
        result = ingest_raw_documents_batched(
            store,
            documents,
            provenance,
        )
        persisted = store.list_documents()
    finally:
        store.close()

    assert result.document_count == 125
    assert result.created_count == 125
    assert len(persisted) == 125


def test_later_batch_failure_reports_committed_partial_state(
    monkeypatch,
    tmp_path,
) -> None:
    calls = 0

    def fake_ingest(store, documents, provenance, *, operation_id=None):
        nonlocal calls
        del store, documents, provenance, operation_id
        calls += 1
        if calls == 2:
            raise RuntimeError("second batch failed")  # noqa: GENERIC_ERR_OK
        return IngestionResult(entries=(), created_count=3)

    monkeypatch.setattr(
        ingestion_module, "ingest_raw_documents_and_finalize", fake_ingest,
    )
    store = KGStore.open(tmp_path / "partial.sqlite")
    document = RawDocument(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/partial",
        title="Partial paper",
        raw_text="Partial paper body",
        doi="10.1000/partial",
        source="crossref",
    )
    provenance = Provenance(str(tmp_path / "partial-run"), seed=0)
    try:
        with pytest.raises(PartialIngestionError) as excinfo:
            ingest_raw_documents_batched(
                store,
                [document] * 101,
                provenance,
            )
    finally:
        store.close()

    assert excinfo.value.completed_batches == 1
    assert excinfo.value.created_count == 3
