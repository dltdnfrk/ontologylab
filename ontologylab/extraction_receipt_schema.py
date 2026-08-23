"""Additive extraction receipt tables and append-only triggers."""

from __future__ import annotations

import sqlite3
from typing import Final


_SCHEMA_STATEMENTS: Final = (
    """
    CREATE TABLE IF NOT EXISTS extraction_run_receipts (
        receipt_id            TEXT PRIMARY KEY,
        representation_id     TEXT NOT NULL REFERENCES documents(id),
        document_content_hash TEXT NOT NULL,
        policy_identity       TEXT NOT NULL,
        config_identity       TEXT NOT NULL,
        chunk_plan_receipt_id TEXT NOT NULL,
        schema_version_id     INTEGER NOT NULL REFERENCES schema_version(id),
        extractor_engine      TEXT NOT NULL,
        extractor_model       TEXT NOT NULL,
        prompt_version        TEXT NOT NULL,
        decode_params_json    TEXT NOT NULL,
        created_ts            REAL NOT NULL,
        UNIQUE (representation_id, policy_identity, config_identity)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS extraction_chunk_receipts (
        receipt_id          TEXT PRIMARY KEY,
        run_receipt_id      TEXT NOT NULL
            REFERENCES extraction_run_receipts(receipt_id),
        chunk_index         INTEGER NOT NULL,
        start_offset        INTEGER NOT NULL,
        end_offset          INTEGER NOT NULL,
        coordinate_profile  TEXT NOT NULL,
        chunk_text_hash     TEXT NOT NULL,
        plan_receipt_id     TEXT NOT NULL,
        UNIQUE (run_receipt_id, chunk_index)
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_extraction_run_receipts_no_update
    BEFORE UPDATE ON extraction_run_receipts
    BEGIN
        SELECT RAISE(ABORT, 'extraction_run_receipts is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_extraction_run_receipts_no_delete
    BEFORE DELETE ON extraction_run_receipts
    BEGIN
        SELECT RAISE(ABORT, 'extraction_run_receipts is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_extraction_chunk_receipts_no_update
    BEFORE UPDATE ON extraction_chunk_receipts
    BEGIN
        SELECT RAISE(ABORT, 'extraction_chunk_receipts is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_extraction_chunk_receipts_no_delete
    BEFORE DELETE ON extraction_chunk_receipts
    BEGIN
        SELECT RAISE(ABORT, 'extraction_chunk_receipts is append-only');
    END
    """,
)


def ensure_receipt_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
