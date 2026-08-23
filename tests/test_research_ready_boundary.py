"""Research consumer must read selected bytes through the ready boundary."""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import sqlite3
from pathlib import Path

import pytest

from ontologylab.file_lifecycle import FileIntegrityError
from ontologylab.research_extract import extract_research_documents
from tests.test_preferred_selection import node_names, plant_c024
from tests.test_research_selection import _session

LEAK_TOKEN = "TamperedRawPathLeak"


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0])


def test_research_refuses_when_selected_ready_bytes_are_tampered(
    tmp_path: Path,
) -> None:
    store, _work_id, publisher_id, pmc_id = plant_c024(tmp_path)
    try:
        relative = store.conn.execute(
            "SELECT raw_text_path FROM documents WHERE id = ?",
            (pmc_id,),
        ).fetchone()["raw_text_path"]
        target = tmp_path / str(relative)
        target.write_bytes((f"{LEAK_TOKEN} tampered ready body. " * 40).encode("utf-8"))
        with pytest.raises(FileIntegrityError) as refused:
            asyncio.run(
                extract_research_documents(
                    store,
                    (publisher_id, pmc_id),
                    _session(tmp_path / "job-tamper"),
                )
            )
        assert refused.value.reason == "hash_mismatch"
        if store.conn.in_transaction:
            store.conn.rollback()
        assert LEAK_TOKEN not in node_names(store)
        assert _table_count(store.conn, "extraction_run_receipts") == 0
        assert _table_count(store.conn, "extraction_chunk_receipts") == 0
        assert _table_count(store.conn, "nodes") == 0
    finally:
        store.close()
