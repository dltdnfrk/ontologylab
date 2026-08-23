"""Additive grounded ReviewDecision table and append-only triggers."""

from __future__ import annotations

import sqlite3
from typing import Final


_SCHEMA_STATEMENTS: Final = (
    """
    CREATE TABLE IF NOT EXISTS grounded_review_decisions (
        receipt_id              TEXT PRIMARY KEY,
        fact_kind               TEXT NOT NULL
            CHECK (fact_kind IN ('node', 'edge')),
        fact_id                 TEXT NOT NULL,
        proposal_id             TEXT NOT NULL,
        fact_revision           TEXT NOT NULL
            CHECK (fact_revision != ''),
        action                  TEXT NOT NULL
            CHECK (action IN (
                'approve', 'reject', 'quarantine', 'retract',
                'compensate', 'approve_with_grounding_waiver'
            )),
        actor                   TEXT NOT NULL CHECK (actor != ''),
        reason                  TEXT NOT NULL CHECK (reason != ''),
        decided_ts              REAL NOT NULL,
        as_of_ts                REAL NOT NULL,
        citation_set_digest     TEXT NOT NULL
            CHECK (citation_set_digest != ''),
        citation_receipt_ids_json TEXT NOT NULL,
        representation_id       TEXT,
        selection_receipt_id    TEXT,
        policy_identity         TEXT,
        run_receipt_id          TEXT,
        predecessor_receipt_id  TEXT,
        pack_ineligible         INTEGER NOT NULL
            CHECK (pack_ineligible IN (0, 1)),
        waived_fact_ids_json    TEXT NOT NULL,
        waived_citation_ids_json TEXT NOT NULL,
        scoped_defects_json     TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_grounded_review_fact_as_of
    ON grounded_review_decisions (fact_kind, fact_id, as_of_ts, receipt_id)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_grounded_review_decisions_no_update
    BEFORE UPDATE ON grounded_review_decisions
    BEGIN
        SELECT RAISE(ABORT, 'grounded_review_decisions is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_grounded_review_decisions_no_delete
    BEFORE DELETE ON grounded_review_decisions
    BEGIN
        SELECT RAISE(ABORT, 'grounded_review_decisions is append-only');
    END
    """,
)


def ensure_grounded_review_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
