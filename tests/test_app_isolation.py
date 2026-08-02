"""Each FastAPI application owns its route dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab.extraction_state import ExtractionState
from ontologylab.extractor import chunk_document
from ontologylab.kgstore import KGStore
from ontologylab.server.app import create_app
from ontologylab.server.jobs import Job


def _client(root: Path) -> TestClient:
    return TestClient(
        create_app(data_dir=root / "data", packs_dir=root / "packs"),
        base_url="http://127.0.0.1",
    )


def _settings(root: Path, engine: str) -> dict[str, object]:
    return {
        "default_engine": engine,
        "default_model": None,
        "data_dir": str(root / "data"),
        "packs_dir": str(root / "packs"),
    }


def test_two_apps_keep_data_settings_provenance_and_packs_isolated(tmp_path) -> None:
    left_root, right_root = tmp_path / "left", tmp_path / "right"
    left, right = _client(left_root), _client(right_root)

    # Interleave after both apps exist; creation order must not choose ownership.
    assert left.post("/api/collect/sample").json()["created"] is True
    assert right.get("/api/documents").json()["count"] == 0
    assert right.post("/api/collect/sample").json()["created"] is True
    assert left.get("/api/documents").json()["count"] == 1

    assert left.put("/api/settings", json=_settings(left_root, "mock")).status_code == 200
    assert right.put("/api/settings", json=_settings(right_root, "claude")).status_code == 200
    assert left.get("/api/settings").json()["default_engine"] == "mock"
    assert right.get("/api/settings").json()["default_engine"] == "claude"

    left_note = tmp_path / "left-note.txt"
    right_note = tmp_path / "right-note.txt"
    left_note.write_text("left provenance", encoding="utf-8")
    right_note.write_text("right provenance", encoding="utf-8")
    assert left.post("/api/collect", json={"files": [str(left_note)]}).json()["ok"]
    assert right.post("/api/collect", json={"files": [str(right_note)]}).json()["ok"]
    left_prov = "".join(p.read_text() for p in (left_root / "data").rglob("provenance.jsonl"))
    right_prov = "".join(p.read_text() for p in (right_root / "data").rglob("provenance.jsonl"))
    assert "left-note" in left_prov and "right-note" not in left_prov
    assert "right-note" in right_prov and "left-note" not in right_prov

    assert left.post("/api/packs/build", json={"name": "left"}).json()["ok"]
    assert right.post("/api/packs/build", json={"name": "right"}).json()["ok"]
    left_packs = left.get("/api/packs").json()["packs"]
    right_packs = right.get("/api/packs").json()["packs"]
    assert len(left_packs) == 1 and left_packs[0]["pack_id"].startswith("left-")
    assert len(right_packs) == 1 and right_packs[0]["pack_id"].startswith("right-")
    assert not left_packs[0]["pack_id"].startswith("right-")
    assert not right_packs[0]["pack_id"].startswith("left-")
    assert (left_root / "packs" / left_packs[0]["pack_id"]).is_dir()
    assert (right_root / "packs" / right_packs[0]["pack_id"]).is_dir()


def test_constructing_second_app_for_same_store_does_not_interrupt_live_claim(
    tmp_path,
) -> None:
    data_dir = tmp_path / "shared" / "data"
    first = create_app(data_dir=data_dir, packs_dir=tmp_path / "first-packs")
    store = KGStore.open(paths.kg_db_path(data_dir))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///live.txt", title="live",
        raw_text="The PaymentGateway uses the DatabaseService.",
        content_hash="sha256:app-live",
    )
    chunks = chunk_document(store.document_raw_text(doc.id))
    state = ExtractionState(store.conn)
    plan = state.plan(
        doc.id, chunks, schema_version_id=1, engine="mock", model=None,
        prompt_version="extract-v1", decode_params=None,
    )
    assert state.claim(plan.run_id, 0)

    second = create_app(data_dir=data_dir, packs_dir=tmp_path / "second-packs")

    assert first.state.jobs is not second.state.jobs
    assert store.conn.execute(
        "SELECT status FROM extraction_chunks WHERE run_id = ?",
        (plan.run_id,),
    ).fetchone()["status"] == "running"
    state.close()
    store.close()


def test_two_apps_keep_job_registries_and_http_job_lists_isolated(tmp_path) -> None:
    left, right = _client(tmp_path / "left"), _client(tmp_path / "right")
    assert left.app.state.jobs is not right.app.state.jobs

    for client, job_id in ((left, "left-only"), (right, "right-only")):
        registry = client.app.state.jobs
        job = Job(job_id=job_id, kind="extract", engine="mock", model=None,
                  started_ts=1.0, _registry=registry)
        with registry._lock:
            registry._jobs[job_id] = job
            registry._order.append(job_id)

    assert [j["job_id"] for j in left.get("/api/jobs").json()["jobs"]] == ["left-only"]
    assert [j["job_id"] for j in right.get("/api/jobs").json()["jobs"]] == ["right-only"]
    assert left.get("/api/jobs/right-only").status_code == 404
    assert right.get("/api/jobs/left-only").status_code == 404


def test_missing_or_malformed_route_state_is_an_explicit_configuration_error(
    tmp_path: Path,
) -> None:
    from ontologylab.server.dependencies import (
        ServerConfigurationError,
        get_app_dependencies,
    )

    app = FastAPI()
    request = Request({"type": "http", "app": app, "path": "/api/documents",
                       "headers": [], "method": "GET", "query_string": b"",
                       "server": ("testserver", 80), "client": ("test", 1),
                       "scheme": "http", "root_path": ""})
    with pytest.raises(ServerConfigurationError, match="data_dir"):
        get_app_dependencies(request)

    app.state.data_dir = "not-a-path"
    app.state.packs_dir = Path("packs")
    app.state.jobs = object()
    with pytest.raises(ServerConfigurationError, match="data_dir"):
        get_app_dependencies(request)

    configured = create_app(
        data_dir=tmp_path / "configured-data",
        packs_dir=tmp_path / "configured-packs",
    )
    del configured.state._state["jobs"]
    client = TestClient(
        configured,
        base_url="http://127.0.0.1",
        raise_server_exceptions=False,
    )
    response = client.get("/api/jobs")
    assert response.status_code == 500
