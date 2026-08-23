"""Public immutable citation receipt API."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Final, TypeVar

from ontologylab.citation_bind import persist_once
from ontologylab.citation_schema import (
    ensure_citation_schema as ensure_citation_schema,
)
from ontologylab.citation_store import get_once, list_for_fact, put_once
from ontologylab.citation_types import (
    ChunkCitationBatch as ChunkCitationBatch,
    CitationBinding as CitationBinding,
    CitationReceipt as CitationReceipt,
    CitationRefusalCode as CitationRefusalCode,
    CitationRefused as CitationRefused,
    FactKind as FactKind,
)


_SAVEPOINT: Final = "citation_receipts_v1"


def put_citation_receipts(
    conn: sqlite3.Connection,
    bindings: tuple[CitationBinding, ...],
) -> tuple[CitationReceipt, ...]:
    """Persist immutable citation receipts inside the caller transaction."""
    return _with_savepoint(conn, lambda: put_once(conn, bindings))


def get_citation_receipt(
    conn: sqlite3.Connection, receipt_id: str,
) -> CitationReceipt | None:
    """Return a stored receipt after verifying it against ready bytes."""
    return get_once(conn, receipt_id)


def list_citation_receipts(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> tuple[CitationReceipt, ...]:
    """Grounded receipts for one fact, oldest first."""
    return list_for_fact(conn, fact_kind, fact_id)


def persist_chunk_citations(
    conn: sqlite3.Connection, batch: ChunkCitationBatch,
) -> tuple[CitationReceipt, ...]:
    """Persist citations for one extracted chunk when Task 2 receipts exist."""
    return _with_savepoint(conn, lambda: persist_once(conn, batch))


_T = TypeVar("_T")


def _with_savepoint(
    conn: sqlite3.Connection, action: Callable[[], _T],
) -> _T:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    try:
        result = action()
    except (CitationRefused, sqlite3.Error):
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
    return result
