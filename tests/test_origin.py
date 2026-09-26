"""Claim layer O-4: every node and edge records how it came to exist."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.packbuilder import build_pack
from ontologylab.pack_completeness import extraction_completeness
from tests.conftest import insert
from tests.factories import make_entity, make_relation


def _seed(store, doc):
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b], [make_relation(a, b)])
    return a, b


def test_extracted_rows_read_back_with_origin(store, doc) -> None:
    _seed(store, doc)
    graph = store.graph_query(include_proposed=True)
    assert {n["origin"] for n in graph["nodes"]} == {"extracted"}
    assert {e["origin"] for e in graph["edges"]} == {"extracted"}


def test_origin_rejects_unknown_values(store, doc) -> None:
    a, _ = _seed(store, doc)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("UPDATE nodes SET origin = 'guessed' WHERE id = ?", (a.id,))


def test_pre_origin_store_migrates_and_backfills(tmp_path: Path) -> None:
    db_path = tmp_path / "old.sqlite"
    store = KGStore.open(db_path)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///o.txt", title="o",
        raw_text="ApiGateway RateLimiter", content_hash="sha256:o",
    )
    _seed(store, doc)
    store.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE nodes DROP COLUMN origin")
        conn.execute("ALTER TABLE edges DROP COLUMN origin")

    migrated = KGStore.open(db_path)
    try:
        for table in ("nodes", "edges"):
            values = {
                row[0] for row in migrated.conn.execute(f"SELECT origin FROM {table}")
            }
            assert values == {"extracted"}
    finally:
        migrated.close()


def test_curated_verified_rows_are_not_extraction_streams(store, doc) -> None:
    """A curated fact has no extraction run; it must not refuse the pack."""
    a, b = _seed(store, doc)
    for item in (a.id, b.id):
        store.approve(item)
    store.conn.execute("UPDATE nodes SET origin = 'curated'")
    store.conn.commit()
    assert extraction_completeness(store.conn)["status"] == "not_applicable"


def test_pack_copies_origin(tmp_path: Path) -> None:
    db_path = tmp_path / "kg.sqlite"
    store = KGStore.open(db_path)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///p.txt", title="p",
        raw_text="ApiGateway RateLimiter", content_hash="sha256:p",
    )
    a, b = _seed(store, doc)
    for item in (a.id, b.id):
        store.approve(item)
    store.conn.execute("UPDATE nodes SET origin = 'curated' WHERE id = ?", (a.id,))
    store.conn.commit()
    store.close()

    manifest = build_pack(
        db_path, tmp_path / "packs", name="origin",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="origin copy fixture",
    )
    pack = tmp_path / "packs" / manifest.pack_id / "pack.sqlite"
    with sqlite3.connect(pack) as conn:
        rows = dict(conn.execute("SELECT id, origin FROM nodes").fetchall())
    assert rows == {a.id: "curated", b.id: "extracted"}
