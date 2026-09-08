"""C-024 research consumer: selected ready PMC full text only."""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import json
from pathlib import Path

import pytest

from ontologylab import paths, research_plan, research_spec
from ontologylab import research_run as research_run_module
from ontologylab.engines import MockEngine
from ontologylab.extractor import TOTALS_KEYS, ExtractionOutcome
from ontologylab.file_lifecycle import content_hash_for
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from ontologylab.research_extract import (
    ResearchExtractSession,
    extract_research_documents,
)
from ontologylab.server.app import create_app
from tests.test_preferred_selection import (
    DOI,
    PMC_BODY,
    PMC_TOKEN,
    PUBLISHER_BODY,
    PUBLISHER_TOKEN,
    caps,
    node_names,
    plant_c024,
    source_doc_ids,
)


def _session(job_dir: Path) -> ResearchExtractSession:
    totals = dict.fromkeys(TOTALS_KEYS, 0)

    def _stats(stats: dict[str, int]) -> None:
        for key in totals:
            totals[key] += stats.get(key, 0)

    job_dir.mkdir(parents=True, exist_ok=True)
    return ResearchExtractSession(
        engine=MockEngine(),
        provenance=Provenance(str(job_dir), seed=0),
        caps=caps(),
        extractor_engine="mock",
        extractor_model="",
        on_progress=lambda _line: None,
        on_stats=_stats,
    )


def test_selection_tie_is_stable_under_insertion_order() -> None:
    from ontologylab.selection_policy import inventory_entry, select_winner
    from ontologylab.selection_types import (
        PolicyVersion,
        RepresentationCandidate,
    )

    left = RepresentationCandidate(
        representation_id="rep-z",
        content_hash="sha256:zz",
        byte_length=100,
        stage="unknown",
        kind="fulltext",
        source="pmc",
        evidence_grade="A",
        state="ready",
    )
    right = RepresentationCandidate(
        representation_id="rep-a",
        content_hash="sha256:aa",
        byte_length=100,
        stage="unknown",
        kind="fulltext",
        source="pmc",
        evidence_grade="A",
        state="ready",
    )
    first = select_winner(
        (inventory_entry(left), inventory_entry(right)), PolicyVersion.V1,
    )
    second = select_winner(
        (inventory_entry(right), inventory_entry(left)), PolicyVersion.V1,
    )
    assert first is not None and second is not None
    assert first.representation_id == second.representation_id == "rep-a"
    assert first.content_hash == "sha256:aa"


def test_no_ready_full_text_is_typed_unavailable_without_fallback(
    tmp_path: Path,
) -> None:
    from ontologylab.selection import put_selection_receipt
    from ontologylab.selection_types import (
        PolicyVersion,
        SelectionRefusalCode,
        SelectionRefused,
    )

    store, work_id, publisher_id, pmc_id = plant_c024(
        tmp_path, pmc_ready=False,
    )
    try:
        receipt = put_selection_receipt(store.conn, work_id, PolicyVersion.V1)
        assert receipt.selected_representation_id is None
        rejected = {
            entry.representation_id: entry.rejection_reason
            for entry in receipt.inventory
        }
        assert rejected[pmc_id] == "not_ready"
        assert publisher_id in rejected
        with pytest.raises(SelectionRefused) as refused:
            asyncio.run(
                extract_research_documents(
                    store,
                    (publisher_id, pmc_id),
                    _session(tmp_path / "job-none"),
                )
            )
        assert refused.value.code is SelectionRefusalCode.NO_ELIGIBLE_READY_FULL_TEXT
        assert node_names(store) == set()
        assert source_doc_ids(store) == set()
    finally:
        store.close()


