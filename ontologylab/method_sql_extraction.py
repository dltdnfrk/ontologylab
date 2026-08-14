"""Explicit SQLite operations for Method extraction lifecycle state."""

from __future__ import annotations

import dataclasses
from pathlib import Path
import sqlite3
from typing import Any, Protocol, Sequence

from ontologylab.method_extraction_store import (
    ExtractionChunkWrite,
    ExtractionRunWrite,
    PolicySnapshotRecord,
    occurrence_parameters,
)
from ontologylab.method_validation import MethodConflictError, OccurrenceWrite
from ontologylab.method_validation import DocumentRecord


class _Connection(Protocol):
    def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        /,
    ) -> sqlite3.Cursor:
        ...

    def executemany(
        self,
        sql: str,
        parameters: Sequence[tuple[Any, ...]],
        /,
    ) -> sqlite3.Cursor:
        ...


_SELECT_POLICY_SNAPSHOT = """
SELECT document_id, document_content_hash, resolution_status
FROM document_policy_snapshot WHERE id=?
"""
_SELECT_DOCUMENT = """
SELECT content_hash, raw_text_path FROM documents WHERE id=?
"""
_DATABASE_LIST = """
PRAGMA database_list
"""
_INSERT_OCCURRENCE = """
INSERT INTO statement_occurrence VALUES
(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""
_INSERT_EXTRACTION_RUN = """
INSERT INTO method_extraction_runs VALUES
(?,?,?,?,?,?,?,?,?,?,'pending',NULL,NULL,NULL,?,?)
"""
_INSERT_EXTRACTION_CHUNK = """
INSERT INTO method_extraction_chunks VALUES
(?,?,?,?,'pending',0,NULL,NULL,NULL,NULL)
"""
_CLAIM_EXTRACTION_RUN = """
UPDATE method_extraction_runs SET status='running', owner_token=?,
error_kind=NULL, error_identity=NULL, updated_ts=?
WHERE id=? AND status IN ('pending','resumed')
"""
_CLAIM_EXTRACTION_CHUNK = """
UPDATE method_extraction_chunks
SET status='running', attempts=attempts+1, owner_token=?,
    stats_json=NULL, error_kind=NULL, error_identity=NULL
WHERE run_id=? AND chunk_index=?
  AND status IN ('pending','failed','interrupted')
  AND EXISTS (SELECT 1 FROM method_extraction_runs
    WHERE id=? AND status='running' AND owner_token=?)
