"""Proposal refusals must survive API serialization and job-history reload."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ontologylab.kgstore import KGStore
from ontologylab.schemas import preset
from ontologylab.server import jobs
from ontologylab.server.app import create_app
from tests.test_partial_chunk_failure import _join


@pytest.mark.parametrize(
    "scenario, expected_status, expected_rejected, expected_nodes",
    [
        ("all_invalid", "failed", 2, 0),
        ("mixed", "complete", 2, 2),
        ("merged", "complete", 2, 2),
        ("empty", "complete", 0, 0),
        ("later_crash", "failed", 1, 1),
        ("capped_invalid", "cancelled", 1, 0),
        ("dependent_relation", "complete", 2, 1),
        ("write_failure", "failed", 1, 0),
    ],
)
def test_job_api_surfaces_rejected_proposals(
    tmp_path, monkeypatch, scenario, expected_status, expected_rejected, expected_nodes,
):
    # Given two documents; no network or actual model is involved.
    data_dir = tmp_path / "data"
    store = KGStore.open(data_dir / "kg.sqlite")
    try:
        schema = preset("agrochem-v2")
        store.install_schema(
            label=schema["label"], description=schema["description"],
            entity_types=schema["entity_types"], relation_types=schema["relation_types"],
        )
        doc_ids = []
        for index in range(2):
            doc, _ = store.insert_document(
                source_kind="upload", source_uri=f"file:///rejection-{index}.txt",
                title=f"rejection-{index}", content_hash=f"sha256:rejection-{index}",
                raw_text=f"BadProduct GoodProduct{index} AgentCedar",
            )
            doc_ids.append(doc.id)
        if scenario == "merged":
            from ontologylab.models import ProposedEntity

            store.insert_proposed([
                ProposedEntity(id=f"existing-{index}", entity_type="Product",
                               name=f"GoodProduct{index}")
                for index in range(2)
            ], [], source_doc_id=doc_ids[0], extractor_engine="fixture")
    finally:
        store.close()

    class ScriptedEngine:
        calls = 0

        async def generate(self, prompt, *, model=None):
            index = self.calls
            self.calls += 1
            if scenario == "later_crash" and index == 1:
                raise RuntimeError("scripted interruption")
            entities = []
            if scenario != "empty":
                entities.append({
                    "name": "BadProduct", "entity_type": "Product",
                    "properties": {"registration_number": None},
                })
            if scenario in {"mixed", "merged", "later_crash", "write_failure"}:
                entities.append({
                    "name": f"GoodProduct{index}", "entity_type": "Product",
                })
            relations = []
            if scenario == "dependent_relation":
                entities.append({"name": "AgentCedar", "entity_type": "ActiveIngredient"})
                relations.append({
                    "source": {"name": "BadProduct", "entity_type": "Product"},
                    "target": {"name": "AgentCedar", "entity_type": "ActiveIngredient"},
                    "relation_type": "contains",
                })
            return json.dumps({"entities": entities, "relations": relations}), {}

    engine = ScriptedEngine()
    monkeypatch.setattr(jobs, "resolve_engine", lambda *args, **kwargs: engine)
    if scenario == "write_failure":
        def fail_write(*args, **kwargs):
            raise RuntimeError("scripted store interruption after validation")

        monkeypatch.setattr(KGStore, "insert_proposed", fail_write)
    app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")

    # When the HTTP entry point's real worker finishes (join, never sleep).
    with TestClient(app) as client:
        started = client.post("/api/extract", json={
            "engine": "mock", "doc_ids": doc_ids, "seed": 7,
            "max_engine_calls": 1 if scenario == "capped_invalid" else 10,
        })
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        job = app.state.jobs.get(job_id)
        _join(job)
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        status = response.json()
        listed = next(row for row in client.get("/api/jobs").json()["jobs"]
                      if row["job_id"] == job_id)

    # Then the wire result exposes exact typed counts, including all-rejected.
    assert status["status"] == expected_status
    expected_relations = 2 if scenario == "dependent_relation" else 0
    expected_warnings = [{
        "code": "proposals_rejected",
        "entities_rejected": expected_rejected,
        "relations_rejected": expected_relations,
    }] if expected_rejected else []
    assert status["warnings"] == listed["warnings"] == expected_warnings
    assert status["totals"]["entities_rejected"] == expected_rejected
    if scenario == "all_invalid":
        assert status["error"] == "extraction failed: all_proposals_rejected"
    elif scenario in {"mixed", "merged", "empty"}:
        assert status["error"] is None
    if scenario == "merged":
        assert status["totals"]["nodes_new"] == 0
        assert status["totals"]["nodes_merged"] == 2
    with KGStore.open(data_dir / "kg.sqlite") as store:
        assert store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == expected_nodes
    records = [json.loads(line) for line in (
        data_dir / "jobs" / job_id / "provenance.jsonl"
    ).read_text().splitlines()]
    assert len([row for row in records
                if row["step"] == "extract.proposal_rejected"]) == (
                    expected_rejected + expected_relations
                )
    if expected_rejected:
        assert any(step["action"] == "proposal_rejected"
                   and step["status"] == "failed" for step in status["steps"])

    # Counts remain visible when the bounded in-memory job log is gone.
    restored_job = jobs.JobRegistry(data_dir).get(job_id)
    assert restored_job is not None
    restored = restored_job.as_status()
    assert restored["status"] == status["status"]
    assert restored["warnings"] == expected_warnings
