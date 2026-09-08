"""Corpus availability when extraction fails after acquisition."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ontologylab import research_run as research_run_module
from ontologylab.server.app import create_app
from tests.test_literature_artifacts import _paper


def test_failed_extraction_still_advertises_reusable_corpus(
    tmp_path,
    monkeypatch,
) -> None:
    async def _fetch(*args, **kwargs):
        del args, kwargs
        return [("crossref", [_paper()])], []

    async def _fail_extract(*args, **kwargs):
        del args, kwargs
        raise OSError("extract failed after corpus write")

    monkeypatch.setattr(research_run_module, "fetch_sources", _fetch)
    monkeypatch.setattr(
        research_run_module,
        "extract_research_documents",
        _fail_extract,
    )
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    client.get("/")
    started = client.post(
        "/api/research",
        json={
            "topic": "artifact survives extraction failure",
            "sources": ["crossref"],
            "engine": "mock",
            "fulltext": False,
            "citation_expansion": False,
        },
    ).json()
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)
    assert job.status == "failed"

    status = client.get(f"/api/jobs/{job.job_id}").json()
    listed = client.get("/api/jobs").json()["jobs"]

    assert status["corpus_available"] is True
    assert next(
        item for item in listed if item["job_id"] == job.job_id
    )["corpus_available"] is True
    assert client.get(f"/api/jobs/{job.job_id}/corpus").status_code == 200
