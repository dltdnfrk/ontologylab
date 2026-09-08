"""Correctness and performance gates for the frozen Wave 2.1 ingest path."""

from __future__ import annotations

from pathlib import Path

import pytest

from ontologylab import ingestion as ingestion_module
from ontologylab.ingestion import (
    MAX_INGEST_BATCH,
    ingest_raw_documents_and_finalize,
)
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from ontologylab.provenance_outbox import load_outbox_events
from tests.wave21.ingest_perf import IngestOutput, measure_current_ingest
from tests.wave21.perf_fixture import deterministic_documents

_HISTORICAL_P95_CEILING_MS = 10_195.704249618575


def test_performance_gate_refuses_repository_cloud_scratch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: benchmark scratch outside the protocol-bound local APFS prefix.
    cloud_root = Path.cwd() / "repository-cloud-scratch"

    def fail_if_opened(_path: Path) -> KGStore:
        pytest.fail("store opened before scratch refusal")

    monkeypatch.setattr(KGStore, "open", fail_if_opened)

    # When/Then: the real gate refuses before opening a store or writing output.
    with pytest.raises(RuntimeError, match="performance_scratch_root"):
        measure_current_ingest(cloud_root, document_count=1, n=1)
    assert not cloud_root.exists()


def test_fixture_outputs_are_preserved_across_create_and_duplicate(
    tmp_path: Path,
) -> None:
    # Given: two complete collision groups from the frozen recipe.
    documents = deterministic_documents(40)
    store = KGStore.open(tmp_path / "kg.sqlite")
    provenance = Provenance(str(tmp_path / "jobs" / "perf"), seed=20260820)

    # When: the production path ingests the fixture twice.
    passes = []
    try:
        for _pass_index in range(2):
            entries = created = conflicts = failures = 0
            for offset in range(0, len(documents), MAX_INGEST_BATCH):
                result = ingest_raw_documents_and_finalize(
                    store,
                    documents[offset : offset + MAX_INGEST_BATCH],
                    provenance,
                )
                entries += result.document_count
                created += result.created_count
                conflicts += len(result.conflicts)
                failures += len(result.failures)
            passes.append((entries, created, conflicts, failures))
        document_rows = store.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[
            0
        ]
        observation_rows = store.conn.execute(
            "SELECT COUNT(*) FROM document_observations"
        ).fetchone()[0]
        outbox_rows = len(load_outbox_events(store.conn))
    finally:
        store.close()

    # Then: every eligible item is represented; no work is silently skipped.
    assert passes == [(38, 38, 2, 0), (38, 0, 2, 0)]
    assert document_rows == 38
    assert observation_rows == 38
    assert outbox_rows == 38


def test_frozen_fixture_ingest_p95_stays_within_bounded_gate(
    tmp_path: Path,
) -> None:
    # Given: three independent samples of the exact frozen 10,000-row recipe.
    expected = (
        IngestOutput(entries=9500, created=9500, conflicts=500, failures=0),
        IngestOutput(entries=9500, created=0, conflicts=500, failures=0),
    )

    # When: the real create+duplicate path is measured repeatedly.
    receipt = measure_current_ingest(
        tmp_path / "perf",
        document_count=10000,
        n=3,
    )

    # Then: p95 is bounded and every sample completed the expected work.
    assert receipt.operation == "current_ingest_create_and_duplicate"
    assert receipt.dataset_documents == 10000
    assert len(receipt.samples_ms) == 3
    assert receipt.p95_ms <= _HISTORICAL_P95_CEILING_MS
    assert receipt.outputs == expected


def test_raw_ingest_avoids_redundant_persist_savepoint(
    tmp_path: Path,
) -> None:
    # Given: SQLite tracing around one real create and duplicate operation.
    documents = deterministic_documents(1)
    store = KGStore.open(tmp_path / "kg.sqlite")
    provenance = Provenance(str(tmp_path / "jobs" / "perf"), seed=20260820)
    statements: list[str] = []
    store.conn.set_trace_callback(statements.append)

    # When: the production ingestion path processes the document twice.
    try:
        ingest_raw_documents_and_finalize(store, documents, provenance)
        ingest_raw_documents_and_finalize(store, documents, provenance)
    finally:
        store.conn.set_trace_callback(None)
        store.close()

    # Then: the outer item/service savepoints provide the atomic boundary.
    assert all("persist_raw_one" not in statement for statement in statements)
    transaction_tokens = [
        statement.split(None, 1)[0].upper()
        for statement in statements
        if statement.strip()
    ]
    assert transaction_tokens.count("BEGIN") == 3
    assert transaction_tokens.count("COMMIT") == 3


def test_duplicate_pass_does_not_refinalize_ready_representations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an observer that preserves the real finalization implementation.
    real_finalize = ingestion_module.finalize_representation
    finalized: list[str] = []

    def observe_finalize(*args, **kwargs):
        finalized.append(args[2])
        return real_finalize(*args, **kwargs)

    monkeypatch.setattr(ingestion_module, "finalize_representation", observe_finalize)

    # When: two complete collision groups run through create and duplicate.
    receipt = measure_current_ingest(tmp_path / "perf", document_count=40, n=1)

    # Then: only the 38 newly created Representations require finalization.
    assert receipt.outputs[0].created == 38
    assert receipt.outputs[1].created == 0
    assert len(finalized) == 38
