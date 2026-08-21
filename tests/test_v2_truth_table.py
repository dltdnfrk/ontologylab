"""Wave 2.1 Step 3 (3C): v2 truth table on a DISPOSABLE constraint layout.

The production layout keeps global ``UNIQUE(content_hash)`` until the Step
9 rebuild, so the v2 truth table is proven only on a disposable store whose
``documents`` table is rebuilt test-side without that global constraint
(per-work representation uniqueness instead). Nothing here claims this
GREEN on the production layout; the Step 1 strict xfail there stays pinned.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.authority_repo import (
    SecondDoiAttachConflict,
    attach_identifier,
    create_work,
)
from ontologylab.kgstore import KGStore
from ontologylab.preferred import preferred_representation


def _disposable_v2_layout(db: Path) -> KGStore:
    """A disposable store whose documents table follows v2 constraints."""
    store = KGStore.open(db)
    conn = store.conn
    # open() committed its schema setup; the FK pragma and the rebuild run
    # in autocommit mode (PRAGMA foreign_keys is a no-op mid-transaction).
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """CREATE TABLE documents_v2 (
            id            TEXT PRIMARY KEY,
            source_kind   TEXT NOT NULL,
            source_uri    TEXT NOT NULL,
            title         TEXT,
            fetched_ts    REAL NOT NULL,
            content_hash  TEXT NOT NULL,
            raw_text_path TEXT NOT NULL,
            doi           TEXT,
            source        TEXT NOT NULL DEFAULT '',
            evidence_grade TEXT NOT NULL DEFAULT '',
            work_id       TEXT REFERENCES works(id),
            representation_state TEXT NOT NULL DEFAULT 'ready'
        )"""
    )
    conn.execute(
        "INSERT INTO documents_v2 SELECT id, source_kind, source_uri, title, "
        "fetched_ts, content_hash, raw_text_path, doi, source, "
        "evidence_grade, work_id, representation_state FROM documents"
    )
    conn.execute("DROP TABLE documents")
    conn.execute("ALTER TABLE documents_v2 RENAME TO documents")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_representation "
        "ON documents (work_id, content_hash) WHERE work_id IS NOT NULL"
    )
    conn.execute("PRAGMA foreign_keys = ON")
    # The INSERT above already started this connection's write transaction;
    # the caller owns the commit, as everywhere else in this suite.
    return store


def _insert_representation(
    store: KGStore,
    *,
    doc_id: str,
    work_id: str,
    content_hash: str,
    body: str,
) -> None:
    (Path(store.db_path).parent / "documents" / doc_id).mkdir(
        parents=True, exist_ok=True
    )
    (Path(store.db_path).parent / "documents" / doc_id / "raw.txt").write_text(
        body, encoding="utf-8"
    )
    store.conn.execute(
        "INSERT INTO documents (id, source_kind, source_uri, title, "
        "fetched_ts, content_hash, raw_text_path, source, evidence_grade, "
        "work_id, representation_state) "
        "VALUES (?, 'paper_api', ?, 'paper', 0.0, ?, ?, '', '', ?, 'ready')",
        (
            doc_id,
            f"https://doi.org/10.5555/{doc_id}",
            content_hash,
            f"documents/{doc_id}/raw.txt",
            work_id,
        ),
    )


def test_two_doi_one_hash_yields_two_works_and_two_representations(
    tmp_path: Path,
) -> None:
    store = _disposable_v2_layout(tmp_path / "kg.sqlite")
    try:
        create_work(store.conn, "work-a")
        create_work(store.conn, "work-b")
        same_bytes = "byte-identical body shared by two works"
        _insert_representation(
            store, doc_id="rep-a", work_id="work-a",
            content_hash="sha256:shared-1", body=same_bytes,
        )
        _insert_representation(
            store, doc_id="rep-b", work_id="work-b",
            content_hash="sha256:shared-1", body=same_bytes,
        )
        attach_identifier(
            store.conn, work_id="work-a", scheme="doi",
            normalized_value="10.1000/v2.a", idempotency_key="op-a",
        )
        attach_identifier(
            store.conn, work_id="work-b", scheme="doi",
            normalized_value="10.1000/v2.b", idempotency_key="op-b",
        )
        works = store.conn.execute(
            "SELECT work_id, COUNT(*) FROM documents GROUP BY work_id "
            "ORDER BY work_id"
        ).fetchall()
        assert [(row[0], row[1]) for row in works] == [
            ("work-a", 1), ("work-b", 1),
        ]
    finally:
        store.close()


def test_one_doi_two_bytes_yields_one_work_two_representations(
    tmp_path: Path,
) -> None:
    store = _disposable_v2_layout(tmp_path / "kg.sqlite")
    try:
        create_work(store.conn, "work-a")
        _insert_representation(
            store, doc_id="rep-abstract", work_id="work-a",
            content_hash="sha256:abstract-1", body="abstract only",
        )
        _insert_representation(
            store, doc_id="rep-fulltext", work_id="work-a",
            content_hash="sha256:fulltext-1", body="the full text",
        )
        attach_identifier(
            store.conn, work_id="work-a", scheme="doi",
            normalized_value="10.1000/v2.one", idempotency_key="op-one",
        )
        count = store.conn.execute(
            "SELECT COUNT(*) FROM documents WHERE work_id = 'work-a'"
        ).fetchone()[0]
        assert count == 2
    finally:
        store.close()


def test_metadata_only_observation_is_representable(tmp_path: Path) -> None:
    store = _disposable_v2_layout(tmp_path / "kg.sqlite")
    try:
        create_work(store.conn, "work-a")
        result = attach_identifier(
            store.conn, work_id="work-a", scheme="doi",
            normalized_value="10.1000/v2.meta", idempotency_key="op-meta",
            representation_id=None,
        )
        row = store.conn.execute(
            "SELECT representation_id FROM document_observations WHERE id = ?",
            (result.observation_id,),
        ).fetchone()
        assert row[0] is None
    finally:
        store.close()


def test_second_doi_attach_still_conflicts_on_the_disposable_layout(
    tmp_path: Path,
) -> None:
    store = _disposable_v2_layout(tmp_path / "kg.sqlite")
    try:
        create_work(store.conn, "work-a")
        attach_identifier(
            store.conn, work_id="work-a", scheme="doi",
            normalized_value="10.1000/v2.first", idempotency_key="op-f",
        )
        with pytest.raises(SecondDoiAttachConflict):
            attach_identifier(
                store.conn, work_id="work-a", scheme="doi",
                normalized_value="10.1000/v2.second", idempotency_key="op-s",
            )
    finally:
        store.close()


_CANDIDATES = (
    # doc_id, stage, kind, grade, source, byte_length, content_hash
    ("rep-1", "submitted", "fulltext", "A", "publisher", 1200, "sha256:a1"),
    ("rep-2", "published", "abstract", "A", "publisher", 400, "sha256:b2"),
    ("rep-3", "submitted", "fulltext", "B", "registry", 900, "sha256:c3"),
)


def test_preferred_representation_is_deterministic_under_permutation(
    tmp_path: Path,
) -> None:
    winners = set()
    for order in (
        (0, 1, 2), (2, 1, 0), (1, 0, 2), (2, 0, 1),
    ):
        ranked = [ _CANDIDATES[i] for i in order ]
        winner = preferred_representation(
            [
                {
                    "doc_id": c[0], "stage": c[1], "kind": c[2],
                    "evidence_grade": c[3], "source": c[4],
                    "byte_length": c[5], "content_hash": c[6],
                }
                for c in ranked
            ]
        )
        winners.add(winner["doc_id"])
    # Fixed policy preferred-representation-v1 ranks stage first:
    # published abstract outranks submitted fulltext.
    assert winners == {"rep-2"}


def test_projection_tie_break_uses_the_lexical_content_hash() -> None:
    """When two candidates tie on stage/kind/grade/source/length, the lexical
    content hash decides deterministically - and dropping that hash from the
    rank must change the outcome."""
    tied = [
        {"doc_id": "rep-x", "stage": "submitted", "kind": "fulltext",
         "evidence_grade": "A", "source": "publisher", "byte_length": 500,
         "content_hash": "sha256:zz"},
        {"doc_id": "rep-y", "stage": "submitted", "kind": "fulltext",
         "evidence_grade": "A", "source": "publisher", "byte_length": 500,
         "content_hash": "sha256:aa"},
    ]
    forward = preferred_representation(tied)
    backward = preferred_representation(list(reversed(tied)))
    assert forward["doc_id"] == backward["doc_id"] == "rep-y"


def test_production_layout_keeps_global_content_hash_constraint(
    tmp_path: Path,
) -> None:
    """The disposable GREEN above never leaks into production: a fresh
    production-layout store still carries the v1 global
    UNIQUE(content_hash) constraint on documents (checked from
    sqlite_master, machine-consumed)."""
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        row = store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'documents'"
        ).fetchone()
        assert "UNIQUE (content_hash)" in row[0]
    finally:
        store.close()
