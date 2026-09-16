"""Server-backed review history + explicit-selection bulk approve.

Two gaps the React rewrite left in the review surface:

- Decided tabs were session-memory — a reload erased who approved or
  rejected what. ``GET /api/proposals/decided`` reads the persisted
  verified_ts/verified_by/review_note columns so history survives.
- ``KGStore.bulk_approve`` existed (filter sweep) but had no HTTP route
  and no UI. ``POST /api/proposals/bulk-approve`` takes the explicit id
  list the reviewer checked; edges whose endpoints are not verified are
  reported as skipped, never silently approved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

pytest.importorskip("fastapi.testclient", reason="fastapi is not installed")
from fastapi.testclient import TestClient  # noqa: E402

from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.models import ProposedEntity, ProposedRelation  # noqa: E402
from ontologylab.server.app import create_app  # noqa: E402


def _seed(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    """Client with two proposed nodes and one proposed edge between them."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = KGStore.open(data_dir / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///t.txt",
        title="t",
        raw_text="Alpha regulates Beta",
        content_hash="db-h1",
    )
    store.insert_proposed(
        [
            ProposedEntity(
                id="n_alpha",
                entity_type="Component",
                name="Alpha",
                confidence=0.9,
            ),
            ProposedEntity(
                id="n_beta",
                entity_type="Component",
                name="Beta",
                confidence=0.8,
            ),
        ],
        [
            ProposedRelation(
                id="e_ab",
                relation_type="part_of",
                src_entity_id="n_alpha",
                dst_entity_id="n_beta",
                confidence=0.7,
            )
        ],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.close()
    return TestClient(create_app(data_dir=data_dir)), {
        "n_alpha": "n_alpha",
        "n_beta": "n_beta",
        "e_ab": "e_ab",
    }


def test_decided_empty_on_fresh_store(tmp_path: Path) -> None:
    client, _ids = _seed(tmp_path)
    body = client.get("/api/proposals/decided").json()
    assert body["items"] == []
    assert body["count"] == 0


def test_decided_lists_approved_with_reviewer_and_note(tmp_path: Path) -> None:
    client, ids = _seed(tmp_path)
    client.post(
        "/api/proposals/approve",
        json={"id": ids["n_alpha"], "by": "reviewer-a", "note": "looks right"},
    )
    body = client.get("/api/proposals/decided").json()
    assert body["count"] == 1
    row = body["items"][0]
    assert row["id"] == ids["n_alpha"]
    assert row["status"] == "verified"
    assert row["verified_by"] == "reviewer-a"
    assert row["review_note"] == "looks right"
    assert row["verified_ts"] is not None


def test_decided_lists_rejected_with_note(tmp_path: Path) -> None:
    client, ids = _seed(tmp_path)
    client.post(
        "/api/proposals/reject",
        json={"id": ids["n_beta"], "by": "reviewer-b", "note": "not a component"},
    )
    body = client.get("/api/proposals/decided?decision=rejected").json()
    assert body["count"] == 1
    row = body["items"][0]
    assert row["status"] == "rejected"
    assert row["verified_by"] == "reviewer-b"
    assert row["review_note"] == "not a component"


def test_decided_filter_by_kind(tmp_path: Path) -> None:
    client, ids = _seed(tmp_path)
    client.post("/api/proposals/approve", json={"id": ids["n_alpha"]})
    client.post("/api/proposals/approve", json={"id": ids["n_beta"]})
    client.post("/api/proposals/approve", json={"id": ids["e_ab"]})
    nodes = client.get("/api/proposals/decided?kind=node").json()
    edges = client.get("/api/proposals/decided?kind=edge").json()
    assert nodes["count"] == 2
    assert edges["count"] == 1
    assert edges["items"][0]["id"] == ids["e_ab"]


def test_decided_rejects_bad_decision(tmp_path: Path) -> None:
    client, _ids = _seed(tmp_path)
    resp = client.get("/api/proposals/decided?decision=proposed")
    assert resp.status_code == 400


def test_bulk_approve_nodes_then_edge(tmp_path: Path) -> None:
    """Approving all three in one batch works: nodes land first."""
    client, ids = _seed(tmp_path)
    resp = client.post(
        "/api/proposals/bulk-approve",
        json={
            "ids": [ids["e_ab"], ids["n_alpha"], ids["n_beta"]],
            "by": "reviewer-c",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert sorted(body["approved"]) == sorted(ids.values())
    assert body["skipped"] == []
    assert body["failed"] == []


def test_bulk_approve_skips_edge_with_unverified_endpoint(tmp_path: Path) -> None:
    """The edge is skipped, not silently approved, when an endpoint is missing."""
    client, ids = _seed(tmp_path)
    resp = client.post(
        "/api/proposals/bulk-approve",
        json={"ids": [ids["e_ab"], ids["n_alpha"]]},
    )
    body = resp.json()
    assert body["approved"] == [ids["n_alpha"]]
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["id"] == ids["e_ab"]
    # The edge is still proposed — the reviewer can re-check it.
    pending = client.get("/api/proposals").json()
    assert any(i["id"] == ids["e_ab"] for i in pending["items"])


def test_bulk_approve_reports_unknown_id(tmp_path: Path) -> None:
    client, ids = _seed(tmp_path)
    resp = client.post(
        "/api/proposals/bulk-approve",
        json={"ids": [ids["n_alpha"], "n_ghost"]},
    )
    body = resp.json()
    assert body["approved"] == [ids["n_alpha"]]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == "n_ghost"


def test_bulk_approve_rejects_empty_ids(tmp_path: Path) -> None:
    client, _ids = _seed(tmp_path)
    resp = client.post("/api/proposals/bulk-approve", json={"ids": []})
    assert resp.status_code == 422


def test_bulk_approve_records_reviewer(tmp_path: Path) -> None:
    client, ids = _seed(tmp_path)
    client.post(
        "/api/proposals/bulk-approve",
        json={"ids": [ids["n_alpha"]], "by": "reviewer-d", "note": "batch ok"},
    )
    decided = client.get("/api/proposals/decided").json()
    assert decided["items"][0]["verified_by"] == "reviewer-d"
    assert decided["items"][0]["review_note"] == "batch ok"


def _seed_stale(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    """Two docs with the same source_uri; the first has a verified node."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = KGStore.open(data_dir / "kg.sqlite")
    doc1, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///paper.txt",
        title="v1",
        raw_text="Alpha",
        content_hash="stale-h1",
    )
    doc2, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///paper.txt",
        title="v2",
        raw_text="Alpha changed",
        content_hash="stale-h2",
    )
    store.insert_proposed(
        [ProposedEntity(
            id="n_stale",
            entity_type="Component",
            name="Alpha",
            confidence=0.9,
        )],
        [],
        source_doc_id=doc1.id,
        extractor_engine="mock",
    )
    store.approve("n_stale", by="reviewer-a")
    store.close()
    return TestClient(create_app(data_dir=data_dir)), {
        "n_stale": "n_stale",
        "doc1": doc1.id,
        "doc2": doc2.id,
    }


def test_stale_flags_verified_with_newer_doc(tmp_path: Path) -> None:
    client, ids = _seed_stale(tmp_path)
    body = client.get("/api/proposals/stale").json()
    assert body["count"] == 1
    row = body["items"][0]
    assert row["id"] == ids["n_stale"]
    assert row["newer_doc_id"] == ids["doc2"]


def test_stale_empty_when_no_newer_doc(tmp_path: Path) -> None:
    client, ids = _seed(tmp_path)
    client.post("/api/proposals/approve", json={"id": ids["n_alpha"]})
    body = client.get("/api/proposals/stale").json()
    assert body["count"] == 0
