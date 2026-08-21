"""Wave 2.1 Step 3 (3A): additive Work/Representation/Observation schema.

The authority surface is additive only: new tables live in
``ontologylab.authority`` (executed from ``KGStore.open`` beside
``extraction_state._SCHEMA``), the two new ``documents`` columns arrive via
``_migrate``, old v1 constraints stay authoritative for current writers, and
read-only stores are never migrated (they degrade instead).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.authority import V2_AUTHORITY_TABLES
from ontologylab.kgstore import KGStore


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type=\'table\'"
        )
    }


def _schema_dump(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()


def _downgrade_to_v1(db: Path) -> None:
    """Strip the v2 authority surface so the file looks pre-Step-3."""
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in sorted(V2_AUTHORITY_TABLES):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        doc_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(documents)")
        }
        for column in ("work_id", "representation_state"):
            if column in doc_cols:
                conn.execute(f"ALTER TABLE documents DROP COLUMN {column}")
        conn.commit()
    finally:
        conn.close()


def test_fresh_store_carries_the_full_v2_authority_surface(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        assert V2_AUTHORITY_TABLES <= _tables(store.conn)
        doc_cols = {
            row["name"]
            for row in store.conn.execute("PRAGMA table_info(documents)")
        }
        assert "work_id" in doc_cols
        assert "representation_state" in doc_cols
    finally:
        store.close()


def test_preexisting_v1_store_gains_the_surface_additively(tmp_path: Path) -> None:
    db = tmp_path / "kg.sqlite"
    store = KGStore.open(db)
    doc, created = store.insert_document(
        source_kind="upload", source_uri="file:///pre.txt", title="pre",
        raw_text="a pre-v2 document body", content_hash="sha256:pre-v2",
    )
    assert created
    store.close()
    _downgrade_to_v1(db)

    store = KGStore.open(db)
    try:
        assert V2_AUTHORITY_TABLES <= _tables(store.conn)
        row = store.conn.execute(
            "SELECT work_id, representation_state FROM documents WHERE id = ?",
            (doc.id,),
        ).fetchone()
        # Pre-existing rows keep their identity: unlinked and ready.
        assert row["work_id"] is None
        assert row["representation_state"] == "ready"
    finally:
        store.close()


def test_reopen_is_schema_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "kg.sqlite"
    KGStore.open(db).close()
    first = _schema_dump(db)
    KGStore.open(db).close()
    second = _schema_dump(db)
    assert first == second


def test_accepted_owner_is_unique_per_scheme_value(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        conn = store.conn
        conn.execute(
            "INSERT INTO works (id, state, created_ts) VALUES (\'w1\',\'active\',0)"
        )
        conn.execute(
            "INSERT INTO works (id, state, created_ts) VALUES (\'w2\',\'active\',0)"
        )
        conn.execute(
            "INSERT INTO work_identifiers "
            "(id, work_id, scheme, normalized_value, status, created_ts) "
            "VALUES (\'i1\',\'w1\',\'doi\',\'10.1/x\',\'accepted\',0)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO work_identifiers "
                "(id, work_id, scheme, normalized_value, status, created_ts) "
                "VALUES (\'i2\',\'w2\',\'doi\',\'10.1/x\',\'accepted\',0)"
            )
        # A pending assertion for the same value is not an owner: allowed.
        conn.execute(
            "INSERT INTO work_identifiers "
            "(id, work_id, scheme, normalized_value, status, created_ts) "
            "VALUES (\'i3\',\'w2\',\'doi\',\'10.1/x\',\'pending\',0)"
        )
    finally:
        store.close()


def test_at_most_one_accepted_doi_per_work(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        conn = store.conn
        conn.execute(
            "INSERT INTO works (id, state, created_ts) VALUES (\'w1\',\'active\',0)"
        )
        conn.execute(
            "INSERT INTO work_identifiers "
            "(id, work_id, scheme, normalized_value, status, created_ts) "
            "VALUES (\'i1\',\'w1\',\'doi\',\'10.1/a\',\'accepted\',0)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO work_identifiers "
                "(id, work_id, scheme, normalized_value, status, created_ts) "
                "VALUES (\'i2\',\'w1\',\'doi\',\'10.1/b\',\'accepted\',0)"
            )
    finally:
        store.close()


def test_v1_content_hash_constraint_stays_authoritative(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        store.insert_document(
            source_kind="upload", source_uri="file:///a.txt", title="a",
            raw_text="body one", content_hash="sha256:same",
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                "INSERT INTO documents "
                "(id, source_kind, source_uri, title, fetched_ts, "
                "content_hash, raw_text_path) "
                "VALUES (\'raw2\',\'upload\',\'file:///b.txt\',\'b\',0,"
                "\'sha256:same\',\'documents/raw2/raw.txt\')"
            )
    finally:
        store.close()


def test_read_only_v1_store_degrades_without_migration(tmp_path: Path) -> None:
    db = tmp_path / "kg.sqlite"
    KGStore.open(db).close()
    _downgrade_to_v1(db)
    store = KGStore.open(db, read_only=True)
    try:
        assert not (V2_AUTHORITY_TABLES & _tables(store.conn))
    finally:
        store.close()
