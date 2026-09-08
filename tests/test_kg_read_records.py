"""Characterize SQLite record values through the existing KGStore facade."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict

import pytest

from ontologylab import kgstore
from ontologylab.connectors.base import RawDocument
from ontologylab.ingestion import ingest_raw_documents_and_finalize
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from tests.conftest import insert
from tests.factories import make_entity, make_relation

NODE = {
    "id": "node-1", "entity_type": "Component", "name": "RateLimiter",
    "aliases_json": '["요청 제한기", "Limiter"]',
    "properties_json": '{"limit":0,"nested":{"active":false}}',
    "status": "proposed", "confidence": 0.0, "source_doc_id": "doc-1",
    "source_span": '{"start":0,"end":12}',
}
EDGE = {
    "id": "edge-1", "relation_type": "uses", "src_node_id": "node-a",
    "dst_node_id": "node-b", "properties_json": '{"weight":2}',
    "qualifiers_json": '{"scope":{"tenant":"A"}}', "status": "verified",
    "confidence": 0.0, "source_doc_id": None, "valid_from": 0.0,
    "invalidated_ts": 27.5,
}
DOCUMENT = {
    "id": "doc-1", "source_kind": "paper_api",
    "source_uri": "https://doi.org/10.1000/RECORD", "title": None,
    "fetched_ts": 0.0, "content_hash": "sha256:literal",
    "raw_text_path": "documents/doc-1/raw.txt", "source": "crossref",
    "evidence_grade": "preprint", "doi": "10.1000/RECORD",
}


def _select(values):
    return "SELECT " + ", ".join(f'? AS "{name}"' for name in values), tuple(values.values())


def _row(store, values):
    row = store.conn.execute(*_select(values)).fetchone()
    assert isinstance(row, sqlite3.Row)
    return row


def _converter(kind):
    return {"node": kgstore._node_dict, "edge": kgstore._edge_dict,
            "document": KGStore._row_to_document}[kind]


@pytest.mark.parametrize("status", ["proposed", "verified", "rejected"])
def test_node_values_and_authority_are_not_reinterpreted(store, status):
    row = _row(store, {**NODE, "status": status})
    before = (store.conn.total_changes, store.conn.in_transaction)
    assert kgstore._node_dict(row) == {
        "id": "node-1", "entity_type": "Component", "name": "RateLimiter",
        "aliases": ["요청 제한기", "Limiter"],
        "properties": {"limit": 0, "nested": {"active": False}},
        "status": status, "confidence": 0.0, "source_doc_id": "doc-1",
        "source_span": {"start": 0, "end": 12},
    }
    assert (store.conn.total_changes, store.conn.in_transaction) == before


@pytest.mark.parametrize("span, expected", [(None, None), ("", None), ("null", None), ("[]", [])])
def test_node_sql_null_json_null_and_empty_span_remain_distinct(store, span, expected):
    row = _row(store, {**NODE, "aliases_json": "null", "properties_json": "null",
                       "source_span": span, "confidence": None, "source_doc_id": None})
    value = kgstore._node_dict(row)
    assert value["aliases"] is value["properties"] is None
    assert value["source_span"] == expected
    assert value["confidence"] is value["source_doc_id"] is None


def test_edge_endpoints_qualifiers_and_invalidation_are_preserved(store):
    assert kgstore._edge_dict(_row(store, EDGE)) == {
        "id": "edge-1", "relation_type": "uses", "source_id": "node-a",
        "target_id": "node-b", "properties": {"weight": 2},
        "qualifiers": {"scope": {"tenant": "A"}}, "status": "verified",
        "confidence": 0.0, "source_doc_id": None, "valid_from": 0.0,
        "invalidated_ts": 27.5,
    }


@pytest.mark.parametrize("mode", ["absent", "sql-null", "empty", "json-null"])
def test_edge_optional_columns_keep_legacy_and_null_semantics(store, mode):
    values = {key: value for key, value in EDGE.items()
              if key not in ("qualifiers_json", "valid_from", "invalidated_ts")}
    if mode != "absent":
        values.update(qualifiers_json={"sql-null": None, "empty": "", "json-null": "null"}[mode],
                      valid_from=None, invalidated_ts=None)
    row = _row(store, values)
    value = kgstore._edge_dict(row)
    assert value["qualifiers"] == (None if mode == "json-null" else {})
    assert value["valid_from"] is value["invalidated_ts"] is None
    assert value["source_id"] == "node-a" and value["target_id"] == "node-b"


@pytest.mark.parametrize("kind, column", [
    ("node", "aliases_json"), ("node", "properties_json"), ("node", "source_span"),
    ("edge", "properties_json"), ("edge", "qualifiers_json"),
])
def test_malformed_json_is_not_silently_replaced(store, kind, column):
    values = dict(NODE if kind == "node" else EDGE)
    values[column] = "{broken"
    with pytest.raises(json.JSONDecodeError):
        _converter(kind)(_row(store, values))


@pytest.mark.parametrize("kind", ["node", "edge"])
def test_required_json_sql_null_keeps_type_error(store, kind):
    values = dict(NODE if kind == "node" else EDGE)
    values["properties_json"] = None
    with pytest.raises(TypeError):
        _converter(kind)(_row(store, values))


@pytest.mark.parametrize("kind, column", [("node", "name"), ("edge", "src_node_id"), ("document", "title")])
def test_missing_required_columns_keep_index_error(store, kind, column):
    values = dict({"node": NODE, "edge": EDGE, "document": DOCUMENT}[kind])
    values.pop(column)
    with pytest.raises(IndexError):
        _converter(kind)(_row(store, values))


@pytest.mark.parametrize("grade, expected", [
    ("preprint", "preprint"), ("peer_reviewed", "peer_reviewed"),
    ("", "unknown"), ("unrecognized", "unknown"), (None, "unknown"),
])
def test_document_metadata_and_grade_normalization(store, grade, expected):
    document = KGStore._row_to_document(_row(store, {**DOCUMENT, "evidence_grade": grade}))
    assert asdict(document) == {
        "id": "doc-1", "source_kind": "paper_api",
        "source_uri": "https://doi.org/10.1000/RECORD", "title": None,
        "fetched_ts": 0.0, "content_hash": "sha256:literal",
        "raw_text_path": "documents/doc-1/raw.txt", "source": "crossref",
        "evidence_grade": expected, "doi": "10.1000/RECORD",
    }


@pytest.mark.parametrize("mode", ["present", "absent", "sql-null"])
def test_document_public_reads_do_not_migrate_immutable_legacy_bytes(tmp_path, mode):
    values = dict(DOCUMENT)
    for column in ("source", "evidence_grade", "doi"):
        if mode == "absent":
            values.pop(column)
        elif mode == "sql-null":
            values[column] = None
    path = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        sql, parameters = _select(values)
        conn.execute("CREATE TABLE documents AS " + sql, parameters)
        conn.commit()
    before = path.read_bytes()
    with closing(KGStore.open(path, read_only=True)) as reader:
        document = reader.get_document("doc-1")
        assert reader.list_documents() == [document]
        assert document.source == ("crossref" if mode == "present" else "" if mode == "absent" else None)
        assert document.evidence_grade == ("preprint" if mode == "present" else "unknown")
        assert document.doi == ("10.1000/RECORD" if mode == "present" else None)
        assert document.title is None and document.fetched_ts == 0.0
        assert document.raw_text_path == "documents/doc-1/raw.txt"
        assert reader.conn.total_changes == 0 and not reader.conn.in_transaction
    assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["first", "second"])
def test_existing_document_ingestion_preserves_static_facade_records(store, tmp_path, operation):
    raw = RawDocument(
        source_kind="paper_api", source_uri="https://doi.org/10.1000/record",
        title="Record conversion", raw_text="ApiGateway uses RateLimiter.",
        doi="10.1000/record", source="crossref", evidence_grade="preprint",
    )
    provenance = Provenance(str(tmp_path / "provenance"), seed=0)
    first = ingest_raw_documents_and_finalize(store, [raw], provenance, operation_id="first")
    assert first.created_count == 1 and not first.failures and not first.conflicts
    expected = first.entries[0].document
    duplicate = ingest_raw_documents_and_finalize(store, [raw], provenance, operation_id=operation)
    assert duplicate.created_count == 0 and duplicate.duplicate_count == 1
    assert not duplicate.failures and not duplicate.conflicts
    actual = duplicate.entries[0].document
    assert asdict(actual) == asdict(expected)
    assert actual.source == "crossref" and actual.evidence_grade == "preprint"
    assert actual.doi == "10.1000/record" and actual.title == "Record conversion"
    assert actual.source_uri == "https://doi.org/10.1000/record"
    assert store.document_raw_text(actual.id) == raw.raw_text
    assert store.conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    observations = store.conn.execute("SELECT count(*) FROM document_observations").fetchone()[0]
    assert observations == (1 if operation == "first" else 2)


def test_public_graph_reads_keep_provenance_and_current_fact_filters(store, doc):
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter", aliases=["요청 제한기"], properties={"language": "Python"},
                          confidence=None, source_span=None)
    insert(store, doc, [gateway, limiter], [make_relation(gateway, limiter)])
    ids = {row["name"]: row["id"] for row in store.conn.execute("SELECT id, name FROM nodes")}
    edge_id = store.conn.execute("SELECT id FROM edges").fetchone()["id"]
    assert store.entity_lookup(id=ids["RateLimiter"]) == []
    proposed = store.entity_lookup(id=ids["RateLimiter"], include_proposed=True)[0]
    assert proposed["status"] == "proposed" and proposed["properties"] == {"language": "Python"}
    assert "요청 제한기" in proposed["aliases"]
    assert proposed["confidence"] is proposed["source_span"] is None
    assert proposed["source_document_ids"] == [doc.id]
    assert store.verified_subgraph() == ([], [])
    for node_id in ids.values():
        store.approve(node_id, by="record-tester")
    store.approve(edge_id, by="record-tester")
    before = store.conn.total_changes
    nodes, edges = store.verified_subgraph()
    assert {node["id"] for node in nodes} == set(ids.values())
    assert len(edges) == 1 and edges[0]["id"] == edge_id
    assert edges[0]["source_id"] == ids["ApiGateway"]
    assert edges[0]["target_id"] == ids["RateLimiter"]
    assert edges[0]["qualifiers"] == {}
    assert edges[0]["source_doc_id"] == doc.id
    assert store.traverse_relations([ids["ApiGateway"]])["edges"] == edges
    assert store.conn.total_changes == before
    store.invalidate_edge(edge_id, by="record-tester", reason="characterization")
    audit = kgstore._edge_dict(store.conn.execute("SELECT * FROM edges WHERE id = ?", (edge_id,)).fetchone())
    assert audit["status"] == "verified" and audit["invalidated_ts"] is not None
    assert store.verified_subgraph()[1] == []
    assert store.graph_query()["edges"] == []
    assert store.traverse_relations([ids["ApiGateway"]])["edges"] == []
