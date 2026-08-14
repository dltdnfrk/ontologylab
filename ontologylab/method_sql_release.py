"""Explicit SQLite operations for compiler receipts, releases, and snapshots."""

from __future__ import annotations

import dataclasses
import sqlite3
from typing import Any, Protocol

from ontologylab import method_validation as mv
from ontologylab.method_release_store import (
    CompilationAttemptRecord,
    CompilationAttemptWrite,
    CompilationGateWrite,
    ReleaseWrite,
)
from ontologylab.method_snapshot_payload import SnapshotRows, snapshot_payload
from ontologylab.method_ir import canonical_json_bytes
import hashlib


class _Connection(Protocol):
    def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        /,
    ) -> sqlite3.Cursor:
        ...


_INSERT_COMPILATION_ATTEMPT = """
INSERT INTO method_compilation_attempt (
id, workspace_id, release_id, compiler_version, input_snapshot_hash,
passed, gate_receipt_json, compiler_receipt_json,
compiler_receipt_hash, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?)
"""
_INSERT_COMPILATION_GATE = """
INSERT INTO method_compilation_gate (
attempt_id, workspace_id, gate_id, passed, reasons_json,
compiler_receipt_hash, compiler_receipt_json) VALUES (?,?,?,?,?,?,?)
"""
_SELECT_COMPILATION_ATTEMPT = """
SELECT passed, release_id, workspace_id, compiler_version,
input_snapshot_hash, gate_receipt_json,
compiler_receipt_json, compiler_receipt_hash
FROM method_compilation_attempt WHERE id=?
"""
_SELECT_COMPILATION_GATES = """
SELECT attempt_id, workspace_id, gate_id, passed, reasons_json,
compiler_receipt_hash, compiler_receipt_json FROM method_compilation_gate
WHERE attempt_id=? ORDER BY gate_id
"""
_INSERT_RELEASE = """
INSERT INTO method_release (
id, workspace_id, method_id, version, canonical_json,
source_index_json, content_hash, compiler_version,
input_snapshot_hash, gate_receipt_json, review_receipt_json,
compiler_receipt_json, compiler_receipt_hash, attempt_id,
created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""
_SNAPSHOT_WORKSPACE = """
SELECT * FROM method_workspace WHERE id=?
"""
_SNAPSHOT_OCCURRENCES = """
SELECT * FROM statement_occurrence WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_FRAGMENTS = """
SELECT * FROM method_fragment WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_FRAGMENT_EVIDENCE = """
SELECT e.* FROM method_fragment_evidence e
JOIN method_fragment f ON f.id=e.fragment_id
WHERE f.workspace_id=? ORDER BY e.id
"""
_SNAPSHOT_LINKS = """
SELECT * FROM method_link WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_GAPS = """
SELECT * FROM method_gap WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_BRIDGES = """
SELECT * FROM bridge_proposal WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_BRIDGE_EVIDENCE = """
SELECT e.* FROM bridge_evidence e
JOIN bridge_proposal b ON b.id=e.bridge_id
WHERE b.workspace_id=? ORDER BY e.id
"""
_SNAPSHOT_REVIEW_EVENTS = """
SELECT * FROM method_review_event WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_COUNTER_SEARCHES = """
SELECT * FROM method_counter_evidence_search
WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_EXTRACTION_RUNS = """
SELECT * FROM method_extraction_runs WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_EXTRACTION_CHUNKS = """
SELECT c.* FROM method_extraction_chunks c
JOIN method_extraction_runs r ON r.id=c.run_id
WHERE r.workspace_id=? ORDER BY c.run_id,c.chunk_index
"""
_SNAPSHOT_POLICY_SNAPSHOTS = """
SELECT DISTINCT p.* FROM document_policy_snapshot p
LEFT JOIN method_extraction_runs r ON r.policy_snapshot_id=p.id
LEFT JOIN statement_occurrence o ON
o.document_id=p.document_id AND
o.document_content_hash=p.document_content_hash
WHERE r.workspace_id=? OR o.workspace_id=? ORDER BY p.id
"""
_SNAPSHOT_SOURCE_POLICIES = """
SELECT DISTINCT s.* FROM source_policy s
JOIN document_policy_snapshot p ON p.source_policy_id=s.id
LEFT JOIN method_extraction_runs r ON r.policy_snapshot_id=p.id
LEFT JOIN statement_occurrence o ON
o.document_id=p.document_id AND
o.document_content_hash=p.document_content_hash
WHERE r.workspace_id=? OR o.workspace_id=? ORDER BY s.id
"""
_SNAPSHOT_COMPILATION_ATTEMPTS = """
SELECT * FROM method_compilation_attempt WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_COMPILATION_GATES = """
SELECT * FROM method_compilation_gate WHERE workspace_id=?
ORDER BY attempt_id, gate_id
"""
_SNAPSHOT_RELEASES = """
SELECT * FROM method_release WHERE workspace_id=? ORDER BY id
"""
_SNAPSHOT_QUERIES = (
    _SNAPSHOT_OCCURRENCES,
    _SNAPSHOT_FRAGMENTS,
    _SNAPSHOT_FRAGMENT_EVIDENCE,
    _SNAPSHOT_LINKS,
    _SNAPSHOT_GAPS,
    _SNAPSHOT_BRIDGES,
    _SNAPSHOT_BRIDGE_EVIDENCE,
    _SNAPSHOT_REVIEW_EVENTS,
    _SNAPSHOT_COUNTER_SEARCHES,
    _SNAPSHOT_EXTRACTION_RUNS,
    _SNAPSHOT_EXTRACTION_CHUNKS,
    _SNAPSHOT_POLICY_SNAPSHOTS,
    _SNAPSHOT_SOURCE_POLICIES,
    _SNAPSHOT_COMPILATION_ATTEMPTS,
    _SNAPSHOT_COMPILATION_GATES,
    _SNAPSHOT_RELEASES,
)


