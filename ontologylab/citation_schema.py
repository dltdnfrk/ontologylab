"""Additive citation receipt table and append-only triggers."""

from __future__ import annotations

import sqlite3
from typing import Final


_SCHEMA_STATEMENTS: Final = (
    """
    CREATE TABLE IF NOT EXISTS citation_receipts (
        receipt_id                   TEXT PRIMARY KEY,
        representation_id            TEXT NOT NULL REFERENCES documents(id),
        representation_content_hash  TEXT NOT NULL,
        run_receipt_id               TEXT NOT NULL
            REFERENCES extraction_run_receipts(receipt_id),
        chunk_receipt_id             TEXT NOT NULL
            REFERENCES extraction_chunk_receipts(receipt_id),
        chunk_start_offset           INTEGER NOT NULL,
        chunk_end_offset             INTEGER NOT NULL,
        coordinate_profile           TEXT NOT NULL,
        chunk_text_hash              TEXT NOT NULL,
        chunk_plan_receipt_id        TEXT NOT NULL,
        selection_receipt_id         TEXT,
        policy_identity              TEXT,
        fact_kind                    TEXT NOT NULL
            CHECK (fact_kind IN ('node', 'edge')),
        fact_id                      TEXT NOT NULL,
        proposal_id                  TEXT NOT NULL,
        fact_revision                TEXT NOT NULL,
        start_offset                 INTEGER NOT NULL,
        end_offset                   INTEGER NOT NULL,
        selected_text                TEXT NOT NULL,
        selected_text_hash           TEXT NOT NULL,
        created_ts                   REAL NOT NULL,
        UNIQUE (
            representation_id, run_receipt_id, chunk_receipt_id,
            fact_kind, fact_id, start_offset, end_offset
        )
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_citation_receipts_no_update
    BEFORE UPDATE ON citation_receipts
    BEGIN
        SELECT RAISE(ABORT, 'citation_receipts is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_citation_receipts_no_delete
    BEFORE DELETE ON citation_receipts
    BEGIN
        SELECT RAISE(ABORT, 'citation_receipts is append-only');
    END
    """,
)


def ensure_citation_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
