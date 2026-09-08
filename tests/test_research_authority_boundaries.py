from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab import research_run as research_run_module
from ontologylab.citation_ids import fact_revision_id
from ontologylab.kgstore import KGStore
from ontologylab.pack_readiness import authorize_publication, receipt_inventory
from ontologylab.research_artifacts import ResearchArtifactStore
from ontologylab.server.app import create_app
from tests.test_pack_readiness_refusal import _ready_fixture
from tests.test_research_run import _fake_fetch, _paper, _run


def _api():
    return importlib.import_module("ontologylab.post_extraction_assessment")


def _positive_input():
    api = _api()
    fact = api.FactRow(
        fact_kind="node",
        fact_id="positive-fact",
        schema_version_id=1,
        type_name="Measurement",
        subject_key="assay",
        target_key=None,
        source_document_id="positive-document",
        fields=(api.SemanticField("property", "dose", "10"),),
    )
    citation = api.CitationRow(
        receipt_id="positive-citation",
        fact_kind="node",
        fact_id=fact.fact_id,
        fact_revision=fact_revision_id("node", fact.fact_id),
        representation_id=fact.source_document_id,
        representation_content_hash="positive-hash",
        run_receipt_id="positive-run",
        chunk_receipt_id="positive-chunk",
    )
    return api.AssessmentInput(
        facts=(fact,),
        schema_rules=(
            api.SingleValueRule("node", "Measurement", "property", "dose"),
        ),
        receipts=api.ReceiptSnapshot(
            citations=(citation,),
            runs=(
                api.RunReceiptRow(
                    "positive-run", "positive-document", "positive-hash",
                ),
            ),
            chunks=(api.ChunkReceiptRow("positive-chunk", "positive-run"),),
            documents=(api.DocumentRow("positive-document", "positive-hash"),),
            inventory_root_before="stable-inventory",
            inventory_root_after="stable-inventory",
            issues=(),
        ),
    )


def _statuses(store: KGStore) -> tuple[tuple[str, str, str], ...]:
    nodes = tuple(
        ("node", str(row[0]), str(row[1]))
        for row in store.conn.execute("SELECT id, status FROM nodes ORDER BY id")
    )
    edges = tuple(
        ("edge", str(row[0]), str(row[1]))
        for row in store.conn.execute("SELECT id, status FROM edges ORDER BY id")
    )
    return (*nodes, *edges)


def _decision_count(store: KGStore) -> int:
    exists = store.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='grounded_review_decisions'"
    ).fetchone()
    if exists is None:
        return 0
    return int(
        store.conn.execute(
            "SELECT COUNT(*) FROM grounded_review_decisions"
        ).fetchone()[0]
    )


def _pack_membership(store: KGStore) -> tuple[tuple[str, str], ...]:
    nodes = tuple(
        ("node", str(row[0]))
        for row in store.conn.execute(
            "SELECT id FROM nodes WHERE status='verified' ORDER BY id"
        )
    )
    edges = tuple(
        ("edge", str(row[0]))
        for row in store.conn.execute(
            "SELECT id FROM edges WHERE status='verified' "
            "AND invalidated_ts IS NULL ORDER BY id"
        )
    )
    return (*nodes, *edges)


def _authority_snapshot(store: KGStore):
    return (
        _statuses(store),
        _decision_count(store),
        receipt_inventory(store.conn).root,
        authorize_publication(store.conn),
        _pack_membership(store),
    )


def test_maximally_positive_advisory_leaves_authority_byte_identical(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    try:
        before = _authority_snapshot(fixture.store)
        result = _api().derive_post_extraction_assessment(_positive_input())
        after = _authority_snapshot(fixture.store)

        assert result.records[0].support_state.value == "receipt_linked"
        assert result.records[0].contradiction_state.value == "not_observed"
        assert after == before
    finally:
        fixture.store.close()


def test_assessment_surface_accepts_no_authority_or_caller_receipt_ids() -> None:
    api = _api()
    fields = inspect.signature(api.FactRow).parameters
    derive = inspect.signature(api.derive_post_extraction_assessment).parameters

    assert "citation_receipt_ids" not in fields
    assert "run_receipt_ids" not in fields
    assert "chunk_receipt_ids" not in fields
    assert tuple(derive) == ("input_value",)


def test_derivation_never_calls_review_receipt_or_pack_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ontologylab import grounded_review, pack_readiness

    def forbidden(*_args, **_kwargs):
        pytest.fail("advisory crossed an authority boundary")

    monkeypatch.setattr(KGStore, "approve", forbidden)
    monkeypatch.setattr(KGStore, "reject", forbidden)
    monkeypatch.setattr(grounded_review, "apply_review", forbidden)
    monkeypatch.setattr(pack_readiness, "authorize_publication", forbidden)
    monkeypatch.setattr(pack_readiness, "receipt_inventory", forbidden)

    result = _api().derive_post_extraction_assessment(_positive_input())

    assert result.records[0].support_state.value == "receipt_linked"


def test_positive_advisory_cannot_satisfy_pack_readiness(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    try:
        before = authorize_publication(fixture.store.conn)
        advisory = _api().post_extraction_assessment_value(
            _api().derive_post_extraction_assessment(_positive_input())
        )
        assert advisory["counts"]["support"]["receipt_linked"] == 1
        after = authorize_publication(fixture.store.conn)
        assert after == before
    finally:
        fixture.store.close()


def test_research_worker_persists_store_resolved_ids_after_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/task-8")])]),
    )
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    job = _run(client)
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        expected_citations = {
            str(row[0])
            for row in store.conn.execute(
                "SELECT receipt_id FROM citation_receipts ORDER BY receipt_id"
            )
        }
        expected_runs = {
            str(row[0])
            for row in store.conn.execute(
                "SELECT receipt_id FROM extraction_run_receipts ORDER BY receipt_id"
            )
        }
        expected_chunks = {
            str(row[0])
            for row in store.conn.execute(
                "SELECT receipt_id FROM extraction_chunk_receipts ORDER BY receipt_id"
            )
        }
    finally:
        store.close()
    replay = ResearchArtifactStore(
        paths.jobs_dir(data_dir) / job.job_id
    ).load()
    assert replay.post_extraction is not None
    payload = json.loads(replay.post_extraction.path.read_text())["payload"]
    records = payload["records"]
    assert len(records) == job.totals["nodes_new"] + job.totals["edges_new"]
    assert {item for row in records for item in row["citation_receipt_ids"]} <= (
        expected_citations
    )
    assert {item for row in records for item in row["extraction_run_receipt_ids"]} <= (
        expected_runs
    )
    assert {
        item for row in records for item in row["extraction_chunk_receipt_ids"]
    } <= expected_chunks
    assert job.research_pointers is not None
    assert job.research_pointers.post_extraction_id == replay.post_extraction.artifact_id
