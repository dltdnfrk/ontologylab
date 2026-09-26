"""Curated interpretations sit beside extracted facts, never inside extraction."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab.extractor import build_extraction_prompt, chunk_document, parse_and_validate_extraction
from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.packbuilder import UnevidencedInterpretationError, build_pack
from ontologylab.server.app import create_app
from tests.conftest import insert
from tests.factories import make_entity


def _overlay_schema(store: KGStore) -> None:
    store.install_schema(
        label="overlay-fixture",
        description="one extracted type, one curated type",
        entity_types=[
            {"name": "Component", "description": "", "attributes": {}},
            {"name": "Question", "description": "a watch question",
             "attributes": {}, "extractable": False},
        ],
        relation_types=[
            {"name": "uses", "domain_type": "Component", "range_type": "Component"},
            {"name": "evidenced_by", "domain_type": "Question", "range_type": "*"},
        ],
    )


def _curate(store: KGStore, question: str, fact: str | None) -> dict:
    entities = [ProposedEntity(id="q", entity_type="Question", name=question)]
    relations = []
    if fact is not None:
        entities.append(ProposedEntity(id="f", entity_type="Component", name=fact))
        relations.append(ProposedRelation(
            id="r", relation_type="evidenced_by", src_entity_id="q", dst_entity_id="f",
        ))
    return store.insert_curated(entities, relations, curator="analyst")


def test_curated_types_are_hidden_from_the_extractor(store) -> None:
    _overlay_schema(store)
    schema = store.get_schema()
    prompt = build_extraction_prompt(schema, "RateLimiter protects ApiGateway")
    assert "Question" not in prompt
    assert "evidenced_by" not in prompt
    assert next(e for e in schema["entity_types"] if e["name"] == "Question")[
        "extractable"
    ] is False


def test_model_output_of_a_curated_type_is_rejected(store) -> None:
    _overlay_schema(store)
    chunk = chunk_document("Will RateLimiter hold?")[0]
    raw = "```json\n" + json.dumps({"entities": [{
        "name": "Will RateLimiter hold?", "entity_type": "Question",
        "source_span": {"start": 0, "end": 22},
    }], "relations": []}) + "\n```"
    result = parse_and_validate_extraction(raw, store.get_schema(), chunk)
    assert result.entities == []


def test_curation_resolves_to_existing_facts_and_marks_origin(store, doc) -> None:
    _overlay_schema(store)
    insert(store, doc, [make_entity("RateLimiter")])
    stats = _curate(store, "Does RateLimiter hold under load?", "RateLimiter")
    assert stats["nodes_merged"] == 1
    origins = dict(store.conn.execute("SELECT name, origin FROM nodes").fetchall())
    assert origins == {
        "RateLimiter": "extracted",
        "Does RateLimiter hold under load?": "curated",
    }
    kinds = {row[0] for row in store.conn.execute("SELECT source_kind FROM documents")}
    assert "curation" in kinds


def _verify_all(store: KGStore) -> None:
    for (item,) in store.conn.execute(
        "SELECT id FROM nodes WHERE status='proposed'"
    ).fetchall():
        store.approve(item)
    for (item,) in store.conn.execute(
        "SELECT id FROM edges WHERE status='proposed'"
    ).fetchall():
        store.approve(item)


def _pack(tmp_path: Path):
    return build_pack(
        tmp_path / "kg.sqlite", tmp_path / "packs", name="overlay",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="overlay fixture",
    )


def test_pack_refuses_an_interpretation_without_verified_evidence(tmp_path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    _overlay_schema(store)
    _curate(store, "Is anything happening?", None)
    _verify_all(store)
    store.close()
    with pytest.raises(UnevidencedInterpretationError):
        _pack(tmp_path)


def test_pack_ships_an_interpretation_linked_to_verified_evidence(tmp_path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    _overlay_schema(store)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///e.txt", title="e",
        raw_text="RateLimiter", content_hash="sha256:e",
    )
    insert(store, doc, [make_entity("RateLimiter")])
    _curate(store, "Does RateLimiter hold?", "RateLimiter")
    _verify_all(store)
    store.close()
    manifest = _pack(tmp_path)
    assert manifest.pack_id


@pytest.fixture()
def client(tmp_path):
    os.environ.setdefault("ONTOLOGYLAB_ALLOWED_HOSTS", "testserver")
    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    test_client = TestClient(app)
    with KGStore.open(tmp_path / "data" / "kg.sqlite") as store:
        _overlay_schema(store)
    return test_client


def test_interpretation_endpoint_records_proposed_curated_rows(client) -> None:
    response = client.post("/api/interpretations", json={
        "curator": "analyst", "note": "watch item",
        "entities": [{"name": "Will it rain?", "entity_type": "Question"},
                     {"name": "RainGauge", "entity_type": "Component"}],
        "relations": [{"relation_type": "evidenced_by", "src": 0, "dst": 1}],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["edges_new"] == 1
    assert len(body["node_ids"]) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"curator": "analyst", "entities": []},
        {"curator": "analyst", "entities": [{"name": "Q", "entity_type": "Question"}],
         "relations": [{"relation_type": "evidenced_by", "src": 0, "dst": 5}]},
        {"curator": "analyst", "entities": [{"name": "Q", "entity_type": "NoSuchType"}]},
    ],
)
def test_interpretation_endpoint_refuses_unusable_input(client, payload) -> None:
    assert client.post("/api/interpretations", json=payload).status_code == 422
