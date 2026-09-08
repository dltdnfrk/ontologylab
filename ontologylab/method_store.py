"""SQLite persistence and transaction ownership for Method workspaces.

This module is the sole owner of Method SQL and direct SQLite connection
access. Pure helper services receive only explicit typed persistence
operations and never a connection or cursor.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from ontologylab import method_validation as mv
from ontologylab.method_commands import MethodCommands
from ontologylab.method_extraction_store import MethodExtractionStore
from ontologylab.method_release_store import MethodReleaseStore
from ontologylab.method_sql_core import _MethodSqlCore
from ontologylab.method_sql_extraction import _MethodSqlExtraction
from ontologylab.method_sql_release import _MethodSqlRelease
from ontologylab.method_snapshot import (
    MethodSnapshot as MethodSnapshot, MethodSnapshotStore,
    canonical_json_text_valid, compiler_receipt_field,
    compiler_receipt_from_json, compiler_receipt_gate_matches,
    compiler_receipt_gate_summary, compiler_receipt_json_valid,
    gate_reasons_json_valid, sha256_text)
from ontologylab.method_uow import UnitOfWorkState

MethodConflictError, MethodError = mv.MethodConflictError, mv.MethodError
MethodNotFoundError, MethodValidationError = mv.MethodNotFoundError,mv.MethodValidationError
MethodBusyError, MethodStateError = mv.MethodBusyError, mv.MethodStateError


_DDL = (
    """CREATE TABLE IF NOT EXISTS source_policy (
        id TEXT PRIMARY KEY, origin_pattern TEXT NOT NULL,
        policy_version TEXT NOT NULL, allowed_quote INTEGER NOT NULL
          CHECK (allowed_quote IN (0,1)),
        allowed_extract INTEGER NOT NULL CHECK (allowed_extract IN (0,1)),
        allowed_pack INTEGER NOT NULL CHECK (allowed_pack IN (0,1)),
        allowed_train INTEGER NOT NULL CHECK (allowed_train IN (0,1)),
        allowed_redistribute INTEGER NOT NULL
          CHECK (allowed_redistribute IN (0,1)),
        sensitivity TEXT NOT NULL, allowed_processors_json TEXT NOT NULL,
        allowed_regions_json TEXT NOT NULL, decision_note TEXT NOT NULL,
        decided_by TEXT NOT NULL, created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS document_policy_snapshot (
        id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
        document_content_hash TEXT NOT NULL,
        source_policy_id TEXT NOT NULL REFERENCES source_policy(id),
        resolution_status TEXT NOT NULL CHECK (resolution_status IN
          ('resolved','ambiguous','denied','discovery_only')),
        resolved_by TEXT NOT NULL, created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS method_workspace (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, objective TEXT NOT NULL,
        scope_json TEXT NOT NULL, method_schema_version TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft' CHECK
          (status IN ('draft','review_ready','compiled','superseded')),
        created_by TEXT NOT NULL, created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS statement_occurrence (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        document_id TEXT NOT NULL REFERENCES documents(id),
        document_content_hash TEXT NOT NULL, span_start INTEGER NOT NULL,
        span_end INTEGER NOT NULL, selected_text_hash TEXT NOT NULL,
        statement_text TEXT NOT NULL, polarity TEXT NOT NULL,
        modality TEXT NOT NULL, temporal_scope_json TEXT NOT NULL,
        applicability_scope_json TEXT NOT NULL,
        extractor_engine TEXT NOT NULL, extractor_model TEXT,
        prompt_version TEXT NOT NULL, decode_params_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'proposed'
          CHECK (status IN ('proposed','accepted','rejected','stale')),
        created_ts REAL NOT NULL, CHECK (span_end > span_start))""",
    """CREATE TABLE IF NOT EXISTS method_extraction_runs (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        document_id TEXT NOT NULL REFERENCES documents(id),
        document_content_hash TEXT NOT NULL,
        policy_snapshot_id TEXT NOT NULL REFERENCES document_policy_snapshot(id),
        extractor_engine TEXT NOT NULL, extractor_model TEXT,
        prompt_version TEXT NOT NULL, decode_params_json TEXT NOT NULL,
        chunk_plan_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
          ('pending','resumed','running','succeeded','failed','interrupted')),
        owner_token TEXT, error_kind TEXT, error_identity TEXT,
        created_ts REAL NOT NULL, updated_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS method_extraction_chunks (
        run_id TEXT NOT NULL REFERENCES method_extraction_runs(id),
        chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
        char_offset INTEGER NOT NULL CHECK (char_offset >= 0),
        content_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
          ('pending','running','succeeded','failed','interrupted')),
        attempts INTEGER NOT NULL DEFAULT 0, owner_token TEXT,
        stats_json TEXT, error_kind TEXT, error_identity TEXT,
        PRIMARY KEY (run_id, chunk_index))""",
    """CREATE TABLE IF NOT EXISTS method_fragment (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        kind TEXT NOT NULL, epistemic_class TEXT NOT NULL CHECK
          (epistemic_class IN ('source_supported','deterministic_derivation',
           'bridge_assumption','operator_constraint')),
        payload_json TEXT NOT NULL, generator TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'proposed'
          CHECK (status IN ('proposed','accepted','rejected','stale')),
        created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS method_fragment_evidence (
        id TEXT PRIMARY KEY,
        fragment_id TEXT NOT NULL REFERENCES method_fragment(id),
        field_path TEXT NOT NULL,
        occurrence_id TEXT NOT NULL REFERENCES statement_occurrence(id),
        evidence_role TEXT NOT NULL CHECK
          (evidence_role IN ('supports','contradicts','qualifies')),
        created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS method_link (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        src_fragment_id TEXT NOT NULL REFERENCES method_fragment(id),
        dst_fragment_id TEXT NOT NULL REFERENCES method_fragment(id),
        kind TEXT NOT NULL, provenance_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'proposed'
          CHECK (status IN ('proposed','accepted','rejected')),
        created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS method_gap (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        gap_class TEXT NOT NULL, target_fragment_id TEXT,
        field_path TEXT, detector_id TEXT NOT NULL,
        detector_version TEXT NOT NULL, input_snapshot_hash TEXT NOT NULL,
        detail_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN
          ('open','resolved_by_evidence','addressed_by_assumption','waived')),
        created_ts REAL NOT NULL, updated_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS bridge_proposal (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        gap_id TEXT NOT NULL REFERENCES method_gap(id),
        hypothesis TEXT NOT NULL, assumptions_json TEXT NOT NULL,
        scope TEXT NOT NULL, limits_json TEXT NOT NULL,
        falsifier TEXT NOT NULL, minimum_validation TEXT NOT NULL,
        decision_status TEXT NOT NULL DEFAULT 'pending' CHECK
          (decision_status IN
           ('pending','accepted_as_assumption','rejected','superseded')),
        epistemic_class TEXT NOT NULL DEFAULT 'bridge_assumption'
          CHECK (epistemic_class = 'bridge_assumption'),
        generator TEXT NOT NULL, model TEXT, prompt_version TEXT NOT NULL,
        created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS bridge_evidence (
        id TEXT PRIMARY KEY,
        bridge_id TEXT NOT NULL REFERENCES bridge_proposal(id),
        occurrence_id TEXT NOT NULL REFERENCES statement_occurrence(id),
        evidence_role TEXT NOT NULL CHECK
          (evidence_role IN ('supports','counters','bounds')),
        created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS method_review_event (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL,
        decision TEXT NOT NULL, reviewer TEXT NOT NULL, note TEXT NOT NULL,
        created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS method_counter_evidence_search (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        gap_id TEXT NOT NULL REFERENCES method_gap(id),
        bridge_id TEXT NOT NULL REFERENCES bridge_proposal(id),
        query TEXT NOT NULL, scope_json TEXT NOT NULL,
        corpus_snapshot_hash TEXT NOT NULL,
        result_occurrence_ids_json TEXT NOT NULL,
        searched_by TEXT NOT NULL, created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS method_compilation_attempt (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        release_id TEXT NOT NULL, compiler_version TEXT NOT NULL,
        input_snapshot_hash TEXT NOT NULL, passed INTEGER NOT NULL
          CHECK (passed IN (0,1)),
        gate_receipt_json TEXT NOT NULL,
        compiler_receipt_json TEXT NOT NULL,
        compiler_receipt_hash TEXT NOT NULL,
        created_ts REAL NOT NULL,
        CHECK (compiler_version='method-compiler-v1'),
        CHECK (sha256_text(compiler_receipt_json)=compiler_receipt_hash),
        CHECK (compiler_receipt_valid(compiler_receipt_json)=1),
        CHECK (receipt_field(compiler_receipt_json,'attempt_id')=id),
        CHECK (receipt_field(compiler_receipt_json,'workspace_id')=workspace_id),
        CHECK (receipt_field(compiler_receipt_json,'release_id')=release_id),
        CHECK (receipt_field(compiler_receipt_json,'compiler_version')
          =compiler_version),
        CHECK (receipt_field(compiler_receipt_json,'input_snapshot_hash')
          =input_snapshot_hash),
        CHECK (receipt_field(compiler_receipt_json,'passed')=passed),
        CHECK (snapshot_hash(workspace_id)=input_snapshot_hash),
        CHECK (receipt_gate_summary(compiler_receipt_json)=gate_receipt_json))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_method_attempt_workspace
       ON method_compilation_attempt(id, workspace_id)""",
    """CREATE TABLE IF NOT EXISTS method_compilation_gate (
        attempt_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        gate_id TEXT NOT NULL CHECK
          (gate_id IN ('G0','G1','G2','G3','G4','G5','G6','G7','G8')),
        passed INTEGER NOT NULL CHECK (passed IN (0,1)),
        reasons_json TEXT NOT NULL, compiler_receipt_hash TEXT NOT NULL,
        compiler_receipt_json TEXT NOT NULL,
        PRIMARY KEY (attempt_id, gate_id),
        FOREIGN KEY (attempt_id, workspace_id)
          REFERENCES method_compilation_attempt(id, workspace_id)
          DEFERRABLE INITIALLY DEFERRED,
        CHECK (gate_reasons_valid(gate_id,passed,reasons_json)=1),
        CHECK (sha256_text(compiler_receipt_json)=compiler_receipt_hash),
        CHECK (receipt_field(compiler_receipt_json,'attempt_id')=attempt_id),
        CHECK (receipt_field(compiler_receipt_json,'workspace_id')=workspace_id),
        CHECK (receipt_gate_matches(
          compiler_receipt_json,gate_id,passed,reasons_json)=1))""",
    """CREATE TABLE IF NOT EXISTS method_release (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES method_workspace(id),
        method_id TEXT NOT NULL, version INTEGER NOT NULL,
        canonical_json TEXT NOT NULL, source_index_json TEXT NOT NULL,
        content_hash TEXT NOT NULL, compiler_version TEXT NOT NULL,
        input_snapshot_hash TEXT NOT NULL,
        gate_receipt_json TEXT NOT NULL, review_receipt_json TEXT NOT NULL,
        compiler_receipt_json TEXT NOT NULL,
        compiler_receipt_hash TEXT NOT NULL,
        attempt_id TEXT NOT NULL REFERENCES method_compilation_attempt(id),
        created_ts REAL NOT NULL, UNIQUE (method_id, version),
        CHECK (compiler_version='method-compiler-v1'),
        CHECK (sha256_text(compiler_receipt_json)=compiler_receipt_hash),
        CHECK (compiler_receipt_valid(compiler_receipt_json)=1),
        CHECK (receipt_field(compiler_receipt_json,'release_version')=version),
        CHECK (receipt_field(compiler_receipt_json,'method_json_hash')
          =sha256_text(canonical_json)),
        CHECK (json_extract(canonical_json,'$.id')=method_id),
        CHECK (json_extract(canonical_json,'$.version')=version),
        CHECK (canonical_json_valid(canonical_json)=1),
        CHECK (canonical_json_valid(source_index_json)=1),
        CHECK (canonical_json_valid(review_receipt_json)=1),
        CHECK (release_binding_valid(
          canonical_json,source_index_json,content_hash,review_receipt_json,
          compiler_receipt_json)=1))""",
    """CREATE INDEX IF NOT EXISTS idx_method_gap_workspace
       ON method_gap(workspace_id, status, id)""",
    """CREATE INDEX IF NOT EXISTS idx_method_occurrence_workspace
       ON statement_occurrence(workspace_id, id)""",
    """CREATE INDEX IF NOT EXISTS idx_method_fragment_workspace
       ON method_fragment(workspace_id, id)""",
    """CREATE TRIGGER IF NOT EXISTS method_release_no_update
       BEFORE UPDATE ON method_release BEGIN
       SELECT RAISE(ABORT, 'method release is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_release_no_delete
       BEFORE DELETE ON method_release BEGIN
       SELECT RAISE(ABORT, 'method release is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_release_requires_passed_gates
       BEFORE INSERT ON method_release
       WHEN NOT EXISTS (
         SELECT 1 FROM method_compilation_attempt a
         WHERE a.id=NEW.attempt_id AND a.workspace_id=NEW.workspace_id
           AND a.release_id=NEW.id AND a.passed=1
           AND a.compiler_version=NEW.compiler_version
           AND a.input_snapshot_hash=NEW.input_snapshot_hash
           AND a.gate_receipt_json=NEW.gate_receipt_json
           AND a.compiler_receipt_json=NEW.compiler_receipt_json
           AND a.compiler_receipt_hash=NEW.compiler_receipt_hash
           AND (SELECT COUNT(*) FROM method_compilation_gate g
                WHERE g.attempt_id=a.id)=9
           AND NOT EXISTS (
             SELECT 1 FROM method_compilation_gate g
             WHERE g.attempt_id=a.id AND
               (g.workspace_id!=a.workspace_id OR g.passed!=1 OR
                g.compiler_receipt_hash!=a.compiler_receipt_hash)))
       BEGIN SELECT RAISE(ABORT,
         'method release requires passed hash-bound G0-G8 gates'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_attempt_semantic_check
       BEFORE INSERT ON method_compilation_attempt WHEN
          NEW.compiler_version!='method-compiler-v1'
         OR sha256_text(NEW.compiler_receipt_json)
            IS NOT NEW.compiler_receipt_hash
         OR compiler_receipt_valid(NEW.compiler_receipt_json) IS NOT 1
         OR receipt_field(NEW.compiler_receipt_json,'attempt_id') IS NOT NEW.id
         OR receipt_field(NEW.compiler_receipt_json,'workspace_id')
            IS NOT NEW.workspace_id
         OR receipt_field(NEW.compiler_receipt_json,'release_id')
            IS NOT NEW.release_id
         OR receipt_field(NEW.compiler_receipt_json,'compiler_version')
            IS NOT NEW.compiler_version
         OR receipt_field(NEW.compiler_receipt_json,'input_snapshot_hash')
            IS NOT NEW.input_snapshot_hash
         OR receipt_field(NEW.compiler_receipt_json,'passed') IS NOT NEW.passed
         OR receipt_gate_summary(NEW.compiler_receipt_json)
            IS NOT NEW.gate_receipt_json
         OR snapshot_hash(NEW.workspace_id) IS NOT NEW.input_snapshot_hash
       BEGIN SELECT RAISE(ABORT,
         'invalid canonical compilation attempt'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_gate_semantic_check
       BEFORE INSERT ON method_compilation_gate WHEN
          gate_reasons_valid(
             NEW.gate_id,NEW.passed,NEW.reasons_json) IS NOT 1
         OR sha256_text(NEW.compiler_receipt_json)
            IS NOT NEW.compiler_receipt_hash
         OR receipt_field(NEW.compiler_receipt_json,'attempt_id')
            IS NOT NEW.attempt_id
         OR receipt_field(NEW.compiler_receipt_json,'workspace_id')
            IS NOT NEW.workspace_id
         OR receipt_gate_matches(NEW.compiler_receipt_json,NEW.gate_id,
            NEW.passed,NEW.reasons_json) IS NOT 1
       BEGIN SELECT RAISE(ABORT,
         'invalid canonical compilation gate'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_release_semantic_check
       BEFORE INSERT ON method_release WHEN
          NEW.compiler_version!='method-compiler-v1'
         OR sha256_text(NEW.compiler_receipt_json)
            IS NOT NEW.compiler_receipt_hash
         OR compiler_receipt_valid(NEW.compiler_receipt_json) IS NOT 1
         OR receipt_field(NEW.compiler_receipt_json,'release_version')
            IS NOT NEW.version
         OR receipt_field(NEW.compiler_receipt_json,'method_json_hash')
            IS NOT sha256_text(NEW.canonical_json)
         OR canonical_json_valid(NEW.canonical_json) IS NOT 1
         OR canonical_json_valid(NEW.source_index_json) IS NOT 1
         OR canonical_json_valid(NEW.review_receipt_json) IS NOT 1
         OR json_extract(NEW.canonical_json,'$.id') IS NOT NEW.method_id
         OR json_extract(NEW.canonical_json,'$.version') IS NOT NEW.version
         OR release_binding_valid(NEW.canonical_json,NEW.source_index_json,
            NEW.content_hash,NEW.review_receipt_json,
            NEW.compiler_receipt_json) IS NOT 1
       BEGIN SELECT RAISE(ABORT,
         'invalid canonical method release'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_review_event_no_update
       BEFORE UPDATE ON method_review_event BEGIN
       SELECT RAISE(ABORT, 'method review event is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_review_event_no_delete
       BEFORE DELETE ON method_review_event BEGIN
       SELECT RAISE(ABORT, 'method review event is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS source_policy_no_update
       BEFORE UPDATE ON source_policy BEGIN
       SELECT RAISE(ABORT, 'source policy is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS source_policy_no_delete
       BEFORE DELETE ON source_policy BEGIN
       SELECT RAISE(ABORT, 'source policy is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS document_policy_snapshot_no_update
       BEFORE UPDATE ON document_policy_snapshot BEGIN
       SELECT RAISE(ABORT, 'document policy snapshot is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS document_policy_snapshot_no_delete
       BEFORE DELETE ON document_policy_snapshot BEGIN
       SELECT RAISE(ABORT, 'document policy snapshot is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_attempt_no_update
       BEFORE UPDATE ON method_compilation_attempt BEGIN
       SELECT RAISE(ABORT, 'method compilation attempt is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_attempt_no_delete
       BEFORE DELETE ON method_compilation_attempt BEGIN
       SELECT RAISE(ABORT, 'method compilation attempt is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_gate_no_update
       BEFORE UPDATE ON method_compilation_gate BEGIN
       SELECT RAISE(ABORT, 'method compilation gate is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_gate_no_delete
       BEFORE DELETE ON method_compilation_gate BEGIN
       SELECT RAISE(ABORT, 'method compilation gate is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_attempt_requires_gates
       AFTER INSERT ON method_compilation_attempt
       WHEN NEW.compiler_receipt_json IS NULL
         OR NEW.compiler_receipt_hash IS NULL
         OR (SELECT COUNT(*) FROM method_compilation_gate
             WHERE attempt_id=NEW.id) != 9
         OR EXISTS (
             SELECT 1 FROM method_compilation_gate
             WHERE attempt_id=NEW.id AND
               (workspace_id != NEW.workspace_id OR
                compiler_receipt_hash != NEW.compiler_receipt_hash))
         OR NEW.passed != (
             SELECT MIN(passed) FROM method_compilation_gate
             WHERE attempt_id=NEW.id)
       BEGIN SELECT RAISE(ABORT,
         'compilation attempt requires exact bound G0-G8 gates'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_counter_search_no_update
       BEFORE UPDATE ON method_counter_evidence_search BEGIN
       SELECT RAISE(ABORT, 'method counter search is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_counter_search_no_delete
       BEFORE DELETE ON method_counter_evidence_search BEGIN
       SELECT RAISE(ABORT, 'method counter search is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_release_attempt_binding
       BEFORE INSERT ON method_release BEGIN
       SELECT CASE WHEN NOT EXISTS (
         SELECT 1 FROM method_compilation_attempt
         WHERE id=NEW.attempt_id AND passed=1 AND release_id=NEW.id
           AND workspace_id=NEW.workspace_id
           AND compiler_version=NEW.compiler_version
           AND input_snapshot_hash=NEW.input_snapshot_hash
           AND gate_receipt_json=NEW.gate_receipt_json
       ) THEN RAISE(ABORT,
         'method release does not match compilation attempt') END; END""",
    """CREATE TRIGGER IF NOT EXISTS method_occurrence_proposal_pending
       BEFORE INSERT ON statement_occurrence WHEN NEW.status != 'proposed' BEGIN
       SELECT RAISE(ABORT, 'method proposal must start pending'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_fragment_proposal_pending
       BEFORE INSERT ON method_fragment WHEN NEW.status != 'proposed' BEGIN
       SELECT RAISE(ABORT, 'method proposal must start pending'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_link_proposal_pending
       BEFORE INSERT ON method_link WHEN NEW.status != 'proposed' BEGIN
       SELECT RAISE(ABORT, 'method proposal must start pending'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_bridge_proposal_pending
       BEFORE INSERT ON bridge_proposal WHEN NEW.decision_status != 'pending' BEGIN
       SELECT RAISE(ABORT, 'method proposal must start pending'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_occurrence_decision_receipt
       BEFORE UPDATE OF status ON statement_occurrence
       WHEN NEW.status != OLD.status BEGIN
       SELECT CASE WHEN NOT EXISTS (
         SELECT 1 FROM method_review_event
         WHERE workspace_id=NEW.workspace_id AND subject_kind='occurrence'
           AND subject_id=NEW.id AND decision=NEW.status
           AND reviewer != '' AND note != ''
       ) THEN RAISE(ABORT, 'method decision requires review event') END; END""",
    """CREATE TRIGGER IF NOT EXISTS method_fragment_decision_receipt
       BEFORE UPDATE OF status ON method_fragment
       WHEN NEW.status != OLD.status BEGIN
       SELECT CASE WHEN NOT EXISTS (
         SELECT 1 FROM method_review_event
         WHERE workspace_id=NEW.workspace_id AND subject_kind='fragment'
           AND subject_id=NEW.id AND decision=NEW.status
           AND reviewer != '' AND note != ''
       ) THEN RAISE(ABORT, 'method decision requires review event') END; END""",
    """CREATE TRIGGER IF NOT EXISTS method_link_decision_receipt
       BEFORE UPDATE OF status ON method_link
       WHEN NEW.status != OLD.status BEGIN
       SELECT CASE WHEN NOT EXISTS (
         SELECT 1 FROM method_review_event
         WHERE workspace_id=NEW.workspace_id AND subject_kind='link'
           AND subject_id=NEW.id AND decision=NEW.status
           AND reviewer != '' AND note != ''
       ) THEN RAISE(ABORT, 'method decision requires review event') END; END""",
    """CREATE TRIGGER IF NOT EXISTS method_gap_decision_receipt
       BEFORE UPDATE OF status ON method_gap
       WHEN NEW.status != OLD.status BEGIN
       SELECT CASE WHEN NOT EXISTS (
         SELECT 1 FROM method_review_event
         WHERE workspace_id=NEW.workspace_id AND subject_kind='gap'
           AND subject_id=NEW.id AND decision=NEW.status
           AND reviewer != '' AND note != ''
       ) THEN RAISE(ABORT, 'method decision requires review event') END; END""",
    """CREATE TRIGGER IF NOT EXISTS method_bridge_decision_receipt
       BEFORE UPDATE OF decision_status ON bridge_proposal
       WHEN NEW.decision_status != OLD.decision_status BEGIN
       SELECT CASE WHEN NOT EXISTS (
         SELECT 1 FROM method_review_event
         WHERE workspace_id=NEW.workspace_id AND subject_kind='bridge'
           AND subject_id=NEW.id AND decision=NEW.decision_status
           AND reviewer != '' AND note != ''
       ) THEN RAISE(ABORT, 'method decision requires review event') END;
       SELECT CASE WHEN NEW.decision_status='accepted_as_assumption'
         AND NOT EXISTS (
           SELECT 1 FROM method_counter_evidence_search
           WHERE workspace_id=NEW.workspace_id AND gap_id=NEW.gap_id
             AND bridge_id=NEW.id
         ) THEN RAISE(ABORT,
           'bridge acceptance requires a counter-evidence search') END; END""",
    """CREATE TRIGGER IF NOT EXISTS method_bridge_fragment_no_support
       BEFORE INSERT ON method_fragment_evidence
       WHEN NEW.evidence_role='supports' AND EXISTS (
         SELECT 1 FROM method_fragment
         WHERE id=NEW.fragment_id AND epistemic_class='bridge_assumption'
       ) BEGIN
       SELECT RAISE(ABORT,
         'bridge assumption cannot have supporting fragment evidence'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_fragment_epistemic_immutable
       BEFORE UPDATE OF epistemic_class ON method_fragment BEGIN
       SELECT RAISE(ABORT, 'method fragment epistemic class is immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_bridge_fragment_no_delete
       BEFORE DELETE ON method_fragment
       WHEN OLD.epistemic_class='bridge_assumption' BEGIN
       SELECT RAISE(ABORT, 'bridge fragment identity is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_gap_target_workspace_insert
       BEFORE INSERT ON method_gap WHEN NEW.target_fragment_id IS NOT NULL
       AND NOT EXISTS (
         SELECT 1 FROM method_fragment
         WHERE id=NEW.target_fragment_id AND workspace_id=NEW.workspace_id
       ) BEGIN
       SELECT RAISE(ABORT, 'gap target must exist in the same workspace'); END""",
    """CREATE TRIGGER IF NOT EXISTS method_gap_target_workspace_update
       BEFORE UPDATE OF target_fragment_id, workspace_id ON method_gap
       WHEN NEW.target_fragment_id IS NOT NULL AND NOT EXISTS (
         SELECT 1 FROM method_fragment
         WHERE id=NEW.target_fragment_id AND workspace_id=NEW.workspace_id
       ) BEGIN
       SELECT RAISE(ABORT, 'gap target must exist in the same workspace'); END""",
)

def _release_binding_valid(
    method_json: str,
    source_index_json: str,
    content_hash: str,
    review_receipt_json: str,
    receipt_json: str,
) -> int:
    receipt = compiler_receipt_from_json(receipt_json)
    if receipt is None:
        return 0
    try:
        method = json.loads(method_json)
        sources = json.loads(source_index_json)
        review = json.loads(review_receipt_json)
        if not isinstance(method, dict) or not isinstance(sources, list):
            return 0
        envelope = MethodReleaseStore.canonical_envelope(
            method,
            sources,
            receipt,
        )
        return int(
            receipt.method_json_hash == sha256_text(envelope.method_json)
            and receipt.source_index_hash
            == sha256_text(envelope.source_index)
            and receipt.reviewer_receipt_hash
            == sha256_text(mv.canonical_json(review))
            and envelope.content_hash == content_hash
        )
    except (TypeError, ValueError, mv.MethodError):
        return 0


def prepare_method_connection(conn: sqlite3.Connection) -> None:
    def snapshot_hash(workspace_id: str) -> str:
        return _MethodSqlRelease.load_snapshot_hash(
            conn,
            workspace_id,
        )

    functions = (
        ("sha256_text", 1, sha256_text),
        ("canonical_json_valid", 1, canonical_json_text_valid),
        ("gate_reasons_valid", 3, gate_reasons_json_valid),
        ("compiler_receipt_valid", 1, compiler_receipt_json_valid),
        ("receipt_field", 2, compiler_receipt_field),
        ("receipt_gate_summary", 1, compiler_receipt_gate_summary),
        ("receipt_gate_matches", 4, compiler_receipt_gate_matches),
        ("release_binding_valid", 5, _release_binding_valid),
        ("snapshot_hash", 1, snapshot_hash),
    )
    for name, arity, function in functions:
        conn.create_function(
            name,
            arity,
            function,
            deterministic=True,
        )


def ensure_method_schema(conn: sqlite3.Connection) -> None:
    """Add all Method objects transactionally without committing the caller."""
    prepare_method_connection(conn)
    started = not conn.in_transaction
    if started:
        conn.execute("BEGIN")
    conn.execute("SAVEPOINT method_schema")
    try:
        additions = (
            (
                "method_compilation_attempt",
                ("compiler_receipt_json", "compiler_receipt_hash"),
            ),
            (
                "method_compilation_gate",
                ("compiler_receipt_json",),
            ),
            (
                "method_release",
                ("compiler_receipt_json", "compiler_receipt_hash"),
            ),
        )
        for table, missing in additions:
            columns = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})")
            }
            for column in missing:
                if columns and column not in columns:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} TEXT"
                    )
        for statement in _DDL:
            conn.execute(statement)
    except Exception:
        conn.execute("ROLLBACK TO method_schema")
        conn.execute("RELEASE method_schema")
        if started:
            conn.rollback()
        raise
    conn.execute("RELEASE method_schema")


class MethodUnitOfWork:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._connection = conn
        self._state = UnitOfWorkState()

    @property
    def active(self) -> bool:
        return self._state.active

    def owns(self, candidate: object, /) -> bool:
        """Return whether this active UoW owns the private connection."""
        return self.active and self._connection is candidate

    def __enter__(self) -> MethodUnitOfWork:
        self._state.prepare_enter(
            ambient_transaction=self._connection.in_transaction
        )
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise mv.MethodBusyError(
                    "Method database is busy"
                ) from exc
            raise
        self._state.mark_active()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        self._state.require_active()
        try:
            if exc_type is None:
                try:
                    self._connection.commit()
                except BaseException:
                    self._connection.rollback()
                    raise
            else:
                self._connection.rollback()
        finally:
            self._state.mark_spent()


class MethodStore(mv.MethodValidationCommands, MethodCommands, MethodExtractionStore,
                  MethodReleaseStore, MethodSnapshotStore):
    def __init__(self, conn: sqlite3.Connection, uow: MethodUnitOfWork) -> None:
        if not uow.owns(conn):
            raise MethodStateError("MethodStore requires the active owning UoW")
        self.conn = conn
        self.uow = uow
        core = _MethodSqlCore(conn, uow)
        extraction = _MethodSqlExtraction(conn)
        release = _MethodSqlRelease(conn)
        self._validation_persistence = core
        self._command_persistence = core
        self._extraction_persistence = extraction
        self._release_persistence = release
        self._snapshot_persistence = release
