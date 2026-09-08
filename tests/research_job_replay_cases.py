from __future__ import annotations

import time
from pathlib import Path

import pytest

from ontologylab import paths
from ontologylab import research_run as research_run_module
from ontologylab.kgstore import KGStore
from ontologylab.research_artifacts import ResearchArtifactStore
from ontologylab.server.jobs import Job, JobRegistry
from tests.research_artifact_fixtures import initial_plan, research_spec


def test_job_pointer_payload_has_no_authoritative_artifact_body(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    job_dir = data_dir / "jobs" / "research-pointers"
    job_dir.mkdir(parents=True)
    store = ResearchArtifactStore(job_dir)
    spec = research_spec()
    plan = initial_plan(spec)
    store.write_spec(spec)
    store.write_plan(plan)
    store.write_acquisition(plan, {"recommendation": "extract", "secret_body": "artifact-only"})
    replay = store.load()
    registry = JobRegistry(data_dir)
    job = Job(
        job_id=job_dir.name,
        kind="research",
        engine="mock",
        model=None,
        started_ts=time.time(),
        research_pointers=replay.pointers(),
    )
    registry.persist(job)
    database = KGStore.open(paths.kg_db_path(data_dir))
    [row] = database.list_runs()
    columns = {entry[1] for entry in database.conn.execute("PRAGMA table_info(runs)")}
    database.close()

    encoded = row["ask"]
    assert isinstance(encoded, str)
    assert "artifact-only" not in encoded
    assert replay.root_hash in encoded
    assert columns == {
        "id", "kind", "status", "phase", "engine", "model",
        "started_ts", "finished_ts", "error", "totals_json", "ask_json",
    }


def test_worker_broaden_appends_without_mutating_v1_and_persists_lineage_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from ontologylab import research_spec as spec_module
    from ontologylab.extractor import ExtractionOutcome
    from ontologylab.server.app import create_app
    from tests.test_research_run import (
        TOPIC,
        _axis,
        _axis_fetch,
        _install_planner,
        _need,
        _paper,
        _planned_reading,
    )

    first = _need(spec_module.EvidenceNeedKind.MECHANISM, "first need")
    second = _need(spec_module.EvidenceNeedKind.RESULT, "second need")
    _install_planner(
        monkeypatch,
        _planned_reading(
            (first, second),
            (
                _axis("first", "first query", (first.need_id,)),
                _axis("second", "second query", (second.need_id,)),
            ),
        ),
    )
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _axis_fetch(
            {
                "first query": [_paper("crossref", "10.1/first")],
                "second query": [_paper("crossref", "10.1/second")],
            }
        ),
    )

    async def _extract(*args, **kwargs):
        del args, kwargs
        return ExtractionOutcome("")

    monkeypatch.setattr(research_run_module, "extract_research_documents", _extract)
    data_dir = tmp_path / "data-worker-lineage"
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
            "max_queries": 2,
        },
    ).json()
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)
    job_dir = data_dir / "jobs" / job.job_id
    first_bytes = (job_dir / "research-plan-0001.json").read_bytes()
    replay = ResearchArtifactStore(job_dir).load()

    assert job.status == "complete", job.error
    assert (job_dir / "research-plan-0001.json").read_bytes() == first_bytes
    assert replay.plans[1].parent_plan_id == replay.plans[0].plan_id
    assert job.research_pointers == replay.pointers()
    restored = JobRegistry(data_dir).get(job.job_id)
    assert restored is not None
    assert restored.research_pointers == replay.pointers()
