"""Research facts cross human approval, pack, and real stdio MCP."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ontologylab import research_run as research_run_module
from ontologylab import research_spec
from ontologylab.server.app import create_app
from tests.test_research_run import (
    _axis,
    _axis_fetch,
    _install_planner,
    _need,
    _paper,
    _planned_reading,
    _run,
)
from tests.wave21.surface import mcp_stdio_roundtrip


def _approve_all_as_reviewer(client: TestClient) -> None:
    items = client.get("/api/proposals").json()["items"]
    nodes = [item for item in items if item["kind"] == "node"]
    edges = [item for item in items if item["kind"] == "edge"]
    assert nodes
    assert edges
    for item in nodes:
        response = client.post(
            "/api/proposals/approve",
            json={"id": item["id"], "by": "qa-reviewer"},
        )
        assert response.status_code == 200, response.text
    for item in edges:
        response = client.post(
            "/api/proposals/approve",
            json={
                "id": item["id"],
                "by": "qa-reviewer",
                "cascade": True,
            },
        )
        assert response.status_code == 200, response.text
    assert client.get("/api/proposals").json()["items"] == []


def _lookup_payload(receipt) -> dict:
    assert receipt.entity_lookup_result["isError"] is False
    return json.loads(receipt.entity_lookup_result["content"][0]["text"])


def test_research_requires_human_approval_before_real_mcp_publication(
    tmp_path: Path,
    monkeypatch,
) -> None:
    need = _need(
        research_spec.EvidenceNeedKind.MECHANISM,
        "payment processing mechanism",
    )
    query = "payment gateway mechanism"
    _install_planner(
        monkeypatch,
        _planned_reading(
            (need,),
            (_axis("mechanism", query, (need.need_id,)),),
        ),
    )
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _axis_fetch({query: [_paper("crossref", "10.1/research-mcp")]}),
    )
    data_dir = tmp_path / "data"
    packs_dir = tmp_path / "packs"
    client = TestClient(
        create_app(data_dir=data_dir, packs_dir=packs_dir)
    )

    job = _run(
        client,
        sources=["crossref"],
        max_queries=1,
        fulltext=False,
    )
    assert job.status == "complete", job.error
    documents = client.get("/api/documents").json()["documents"]
    document_ids = {document["id"] for document in documents}
    assert document_ids

    before = client.post(
        "/api/packs/build",
        json={"name": "research-before-review"},
    ).json()
    assert before["ok"] is True
    before_receipt = mcp_stdio_roundtrip(
        packs_dir,
        before["manifest"]["pack_id"],
        entity_name="PaymentGateway",
    )
    assert _lookup_payload(before_receipt)["count"] == 0

    _approve_all_as_reviewer(client)

    after = client.post(
        "/api/packs/build",
        json={"name": "research-after-review"},
    ).json()
    assert after["ok"] is True
    after_pack_id = after["manifest"]["pack_id"]
    after_receipt = mcp_stdio_roundtrip(
        packs_dir,
        after_pack_id,
        entity_name="PaymentGateway",
    )
    payload = _lookup_payload(after_receipt)

    assert payload["count"] >= 1
    assert payload["matches"][0]["status"] == "verified"
    assert payload["matches"][0]["source_doc_id"] in document_ids
    assert payload["pack"]["pack_id"] == after_pack_id
    assert after_receipt.process_returncode == 0
