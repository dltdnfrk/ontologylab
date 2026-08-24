"""Additive append-only review decision tables."""

from __future__ import annotations

import sqlite3
from typing import Final


_SCHEMA_STATEMENTS: Final = (
    """
    CREATE TABLE IF NOT EXISTS review_decisions (
        decision_id         TEXT PRIMARY KEY,
        decision_kind       TEXT NOT NULL
            CHECK (decision_kind IN ('approve', 'reject', 'waiver')),
        fact_kind           TEXT NOT NULL
            CHECK (fact_kind IN ('node', 'edge')),
        fact_id             TEXT NOT NULL,
        fact_revision       TEXT NOT NULL,
        citation_set_hash   TEXT NOT NULL,
        grounding_class     TEXT NOT NULL
            CHECK (grounding_class IN ('grounded', 'ungrounded', 'waived')),
        actor               TEXT NOT NULL,
        reason              TEXT,
        batch_id            TEXT NOT NULL,
        member_ids_json     TEXT NOT NULL,
        created_ts          REAL NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_review_decisions_fact
    ON review_decisions (fact_kind, fact_id, created_ts)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_review_decisions_batch
    ON review_decisions (batch_id)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_review_decisions_no_update
    BEFORE UPDATE ON review_decisions
    BEGIN
        SELECT RAISE(ABORT, 'review_decisions is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_review_decisions_no_delete
    BEFORE DELETE ON review_decisions
    BEGIN
        SELECT RAISE(ABORT, 'review_decisions is append-only');
    END
    """,
    """
    CREATE TABLE IF NOT EXISTS review_publication (
        fact_kind           TEXT NOT NULL
            CHECK (fact_kind IN ('node', 'edge')),
        fact_id             TEXT NOT NULL,
        publication_class   TEXT NOT NULL
            CHECK (publication_class IN ('sourced', 'working_only')),
        decision_id         TEXT NOT NULL
            REFERENCES review_decisions(decision_id),
        updated_ts          REAL NOT NULL,
        PRIMARY KEY (fact_kind, fact_id)
    )
    """,
)


def ensure_review_decision_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
