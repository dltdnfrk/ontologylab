"""A valid request reaches pack authority and leaves no refused output."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from ontologylab.kgstore import KGStore
from ontologylab.server.jobs import JobRegistry
from tests.test_server_m8 import _approve_all, _make_client, _sample_file


def test_valid_pack_request_is_refused_by_completeness_authority(
    tmp_path: Path,
) -> None:
    client, data_dir, packs_dir = _make_client(tmp_path)
    collected = client.post(
        "/api/collect",
        json={"files": [str(_sample_file(tmp_path))]},
    )
    assert collected.status_code == 200
    started = client.post("/api/extract", json={"engine": "mock"}).json()
    app = client.app
    assert isinstance(app, FastAPI)
    registry = app.state.jobs
    assert isinstance(registry, JobRegistry)
    job = registry.get(started["job_id"])
    assert job is not None
    thread = job._thread
    assert thread is not None
    thread.join(30)
    assert not thread.is_alive()
    assert job.status == "complete"
    _approve_all(client)

    store = KGStore.open(data_dir / "kg.sqlite")
    try:
        store.conn.execute(
            "UPDATE extraction_runs SET status = 'interrupted'"
        )
        store.conn.execute(
            "UPDATE extraction_chunks SET status = 'interrupted'"
        )
        store.conn.commit()
    finally:
        store.close()

    response = client.post(
        "/api/packs/build",
        json={"name": "authority-refused"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error_code"] == "incomplete_extraction"
    assert body["extraction_completeness"]["status"] == "incomplete"
    assert not packs_dir.exists() or not any(packs_dir.iterdir())