class _MethodSqlRelease:
    """Typed compilation-attempt, release, and snapshot-row operations."""

    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    @staticmethod
    def load_snapshot_hash(
        owner: _Connection,
        workspace_id: str,
    ) -> str:
        rows = _MethodSqlRelease._load_snapshot(
            owner,
            workspace_id,
        )
        if rows is None:
            return ""
        canonical = canonical_json_bytes(
            snapshot_payload(
                rows,
                include_compilation_outputs=False,
            )
        )
        return "sha256:" + hashlib.sha256(canonical).hexdigest()

    def insert_compilation_attempt(
        self,
        row: CompilationAttemptWrite,
    ) -> None:
        try:
            self._connection.execute(
                _INSERT_COMPILATION_ATTEMPT,
                dataclasses.astuple(row),
            )
        except sqlite3.IntegrityError as exc:
            raise mv.MethodConflictError(
                "attempt identity already exists"
            ) from exc

    def insert_compilation_gate(
        self,
        row: CompilationGateWrite,
    ) -> None:
        try:
            self._connection.execute(
                _INSERT_COMPILATION_GATE,
                dataclasses.astuple(row),
            )
        except sqlite3.IntegrityError as exc:
            raise mv.MethodConflictError(
                "gate identity already exists"
            ) from exc

    def compilation_attempt(
        self,
        attempt_id: str,
    ) -> CompilationAttemptRecord | None:
        row = self._connection.execute(
            _SELECT_COMPILATION_ATTEMPT,
            (attempt_id,),
        ).fetchone()
        return None if row is None else CompilationAttemptRecord(*row)

    def compilation_gates(
        self,
        attempt_id: str,
    ) -> tuple[CompilationGateWrite, ...]:
        rows = self._connection.execute(
            _SELECT_COMPILATION_GATES,
            (attempt_id,),
        )
        return tuple(CompilationGateWrite(*row) for row in rows)

    def insert_release_row(self, row: ReleaseWrite) -> None:
        try:
            self._connection.execute(
                _INSERT_RELEASE,
                dataclasses.astuple(row),
            )
        except sqlite3.IntegrityError as exc:
            raise mv.MethodConflictError(
                "release identity already exists"
            ) from exc

    def load_snapshot(self, workspace_id: str) -> SnapshotRows | None:
        return self._load_snapshot(self._connection, workspace_id)

    @staticmethod
    def _load_snapshot(
        owner: _Connection,
        workspace_id: str,
    ) -> SnapshotRows | None:
        workspace = owner.execute(
            _SNAPSHOT_WORKSPACE,
            (workspace_id,),
        ).fetchone()
        if workspace is None:
            return None
        one = (workspace_id,)
        two = (workspace_id, workspace_id)
        parameters = (one,) * 11 + (two,) * 2 + (one,) * 3
        sections = tuple(
            tuple(
                map(
                    dict,
                    owner.execute(statement, values),
                )
            )
            for statement, values in zip(
                _SNAPSHOT_QUERIES,
                parameters,
                strict=True,
            )
        )
        return SnapshotRows(dict(workspace), *sections)
