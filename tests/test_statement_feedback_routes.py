"""Exercise one-event review commands through the authenticated HTTP API."""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ontologylab.kgstore import KGStore
from ontologylab.kgstore_review import ReviewMixin
from ontologylab.models import ProposedEntity
from ontologylab.schemas import preset
from ontologylab.server.app import create_app


@pytest.fixture
def surface(tmp_path):
    data_dir = tmp_path / "data"
    client = TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))
    with KGStore.open(data_dir / "kg.sqlite") as store:
        store.install_schema(**preset("agrochem-v2"))
        document, _ = store.insert_document(
            source_kind="upload", source_uri="file:///review.txt", title="Review",
            raw_text="Spinosad did not reduce oviposition.",
            content_hash="sha256:feedback-source",
        )
        store.insert_proposed(
            [ProposedEntity(id="review-a", entity_type="ActiveIngredient", name="A"),
             ProposedEntity(id="review-b", entity_type="ActiveIngredient", name="B")],
            [], source_doc_id=document.id, extractor_engine="mock",
        )
    return client, data_dir, document.id


def _statement() -> dict:
    return {
        "curator": "reviewer", "start": 0, "end": 36,
        "text": "Spinosad did not reduce oviposition.",
        "subject": {"name": "Spinosad", "entity_type": "ActiveIngredient"},
        "object": {"name": "Drosophila suzukii", "entity_type": "Pest"},
        "relation_type": "controls", "polarity": "no_effect",
        "qualifiers": {"study_context": "field_trial"},
    }


def _interpretation() -> dict:
    return {
        "curator": "reviewer", "note": "compare candidates",
        "entities": [
            {"name": "Candidate A", "entity_type": "ActiveIngredient",
             "properties": {"cas_number": "58-08-2"}},
            {"name": "Candidate B", "entity_type": "ActiveIngredient",
             "properties": {"cas_number": "58-08-2"}},
        ],
    }


@pytest.mark.parametrize(
    ("endpoint", "payload", "expected_action", "expected_ids"),
    [
        ("/api/proposals/approve", {"id": "review-a", "by": "reviewer"},
         "approve", ("review-a",)),
        ("/api/proposals/reject", {"id": "review-a", "by": "reviewer"},
         "reject", ("review-a",)),
        ("/api/proposals/bulk-approve",
         {"ids": ["review-a", "review-b"], "by": "reviewer"},
         "bulk_approve", ("review-a", "review-b")),
    ],
)
def test_review_http_command_writes_exactly_one_event(
    surface, endpoint, payload, expected_action, expected_ids,
) -> None:
    client, data_dir, _doc_id = surface
    response = client.post(endpoint, json=payload)
    assert response.status_code == 200, response.text
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        rows = store.conn.execute("SELECT * FROM statement_review_events").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == expected_action
        assert row["actor"] == "reviewer"
        assert tuple(json.loads(row["item_ids_json"])) == expected_ids
        before = json.loads(row["before_json"])
        after = json.loads(row["after_json"])
        assert [item["status"] for item in before] == ["proposed"] * len(expected_ids)
        assert [item["status"] for item in after] == [
            "rejected" if expected_action == "reject" else "verified"
        ] * len(expected_ids)
        assert json.loads(row["source_hashes_json"]) == [
            "sha256:feedback-source"
        ]


