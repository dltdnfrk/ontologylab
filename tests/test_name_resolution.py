"""Regression tests for the 2026-08-01 algorithm audit's two confirmed
resolution defects: short-symbol false merges and punctuation-variant
span rejection. RED before the fix, GREEN after."""

from __future__ import annotations

import json
import sqlite3

import pytest

from ontologylab.kgstore import KGStore, normalize_name
from ontologylab.models import ProposedEntity
from ontologylab.extractor import Chunk, parse_and_validate_extraction


# R2 — skeleton keys must not collapse distinct short symbols. Long names
# keep the existing punctuation-blind unification; the merge scanner (human
# review) is the recovery path for borderline short names like IL-6/IL6.


def test_short_symbols_with_punctuation_do_not_share_a_key() -> None:
    assert normalize_name("C") != normalize_name("C++")
    assert normalize_name("C") != normalize_name("C#")
    assert normalize_name("C++") != normalize_name("C#")
    assert normalize_name("A/B") != normalize_name("AB")


def test_long_names_still_unify_punctuation_variants() -> None:
    assert normalize_name("Rate Limiter") == normalize_name("rate-limiter")
    assert normalize_name("RateLimiter") == normalize_name("rate-limiter")


def test_insert_keeps_c_and_cxx_as_separate_nodes(tmp_path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        doc, _ = store.insert_document(
            source_kind="t", source_uri="t://1", title="t",
            raw_text="x", content_hash="h",
        )
        store.insert_proposed(
            [ProposedEntity(id="a" * 32, entity_type="Concept", name="C")],
            [], source_doc_id=doc.id, extractor_engine="t",
        )
        result = store.insert_proposed(
            [ProposedEntity(id="b" * 32, entity_type="Concept", name="C++")],
            [], source_doc_id=doc.id, extractor_engine="t",
        )
        names = [
            row["name"]
            for row in store.conn.execute("SELECT name FROM nodes")
        ]
        assert result["nodes_merged"] == 0
        assert sorted(names) == ["C", "C++"]
    finally:
        store.close()


def test_open_recomputes_stale_short_symbol_keys(tmp_path) -> None:
    db = tmp_path / "kg.sqlite"
    store = KGStore.open(db)
    store.close()
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO documents (id, source_kind, source_uri, title, "
        "fetched_ts, content_hash, raw_text_path) "
        "VALUES ('d1', 't', 't://1', 't', 0, 'h', 'p')"
    )
    conn.execute(
        "INSERT INTO nodes (id, schema_version_id, entity_type, name, "
        "normalized_name, status, source_doc_id, created_ts, extractor_engine) "
        "SELECT 'z' || printf('%031d', 0), id, 'Concept', 'C++', 'c', "
        "'proposed', 'd1', 0, 't' FROM schema_version LIMIT 1"
    )
    conn.commit()
    conn.close()
    store = KGStore.open(db)
    try:
        row = store.conn.execute(
            "SELECT normalized_name FROM nodes WHERE name = 'C++'"
        ).fetchone()
        assert row["normalized_name"] == normalize_name("C++")
    finally:
        store.close()


# R1 — a name grounded in the chunk with different punctuation must be
# accepted and relocated, not rejected.

_SCHEMA = {
    "entity_types": [{"name": "Component", "description": "c", "attributes": {}}],
    "relation_types": [],
}


def _parse(name: str, chunk_text: str):
    raw = "```json\n" + json.dumps(
        {"entities": [{"entity_type": "Component", "name": name}]}
    ) + "\n```"
    return parse_and_validate_extraction(
        raw, _SCHEMA, Chunk(index=0, char_offset=0, text=chunk_text)
    )


def test_hyphenated_mention_grounds_camelcase_name() -> None:
    result = _parse("RateLimiter", "The rate-limiter throttles requests.")
    assert len(result.entities) == 1
    span = result.entities[0].source_span
    assert span is not None
    assert span.start == 4 and span.end == 16


def test_spaced_mention_grounds_camelcase_name() -> None:
    result = _parse("RateLimiter", "A rate limiter sits here.")
    assert len(result.entities) == 1


def test_truly_absent_name_is_still_rejected() -> None:
    result = _parse("Tokenizer", "The rate-limiter throttles requests.")
    assert len(result.entities) == 0
