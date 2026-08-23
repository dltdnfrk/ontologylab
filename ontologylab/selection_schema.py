"""Additive preferred-selection receipt table and append-only triggers."""

from __future__ import annotations

import sqlite3
from typing import Final


_SCHEMA_STATEMENTS: Final = (
    """
    CREATE TABLE IF NOT EXISTS preferred_selection_receipts (
        receipt_id                   TEXT PRIMARY KEY,
        work_id                      TEXT NOT NULL,
        policy_version               TEXT NOT NULL,
        policy_hash                  TEXT NOT NULL,
        selected_representation_id   TEXT,
        selected_content_hash        TEXT,
        inventory_json               TEXT NOT NULL,
        created_ts                   REAL NOT NULL
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_preferred_selection_receipts_no_update
    BEFORE UPDATE ON preferred_selection_receipts
    BEGIN
        SELECT RAISE(ABORT, 'preferred_selection_receipts is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_preferred_selection_receipts_no_delete
    BEFORE DELETE ON preferred_selection_receipts
    BEGIN
        SELECT RAISE(ABORT, 'preferred_selection_receipts is append-only');
    END
    """,
)


def ensure_selection_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
