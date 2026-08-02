"""Offline tests for the M8 dashboard backend API.

Covers the frozen dashboard contract: /api/documents, /api/collect,
/api/extract + /api/jobs polling, /api/packs (+build), /api/mcp/status,
and the M8 acceptance flow (zero -> queryable pack via the API only).
Everything runs offline: file ingest, mock engine, canned Atom fixture.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

if TestClient is None:
    pytest.skip("fastapi is not installed", allow_module_level=True)

from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.mcp_server import PackSession  # noqa: E402
from ontologylab.server.app import create_app  # noqa: E402

SAMPLE_TEXT = (
    "# Service notes\n\n"
    "The ApiGateway forwards requests to the RateLimiter before they reach\n"
    "the OrderService. The RateLimiter implements the TokenBucketAlgorithm\n"
    "and stores counters in the SessionCache. The OrderService writes into\n"
    "the OrderDatabase.\n"
)

ATOM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query: search_query=all:databases</title>
  <entry>
    <id>http://arxiv.org/abs/9001.00001v1</id>
    <title>Write-Ahead Logging Revisited</title>
    <summary>A survey of WAL implementations in embedded storage engines.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/9001.00002v1</id>
    <title>Cost-Based Join Ordering</title>
    <summary>Cardinality estimation errors and their effect on join plans.</summary>
  </entry>
</feed>
"""


def _make_client(tmp_path: Path) -> tuple[TestClient, Path, Path]:
    data_dir = tmp_path / "data"
    packs_dir = tmp_path / "packs"
    client = TestClient(create_app(data_dir=data_dir, packs_dir=packs_dir))
    return client, data_dir, packs_dir


def _sample_file(tmp_path: Path) -> Path:
    path = tmp_path / "notes.md"
    path.write_text(SAMPLE_TEXT, encoding="utf-8")
    return path


