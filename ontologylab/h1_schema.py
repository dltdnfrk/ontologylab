"""Additive H1 classification and ledger tables. No COMMIT."""

from __future__ import annotations

import sqlite3
from typing import Final


_SCHEMA_STATEMENTS: Final = (
    """
    CREATE TABLE IF NOT EXISTS h1_migration_ledger (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        phase TEXT NOT NULL,
        cursor TEXT,
        generation INTEGER NOT NULL,
        source_fingerprint TEXT,
        created_ts REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS h1_anchor_receipts (
        receipt_id TEXT PRIMARY KEY,
        family TEXT NOT NULL
            CHECK (family IN ('run', 'chunk', 'citation', 'review')),
        anchor_id TEXT NOT NULL UNIQUE,
        legacy_pk TEXT NOT NULL,
        classification TEXT NOT NULL
            CHECK (classification IN ('verified', 'quarantined')),
        quarantine_reason TEXT,
        representation_id TEXT,
        family_receipt_id TEXT,
        raw_byte_seal TEXT,
        file_hash TEXT,
        span_hash TEXT,
        evidence_json TEXT NOT NULL,
        created_ts REAL NOT NULL
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_h1_anchor_receipts_no_update
    BEFORE UPDATE ON h1_anchor_receipts
    BEGIN
        SELECT RAISE(ABORT, 'h1_anchor_receipts is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_h1_anchor_receipts_no_delete
    BEFORE DELETE ON h1_anchor_receipts
    BEGIN
        SELECT RAISE(ABORT, 'h1_anchor_receipts is append-only');
    END
    """,
)


def ensure_h1_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
