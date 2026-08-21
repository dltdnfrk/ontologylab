"""Additive Work/Representation/Observation authority schema (Wave 2.1 3A).

Executed from ``KGStore.open`` beside ``extraction_state._SCHEMA`` on
writable stores only; read-only stores are never migrated and degrade
instead. Everything here is additive: no existing table, index, or
constraint changes, and the v1 constraints (global ``UNIQUE(content_hash)``,
partial DOI index) keep write authority until the Step 9 constraint rebuild.
"""

from __future__ import annotations

V2_AUTHORITY_TABLES: frozenset[str] = frozenset({
    "works",
    "work_identifiers",
    "work_relations",
    "identifier_assertions",
    "work_redirect_decisions",
    "document_observations",
    "provenance_outbox",
    "v2_migration_ledger",
})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
    id          TEXT PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT 'active'
                    CHECK (state IN ('active','redirected')),
    created_ts  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS work_identifiers (
    id               TEXT PRIMARY KEY,
    work_id          TEXT NOT NULL REFERENCES works(id),
    scheme           TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('accepted','pending','retracted')),
    created_ts       REAL NOT NULL
);
-- Invariant (D05): at most one active ACCEPTED owner per identifier...
CREATE UNIQUE INDEX IF NOT EXISTS idx_work_identifiers_accepted_owner
    ON work_identifiers (scheme, normalized_value)
    WHERE status = 'accepted';
-- ...and at most one active accepted DOI per Work.
CREATE UNIQUE INDEX IF NOT EXISTS idx_work_identifiers_one_doi_per_work
    ON work_identifiers (work_id)
    WHERE status = 'accepted' AND scheme = 'doi';
CREATE INDEX IF NOT EXISTS idx_work_identifiers_work
    ON work_identifiers (work_id);

-- Provenance-carrying typed relations between Works (preprint/VoR etc.);
-- clusters are derived at read time, never stored (D06).
CREATE TABLE IF NOT EXISTS work_relations (
    id              TEXT PRIMARY KEY,
    source_work_id  TEXT NOT NULL REFERENCES works(id),
    target_work_id  TEXT NOT NULL REFERENCES works(id),
    relation_type   TEXT NOT NULL,
    provenance      TEXT NOT NULL DEFAULT '',
    created_ts      REAL NOT NULL
);

-- One Observation per acquisition operation; retries of that operation are
-- idempotent on idempotency_key (D08). representation_id is nullable for
-- metadata-only observations.
CREATE TABLE IF NOT EXISTS document_observations (
    id                TEXT PRIMARY KEY,
    representation_id TEXT REFERENCES documents(id),
    idempotency_key   TEXT NOT NULL UNIQUE,
    source            TEXT NOT NULL DEFAULT '',
    evidence_grade    TEXT NOT NULL DEFAULT '',
    -- Provider-asserted stage and representation kind feed the pure
    -- preferred-representation-v1 projection (D07); they are Observation
    -- metadata, never a stored preference.
    stage             TEXT NOT NULL DEFAULT 'unknown',
    content_kind      TEXT NOT NULL DEFAULT 'metadata_only',
    created_ts        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_document_observations_representation
    ON document_observations (representation_id);

-- Append-only: links one identifier to the Observation that attested it,
-- inserted in the same transaction as the Observation (invariant 3).
CREATE TABLE IF NOT EXISTS identifier_assertions (
    identifier_id  TEXT NOT NULL REFERENCES work_identifiers(id),
    observation_id TEXT NOT NULL REFERENCES document_observations(id),
    created_ts     REAL NOT NULL,
    PRIMARY KEY (identifier_id, observation_id)
);

-- Append-only human decisions; compensation supersedes a prior decision,
-- it never rewrites rows or FKs (D09).
CREATE TABLE IF NOT EXISTS work_redirect_decisions (
    id             TEXT PRIMARY KEY,
    source_work_id TEXT NOT NULL REFERENCES works(id),
    target_work_id TEXT NOT NULL REFERENCES works(id),
    action         TEXT NOT NULL CHECK (action IN ('merge','compensate')),
    supersedes_id  TEXT REFERENCES work_redirect_decisions(id),
    actor          TEXT NOT NULL,
    reason         TEXT NOT NULL,
    created_ts     REAL NOT NULL
);

-- The SQLite outbox is provenance truth; JSONL is a deterministic
-- projection keyed by event_id (D12).
CREATE TABLE IF NOT EXISTS provenance_outbox (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL UNIQUE,
    step         TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_ts   REAL NOT NULL,
    mirrored_ts  REAL
);

-- Append-only enforcement for the audit trail (D09 / invariant 3).
CREATE TRIGGER IF NOT EXISTS trg_identifier_assertions_no_update
BEFORE UPDATE ON identifier_assertions
BEGIN
    SELECT RAISE(ABORT, 'identifier_assertions is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_identifier_assertions_no_delete
BEFORE DELETE ON identifier_assertions
BEGIN
    SELECT RAISE(ABORT, 'identifier_assertions is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_work_redirect_decisions_no_update
BEFORE UPDATE ON work_redirect_decisions
BEGIN
    SELECT RAISE(ABORT, 'work_redirect_decisions is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_work_redirect_decisions_no_delete
BEFORE DELETE ON work_redirect_decisions
BEGIN
    SELECT RAISE(ABORT, 'work_redirect_decisions is append-only');
END;

-- Phase/cursor/generation ledger consumed by the Step 5 migration core.
CREATE TABLE IF NOT EXISTS v2_migration_ledger (
    seq                INTEGER PRIMARY KEY AUTOINCREMENT,
    phase              TEXT NOT NULL,
    cursor             TEXT,
    generation         INTEGER NOT NULL DEFAULT 0,
    source_fingerprint TEXT,
    created_ts         REAL NOT NULL
);
"""
