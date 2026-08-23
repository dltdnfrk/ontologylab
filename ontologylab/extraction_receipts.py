"""Public Representation-scoped extraction receipt API."""

from __future__ import annotations

import sqlite3
from typing import Final

from ontologylab.extraction_receipt_schema import (
    ensure_receipt_schema as ensure_receipt_schema,
)
from ontologylab.extraction_receipt_store import put_once
from ontologylab.extraction_receipt_types import (
    DOCUMENT_UTF8_V1 as DOCUMENT_UTF8_V1,
    ChunkSpan as ChunkSpan,
    CoordinateProfile as CoordinateProfile,
    ExtractionChunkReceipt as ExtractionChunkReceipt,
    ExtractionReceiptRefusalCode as ExtractionReceiptRefusalCode,
    ExtractionReceiptRefused as ExtractionReceiptRefused,
    ExtractionReceiptSet as ExtractionReceiptSet,
    ExtractionRunBinding as ExtractionRunBinding,
    ExtractionRunReceipt as ExtractionRunReceipt,
)


_SAVEPOINT: Final = "extraction_receipts_v1"


def put_extraction_receipts(
    conn: sqlite3.Connection,
    binding: ExtractionRunBinding,
    chunks: tuple[ChunkSpan, ...],
) -> ExtractionReceiptSet:
    """Persist immutable run/chunk receipts inside the caller transaction."""
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    try:
        ensure_receipt_schema(conn)
        result = put_once(conn, binding, chunks)
    except (ExtractionReceiptRefused, sqlite3.Error):
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
    return result
