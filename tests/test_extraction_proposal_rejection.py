"""Store-invalid model proposals must not discard their valid neighbors."""

from __future__ import annotations

import json

import pytest

from ontologylab import extractor
from ontologylab.kgstore import SchemaValidationError
from ontologylab.models import ProposedEntity
from ontologylab.schemas import preset
from tests.test_engine_json_retry import CountingEngine, drive


@pytest.mark.parametrize("invalid_value", [None, "", 123, [], {}])
def test_invalid_product_is_rejected_without_aborting_chunk_or_run(
    store, tmp_path, monkeypatch, invalid_value,
):
    # Given two chunks and an invalid Product beside valid nodes and edges.
    schema = preset("agrochem-v2")
    store.install_schema(
        label=schema["label"], description=schema["description"],
        entity_types=schema["entity_types"], relation_types=schema["relation_types"],
    )
    text = "BadProduct GoodProduct AgentCedar LaterProduct"
    monkeypatch.setattr(extractor, "chunk_document", lambda raw: [
        extractor.Chunk(0, 0, raw[:34]),
        extractor.Chunk(1, 34, raw[34:]),
    ])
    entities = [
        {"name": "BadProduct", "entity_type": "Product",
         "properties": {"registration_number": invalid_value}},
        {"name": "GoodProduct", "entity_type": "Product",
         "properties": {"registration_number": "REG-1"}},
        {"name": "AgentCedar", "entity_type": "ActiveIngredient"},
    ]
    relations = [
        {"source": {"name": name, "entity_type": "Product"},
         "target": {"name": "AgentCedar", "entity_type": "ActiveIngredient"},
         "relation_type": "contains"}
        for name in ("BadProduct", "GoodProduct")
    ]
    engine = CountingEngine([
        json.dumps({"entities": entities, "relations": relations}),
        json.dumps({"entities": [
            {"name": "LaterProduct", "entity_type": "Product"},
        ], "relations": []}),
    ])

    # When the real extraction loop parses, normalizes and writes the chunk.
    outcome, provenance = drive(store, tmp_path, engine, text=text)

    # Then valid neighbors and the next chunk survive without coercion.
    assert outcome == ""
    assert not outcome.chunk_failed
    assert engine.calls == provenance.engine_calls == 2
    assert {row[0] for row in store.conn.execute("SELECT name FROM nodes")} == {
        "GoodProduct", "AgentCedar", "LaterProduct",
    }
    assert store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 1
    assert [row[0] for row in store.conn.execute(
        "SELECT status FROM extraction_chunks ORDER BY chunk_index"
    )] == ["succeeded", "succeeded"]
    assert store.conn.execute(
        "SELECT status FROM extraction_runs"
    ).fetchone()[0] == "complete"
    records = [json.loads(line) for line in provenance.jsonl_path.read_text().splitlines()]
    rejected = [row["payload"] for row in records
                if row["step"] == "extract.proposal_rejected"]
    assert len(rejected) == 2
    entity_rejection = next(row for row in rejected if row["kind"] == "entity")
    assert entity_rejection["name"] == "BadProduct"
    assert entity_rejection["type"] == "SchemaValidationError"
    assert "registration_number" in entity_rejection["error"]
    assert entity_rejection["chunk"] == 0
    assert entity_rejection["doc_id"]
    relation_rejection = next(row for row in rejected if row["kind"] == "relation")
    assert relation_rejection["reason"] == "rejected_endpoint"

    # Direct callers still receive the strict store refusal.
    with pytest.raises(SchemaValidationError, match="registration_number"):
        store.insert_proposed(
            [ProposedEntity(
                id="direct-invalid", name="BadProduct", entity_type="Product",
                properties={"registration_number": invalid_value},
            )],
            [], source_doc_id=entity_rejection["doc_id"], extractor_engine="scripted",
        )
