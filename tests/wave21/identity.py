"""Shared helpers for the G002 direct-service ingestion identity
characterization tests (`tests/test_wave21_identity_characterization.py`).

Every helper returns a plain dataclass of machine-consumed facts pulled
straight from `KGStore`/sqlite state — row counts, ids, `doi` column
contents, byte contents on disk — never prose. The owning test module
turns those facts into assertions; this module only produces them.

Scope: Wave 2.1 Step 1 Goal G002 only. Nothing here is imported by, or
imports from, the G001 (harness) or G003 (real-surface) test modules.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ontologylab.kgstore import KGStore


@dataclass(frozen=True, slots=True)
class InsertReceipt:
    """One `insert_document` outcome plus the row state it actually left."""

    doc_id: str
    created: bool
    doi_column: str | None
    raw_text: str
    document_count: int


def _receipt(store: KGStore, doc, created: bool) -> InsertReceipt:
    row = store.conn.execute(
        "SELECT doi FROM documents WHERE id = ?", (doc.id,)
    ).fetchone()
    return InsertReceipt(
        doc_id=doc.id,
        created=created,
        doi_column=row["doi"],
        raw_text=store.document_raw_text(doc.id),
        document_count=len(store.list_documents()),
    )


def insert_same_doi_new_bytes(
    store: KGStore,
    *,
    doi: str,
    first_text: str,
    second_text: str,
) -> tuple[InsertReceipt, InsertReceipt]:
    """Same DOI arrives twice with different bytes (abstract, then full text).

    Returns (first, second) receipts so the caller can compare row identity
    and which bytes are on disk after the second write.
    """
    first_doc, first_created = store.insert_document(
        source_kind="paper_api",
        source_uri=f"https://doi.org/{doi}",
        title="Paper",
        raw_text=first_text,
        content_hash=f"sha256:{hash(first_text) & 0xffffffff:x}",
        doi=doi,
    )
    second_doc, second_created = store.insert_document(
        source_kind="paper_api",
        source_uri=f"https://doi.org/{doi}",
        title="Paper",
        raw_text=second_text,
        content_hash=f"sha256:{hash(second_text) & 0xffffffff:x}",
        doi=doi,
    )
    return (
        _receipt(store, first_doc, first_created),
        _receipt(store, second_doc, second_created),
    )


def insert_different_doi_same_bytes(
    store: KGStore,
    *,
    first_doi: str,
    second_doi: str,
    shared_text: str,
) -> tuple[InsertReceipt, InsertReceipt]:
    """Two distinct, real DOIs both carry byte-identical text.

    `content_hash` is derived from `shared_text` for both calls (same
    function of the same bytes), matching how a real connector computes it —
    the test is entitled to assume equal bytes hash equal, not to fabricate
    a hash collision that would not occur in production.
    """
    content_hash = f"sha256:{hash(shared_text) & 0xffffffff:x}"
    first_doc, first_created = store.insert_document(
        source_kind="paper_api",
        source_uri=f"https://doi.org/{first_doi}",
        title="Paper A",
        raw_text=shared_text,
        content_hash=content_hash,
        doi=first_doi,
    )
    second_doc, second_created = store.insert_document(
        source_kind="paper_api",
        source_uri=f"https://doi.org/{second_doi}",
        title="Paper B",
        raw_text=shared_text,
        content_hash=content_hash,
        doi=second_doi,
    )
    return (
        _receipt(store, first_doc, first_created),
        _receipt(store, second_doc, second_created),
    )


def seed_premigration_documents_row(
    db_path: Path,
    *,
    doc_id: str,
    source_uri: str,
    raw_text: str,
    content_hash: str,
) -> None:
    """Populate a `documents` row on a store that predates the `doi` column.

    Mirrors `test_existing_store_gains_doi_identity`'s schema-downgrade
    technique (open once, drop the column added by `_migrate`, then reopen
    to re-trigger migration) but — unlike that test, which migrates an
    *empty* table — writes a row here BEFORE the downgraded store is
    reopened. That is the "populated legacy resolver DOI" case: a document
    collected under a genuinely legacy on-disk database, whose resolver-
    shaped `source_uri` is the only place the DOI ever lived, since the row
    predates the `doi` column entirely.
    """
    store = KGStore.open(db_path)
    store.close()
    conn = sqlite3.connect(db_path)
    conn.execute("DROP INDEX idx_documents_doi")
    conn.execute("ALTER TABLE documents DROP COLUMN doi")
    conn.commit()
    rel_path = f"documents/{doc_id}/raw.txt"
    abs_path = db_path.parent / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(raw_text, encoding="utf-8")
    conn.execute(
        "INSERT INTO documents "
        "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
        "raw_text_path, source, evidence_grade) "
        "VALUES (?, 'paper_api', ?, 'Legacy paper', 0.0, ?, ?, '', '')",
        (doc_id, source_uri, content_hash, rel_path),
    )
    conn.commit()
    conn.close()


@dataclass(frozen=True, slots=True)
class LegacyResolverReceipt:
    """State after migrating a populated legacy store and re-inserting the
    same paper by (normalized) DOI."""

    legacy_row_doi_after_migration: str | None
    reinsert_created: bool
    reinsert_doc_id: str
    legacy_doc_id: str
    document_count: int


def migrate_and_reinsert_by_doi(
    db_path: Path,
    *,
    legacy_doc_id: str,
    doi: str,
    new_text: str,
) -> LegacyResolverReceipt:
    """Reopen a populated legacy store (triggering `_migrate`), then insert
    the same paper again giving the normalized DOI explicitly.

    A migration that only adds the nullable column, without backfilling it
    from the resolver-shaped `source_uri` values already on disk, leaves the
    legacy row's `doi` column NULL — so this reinsert cannot find it via the
    DOI lookup and is free to create a second row for the same paper.
    """
    store = KGStore.open(db_path)
    try:
        legacy_row = store.conn.execute(
            "SELECT doi FROM documents WHERE id = ?", (legacy_doc_id,)
        ).fetchone()
        new_doc, created = store.insert_document(
            source_kind="paper_api",
            source_uri=f"https://doi.org/{doi}",
            title="Legacy paper",
            raw_text=new_text,
            content_hash=f"sha256:{hash(new_text) & 0xffffffff:x}",
            doi=doi,
        )
        return LegacyResolverReceipt(
            legacy_row_doi_after_migration=legacy_row["doi"],
            reinsert_created=created,
            reinsert_doc_id=new_doc.id,
            legacy_doc_id=legacy_doc_id,
            document_count=len(store.list_documents()),
        )
    finally:
        store.close()


@dataclass(frozen=True, slots=True)
class TerminalParenRoundTripReceipt:
    """Whether a registered terminal-`)` DOI survives `normalize_doi` and a
    real insert/read round trip intact."""

    input_doi: str
    normalized_doi: str | None
    stored_doi: str | None
    round_trips: bool


def terminal_paren_round_trip(
    store: KGStore, *, doi: str, raw_text: str
) -> TerminalParenRoundTripReceipt:
    """Insert a document under a real, registered DOI whose registered form
    ends in `)` (e.g. `10.1002/0471221929.ch26(vii)`) and read back what the
    store actually persisted.
    """
    from ontologylab.connectors.base import normalize_doi

    normalized = normalize_doi(doi)
    doc, _created = store.insert_document(
        source_kind="paper_api",
        source_uri=f"https://doi.org/{doi}",
        title="Registered chapter",
        raw_text=raw_text,
        content_hash=f"sha256:{hash(raw_text) & 0xffffffff:x}",
        doi=doi,
    )
    row = store.conn.execute(
        "SELECT doi FROM documents WHERE id = ?", (doc.id,)
    ).fetchone()
    stored = row["doi"]
    return TerminalParenRoundTripReceipt(
        input_doi=doi,
        normalized_doi=normalized,
        stored_doi=stored,
        round_trips=(stored == doi),
    )