def _wait_for_job(client: TestClient, job_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    pytest.fail(f"job {job_id} still running after {timeout_s}s")


def _approve_all(client: TestClient) -> None:
    """Approve every pending proposal: nodes first, then edges (cascade)."""
    for _ in range(10):  # bounded; one pass normally suffices
        items = client.get("/api/proposals").json()["items"]
        if not items:
            return
        for item in [i for i in items if i["kind"] == "node"]:
            resp = client.post("/api/proposals/approve", json={"id": item["id"]})
            assert resp.status_code == 200, resp.text
        for item in [i for i in items if i["kind"] == "edge"]:
            resp = client.post(
                "/api/proposals/approve", json={"id": item["id"], "cascade": True}
            )
            assert resp.status_code == 200, resp.text
    pytest.fail("proposals queue did not drain")


# ---------------------------------------------------------------------------
# /api/documents + /api/collect (file ingest, dedupe)
# ---------------------------------------------------------------------------


def test_collect_file_then_documents_lists_it(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    empty = client.get("/api/documents")
    assert empty.status_code == 200
    assert empty.json() == {"documents": [], "count": 0}

    resp = client.post(
        "/api/collect", json={"files": [str(_sample_file(tmp_path))]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "documents": 1, "created": 1, "duplicates": 0}

    listed = client.get("/api/documents").json()
    assert listed["count"] == 1
    doc = listed["documents"][0]
    assert doc["source_kind"] == "upload"
    assert doc["title"] == "notes"
    assert set(doc) == {
        "id", "source_kind", "source_uri", "title", "fetched_ts", "content_hash",
    }


def test_collect_duplicate_file_counts_duplicates(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    sample = str(_sample_file(tmp_path))
    assert client.post("/api/collect", json={"files": [sample]}).json()["created"] == 1

    again = client.post("/api/collect", json={"files": [sample]}).json()
    assert again == {"ok": True, "documents": 1, "created": 0, "duplicates": 1}
    assert client.get("/api/documents").json()["count"] == 1


# ---------------------------------------------------------------------------
# /api/collect gate rejections (200 + ok:false, never 4xx/5xx)
# ---------------------------------------------------------------------------


def test_collect_non_allowlisted_url_rejected(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    resp = client.post(
        "/api/collect", json={"urls": ["https://evil.example.com/page"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_kind"] == "rejected"
    assert "allowlist" in body["detail"]
    # gate fired before any fetch -> nothing was ingested
    assert client.get("/api/documents").json()["count"] == 0


CROSSREF_FIXTURE = """{
  "message": {
    "items": [
      {
        "DOI": "10.1145/1327452.1327492",
        "URL": "https://doi.org/10.1145/1327452.1327492",
        "title": ["MapReduce: simplified data processing on large clusters"],
        "abstract": "<jats:p>A programming model for large data sets.</jats:p>"
      }
    ]
  }
}"""


def test_collect_crossref_allowlisted_query_ingests(
    tmp_path: Path, monkeypatch
) -> None:
    """crossref is a real source now: an allowlisted query ingests rows."""
    client, _, _ = _make_client(tmp_path)
    monkeypatch.setattr(
        "ontologylab.connectors.paper_api._http_get_text",
        lambda url: CROSSREF_FIXTURE,
    )
    resp = client.post(
        "/api/collect",
        json={"paper_queries": ["databases"], "paper_source": "crossref"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "documents": 1, "created": 1, "duplicates": 0}
    listed = client.get("/api/documents").json()
    assert listed["count"] == 1
    assert listed["documents"][0]["source_kind"] == "paper_api"


def test_collect_non_allowlisted_source_rejected(tmp_path: Path) -> None:
    """A source outside the allowlist is rejected before any fetch."""
    client, _, _ = _make_client(tmp_path)
    resp = client.post(
        "/api/collect",
        json={"paper_queries": ["databases"], "paper_source": "semantic-scholar"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_kind"] == "rejected"


def test_collect_no_inputs_is_ok_false(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    resp = client.post("/api/collect", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_kind"] == "rejected"
    for word in ("urls", "files", "paper_queries"):
        assert word in body["detail"]


# ---------------------------------------------------------------------------
# /api/collect paper query (canned Atom fixture, offline)
# ---------------------------------------------------------------------------


def test_collect_paper_query_with_canned_atom(tmp_path: Path, monkeypatch) -> None:
    client, _, _ = _make_client(tmp_path)
    monkeypatch.setattr(
        "ontologylab.connectors.paper_api._http_get_text", lambda url: ATOM_FIXTURE
    )
    resp = client.post("/api/collect", json={"paper_queries": ["databases"]})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "documents": 2, "created": 2, "duplicates": 0}

    listed = client.get("/api/documents").json()
    assert listed["count"] == 2
    assert {d["source_kind"] for d in listed["documents"]} == {"paper_api"}
    titles = {d["title"] for d in listed["documents"]}
    assert "Write-Ahead Logging Revisited" in titles


# ---------------------------------------------------------------------------
# /api/extract + /api/jobs lifecycle
# ---------------------------------------------------------------------------


def test_extract_job_lifecycle(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    client.post("/api/collect", json={"files": [str(_sample_file(tmp_path))]})

    resp = client.post("/api/extract", json={"engine": "mock"})
    assert resp.status_code == 202
    body = resp.json()
    job_id = body["job_id"]
    assert body == {"job_id": job_id, "status": "running"}

    status = _wait_for_job(client, job_id)
    assert status["status"] == "complete"
    assert status["kind"] == "extract"
    assert status["engine"] == "mock"
    assert status["error"] is None
    assert status["finished_ts"] is not None
    assert status["totals"]["nodes_new"] > 0
    assert status["totals"]["edges_new"] > 0
    assert status["progress"]  # ring-buffer log lines
    assert len(status["progress"]) <= 50

    jobs = client.get("/api/jobs").json()["jobs"]
    assert [j["job_id"] for j in jobs] == [job_id]
    assert jobs[0]["status"] == "complete"

    missing = client.get("/api/jobs/does-not-exist")
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# /api/packs + /api/packs/build + /api/mcp/status
# ---------------------------------------------------------------------------


def test_packs_build_list_and_mcp_status(tmp_path: Path) -> None:
    client, _, packs_dir = _make_client(tmp_path)
    client.post("/api/collect", json={"files": [str(_sample_file(tmp_path))]})
    job_id = client.post("/api/extract", json={"engine": "mock"}).json()["job_id"]
    assert _wait_for_job(client, job_id)["status"] == "complete"
    _approve_all(client)

    assert client.get("/api/packs").json() == {"packs": [], "count": 0}

    built = client.post("/api/packs/build", json={"name": "svcnotes"})
    assert built.status_code == 200
    body = built.json()
    assert body["ok"] is True
    manifest = body["manifest"]
    pack_id = manifest["pack_id"]
    assert pack_id.startswith("svcnotes-")
    assert manifest["counts"]["nodes_verified"] > 0

    listed = client.get("/api/packs").json()
    assert listed["count"] == 1
    assert listed["packs"][0]["pack_id"] == pack_id

    status = client.get("/api/mcp/status").json()
    packs_abs = status["packs_dir"]
    assert packs_abs == str(packs_dir.resolve())
    assert status["count"] == 1
    entry = status["packs"][0]
    assert entry["pack_id"] == pack_id
    assert entry["counts"] == manifest["counts"]
    assert entry["created_ts"] == manifest["created_ts"]
    assert entry["serve_command"] == (
        f"python -m ontologylab.mcp_server --packs-dir {packs_abs} --pack {pack_id}"
    )
    assert entry["stdio_config"] == {
        "command": "python",
        "args": [
            "-m", "ontologylab.mcp_server", "--packs-dir", packs_abs,
            "--pack", pack_id,
        ],
    }


def test_packs_api_refuses_incomplete_and_accepts_audited_override(
    tmp_path: Path,
) -> None:
    client, data_dir, _ = _make_client(tmp_path)
    client.post("/api/collect", json={"files": [str(_sample_file(tmp_path))]})
    job_id = client.post("/api/extract", json={"engine": "mock"}).json()["job_id"]
    assert _wait_for_job(client, job_id)["status"] == "complete"
    _approve_all(client)

    store = KGStore.open(data_dir / "kg.sqlite")
    store.conn.execute("UPDATE extraction_runs SET status = 'interrupted'")
    store.conn.execute("UPDATE extraction_chunks SET status = 'interrupted'")
    store.conn.commit()
    store.close()

    refused = client.post("/api/packs/build", json={"name": "refused"}).json()
    assert refused["ok"] is False
    assert refused["error_code"] == "incomplete_extraction"
    assert refused["extraction_completeness"]["status"] == "incomplete"

    built = client.post(
        "/api/packs/build",
        json={
            "name": "overridden",
            "allow_incomplete_extraction": True,
            "override_intent": "publish after manual review",
        },
    ).json()
    assert built["ok"] is True
    assert built["manifest"]["extraction_completeness"]["override"] == {
        "used": True,
        "operator_intent": "publish after manual review",
    }


def test_packs_build_with_zero_verified_rows_is_ok(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    built = client.post("/api/packs/build", json={"name": "empty"})
    assert built.status_code == 200
    body = built.json()
    assert body["ok"] is True
    assert body["manifest"]["counts"]["nodes_verified"] == 0


# ---------------------------------------------------------------------------
# M8 acceptance: zero -> queryable pack entirely through the API
# ---------------------------------------------------------------------------


def test_m8_acceptance_zero_to_queryable_pack(tmp_path: Path) -> None:
    client, _, packs_dir = _make_client(tmp_path)
    assert client.get("/api/documents").json()["count"] == 0

    # collect (file ingest, offline)
    collected = client.post(
        "/api/collect", json={"files": [str(_sample_file(tmp_path))]}
    ).json()
    assert collected["ok"] is True and collected["created"] == 1

    # extract (mock engine) and poll to completion
    job_id = client.post("/api/extract", json={"engine": "mock"}).json()["job_id"]
    status = _wait_for_job(client, job_id)
    assert status["status"] == "complete"
    assert status["totals"]["nodes_new"] > 0

    # human gate + pack build, all via the API
    _approve_all(client)
    built = client.post("/api/packs/build", json={"name": "m8accept"}).json()
    assert built["ok"] is True
    pack_id = built["manifest"]["pack_id"]

    # MCP status shows the pack with its stdio serve config
    status = client.get("/api/mcp/status").json()
    by_id = {p["pack_id"]: p for p in status["packs"]}
    assert pack_id in by_id
    assert by_id[pack_id]["stdio_config"]["args"][-1] == pack_id

    # ...and the pack is actually queryable through the MCP session layer.
    session = PackSession(packs_dir)
    try:
        loaded = session.load_pack(pack_id)
        assert loaded["counts"]["nodes_verified"] > 0
        found = session.entity_lookup(name="ApiGateway")
        assert found["count"] >= 1
        assert found["matches"][0]["status"] == "verified"
    finally:
        session.close()
