"""Caller-owned persistence for preferred-selection receipts."""

from __future__ import annotations

import sqlite3
import time

from ontologylab.selection_ids import (
    inventory_json,
    parse_inventory,
    policy_hash,
    receipt_from_parts,
)
from ontologylab.selection_policy import inventory_entry, select_winner
from ontologylab.selection_schema import ensure_selection_schema
from ontologylab.selection_types import (
    PolicyVersion,
    SelectionReceipt,
    SelectionRefusalCode,
    refuse,
)
from ontologylab.work_view import WorkNotFound, work_candidates


def put_once(
    conn: sqlite3.Connection,
    work_id: str,
    policy: PolicyVersion,
) -> SelectionReceipt:
    if not work_id.strip():
        refuse(
            SelectionRefusalCode.MISSING_BINDING,
            work_id,
            "work identity is required",
        )
    ensure_selection_schema(conn)
    try:
        candidates = work_candidates(conn, work_id)
    except WorkNotFound:
        refuse(
            SelectionRefusalCode.UNKNOWN_WORK,
            work_id,
            f"unknown work {work_id!r}",
        )
    inventory = tuple(inventory_entry(candidate) for candidate in candidates)
    winner = select_winner(inventory, policy)
    selected_id = None if winner is None else winner.representation_id
    selected_hash = None if winner is None else winner.content_hash
    hashed = policy_hash(policy)
    expected = receipt_from_parts(
        work_id, policy, hashed, inventory, selected_id, selected_hash,
        created=True,
    )
    existing = _existing(conn, expected.receipt_id)
    if existing is not None:
        return existing
    _insert(conn, expected)
    return expected


def get_once(conn: sqlite3.Connection, receipt_id: str) -> SelectionReceipt | None:
    ensure_selection_schema(conn)
    return _existing(conn, receipt_id)


def list_for_work(
    conn: sqlite3.Connection, work_id: str,
) -> tuple[SelectionReceipt, ...]:
    ensure_selection_schema(conn)
    rows = conn.execute(
        "SELECT receipt_id, work_id, policy_version, policy_hash, "
        "selected_representation_id, selected_content_hash, inventory_json "
        "FROM preferred_selection_receipts WHERE work_id = ? "
        "ORDER BY created_ts, receipt_id",
        (work_id,),
    ).fetchall()
    return tuple(_row_receipt(row, created=False) for row in rows)


def _existing(
    conn: sqlite3.Connection, receipt_id: str,
) -> SelectionReceipt | None:
    row = conn.execute(
        "SELECT receipt_id, work_id, policy_version, policy_hash, "
        "selected_representation_id, selected_content_hash, inventory_json "
        "FROM preferred_selection_receipts WHERE receipt_id = ?",
        (receipt_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_receipt(row, created=False)


def _row_receipt(row: sqlite3.Row, *, created: bool) -> SelectionReceipt:
    return SelectionReceipt(
        receipt_id=str(row["receipt_id"]),
        work_id=str(row["work_id"]),
        policy_version=str(row["policy_version"]),
        policy_hash=str(row["policy_hash"]),
        selected_representation_id=(
            None
            if row["selected_representation_id"] is None
            else str(row["selected_representation_id"])
        ),
        selected_content_hash=(
            None
            if row["selected_content_hash"] is None
            else str(row["selected_content_hash"])
        ),
        inventory=parse_inventory(str(row["inventory_json"])),
        created=created,
    )


def _insert(conn: sqlite3.Connection, receipt: SelectionReceipt) -> None:
    conn.execute(
        "INSERT INTO preferred_selection_receipts ("
        "receipt_id, work_id, policy_version, policy_hash, "
        "selected_representation_id, selected_content_hash, inventory_json, "
        "created_ts) VALUES (?,?,?,?,?,?,?,?)",
        (
            receipt.receipt_id,
            receipt.work_id,
            receipt.policy_version,
            receipt.policy_hash,
            receipt.selected_representation_id,
            receipt.selected_content_hash,
            inventory_json(receipt.inventory),
            time.time(),
        ),
    )