def test_c024_research_extracts_only_pmc_and_binds_task2_run(
    tmp_path: Path,
) -> None:
    from ontologylab.selection import list_selection_receipts
    from ontologylab.selection_types import PolicyVersion

    store, work_id, publisher_id, pmc_id = plant_c024(tmp_path)
    try:
        asyncio.run(
            extract_research_documents(
                store,
                (publisher_id, pmc_id),
                _session(tmp_path / "job-c024"),
            )
        )
        names = node_names(store)
        assert PMC_TOKEN in names
        assert PUBLISHER_TOKEN not in names
        assert source_doc_ids(store) == {pmc_id}
        receipts = list_selection_receipts(store.conn, work_id)
        assert len(receipts) == 1
        assert receipts[0].selected_representation_id == pmc_id
        assert receipts[0].policy_version == str(PolicyVersion.V1)
        runs = store.conn.execute(
            "SELECT representation_id, document_content_hash "
            "FROM extraction_run_receipts"
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["representation_id"] == pmc_id
        assert runs[0]["document_content_hash"] == content_hash_for(PMC_BODY)
    finally:
        store.close()


def test_research_http_selects_pmc_from_publisher_and_pmc_fake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from ontologylab import paths
    from ontologylab.connectors.base import RawDocument, normalize_doi
    from ontologylab.selection_types import PolicyVersion
    from ontologylab.server.app import create_app

    doi = normalize_doi(DOI)
    publisher = RawDocument(
        source_kind="paper_api",
        source_uri="https://example.invalid/publisher/c024",
        title="C024",
        raw_text=PUBLISHER_BODY.decode("utf-8"),
        doi=doi,
        source="publisher",
        evidence_grade="A",
        stage="published",
        content_kind="abstract",
    )
    pmc = RawDocument(
        source_kind="paper_api",
        source_uri="https://example.invalid/pmc/c024",
        title="C024",
        raw_text=PMC_BODY.decode("utf-8"),
        doi=doi,
        source="pmc",
        evidence_grade="A",
        stage="unknown",
        content_kind="fulltext",
    )

    async def _fetch(
        sources,
        query,
        limit=None,
        data_dir=None,
        on_event=None,
        source_queries=None,
        search_axis="",
        query_terms=(),
    ):
        del source_queries, search_axis, query_terms
        if on_event is not None:
            for name in sources:
                on_event("source_start", name, None)
            on_event("source_ok", "publisher", 1)
            on_event("source_ok", "pmc", 1)
        return [("publisher", [publisher]), ("pmc", [pmc])], []

    monkeypatch.setattr(research_run_module, "fetch_sources", _fetch)
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    started = client.post(
        "/api/research",
        json={
            "topic": "c024 selection fixture",
            "engine": "mock",
            "sources": ["crossref"],
            "fulltext": False,
        },
    ).json()
    assert started.get("ok") is True, started
    job = app.state.jobs.get(started["job_id"])
    assert job is not None
    assert job._thread is not None
    job._thread.join(timeout=30)
    assert job.status == "complete", job.error
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        names = node_names(store)
        assert PMC_TOKEN in names
        assert PUBLISHER_TOKEN not in names
        rows = store.conn.execute(
            "SELECT selected_representation_id, policy_version, policy_hash, "
            "inventory_json FROM preferred_selection_receipts"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["policy_version"] == str(PolicyVersion.V1)
        assert str(rows[0]["policy_hash"]).startswith("sha256:")
        inventory = json.loads(str(rows[0]["inventory_json"]))
        assert len(inventory) == 2
        assert {entry["usable_full_text"] for entry in inventory} == {0, 1}
        selected = rows[0]["selected_representation_id"]
        run = store.conn.execute(
            "SELECT representation_id FROM extraction_run_receipts"
        ).fetchone()
        assert run is not None
        assert run["representation_id"] == selected
        assert source_doc_ids(store) == {selected}
    finally:
        store.close()


def test_stop_no_usable_source_never_enters_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient


    need = research_spec.build_evidence_need(
        research_spec.EvidenceNeedDraft(
            research_spec.EvidenceNeedKind.MECHANISM,
            "mechanism evidence",
            True,
            research_spec.ContentClass.FULLTEXT,
        )
    )
    reading = research_plan.PlannerReading(
        "mechanism goal",
        (need,),
        (),
        (
            research_plan.NeedLinkedAxis(
                "mechanism",
                "mechanism query",
                ("mechanism",),
                (need.need_id,),
                (),
                (("crossref", "mechanism query"),),
            ),
        ),
        None,
    )

    async def _plan(*args, **kwargs):
        del args, kwargs
        return reading, {"calls": 1}

    async def _fetch(*args, **kwargs):
        del args, kwargs
        return [], []

    extraction_calls = 0

    async def _extract(*args, **kwargs):
        nonlocal extraction_calls
        del args, kwargs
        extraction_calls += 1
        return ExtractionOutcome("")

    monkeypatch.setattr(
        research_run_module,
        "formulate_research_plan",
        _plan,
        raising=False,
    )
    monkeypatch.setattr(research_run_module, "fetch_sources", _fetch)
    monkeypatch.setattr(research_run_module, "extract_research_documents", _extract)
    data_dir = tmp_path / "data-stop"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    started = client.post(
        "/api/research",
        json={
            "topic": "mechanism goal",
            "sources": ["crossref"],
            "engine": "mock",
            "fulltext": False,
            "citation_expansion": False,
            "max_queries": 1,
        },
    ).json()
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)

    assert job.status == "failed"
    assert job.error is not None and "no_usable_source" in job.error
    assert extraction_calls == 0


def test_extraction_receives_exact_ingestion_result_document_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from tests.test_research_run import (
        TOPIC,
        _axis,
        _axis_fetch,
        _install_planner,
        _need,
        _paper,
        _planned_reading,
    )

    data_dir = tmp_path / "data-exact-ids"
    stale_store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        stale, _created = stale_store.insert_document(
            source_kind="upload",
            source_uri="file:///stale.txt",
            title="stale",
            raw_text="LegacyThing calls OldThing.",
            content_hash="sha256:" + "d" * 64,
        )
    finally:
        stale_store.close()
    need = _need(research_spec.EvidenceNeedKind.GENERAL, "current evidence")
    _install_planner(
        monkeypatch,
        _planned_reading(
            (need,),
            (_axis("current", "current query", (need.need_id,)),),
        ),
    )
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _axis_fetch(
            {"current query": [_paper("crossref", "10.1/current")]}
        ),
    )
    real_ingest = research_run_module.ingest_raw_documents_batched
    ingested_ids: tuple[str, ...] = ()

    def _ingest(*args, **kwargs):
        nonlocal ingested_ids
        result = real_ingest(*args, **kwargs)
        ingested_ids = result.document_ids
        return result

    extracted_ids: tuple[str, ...] = ()

    async def _extract(_store, document_ids, _session):
        nonlocal extracted_ids
        extracted_ids = document_ids
        return ExtractionOutcome("")

    monkeypatch.setattr(
        research_run_module,
        "ingest_raw_documents_batched",
        _ingest,
    )
    monkeypatch.setattr(research_run_module, "extract_research_documents", _extract)
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    started = client.post(
        "/api/research",
        json={
            "topic": TOPIC,
            "sources": ["crossref"],
            "engine": "mock",
            "fulltext": False,
            "citation_expansion": False,
            "max_queries": 1,
        },
    ).json()
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)

    assert job.status == "complete", job.error
    assert extracted_ids == ingested_ids
    assert extracted_ids
    assert stale.id not in extracted_ids
