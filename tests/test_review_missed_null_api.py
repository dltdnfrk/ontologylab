"""Read-only review candidates retain already extracted comparison arms."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ontologylab.kgstore import KGStore
from ontologylab.schemas import preset
from ontologylab.server.app import create_app


def test_review_candidates_show_partial_sentence_and_cited_statements(tmp_path) -> None:
    # Given one sentence reporting two null arms and a reviewer-created first arm.
    text = "Spinosad and deltamethrin were ineffective against D. suzukii."
    data_dir = tmp_path / "data"
    client = TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))
    with KGStore.open(data_dir / "kg.sqlite") as store:
        store.install_schema(**preset("agrochem-v2"))
        document, _ = store.insert_document(
            source_kind="upload", source_uri="file:///two-arms.txt", title="Two arms",
            raw_text=text, content_hash="sha256:two-arms",
        )
    body = {
        "curator": "reviewer", "start": 0, "end": len(text), "text": text,
        "subject": {"name": "Spinosad", "entity_type": "ActiveIngredient"},
        "relation_type": "controls",
        "object": {"name": "Drosophila suzukii", "entity_type": "Pest"},
        "polarity": "no_effect", "qualifiers": {"study_context": "field_trial"},
    }
    first = client.get("/api/review/missed-null")
    assert first.status_code == 200, first.text
    assert first.json()["count"] == 1
    initial = first.json()["documents"][0]["candidates"][0]
    assert (initial["status"], initial["existing_statements"]) == ("unextracted", [])
    created = client.post(f"/api/documents/{document.id}/statements", json=body)
    assert created.status_code == 200, created.text

    # When the same document is read after one arm has been proposed.
    response = client.get("/api/review/missed-null")

    # Then the sentence remains in review and names the existing arm.
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 1
    candidate = response.json()["documents"][0]["candidates"][0]
    assert candidate["text"] == text
    assert candidate["status"] == "partially_extracted"
    assert candidate["existing_statements"] == [{
        "edge_id": created.json()["edge_id"],
        "subject": "Spinosad",
        "relation_type": "controls",
        "object": "Drosophila suzukii",
        "polarity": "no_effect",
        "qualifiers": {"polarity": "no_effect", "study_context": "field_trial"},
        "status": "proposed",
        "origin": "curated",
        "start": 0,
        "end": len(text),
    }]
    second = client.post(f"/api/documents/{document.id}/statements", json={
        **body, "subject": {"name": "Deltamethrin", "entity_type": "ActiveIngredient"}
    })
    assert second.status_code == 200, second.text
    assert len(client.get("/api/review/missed-null").json()["documents"][0][
        "candidates"][0]["existing_statements"]) == 2
    queue = client.get("/api/proposals?kind=edge").json()["items"]
    assert {created.json()["edge_id"], second.json()["edge_id"]} <= {
        item["id"] for item in queue
    }