def test_statement_http_command_has_one_event_and_stays_proposed(surface) -> None:
    client, data_dir, doc_id = surface
    response = client.post(f"/api/documents/{doc_id}/statements", json=_statement())
    assert response.status_code == 200, response.text
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        rows = store.conn.execute(
            "SELECT action, before_json, after_json FROM statement_review_events"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["action"] == "create_statement"
        before = json.loads(rows[0]["before_json"])
        assert before == [{
            "id": doc_id, "kind": "document", "status": None,
            "source_doc_id": doc_id, "source_hash": "sha256:feedback-source",
            "source_span": None, "qualifiers": None, "verified_by": None,
            "invalidated_ts": None,
        }]
        assert any(
            item["id"] == response.json()["edge_id"] and item["status"] == "proposed"
            for item in json.loads(rows[0]["after_json"])
        )


def test_interpretation_http_command_has_one_event_and_stays_proposed(surface) -> None:
    client, data_dir, _doc_id = surface
    response = client.post("/api/interpretations", json=_interpretation())
    assert response.status_code == 200, response.text
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        assert store.conn.execute(
            "SELECT count(*) FROM statement_review_events"
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT count(*) FROM nodes WHERE origin='curated' AND status='proposed'"
        ).fetchone()[0] == 2
        assert store.conn.execute(
            "SELECT count(*) FROM merge_candidates WHERE status='proposed'"
        ).fetchone()[0] == 1


def test_interpretation_snapshots_existing_node_before_alias_merge(surface) -> None:
    client, data_dir, _doc_id = surface
    # Given an extracted node with no aliases, reused by a curated command.
    response = client.post("/api/interpretations", json={
        "curator": "reviewer",
        "entities": [{
            "name": "A", "entity_type": "ActiveIngredient",
            "aliases": ["Alternate A"],
        }],
    })
    assert response.status_code == 200, response.text
    assert response.json()["nodes_merged"] == 1

    # Then the event preserves the original node row, not its post-merge alias.
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        event = store.conn.execute(
            "SELECT before_json, after_json FROM statement_review_events"
        ).fetchone()
        before = {row["id"]: row for row in json.loads(event["before_json"])}
        after = {row["id"]: row for row in json.loads(event["after_json"])}
        assert before["review-a"]["aliases_json"] == "[]"
        assert json.loads(after["review-a"]["aliases_json"]) == ["Alternate A"]
        assert before["review-a"]["source_hash"] == "sha256:feedback-source"


def test_interpretation_snapshots_node_resolved_by_alias(surface) -> None:
    client, data_dir, _doc_id = surface
    first = client.post("/api/interpretations", json={
        "curator": "reviewer",
        "entities": [{
            "name": "A", "entity_type": "ActiveIngredient",
            "aliases": ["Known A"],
        }],
    })
    assert first.status_code == 200, first.text

    second = client.post("/api/interpretations", json={
        "curator": "reviewer",
        "entities": [{
            "name": "Known A", "entity_type": "ActiveIngredient",
            "aliases": ["Another A"],
        }],
    })
    assert second.status_code == 200, second.text
    assert second.json()["nodes_merged"] == 1
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        events = store.conn.execute(
            "SELECT before_json, after_json FROM statement_review_events "
            "ORDER BY created_ts"
        ).fetchall()
        before = {row["id"]: row for row in json.loads(events[1]["before_json"])}
        after = {row["id"]: row for row in json.loads(events[1]["after_json"])}
        assert json.loads(before["review-a"]["aliases_json"]) == ["Known A"]
        assert json.loads(after["review-a"]["aliases_json"]) == [
            "Known A", "Another A"
        ]


def test_statement_snapshots_existing_node_before_alias_merge(surface) -> None:
    client, data_dir, doc_id = surface
    with KGStore.open(data_dir / "kg.sqlite") as store:
        store.insert_proposed(
            [ProposedEntity(
                id="existing-spinosad", entity_type="ActiveIngredient",
                name="Spinosad",
            )],
            [], source_doc_id=doc_id, extractor_engine="mock",
        )

    response = client.post(
        f"/api/documents/{doc_id}/statements",
        json=_statement() | {
            "subject": {
                "name": "Spinosad", "entity_type": "ActiveIngredient",
                "aliases": ["Spinosad Alias"],
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["nodes_new"] == 1
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        event = store.conn.execute(
            "SELECT before_json, after_json FROM statement_review_events"
        ).fetchone()
        before = {row["id"]: row for row in json.loads(event["before_json"])}
        after = {row["id"]: row for row in json.loads(event["after_json"])}
        assert before["existing-spinosad"]["aliases_json"] == "[]"
        assert json.loads(after["existing-spinosad"]["aliases_json"]) == [
            "Spinosad Alias"
        ]


def test_interpretation_snapshots_existing_edge_before_citation_merge(surface) -> None:
    client, data_dir, _doc_id = surface
    command = {
        "curator": "reviewer",
        "entities": [
            {"name": "Spinosad", "entity_type": "ActiveIngredient"},
            {"name": "Drosophila suzukii", "entity_type": "Pest"},
        ],
        "relations": [{
            "relation_type": "controls", "src": 0, "dst": 1,
            "qualifiers": {"polarity": "no_effect"},
        }],
    }
    first = client.post("/api/interpretations", json=command)
    assert first.status_code == 200, first.text
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        edge_id = store.conn.execute("SELECT id FROM edges").fetchone()["id"]

    second = client.post(
        "/api/interpretations", json=command | {"note": "second citation"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["edges_new"] == 0
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        event = store.conn.execute(
            "SELECT before_json FROM statement_review_events "
            "WHERE action='create_interpretation' ORDER BY created_ts DESC LIMIT 1"
        ).fetchone()
        before = {row["id"]: row for row in json.loads(event["before_json"])}
        assert before[edge_id]["kind"] == "edge"
        assert before[edge_id]["status"] == "proposed"
        assert store.conn.execute(
            "SELECT count(*) FROM citations WHERE kind='edge' AND item_id=?",
            (edge_id,),
        ).fetchone()[0] == 2


@pytest.mark.parametrize("command", ("approve", "statement", "interpretation"))
def test_failed_event_rolls_back_http_command(surface, monkeypatch, command) -> None:
    client, data_dir, doc_id = surface
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        before_docs = store.conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        before_nodes = store.conn.execute("SELECT count(*) FROM nodes").fetchone()[0]

    def fail_event(_self: ReviewMixin, _event) -> str:
        raise sqlite3.OperationalError("forced event failure")

    monkeypatch.setattr(ReviewMixin, "record_review_event", fail_event)
    if command == "approve":
        response = client.post("/api/proposals/approve", json={"id": "review-a"})
    elif command == "statement":
        response = client.post(f"/api/documents/{doc_id}/statements", json=_statement())
    else:
        response = client.post("/api/interpretations", json=_interpretation())
    assert response.status_code == 500

    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        assert store.conn.execute(
            "SELECT status FROM nodes WHERE id='review-a'"
        ).fetchone()[0] == "proposed"
        assert store.conn.execute("SELECT count(*) FROM documents").fetchone()[0] == before_docs
        assert store.conn.execute("SELECT count(*) FROM nodes").fetchone()[0] == before_nodes
        for table in ("edges", "merge_candidates", "statement_review_events"):
            assert store.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT count(*) FROM artifacts WHERE kind='source_doc'"
        ).fetchone()[0] == before_docs
    raw_files = list((data_dir / "documents").glob("*/raw.txt"))
    assert len(raw_files) == before_docs


def test_failed_review_action_does_not_write_event(surface) -> None:
    client, data_dir, _doc_id = surface
    response = client.post("/api/proposals/approve", json={"id": "missing"})
    assert response.status_code == 404
    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        assert store.conn.execute(
            "SELECT count(*) FROM statement_review_events"
        ).fetchone()[0] == 0
