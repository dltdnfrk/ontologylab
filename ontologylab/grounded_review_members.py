"""Current fact-member citation receipts without ready-byte re-verify."""

from __future__ import annotations

import json
import sqlite3

from ontologylab.citation import list_stored_citation_receipts
from ontologylab.citation_ids import fact_revision_id
from ontologylab.citation_types import CitationReceipt
from ontologylab.h1_existing import (
    current_run_receipt_id,
    has_table,
    selection_policy,
    selection_receipt_id,
)


def stored_member_citations(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> tuple[CitationReceipt, ...]:
    """Receipts that join current ``citations`` memberships for this fact."""
    stored = list_stored_citation_receipts(conn, fact_kind, fact_id)
    if not stored or not has_table(conn, "citations"):
        return ()
    members = conn.execute(
        "SELECT source_doc_id, source_span FROM citations "
        "WHERE kind = ? AND item_id = ?",
        (fact_kind, fact_id),
    ).fetchall()
    allowed: set[tuple[str, int | None, int | None]] = set()
    for row in members:
        raw = row["source_span"]
        start, end = _span_offsets(None if raw is None else str(raw))
        allowed.add((str(row["source_doc_id"]), start, end))
    if not allowed:
        return ()
    revision = fact_revision_id(fact_kind, fact_id)
    found: list[CitationReceipt] = []
    for receipt in stored:
        if receipt.fact_revision != revision:
            continue
        if (receipt.representation_id, receipt.start_offset, receipt.end_offset) not in allowed:
            if (receipt.representation_id, None, None) not in allowed:
                continue
        if not _current_identity(conn, receipt):
            continue
        found.append(receipt)
    return tuple(found)


def _span_offsets(raw: str | None) -> tuple[int | None, int | None]:
    if raw is None or raw == "":
        return None, None
    try:
        payload = json.loads(str(raw))
    except json.JSONDecodeError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    start = payload.get("start")
    end = payload.get("end")
    if isinstance(start, int) and isinstance(end, int):
        return start, end
    return None, None


def _current_identity(conn: sqlite3.Connection, receipt: CitationReceipt) -> bool:
    hash_row = conn.execute(
        "SELECT content_hash FROM documents WHERE id = ?",
        (receipt.representation_id,),
    ).fetchone()
    if hash_row is None:
        return False
    run_id = current_run_receipt_id(
        conn, receipt.representation_id, str(hash_row[0]),
    )
    if run_id is not None and receipt.run_receipt_id != run_id:
        return False
    expected_sel = selection_receipt_id(conn, receipt.representation_id)
    expected_policy = selection_policy(conn, receipt.representation_id)
    if expected_sel is not None and receipt.selection_receipt_id != expected_sel:
        return False
    if expected_policy is not None and receipt.policy_identity != expected_policy:
        return False
    return True
