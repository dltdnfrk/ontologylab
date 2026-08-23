"""Public F9 preferred-representation selection receipt API."""

from __future__ import annotations

import sqlite3
from typing import Final

from ontologylab.selection_schema import (
    ensure_selection_schema as ensure_selection_schema,
)
from ontologylab.selection_store import get_once, list_for_work, put_once
from ontologylab.selection_types import (
    PolicyVersion,
    SelectionReceipt,
    SelectionRefusalCode as SelectionRefusalCode,
    SelectionRefused as SelectionRefused,
)


_SAVEPOINT: Final = "preferred_selection_v1"


def put_selection_receipt(
    conn: sqlite3.Connection,
    work_id: str,
    policy: PolicyVersion,
) -> SelectionReceipt:
    """Persist an immutable selection receipt inside the caller transaction."""
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    try:
        result = put_once(conn, work_id, policy)
    except (SelectionRefused, sqlite3.Error):
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
    return result


def get_selection_receipt(
    conn: sqlite3.Connection, receipt_id: str,
) -> SelectionReceipt | None:
    """Return a stored receipt without recomputing the policy."""
    return get_once(conn, receipt_id)


def list_selection_receipts(
    conn: sqlite3.Connection, work_id: str,
) -> tuple[SelectionReceipt, ...]:
    """Historical receipts for one Work, oldest first."""
    return list_for_work(conn, work_id)
