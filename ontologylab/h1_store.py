"""Persist H1 classification rows. Caller owns the transaction."""

from __future__ import annotations

import sqlite3
import time

from ontologylab.h1_ids import classification_receipt_id
from ontologylab.h1_schema import ensure_h1_schema
from ontologylab.h1_types import H1Decision


def classified_anchor_ids(conn: sqlite3.Connection) -> frozenset[str]:
    ensure_h1_schema(conn)
    rows = conn.execute("SELECT anchor_id FROM h1_anchor_receipts").fetchall()
    return frozenset(str(row[0]) for row in rows)


def persist_decision(conn: sqlite3.Connection, decision: H1Decision) -> None:
    ensure_h1_schema(conn)
    existing = conn.execute(
        "SELECT receipt_id FROM h1_anchor_receipts WHERE anchor_id = ?",
        (decision.anchor_id,),
    ).fetchone()
    if existing is not None:
        return
    receipt_id = classification_receipt_id(
        family=decision.family,
        anchor=decision.anchor_id,
        classification=decision.classification,
        reason=decision.reason,
        family_receipt_id=decision.family_receipt_id,
        raw_byte_seal=decision.raw_byte_seal,
        file_hash=decision.file_hash,
        span_hash=decision.span_hash,
    )
    reason = None if decision.reason is None else decision.reason.value
    conn.execute(
        "INSERT INTO h1_anchor_receipts ("
        "receipt_id, family, anchor_id, legacy_pk, classification, "
        "quarantine_reason, representation_id, family_receipt_id, "
        "raw_byte_seal, file_hash, span_hash, evidence_json, created_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            receipt_id,
            decision.family.value,
            decision.anchor_id,
            decision.legacy_pk,
            decision.classification.value,
            reason,
            decision.representation_id,
            decision.family_receipt_id,
            decision.raw_byte_seal,
            decision.file_hash,
            decision.span_hash,
            decision.evidence_json,
            time.time(),
        ),
    )


def latest_cursor(conn: sqlite3.Connection) -> str | None:
    ensure_h1_schema(conn)
    row = conn.execute(
        "SELECT cursor FROM h1_migration_ledger ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return row[0]


def checkpoint(conn: sqlite3.Connection, cursor: str, fingerprint: str) -> None:
    ensure_h1_schema(conn)
    conn.execute(
        "INSERT INTO h1_migration_ledger "
        "(phase, cursor, generation, source_fingerprint, created_ts) "
        "VALUES ('h1', ?, 0, ?, julianday('now'))",
        (cursor, fingerprint),
    )


def phase_complete(conn: sqlite3.Connection) -> bool:
    return latest_cursor(conn) == "$complete"
