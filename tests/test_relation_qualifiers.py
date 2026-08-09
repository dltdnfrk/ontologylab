"""First-class relation qualifier contract across extraction, review, and packs."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from ontologylab.engines import EngineError, MockEngine, extract_fenced_block
from ontologylab.extractor import (
    Chunk,
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
)
from ontologylab.kgstore import KGStore, SchemaValidationError
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.packbuilder import build_pack


QUALIFIER_SPECS = {
    "evidence_level": {
        "type": "string",
        "enum": ["field", "laboratory"],
        "required": False,
    },
    "replicate_count": {"type": "integer", "minimum": 1, "required": False},
}


def _install_qualified_schema(store: KGStore) -> dict:
    store.install_schema(
        label="qualified-v1",
        description="relation qualifier fixture",
        entity_types=[
            {"name": "Component", "description": "", "attributes": {}}
        ],
        relation_types=[
            {
                "name": "uses",
                "description": "source uses target",
                "domain_type": "Component",
                "range_type": "Component",
                "directed": True,
                "qualifiers": QUALIFIER_SPECS,
            }
        ],
    )
    return store.get_schema()


def _mock_output_with_qualifiers(schema: dict, text: str, qualifiers: dict) -> tuple[str, Chunk]:
    """Use the real schema-driven MockEngine, then supply its model qualifier output."""
    chunk = chunk_document(text)[0]
    raw, _usage = asyncio.run(
        MockEngine().generate(build_extraction_prompt(schema, chunk.text), model=None)
    )
    payload = json.loads(extract_fenced_block(raw))
    assert payload["relations"], "fixture requires MockEngine to emit a relation"
    payload["relations"][0]["qualifiers"] = qualifiers
    return "```json\n" + json.dumps(payload) + "\n```", chunk


def _insert_document(store: KGStore, text: str, content_hash: str):
    document, created = store.insert_document(
        source_kind="upload",
        source_uri="file:///qualifiers.txt",
        title="qualifiers",
        raw_text=text,
        content_hash=content_hash,
    )
    assert created
    return document


def test_existing_mock_extraction_reaches_review_without_qualifiers(store, doc) -> None:
    """Characterize the pre-qualifier extraction-to-review happy path."""
    schema = store.get_schema()
    chunk = chunk_document("ApiGateway uses RateLimiter.")[0]
    raw, _usage = asyncio.run(
        MockEngine().generate(build_extraction_prompt(schema, chunk.text), model=None)
    )
    result = parse_and_validate_extraction(raw, schema, chunk)

    store.insert_proposed(
        result.entities,
        result.relations,
        source_doc_id=doc.id,
        extractor_engine="mock",
    )

    edge_rows = store.pending_review(kind="edge")
    assert len(edge_rows) == 1
    assert edge_rows[0]["type_name"] == result.relations[0].relation_type


def test_qualifier_round_trips_extraction_review_pack_and_query(tmp_path: Path) -> None:
    kg_path = tmp_path / "kg.sqlite"
    store = KGStore.open(kg_path)
    schema = _install_qualified_schema(store)
    prompt = build_extraction_prompt(schema, "ApiGateway uses RateLimiter.")
    assert '"evidence_level"' in prompt
    assert '"field"' in prompt

    raw, chunk = _mock_output_with_qualifiers(
        schema,
        "ApiGateway uses RateLimiter.",
        {"evidence_level": "field", "replicate_count": 3},
    )
    result = parse_and_validate_extraction(raw, schema, chunk)
    assert result.relations[0].qualifiers == {
        "evidence_level": "field",
        "replicate_count": 3,
    }

    doc = _insert_document(store, chunk.text, "qualifier-roundtrip")
    store.insert_proposed(
        result.entities,
        result.relations,
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    review_edge = store.pending_review(kind="edge")[0]
    assert review_edge["qualifiers"] == result.relations[0].qualifiers
    entity_review = store.entity_review_context(result.entities[0].id)
    assert entity_review["relations"][0]["qualifiers"] == result.relations[0].qualifiers

    for entity in result.entities:
        store.approve(entity.id, by="qualifier-test")
    store.approve(result.relations[0].id, by="qualifier-test")
    store.close()

    manifest = build_pack(
        kg_path,
        tmp_path / "packs",
        name="qualified",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="deterministic qualifier fixture",
    )
    pack_path = tmp_path / "packs" / manifest.pack_id / "pack.sqlite"
    with sqlite3.connect(pack_path) as conn:
        packed_json = conn.execute(
            "SELECT qualifiers_json FROM edges WHERE id = ?",
            (result.relations[0].id,),
        ).fetchone()[0]
    assert json.loads(packed_json) == result.relations[0].qualifiers
    assert b'evidence_level' in pack_path.read_bytes()
    assert b'field' in pack_path.read_bytes()

    pack_store = KGStore.open(pack_path, read_only=True)
    try:
        graph = pack_store.graph_query(relation_type="uses")
        assert graph["edges"][0]["qualifiers"] == result.relations[0].qualifiers
        assert pack_store.verified_subgraph()[1][0]["qualifiers"] == result.relations[0].qualifiers
    finally:
        pack_store.close()


@pytest.mark.parametrize(
    ("qualifiers", "message"),
    [
        ({"not_declared); DROP TABLE edges;--": "field"}, "undeclared qualifier"),
        ({"replicate_count": "three"}, "must be"),
        ({"evidence_level": "anecdotal"}, "outside its enum"),
        ({"replicate_count": 0}, "below minimum"),
    ],
)
def test_parser_rejects_invalid_model_qualifiers(
    store: KGStore, qualifiers: dict, message: str
) -> None:
    schema = _install_qualified_schema(store)
    raw, chunk = _mock_output_with_qualifiers(
        schema, "ApiGateway uses RateLimiter.", qualifiers
    )

    with pytest.raises(EngineError, match=message):
        parse_and_validate_extraction(raw, schema, chunk)


def test_store_rejects_undeclared_and_enum_violating_qualifiers(store, doc) -> None:
    _install_qualified_schema(store)
    entities = [
        ProposedEntity(id="source", entity_type="Component", name="ApiGateway"),
        ProposedEntity(id="target", entity_type="Component", name="RateLimiter"),
    ]

    with pytest.raises(SchemaValidationError, match="undeclared qualifier"):
        store.insert_proposed(
            entities,
            [
                ProposedRelation(
                    id="bad-name",
                    relation_type="uses",
                    src_entity_id="source",
                    dst_entity_id="target",
                    qualifiers={"__proto__": "field"},
                )
            ],
            source_doc_id=doc.id,
            extractor_engine="direct",
        )
    assert store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0

    with pytest.raises(SchemaValidationError, match="outside its enum"):
        store.insert_proposed(
            entities,
            [
                ProposedRelation(
                    id="bad-enum",
                    relation_type="uses",
                    src_entity_id="source",
                    dst_entity_id="target",
                    qualifiers={"evidence_level": "anecdotal"},
                )
            ],
            source_doc_id=doc.id,
            extractor_engine="direct",
        )
    assert store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


def test_old_writable_database_migrates_qualifier_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "old.sqlite"
    old = KGStore.open(db_path)
    old.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE edges DROP COLUMN qualifiers_json")
        conn.execute("ALTER TABLE relation_type DROP COLUMN qualifiers_json")

    migrated = KGStore.open(db_path)
    try:
        edge_columns = {
            row[1] for row in migrated.conn.execute("PRAGMA table_info(edges)")
        }
        relation_columns = {
            row[1] for row in migrated.conn.execute("PRAGMA table_info(relation_type)")
        }
        assert "qualifiers_json" in edge_columns
        assert "qualifiers_json" in relation_columns
        assert migrated.conn.execute(
            "SELECT qualifiers_json FROM relation_type LIMIT 1"
        ).fetchone()[0] == "{}"
    finally:
        migrated.close()


def test_old_read_only_pack_degrades_to_empty_qualifiers(tmp_path: Path) -> None:
    db_path = tmp_path / "old-pack.sqlite"
    store = KGStore.open(db_path)
    doc = _insert_document(store, "ApiGateway uses RateLimiter.", "legacy-pack")
    entities = [
        ProposedEntity(id="source", entity_type="Component", name="ApiGateway"),
        ProposedEntity(id="target", entity_type="Component", name="RateLimiter"),
    ]
    store.insert_proposed(
        entities,
        [
            ProposedRelation(
                id="edge",
                relation_type="uses",
                src_entity_id="source",
                dst_entity_id="target",
            )
        ],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    for item_id in ("source", "target", "edge"):
        store.approve(item_id, by="legacy")
    store.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("ALTER TABLE edges DROP COLUMN qualifiers_json")

    legacy_pack = KGStore.open(db_path, read_only=True)
    try:
        assert legacy_pack.graph_query()["edges"][0]["qualifiers"] == {}
        columns = {
            row[1] for row in legacy_pack.conn.execute("PRAGMA table_info(edges)")
        }
        assert "qualifiers_json" not in columns
    finally:
        legacy_pack.close()