"""
_SUCCEED_EXTRACTION_CHUNK = """
UPDATE method_extraction_chunks SET status='succeeded',
owner_token=NULL, stats_json=? WHERE run_id=? AND chunk_index=?
AND status='running' AND owner_token=?
"""
_INTERRUPT_EXTRACTION_RUN = """
UPDATE method_extraction_runs SET status='interrupted',
owner_token=NULL, error_kind='interrupted', error_identity=?,
updated_ts=? WHERE id=? AND status='running' AND owner_token=?
"""
_INTERRUPT_RUNNING_CHUNKS = """
UPDATE method_extraction_chunks SET status='interrupted', owner_token=NULL
WHERE run_id=? AND status='running' AND owner_token=?
"""
_RESUME_EXTRACTION_RUN = """
UPDATE method_extraction_runs SET status='resumed', owner_token=NULL,
updated_ts=? WHERE id=? AND status IN ('failed','interrupted')
"""
_SELECT_RETRYABLE_CHUNKS = """
SELECT chunk_index FROM method_extraction_chunks WHERE run_id=?
AND status IN ('pending','failed','interrupted') ORDER BY chunk_index
"""
_FAIL_EXTRACTION_CHUNK = """
UPDATE method_extraction_chunks SET status='failed', owner_token=NULL,
error_kind=?, error_identity=? WHERE run_id=? AND chunk_index=?
AND status='running' AND owner_token=?
"""
_MARK_RUN_FAILED_FROM_CHUNK = """
UPDATE method_extraction_runs SET status='failed', owner_token=NULL,
error_kind=?, error_identity=?, updated_ts=? WHERE id=?
"""
_COUNT_UNFINISHED_CHUNKS = """
SELECT COUNT(*) FROM method_extraction_chunks
WHERE run_id=? AND status!='succeeded'
"""
_SUCCEED_EXTRACTION_RUN = """
UPDATE method_extraction_runs SET status='succeeded',
owner_token=NULL, error_kind=NULL, error_identity=NULL, updated_ts=?
WHERE id=? AND status='running' AND owner_token=?
"""
_FAIL_EXTRACTION_RUN = """
UPDATE method_extraction_runs SET status='failed', owner_token=NULL,
error_kind=?, error_identity=?, updated_ts=? WHERE id=?
AND status='running' AND owner_token=?
"""


class _MethodSqlExtraction:
    """Typed extraction run, chunk, and occurrence state operations."""

    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    def policy_snapshot(
        self,
        snapshot_id: str,
    ) -> PolicySnapshotRecord | None:
        row = self._connection.execute(
            _SELECT_POLICY_SNAPSHOT,
            (snapshot_id,),
        ).fetchone()
        return None if row is None else PolicySnapshotRecord(*row)

    def document(self, document_id: str) -> DocumentRecord | None:
        row = self._connection.execute(
            _SELECT_DOCUMENT,
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        database_path = Path(
            self._connection.execute(_DATABASE_LIST).fetchone()["file"]
        )
        return DocumentRecord(
            database_path.resolve(), row["content_hash"], row["raw_text_path"]
        )

    def insert_occurrence(self, row: OccurrenceWrite) -> None:
        try:
            self._connection.execute(
                _INSERT_OCCURRENCE,
                occurrence_parameters(row),
            )
        except sqlite3.IntegrityError as exc:
            if (
                str(exc)
                != "UNIQUE constraint failed: statement_occurrence.id"
            ):
                raise
            raise MethodConflictError(
                "occurrence identity already exists"
            ) from exc

    def insert_extraction_run(
        self,
        run: ExtractionRunWrite,
        chunks: Sequence[ExtractionChunkWrite],
    ) -> None:
        self._connection.execute(
            _INSERT_EXTRACTION_RUN,
            dataclasses.astuple(run),
        )
        self._connection.executemany(
            _INSERT_EXTRACTION_CHUNK,
            tuple(dataclasses.astuple(chunk) for chunk in chunks),
        )

    def claim_extraction_run(
        self,
        run_id: str,
        owner_token: str,
        updated_ts: float,
    ) -> bool:
        return (
            self._connection.execute(
                _CLAIM_EXTRACTION_RUN,
                (owner_token, updated_ts, run_id),
            ).rowcount
            == 1
        )

    def claim_extraction_chunk(
        self,
        run_id: str,
        chunk_index: int,
        owner_token: str,
    ) -> bool:
        values = (
            owner_token,
            run_id,
            chunk_index,
            run_id,
            owner_token,
        )
        return (
            self._connection.execute(
                _CLAIM_EXTRACTION_CHUNK,
                values,
            ).rowcount
            == 1
        )

    def succeed_extraction_chunk(
        self,
        run_id: str,
        chunk_index: int,
        owner_token: str,
        stats_json: str,
    ) -> bool:
        values = (stats_json, run_id, chunk_index, owner_token)
        return (
            self._connection.execute(
                _SUCCEED_EXTRACTION_CHUNK,
                values,
            ).rowcount
            == 1
        )

    def interrupt_extraction_run(
        self,
        run_id: str,
        owner_token: str,
        reason: str,
        updated_ts: float,
    ) -> bool:
        values = (reason, updated_ts, run_id, owner_token)
        return (
            self._connection.execute(
                _INTERRUPT_EXTRACTION_RUN,
                values,
            ).rowcount
            == 1
        )

    def interrupt_running_chunks(
        self,
        run_id: str,
        owner_token: str,
    ) -> None:
        self._connection.execute(
            _INTERRUPT_RUNNING_CHUNKS,
            (run_id, owner_token),
        )

    def resume_extraction_run(
        self,
        run_id: str,
        updated_ts: float,
    ) -> bool:
        return (
            self._connection.execute(
                _RESUME_EXTRACTION_RUN,
                (updated_ts, run_id),
            ).rowcount
            == 1
        )

    def retryable_extraction_chunks(
        self,
        run_id: str,
    ) -> tuple[int, ...]:
        rows = self._connection.execute(
            _SELECT_RETRYABLE_CHUNKS,
            (run_id,),
        )
        return tuple(row["chunk_index"] for row in rows)

    def fail_extraction_chunk(
        self,
        run_id: str,
        chunk_index: int,
        owner_token: str,
        error_kind: str,
        error_identity: str,
    ) -> bool:
        values = (
            error_kind,
            error_identity,
            run_id,
            chunk_index,
            owner_token,
        )
        return (
            self._connection.execute(
                _FAIL_EXTRACTION_CHUNK,
                values,
            ).rowcount
            == 1
        )

    def mark_run_failed_from_chunk(
        self,
        run_id: str,
        error_kind: str,
        error_identity: str,
        updated_ts: float,
    ) -> None:
        values = (error_kind, error_identity, updated_ts, run_id)
        self._connection.execute(
            _MARK_RUN_FAILED_FROM_CHUNK,
            values,
        )

    def unfinished_extraction_chunks(self, run_id: str) -> int:
        return self._connection.execute(
            _COUNT_UNFINISHED_CHUNKS,
            (run_id,),
        ).fetchone()[0]

    def succeed_extraction_run(
        self,
        run_id: str,
        owner_token: str,
        updated_ts: float,
    ) -> bool:
        values = (updated_ts, run_id, owner_token)
        return (
            self._connection.execute(
                _SUCCEED_EXTRACTION_RUN,
                values,
            ).rowcount
            == 1
        )

    def fail_extraction_run(
        self,
        run_id: str,
        owner_token: str,
        error_kind: str,
        error_identity: str,
        updated_ts: float,
    ) -> bool:
        values = (
            error_kind,
            error_identity,
            updated_ts,
            run_id,
            owner_token,
        )
        return (
            self._connection.execute(
                _FAIL_EXTRACTION_RUN,
                values,
            ).rowcount
            == 1
        )
