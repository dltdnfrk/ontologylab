"""Exact classified Task 4 citation lookup for H1 family linking."""

from __future__ import annotations

import json
import sqlite3

from ontologylab.citation import get_citation_receipt
from ontologylab.citation_ids import fact_revision_id
from ontologylab.citation_types import CitationReceipt, CitationRefused
from ontologylab.extraction_receipt_types import DOCUMENT_UTF8_V1
from ontologylab.h1_existing import (
    current_run_receipt_id,
    has_table,
    selection_policy,
    selection_receipt_id,
)
from ontologylab.h1_ids import LEGACY_POLICY
from ontologylab.h1_types import H1Decision


def existing_citation_receipt(
    conn: sqlite3.Connection, decision: H1Decision,
) -> str | None:
    if not has_table(conn, "citation_receipts"):
        return None
    key = _citation_key(decision)
    if key is None:
        return None
    expected = _expected_citation(conn, key)
    if expected is None:
        return None
    loaded = verified_citation(conn, expected)
    if loaded is None:
        return None
    if not citation_matches(loaded, key, conn):
        return None
    return expected


def verified_citation(
    conn: sqlite3.Connection, receipt_id: str,
) -> CitationReceipt | None:
    try:
        return get_citation_receipt(conn, receipt_id)
    except CitationRefused:
        return None


def expected_cite_ids(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> tuple[str, ...]:
    if not has_table(conn, "citation_receipts"):
        return ()
    found: list[str] = []
    for row in conn.execute(
        "SELECT receipt_id FROM citation_receipts "
        "WHERE fact_kind = ? AND fact_id = ? ORDER BY receipt_id",
        (fact_kind, fact_id),
    ):
        loaded = verified_citation(conn, str(row[0]))
        if loaded is None:
            continue
        key = (
            loaded.representation_id, loaded.fact_kind, loaded.fact_id,
            loaded.start_offset, loaded.end_offset,
            loaded.representation_content_hash, loaded.selected_text_hash,
        )
        if citation_matches(loaded, key, conn):
            found.append(loaded.receipt_id)
    return tuple(found)


def citation_matches(
    loaded: CitationReceipt,
    key: tuple[str, str, str, int, int, str, str],
    conn: sqlite3.Connection,
) -> bool:
    if (
        loaded.representation_id != key[0]
        or loaded.fact_kind != key[1]
        or loaded.fact_id != key[2]
        or loaded.start_offset != key[3]
        or loaded.end_offset != key[4]
        or loaded.representation_content_hash != key[5]
        or loaded.selected_text_hash != key[6]
        or loaded.fact_revision != fact_revision_id(key[1], key[2])
        or loaded.coordinate_profile != DOCUMENT_UTF8_V1
    ):
        return False
    run_id = current_run_receipt_id(conn, key[0], key[5])
    if run_id is None or loaded.run_receipt_id != run_id:
        return False
    expected_sel = selection_receipt_id(conn, key[0])
    expected_policy = selection_policy(conn, key[0])
    if expected_policy is None:
        expected_policy = LEGACY_POLICY
    if loaded.selection_receipt_id != expected_sel:
        return False
    return loaded.policy_identity == expected_policy


def _expected_citation(
    conn: sqlite3.Connection,
    key: tuple[str, str, str, int, int, str, str],
) -> str | None:
    run_id = current_run_receipt_id(conn, key[0], key[5])
    if run_id is None:
        return None
    chunk = conn.execute(
        "SELECT receipt_id, start_offset, end_offset, coordinate_profile, "
        "chunk_text_hash, plan_receipt_id FROM extraction_chunk_receipts "
        "WHERE run_receipt_id = ? AND start_offset <= ? AND end_offset >= ? "
        "ORDER BY chunk_index, receipt_id",
        (run_id, key[3], key[4]),
    ).fetchone()
    if chunk is None:
        return None
    selection = selection_receipt_id(conn, key[0])
    policy = selection_policy(conn, key[0])
    if policy is None:
        policy = LEGACY_POLICY
    row = conn.execute(
        "SELECT receipt_id FROM citation_receipts "
        "WHERE representation_id = ? AND run_receipt_id = ? "
        "AND chunk_receipt_id = ? AND coordinate_profile = ? "
        "AND chunk_plan_receipt_id = ? AND fact_kind = ? AND fact_id = ? "
        "AND start_offset = ? AND end_offset = ? "
        "AND ifnull(selection_receipt_id, '') = ? "
        "AND ifnull(policy_identity, '') = ? ORDER BY receipt_id",
        (
            key[0], run_id, str(chunk[0]), str(chunk[3]), str(chunk[5]),
            key[1], key[2], key[3], key[4],
            selection or "", policy,
        ),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def _citation_key(
    decision: H1Decision,
) -> tuple[str, str, str, int, int, str, str] | None:
    evidence = json.loads(decision.evidence_json)
    start = evidence.get("start")
    end = evidence.get("end")
    fact_kind = evidence.get("fact_kind")
    fact_id = evidence.get("fact_id")
    representation_id = decision.representation_id
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or not isinstance(fact_kind, str)
        or not isinstance(fact_id, str)
        or representation_id is None
        or decision.raw_byte_seal is None
        or decision.span_hash is None
    ):
        return None
    return (
        representation_id, fact_kind, fact_id, start, end,
        decision.raw_byte_seal, decision.span_hash,
    )
