"""`GET /api/jobs` and `GET /api/jobs/{id}` carry per-source outcomes as a list.

The Sources screen renders every entry that did not answer as
`<name>: <detail>`, so the wire shape is pinned here: `sources` is a LIST of
`{name, status, detail}` — exactly what `Job.as_status` serialises from the
collect fan-out's reporter — never a name-keyed map.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    with TestClient(app) as tc:
        yield tc


def _finished_job(registry):
    """A real registered job whose worker has already returned.

    An empty document list gives the worker nothing to extract, so it exits
    at once; joining its thread (not sleeping) makes the assertions below
    read a settled job instead of racing its terminal write.
    """
    job = registry.create(
        engine="mock",
        model=None,
        doc_ids=[],
        max_engine_calls=1,
        time_budget=1.0,
        seed=0,
    )
    assert job._thread is not None
    job._thread.join(timeout=30)
    assert not job._thread.is_alive(), "the worker did not finish"
    return job


def test_a_failed_source_is_listed_with_its_detail(client) -> None:
    registry = client.app.state.jobs
    job = _finished_job(registry)
    # The same reporter the collect fan-out is handed as `on_event`.
    report = registry._source_event(job)
    report("source_start", "arxiv", None)
    report("source_failed", "arxiv", "network_error")
    report("source_ok", "pubmed", 3)

    single = client.get(f"/api/jobs/{job.job_id}")
    assert single.status_code == 200, single.text
    sources = single.json()["sources"]
    assert isinstance(sources, list)
    assert {"name": "arxiv", "status": "failed", "detail": "network_error"} in sources
    assert {"name": "pubmed", "status": "ok", "detail": "3"} in sources
    assert len(sources) == 2

    listed = client.get("/api/jobs")
    assert listed.status_code == 200, listed.text
    mine = next(
        item for item in listed.json()["jobs"] if item["job_id"] == job.job_id
    )
    assert mine["sources"] == sources


def test_a_job_without_a_fan_out_carries_an_empty_list(client) -> None:
    registry = client.app.state.jobs
    job = _finished_job(registry)

    body = client.get(f"/api/jobs/{job.job_id}").json()

    assert body["sources"] == []
