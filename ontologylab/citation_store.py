"""Caller-owned persistence for citation receipts."""

from __future__ import annotations

import sqlite3
import time

from ontologylab.citation_ids import citation_receipt_id, receipt_from_binding
from ontologylab.citation_schema import ensure_citation_schema
from ontologylab.citation_types import (
    CitationBinding,
    CitationReceipt,
    CitationRefusalCode,
    refuse,
)
from ontologylab.citation_verify import ready_document, verify_binding


def put_once(
    conn: sqlite3.Connection, bindings: tuple[CitationBinding, ...],
) -> tuple[CitationReceipt, ...]:
    ensure_citation_schema(conn)
    if not bindings:
        return ()
    written: list[CitationReceipt] = []
    for binding in bindings:
        text, content_hash = ready_document(conn, binding.representation_id)
        verify_binding(conn, binding, text, content_hash)
        expected = receipt_from_binding(binding, created=True)
        existing = _existing(conn, binding)
        if existing is not None:
            if existing.receipt_id != expected.receipt_id:
                refuse(
                    CitationRefusalCode.CONFLICT,
                    "retry does not match the immutable citation receipt",
                )
            written.append(existing)
            continue
        _insert(conn, expected)
        written.append(expected)
    return tuple(written)


def get_once(
    conn: sqlite3.Connection, receipt_id: str,
) -> CitationReceipt | None:
    ensure_citation_schema(conn)
    row = conn.execute(
        "SELECT * FROM citation_receipts WHERE receipt_id = ?",
        (receipt_id,),
    ).fetchone()
    if row is None:
        return None
    receipt = _row_receipt(row, created=False)
    _verify_stored(conn, receipt)
    return receipt


def list_for_fact(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> tuple[CitationReceipt, ...]:
    ensure_citation_schema(conn)
    rows = conn.execute(
        "SELECT * FROM citation_receipts WHERE fact_kind = ? AND fact_id = ? "
        "ORDER BY created_ts, receipt_id",
        (fact_kind, fact_id),
    ).fetchall()
    receipts = tuple(_row_receipt(row, created=False) for row in rows)
    for receipt in receipts:
        _verify_stored(conn, receipt)
    return receipts


def list_stored_for_fact(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> tuple[CitationReceipt, ...]:
    ensure_citation_schema(conn)
    rows = conn.execute(
        "SELECT * FROM citation_receipts WHERE fact_kind = ? AND fact_id = ? "
        "ORDER BY created_ts, receipt_id",
        (fact_kind, fact_id),
    ).fetchall()
    return tuple(_row_receipt(row, created=False) for row in rows)


def _verify_stored(
    conn: sqlite3.Connection, receipt: CitationReceipt,
) -> None:
    binding = CitationBinding(
        representation_id=receipt.representation_id,
        representation_content_hash=receipt.representation_content_hash,
        run_receipt_id=receipt.run_receipt_id,
        chunk_receipt_id=receipt.chunk_receipt_id,
        chunk_start_offset=receipt.chunk_start_offset,
        chunk_end_offset=receipt.chunk_end_offset,
        coordinate_profile=receipt.coordinate_profile,
        chunk_text_hash=receipt.chunk_text_hash,
        chunk_plan_receipt_id=receipt.chunk_plan_receipt_id,
        selection_receipt_id=receipt.selection_receipt_id,
        policy_identity=receipt.policy_identity,
        fact_kind=receipt.fact_kind,
        fact_id=receipt.fact_id,
        proposal_id=receipt.proposal_id,
        fact_revision=receipt.fact_revision,
        start_offset=receipt.start_offset,
        end_offset=receipt.end_offset,
        selected_text=receipt.selected_text,
        selected_text_hash=receipt.selected_text_hash,
    )
    text, content_hash = ready_document(conn, receipt.representation_id)
    verify_binding(conn, binding, text, content_hash)
    if citation_receipt_id(binding) != receipt.receipt_id:
        refuse(
            CitationRefusalCode.CONFLICT,
            "stored citation receipt identity does not match its fields",
        )


def _existing(
    conn: sqlite3.Connection, binding: CitationBinding,
) -> CitationReceipt | None:
    row = conn.execute(
        "SELECT * FROM citation_receipts WHERE representation_id = ? AND "
        "run_receipt_id = ? AND chunk_receipt_id = ? AND fact_kind = ? AND "
        "fact_id = ? AND start_offset = ? AND end_offset = ?",
        (
            binding.representation_id,
            binding.run_receipt_id,
            binding.chunk_receipt_id,
            binding.fact_kind,
            binding.fact_id,
            binding.start_offset,
            binding.end_offset,
        ),
    ).fetchone()
    if row is None:
        return None
    return _row_receipt(row, created=False)


def _row_receipt(row: sqlite3.Row, *, created: bool) -> CitationReceipt:
    selection = row["selection_receipt_id"]
    policy = row["policy_identity"]
    return CitationReceipt(
        receipt_id=str(row["receipt_id"]),
        representation_id=str(row["representation_id"]),
        representation_content_hash=str(row["representation_content_hash"]),
        run_receipt_id=str(row["run_receipt_id"]),
        chunk_receipt_id=str(row["chunk_receipt_id"]),
        chunk_start_offset=int(row["chunk_start_offset"]),
        chunk_end_offset=int(row["chunk_end_offset"]),
        coordinate_profile=str(row["coordinate_profile"]),
        chunk_text_hash=str(row["chunk_text_hash"]),
        chunk_plan_receipt_id=str(row["chunk_plan_receipt_id"]),
        selection_receipt_id=None if selection is None else str(selection),
        policy_identity=None if policy is None else str(policy),
        fact_kind=str(row["fact_kind"]),
        fact_id=str(row["fact_id"]),
        proposal_id=str(row["proposal_id"]),
        fact_revision=str(row["fact_revision"]),
        start_offset=int(row["start_offset"]),
        end_offset=int(row["end_offset"]),
        selected_text=str(row["selected_text"]),
        selected_text_hash=str(row["selected_text_hash"]),
        created=created,
    )


def _insert(conn: sqlite3.Connection, receipt: CitationReceipt) -> None:
    conn.execute(
        "INSERT INTO citation_receipts ("
        "receipt_id, representation_id, representation_content_hash, "
        "run_receipt_id, chunk_receipt_id, chunk_start_offset, "
        "chunk_end_offset, coordinate_profile, chunk_text_hash, "
        "chunk_plan_receipt_id, selection_receipt_id, policy_identity, "
        "fact_kind, fact_id, proposal_id, fact_revision, start_offset, "
        "end_offset, selected_text, selected_text_hash, created_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            receipt.receipt_id,
            receipt.representation_id,
            receipt.representation_content_hash,
            receipt.run_receipt_id,
            receipt.chunk_receipt_id,
            receipt.chunk_start_offset,
            receipt.chunk_end_offset,
            receipt.coordinate_profile,
            receipt.chunk_text_hash,
            receipt.chunk_plan_receipt_id,
            receipt.selection_receipt_id,
            receipt.policy_identity,
            receipt.fact_kind,
            receipt.fact_id,
            receipt.proposal_id,
            receipt.fact_revision,
            receipt.start_offset,
            receipt.end_offset,
            receipt.selected_text,
            receipt.selected_text_hash,
            time.time(),
        ),
    )
