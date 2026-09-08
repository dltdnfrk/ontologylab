"""A research job exposes its merged corpus as a reusable artifact."""

from __future__ import annotations

import json
import stat
from dataclasses import replace

from fastapi.testclient import TestClient

from ontologylab import research_run as research_run_module
from ontologylab import research_spec
from ontologylab.connectors.base import RawDocument
from ontologylab.literature import corpus_summary
from ontologylab.literature_artifacts import write_corpus_artifacts
from ontologylab.server.app import create_app


def _paper() -> RawDocument:
    return RawDocument(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/artifact",
        title="Artifact paper",
        raw_text="Artifact paper\n\nFull abstract text.",
        doi="10.1000/artifact",
        source="crossref",
        content_kind="fulltext",
        all_sources=("crossref", "pubmed"),
        authors=("Kim", "Lee"),
        year=2025,
        cited_by=9,
        search_axes=("mechanism", "method"),
        search_queries=("artifact mechanism", "artifact method"),
    )


def test_research_corpus_download_preserves_merged_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    async def _fetch(*args, **kwargs):
        del args, kwargs
        return [("crossref", [_paper()])], []

    monkeypatch.setattr(research_run_module, "fetch_sources", _fetch)
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    client.get("/")
    started = client.post(
        "/api/research",
        json={
            "topic": "artifact fixture",
            "sources": ["crossref"],
            "engine": "mock",
            "fulltext": False,
            "citation_expansion": False,
        },
    ).json()
    assert started["ok"] is True
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)
    assert job.status == "complete", job.error

    response = client.get(f"/api/jobs/{job.job_id}/corpus")

    assert response.status_code == 200
    [record] = [
        json.loads(line)
        for line in response.text.splitlines()
        if line.strip()
    ]
    assert record["doi"] == "10.1000/artifact"
    assert record["all_sources"] == ["crossref", "pubmed"]
    assert record["authors"] == ["Kim", "Lee"]
    assert record["search_axes"] == ["mechanism", "method", "topic"]
    assert record["search_queries"] == [
        "artifact mechanism",
        "artifact method",
        "artifact fixture",
    ]
    assert record["document_id"] == "doi:10.1000/artifact"
    assert record["content_kind"] == "fulltext"
    corpus_path = data_dir / "jobs" / job.job_id / "literature-corpus.jsonl"
    assert stat.S_IMODE(corpus_path.stat().st_mode) == 0o600


def test_summary_is_finalized_from_documents_after_fulltext_enrichment(
    tmp_path,
) -> None:
    abstract = replace(_paper(), content_kind="abstract")
    assessment = {
        "assessment_event_id": "sha256:fixture",
        "recommendation": "extract",
        "stop_reason": None,
        "need_occupancy": [
            {
                "need_id": "need:fixture",
                "kind": "mechanism",
                "mandatory": True,
                "minimum_content": "fulltext",
                "occupied": True,
                "eligible_documents": [
                    {
                        "document_id": "doi:10.1000/artifact",
                        "content_class": "fulltext",
                    }
                ],
            }
        ],
        "source_failures": [{"source": "pubmed", "kind": "timeout"}],
        "overlap_and_diversity": {
            "document_count": 1,
            "eligible_document_count": 1,
            "redundant_source_observation_count": 0,
            "marginal_unique_eligible_document_count": 1,
        },
    }
    stale_summary = corpus_summary(
        raw_count=1,
        documents=[abstract],
        queries=[],
        assessment=assessment,
    )
    stale_summary["access_class_counts"] = {
        "abstract": 1,
        "fulltext": 0,
        "metadata_only": 0,
        "unknown": 0,
    }
    enriched = replace(
        abstract,
        raw_text=abstract.raw_text + "\n\nFull methods and results.",
        content_kind="fulltext",
    )

    _corpus_path, summary_path = write_corpus_artifacts(
        tmp_path,
        [enriched],
        stale_summary,
    )
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))

    assert persisted["raw_documents"] == 1
    assert persisted["query_axes"] == []
    assert persisted["acquisition_assessment"] == assessment
    assert persisted["access_class_counts"] == {
        "abstract": 0,
        "fulltext": 1,
        "metadata_only": 0,
        "unknown": 0,
    }


def test_partial_exhausted_corpus_is_written_and_extracted_with_warning(
    tmp_path,
    monkeypatch,
) -> None:
    from ontologylab.extractor import ExtractionOutcome
    from tests.test_research_run import (
        TOPIC,
        _axis,
        _axis_fetch,
        _install_planner,
        _need,
        _paper,
        _planned_reading,
    )

    covered = _need(
        research_spec.EvidenceNeedKind.CONTEXT,
        "covered context",
    )
    missing = _need(
        research_spec.EvidenceNeedKind.MECHANISM,
        "missing mechanism",
    )
    _install_planner(
        monkeypatch,
        _planned_reading(
            (covered, missing),
            (_axis("context", "partial query", (covered.need_id,)),),
        ),
    )
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _axis_fetch(
            {"partial query": [_paper("crossref", "10.1/partial")]}
        ),
    )
    extraction_calls = 0

    async def _extract(*args, **kwargs):
        nonlocal extraction_calls
        del args, kwargs
        extraction_calls += 1
        return ExtractionOutcome("")

    monkeypatch.setattr(research_run_module, "extract_research_documents", _extract)
    data_dir = tmp_path / "data-partial"
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
    summary = json.loads(
        (
            data_dir
            / "jobs"
            / job.job_id
            / "literature-corpus-summary.json"
        ).read_text(encoding="utf-8")
    )

    assert job.status == "complete", job.error
    assert extraction_calls == 1
    assert summary["unique_documents"] == 1
    assessment = summary["acquisition_assessment"]
    assert assessment["recommendation"] == "extract"
    assert assessment["stop_reason"] == "budget_exhausted"
    assert any("budget_exhausted" in line for line in job.progress)
