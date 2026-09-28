"""A reviewer can propose a source-cited qualified statement over HTTP."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ontologylab.kgstore import KGStore
from ontologylab.schemas import preset
from ontologylab.server.app import create_app


TEXT = "D. suzukii was ineffective in the field.\nSpinosad did not reduce oviposition."


@pytest.fixture
def surface(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    with KGStore.open(data_dir / "kg.sqlite") as store:
        store.install_schema(**preset("agrochem-v2"))
        document, _ = store.insert_document(
            source_kind="upload", source_uri="file:///paper.txt", title="Paper",
            raw_text=TEXT, content_hash="sha256:review-source",
        )
    return TestClient(app), data_dir, document.id


def _request() -> dict:
    start = TEXT.index("Spinosad")
    return {
        "curator": "reviewer", "start": start, "end": len(TEXT),
        "text": TEXT[start:],
        "subject": {"name": "Spinosad", "entity_type": "ActiveIngredient"},
        "relation_type": "controls",
        "object": {"name": "Drosophila suzukii", "entity_type": "Pest"},
        "polarity": "no_effect",
        "qualifiers": {"study_context": "field trial"},
    }


def test_curated_statement_cites_exact_document_span_and_enters_queue(surface) -> None:
    client, data_dir, doc_id = surface
    # Given a valid statement over one exact document span.

    # When a reviewer submits the exact span through the HTTP boundary.
    response = client.post(f"/api/documents/{doc_id}/statements", json=_request())

    # Then the normal queue contains the proposed edge with source citation.
    assert response.status_code == 200, response.text
    edge_id = response.json()["edge_id"]
    assert response.json()["status"] == "proposed"
    queue = client.get("/api/proposals?kind=edge").json()["items"]
    assert any(item["id"] == edge_id for item in queue)
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        edge = store.conn.execute(
            "SELECT status, origin, source_doc_id, source_span, qualifiers_json "
            "FROM edges WHERE id=?", (edge_id,),
        ).fetchone()
        assert (edge["status"], edge["origin"], edge["source_doc_id"]) == (
            "proposed", "curated", doc_id,
        )
        assert json.loads(edge["source_span"]) == {
            "start": _request()["start"], "end": len(TEXT),
        }
        assert json.loads(edge["qualifiers_json"]) == {
            "study_context": "field_trial", "polarity": "no_effect",
        }
        citation = store.conn.execute(
            "SELECT source_doc_id, source_span FROM citations "
            "WHERE kind='edge' AND item_id=?", (edge_id,),
        ).fetchone()
        assert citation["source_doc_id"] == doc_id
        assert json.loads(citation["source_span"]) == json.loads(edge["source_span"])
@pytest.mark.parametrize("change", [
    {"text": "did not reduce"},
    {"start": 999999, "end": 1000000},
    {"end": 0},
])
def test_curated_statement_refuses_nonexact_span_without_writes(surface, change) -> None:
    client, data_dir, doc_id = surface
    # Given a nonexact, out-of-bounds, or reversed document span.
    payload = _request() | change
    # When the reviewer submits it.
    response = client.post(f"/api/documents/{doc_id}/statements", json=payload)
    # Then no graph edge or citation has been recorded.
    assert response.status_code == 422, response.text
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        assert store.conn.execute("SELECT count(*) FROM edges").fetchone()[0] == 0


def test_curated_statement_refuses_unknown_document_and_qualifier(surface) -> None:
    client, data_dir, doc_id = surface
    # Given a missing document or a qualifier outside the closed vocabulary.
    missing = client.post("/api/documents/missing/statements", json=_request())
    bad = client.post(
        f"/api/documents/{doc_id}/statements",
        json=_request() | {"qualifiers": {"invented_scope": "field"}},
    )
    # Then both errors are typed and neither records a proposal.
    assert missing.status_code == 422
    assert bad.status_code == 422
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        assert store.conn.execute("SELECT count(*) FROM edges").fetchone()[0] == 0


def test_duplicate_statement_cannot_relabel_extracted_or_verified_edge(surface) -> None:
    client, data_dir, doc_id = surface
    # Given a proposed curated statement with a canonical qualifier identity.
    first = client.post(f"/api/documents/{doc_id}/statements", json=_request())
    assert first.status_code == 200
    # When the same identity is submitted with its canonical study context.
    repeated = client.post(
        f"/api/documents/{doc_id}/statements",
        json=_request() | {"qualifiers": {"study_context": "field_trial"}},
    )
    # Then it is rejected instead of returning an already-present row as new.
    assert repeated.status_code == 409
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        assert store.conn.execute("SELECT count(*) FROM edges").fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT count(*) FROM citations WHERE kind='edge'"
        ).fetchone()[0] == 1
