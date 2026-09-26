"""Shared module state for the split KG store.

Constants, error types, DDL, and module-level helpers moved here verbatim
from ontologylab/kgstore.py so the mixin modules and the public
ontologylab.kgstore facade can share them without circular imports.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from ontologylab import kg_records
from ontologylab.storage_compatibility import bootstrap_metadata_sql

REVIEW_STATUSES = ("proposed", "verified", "rejected")

# match_score display precision, shared by every ranking surface (lexical,
# vector, hybrid, lookup) so all tiers round identically.
MATCH_SCORE_PRECISION = 4

# sqlite-vec KNN prefilter over-fetch: the shortlist must stay wide enough
# that post-KNN status/type filtering can't starve top_k — with these knobs
# the accelerated path returns results identical to brute force at local
# scale (asserted by the parity tests).
VEC_SHORTLIST_FACTOR = 8
VEC_SHORTLIST_MIN_MARGIN = 64


def _execute_sql_script(conn: sqlite3.Connection, script: str) -> None:
    """Execute a SQL script without sqlite3.executescript's implicit commit."""
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise sqlite3.OperationalError("incomplete schema statement")


class KGStoreError(Exception):
    """Generic store-level error (unknown item, bad filter, misuse)."""


class SchemaValidationError(KGStoreError):
    """Raised when a graph write does not conform to its row's ontology."""


@dataclass(frozen=True, slots=True)
class DocumentIdentityConflict(KGStoreError):
    """Same bytes under two different explicit DOIs: merge refused.

    Content-hash equality caches bytes but cannot establish work identity
    (Wave 2.1 D05). Until the v2 schema can hold both rows, the insert
    refuses with this typed conflict instead of silently returning the
    other DOI's document.
    """

    existing_doc_id: str
    existing_doi: str
    incoming_doi: str
    content_hash: str

    def __str__(self) -> str:
        return (
            f"document {self.existing_doc_id} already holds these bytes "
            f"(content_hash {self.content_hash}) under DOI "
            f"{self.existing_doi!r}; refusing to merge DOI "
            f"{self.incoming_doi!r}"
        )


@dataclass(frozen=True, slots=True)
class OntologyTermValidationError(KGStoreError):
    """A rejected ontology-term field at the store boundary."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"invalid ontology term {self.field}: {self.message}"


@dataclass(frozen=True, slots=True)
class XrefValidationError(KGStoreError):
    """A rejected external cross-reference field at the store boundary."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"invalid term xref {self.field}: {self.message}"


class EndpointNotVerified(KGStoreError):
    """Raised when approving an edge whose endpoints are not both verified."""


class InvalidTransition(KGStoreError):
    """Raised when a review action targets a row in the wrong state.

    approve/reject act on `proposed` rows only; undoing a decision goes
    through reopen(). Before this existed, _set_status was an unconditional
    UPDATE and a rejected row could be verified in place (or vice versa)
    with no trace of the reversal.
    """


class UnknownItem(KGStoreError):
    """Raised when an id matches neither a node nor an edge."""


class GroundingPreflightError(KGStoreError):
    """Ordinary review refused: a member Citation failed preflight."""


# One definition of "a mention in context": consumed by span_excerpt's
# defaults, entity_review_context, and critic.py's evidence prompts.
SPAN_EXCERPT_CONTEXT_CHARS = 160
SPAN_EXCERPT_MAX_CHARS = 600

# How much of a source document the review panel receives. Full text of an
# open-access paper runs to tens of thousands of characters; past this the
# panel is scrolling, not reading. Truncation is reported, never silent.
DOCUMENT_PANEL_MAX_CHARS = 40_000


def span_excerpt(
    raw_text: str,
    span: dict | None,
    *,
    context_chars: int = SPAN_EXCERPT_CONTEXT_CHARS,
    max_chars: int = SPAN_EXCERPT_MAX_CHARS,
) -> str:
    """The cited span ± context, with >>> <<< marking the span itself.

    Shared by critic evidence prompts and the entity-centric review view —
    one definition of "what a mention looks like in context".
    """
    if not span or not raw_text:
        return ""
    start = max(0, int(span.get("start", 0)))
    end = min(len(raw_text), int(span.get("end", 0)))
    if end <= start:
        return ""
    lo = max(0, start - context_chars)
    hi = min(len(raw_text), end + context_chars)
    excerpt = (
        raw_text[lo:start] + ">>>" + raw_text[start:end] + "<<<" + raw_text[end:hi]
    )
    return excerpt[:max_chars]


def normalize_name(name: str) -> str:
    """Normalization key for entity resolution.

    Casefolds and strips all non-alphanumeric characters, so surface variants
    like "RateLimiter" / "rate-limiter" / "Rate Limiter" share one key.
    (ARCHITECTURE.md §5.5 specifies casefold+whitespace-collapse; that formula
    does not unify its own §5.5 acceptance-test variants, so the key here is
    the stricter alphanumeric-only reduction. Still exact-match resolution —
    no fuzzy merging.)

    Exception: when the alphanumeric skeleton is at most three characters,
    punctuation IS the name — C, C++ and C# are different things, and a
    skeleton of "c" would auto-merge them without human review (measured in
    the 2026-08-01 algorithm audit: inserting C++ after C silently merged).
    Short names therefore key on casefold with whitespace removed but
    punctuation kept. Borderline short pairs that ARE the same thing
    (IL-6 vs IL6) now stay separate at insert; the merge scanner proposes
    them to a human, which is the safe direction for an auto-merge.
    """
    folded = name.casefold()
    alnum = re.sub(r"[^0-9a-z]+", "", folded)
    if len(alnum) <= 3:
        return re.sub(r"\s+", "", folded)
    return alnum


_SCHEMA = bootstrap_metadata_sql() + """
CREATE TABLE IF NOT EXISTS schema_version (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT NOT NULL,
    description   TEXT,
    created_ts    REAL NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS entity_type (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version_id INTEGER NOT NULL REFERENCES schema_version(id),
    name              TEXT NOT NULL,
    description       TEXT,
    attributes_json   TEXT NOT NULL DEFAULT '{}',
    -- is-a: the name of another entity_type in the same schema_version.
    -- NULL = top-level. Names, not ids, so a schema document stays
    -- self-contained and order-independent at install time.
    parent_name       TEXT,
    -- 0 = interpretation-overlay type (Question, Scenario, ...): written by
    -- people through insert_curated, never offered to or accepted from the
    -- extractor.
    extractable       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (schema_version_id, name)
);

CREATE TABLE IF NOT EXISTS relation_type (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version_id INTEGER NOT NULL REFERENCES schema_version(id),
    name              TEXT NOT NULL,
    description       TEXT,
    domain_type       TEXT NOT NULL,
    range_type        TEXT NOT NULL,
    directed          INTEGER NOT NULL DEFAULT 1,
    qualifiers_json   TEXT NOT NULL DEFAULT '{}',
    extractable       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (schema_version_id, name)
);

CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    source_kind   TEXT NOT NULL,
    source_uri    TEXT NOT NULL,
    title         TEXT,
    fetched_ts    REAL NOT NULL,
    content_hash  TEXT NOT NULL,
    raw_text_path TEXT NOT NULL,
    doi           TEXT,
    -- Which connector fetched this, and what kind of record it is. Neither
    -- is recoverable from source_uri: most rows resolve through doi.org,
    -- which names no source and implies no review.
    source        TEXT NOT NULL DEFAULT '',
    evidence_grade TEXT NOT NULL DEFAULT '',
    UNIQUE (content_hash)
);

CREATE TABLE IF NOT EXISTS nodes (
    id                TEXT PRIMARY KEY,
    schema_version_id INTEGER NOT NULL REFERENCES schema_version(id),
    entity_type       TEXT NOT NULL,
    name              TEXT NOT NULL,
    normalized_name   TEXT NOT NULL,
    aliases_json      TEXT NOT NULL DEFAULT '[]',
    properties_json   TEXT NOT NULL DEFAULT '{}',

    status            TEXT NOT NULL DEFAULT 'proposed'
                          CHECK (status IN ('proposed','verified','rejected')),
    confidence        REAL,
    source_doc_id     TEXT NOT NULL REFERENCES documents(id),
    source_span       TEXT,
    extractor_engine  TEXT NOT NULL,
    extractor_model   TEXT,
    prompt_version    TEXT,
    created_ts        REAL NOT NULL,
    verified_ts       REAL,
    verified_by       TEXT,
    review_note       TEXT,

    embedding         BLOB,
    embedding_model   TEXT,
    decode_params     TEXT,
    origin            TEXT NOT NULL DEFAULT 'extracted'
                          CHECK (origin IN ('extracted','inferred','curated'))
);
-- (decode_params on nodes/edges: the sampling parameters the producing run
-- selected, as canonical JSON with sorted keys; NULL when the engine has no
-- sampler control. Kept out of the CREATE body for the same reason as the
-- bitemporal note below: sqlite's ALTER TABLE DROP COLUMN chokes on
-- in-parens comments.)
CREATE INDEX IF NOT EXISTS idx_nodes_type_status ON nodes (entity_type, status);
CREATE INDEX IF NOT EXISTS idx_nodes_source_doc  ON nodes (source_doc_id);
CREATE INDEX IF NOT EXISTS idx_nodes_name        ON nodes (name);
-- Resolution key. Partial: a rejected row keeps its key but stops occupying
-- it, so a later re-extraction becomes a fresh proposed row (resolution only
-- ever matches proposed/verified rows).
CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_resolve
    ON nodes (schema_version_id, entity_type, normalized_name)
    WHERE status IN ('proposed','verified');

CREATE TABLE IF NOT EXISTS node_aliases (
    node_id          TEXT NOT NULL REFERENCES nodes(id),
    normalized_alias TEXT NOT NULL,
    surface          TEXT NOT NULL,
    PRIMARY KEY (node_id, normalized_alias)
);
CREATE INDEX IF NOT EXISTS idx_node_aliases_alias ON node_aliases (normalized_alias);

CREATE TABLE IF NOT EXISTS edges (
    id                TEXT PRIMARY KEY,
    schema_version_id INTEGER NOT NULL REFERENCES schema_version(id),
    relation_type     TEXT NOT NULL,
    src_node_id       TEXT NOT NULL REFERENCES nodes(id),
    dst_node_id       TEXT NOT NULL REFERENCES nodes(id),
    properties_json   TEXT NOT NULL DEFAULT '{}',
    qualifiers_json   TEXT NOT NULL DEFAULT '{}',

    status            TEXT NOT NULL DEFAULT 'proposed'
                          CHECK (status IN ('proposed','verified','rejected')),
    confidence        REAL,
    source_doc_id     TEXT NOT NULL REFERENCES documents(id),
    source_span       TEXT,
    extractor_engine  TEXT NOT NULL,
    extractor_model   TEXT,
    prompt_version    TEXT,
    created_ts        REAL NOT NULL,
    verified_ts       REAL,
    verified_by       TEXT,
    review_note       TEXT,
    valid_from            REAL,
    invalidated_ts        REAL,
    invalidated_by        TEXT,
    invalidation_reason   TEXT,
    decode_params         TEXT,
    origin                TEXT NOT NULL DEFAULT 'extracted'
                              CHECK (origin IN ('extracted','inferred','curated'))
);
-- (The last four edge columns are W13 bitemporal: event-time vs ingestion-
-- time, and invalidation INSTEAD of deletion — a contradicted fact stays
-- auditable but is never served as current truth. Kept out of the CREATE
-- body: sqlite's ALTER TABLE DROP COLUMN chokes on in-parens comments.)
CREATE INDEX IF NOT EXISTS idx_edges_src_status ON edges (src_node_id, status);
CREATE INDEX IF NOT EXISTS idx_edges_dst_status ON edges (dst_node_id, status);
CREATE INDEX IF NOT EXISTS idx_edges_type       ON edges (relation_type, status);
-- Dedup covers CURRENT rows only: an invalidated edge frees its triple key,
-- so a later re-assertion becomes a fresh proposed row coexisting with the
-- invalidated one (bitemporal history, no unique-key collision). The index
-- (idx_edges_dedup) is created by KGStore._migrate, not here: it keys on
-- qualifiers_json polarity, and a pre-qualifier store gains that column
-- only during migration.

-- Multi-source citations: every mention of a fact (including the first, and
-- every resolution-merge afterwards) appends one row here. The inline
-- source_doc_id/source_span on nodes/edges stays the first citation.
CREATE TABLE IF NOT EXISTS citations (
    kind             TEXT NOT NULL CHECK (kind IN ('node','edge')),
    item_id          TEXT NOT NULL,
    source_doc_id    TEXT NOT NULL REFERENCES documents(id),
    source_span      TEXT,
    created_ts       REAL NOT NULL,
    extractor_engine TEXT,
    extractor_model  TEXT,
    prompt_version   TEXT,
    decode_params    TEXT
);
CREATE INDEX IF NOT EXISTS idx_citations_item ON citations (kind, item_id);

-- W12 communities: computed ONCE at pack build time over the verified
-- subgraph (deterministic label propagation), then served read-only. The
-- working DB normally leaves these empty — they answer corpus-level
-- questions against an immutable pack, not a moving working set.
CREATE TABLE IF NOT EXISTS communities (
    id               TEXT PRIMARY KEY,
    member_count     INTEGER NOT NULL,
    top_members_json TEXT NOT NULL DEFAULT '[]',
    summary          TEXT,
    summary_method   TEXT NOT NULL DEFAULT 'extractive',
    created_ts       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS community_members (
    community_id TEXT NOT NULL REFERENCES communities(id),
    node_id      TEXT NOT NULL REFERENCES nodes(id),
    PRIMARY KEY (community_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_community_members_node
    ON community_members (node_id);

-- W8 critic triage: a second model pre-scores proposed extractions so the
-- review queue can be sorted and disagreements flagged. Scores are advisory
-- ONLY: nothing in this table feeds approve()/bulk_approve(), no score ever
-- flips a status, and the UI must never pre-select a decision from it
-- (anchoring-bias guard).
CREATE TABLE IF NOT EXISTS critic_reviews (
    kind           TEXT NOT NULL CHECK (kind IN ('node','edge')),
    item_id        TEXT NOT NULL,
    engine         TEXT NOT NULL,
    model          TEXT,
    prompt_version TEXT NOT NULL,
    score          REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
    rationale      TEXT,
    created_ts     REAL NOT NULL,
    PRIMARY KEY (kind, item_id, engine, prompt_version)
);
CREATE INDEX IF NOT EXISTS idx_critic_reviews_item ON critic_reviews (kind, item_id);

-- W7 merge review: fuzzy duplicate PAIRS proposed by the scanner, decided
-- only by a human. A candidate never mutates the graph by itself; the only
-- mutation path is an explicit merge_nodes()/dismiss call. Pairs are stored
-- canonically (node_a_id < node_b_id) so re-scans cannot duplicate a pair,
-- and a dismissed pair is never re-proposed.
CREATE TABLE IF NOT EXISTS merge_candidates (
    id           TEXT PRIMARY KEY,
    node_a_id    TEXT NOT NULL REFERENCES nodes(id),
    node_b_id    TEXT NOT NULL REFERENCES nodes(id),
    score        REAL NOT NULL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'proposed'
                     CHECK (status IN ('proposed','merged','dismissed','stale')),
    created_ts   REAL NOT NULL,
    decided_ts   REAL,
    decided_by   TEXT,
    decision_note TEXT,
    UNIQUE (node_a_id, node_b_id)
);
CREATE INDEX IF NOT EXISTS idx_merge_candidates_status ON merge_candidates (status);

-- Annotations: facts a curated resource holds about a node, proposed for
-- review. Deliberately NOT merged into `properties_json` on arrival.
--
-- The shape mirrors merge_candidates because the decision has the same
-- shape: something outside the graph proposes a link, and only a human
-- makes it real. What differs is what the reviewer is judging. An
-- extraction asks "is this claim true"; an annotation asks **"is this the
-- right record"** — UniProt does not invent a protein's function, but a
-- lookup can attach P38398's true facts to the wrong node. So the row
-- stores the resource's own name for the record next to the id, and the
-- URL, because those are the evidence: nothing else lets a person check
-- the match.
--
-- `facts_json` is the payload as fetched, not merged into the node. Merging
-- on arrival would make an unreviewed external claim indistinguishable from
-- an approved one the moment it landed.
CREATE TABLE IF NOT EXISTS annotations (
    id            TEXT PRIMARY KEY,
    node_id       TEXT NOT NULL REFERENCES nodes(id),
    resource      TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    record_url    TEXT NOT NULL,
    matched_name  TEXT NOT NULL,
    facts_json    TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'proposed'
                      CHECK (status IN ('proposed','verified','rejected')),
    created_ts    REAL NOT NULL,
    decided_ts    REAL,
    decided_by    TEXT,
    decision_note TEXT,
    -- One record per (node, resource). A second lookup refreshes rather
    -- than stacking duplicates a reviewer would have to reject one by one.
    UNIQUE (node_id, resource)
);
CREATE INDEX IF NOT EXISTS idx_annotations_status ON annotations (status);
CREATE INDEX IF NOT EXISTS idx_annotations_node ON annotations (node_id);

CREATE VIEW IF NOT EXISTS pending_review AS
SELECT 'node' AS kind, id, entity_type AS type_name, name AS label,
       confidence, source_doc_id, created_ts
FROM nodes WHERE status = 'proposed'
UNION ALL
SELECT 'edge' AS kind, id, relation_type AS type_name,
       src_node_id || ' -> ' || dst_node_id AS label,
       confidence, source_doc_id, created_ts
FROM edges WHERE status = 'proposed'
ORDER BY created_ts ASC;

-- Tier-1 lexical search index (external content on nodes). Kept in sync by
-- triggers on the working DB; rebuilt into a pack at build time.
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    name, aliases_json, properties_json,
    content='nodes', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS nodes_fts_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, name, aliases_json, properties_json)
    VALUES (new.rowid, new.name, new.aliases_json, new.properties_json);
END;
CREATE TRIGGER IF NOT EXISTS nodes_fts_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, aliases_json, properties_json)
    VALUES ('delete', old.rowid, old.name, old.aliases_json, old.properties_json);
END;
CREATE TRIGGER IF NOT EXISTS nodes_fts_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, aliases_json, properties_json)
    VALUES ('delete', old.rowid, old.name, old.aliases_json, old.properties_json);
    INSERT INTO nodes_fts(rowid, name, aliases_json, properties_json)
    VALUES (new.rowid, new.name, new.aliases_json, new.properties_json);
END;

-- Durable job history (GAP-O2). The job registry mirrors each job here on
-- creation and state change so a server restart no longer empties the jobs
-- screen; at startup the table becomes the history. project_id/session_id
-- are deliberately absent — they belong to the Project/Session migration and
-- would be speculative NULLs until then.
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'running',
    phase         TEXT NOT NULL DEFAULT '',
    engine        TEXT,
    model         TEXT,
    started_ts    REAL NOT NULL,
    finished_ts   REAL,
    error         TEXT,
    totals_json   TEXT NOT NULL DEFAULT '{}',
    ask_json      TEXT
);

-- Artifacts library (GAP-O3): every newly-created document and every built
-- pack registers a row here so the UI can list and consume outputs beyond
-- the pack. source_doc rows link to documents; pack_release rows name the
-- pack dir. Versions/dependencies are a later story and stay out of scope.
CREATE TABLE IF NOT EXISTS artifacts (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    source_doc_id TEXT,
    run_id        TEXT,
    filename      TEXT,
    created_ts    REAL NOT NULL
);

-- Advisory registry lookups (science-skills slice 2): what UniProt /
-- PubChem / ClinVar said about a proposed entity's name. Advisory only —
-- nothing here can change a row's status; the row exists so the human
-- reviewing the proposal sees the check happened. One row per
-- (node, registry); a re-run replaces the earlier answer.
CREATE TABLE IF NOT EXISTS entity_enrichments (
    node_id     TEXT NOT NULL,
    registry    TEXT NOT NULL,
    identifier  TEXT NOT NULL,
    label       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    fetched_ts  REAL NOT NULL,
    error       TEXT,
    PRIMARY KEY (node_id, registry)
);
"""

# Claim identity beyond the triple: a 'no_effect' finding is a different claim
# from a 'supports' one on the same (relation, src, dst), never a citation of
# it. Absent polarity maps to '' so every pre-polarity row keeps its identity.
EDGE_POLARITY_SQL = "COALESCE(json_extract(qualifiers_json, '$.polarity'), '')"


def edge_polarity(qualifiers: dict[str, Any] | None) -> str:
    value = (qualifiers or {}).get("polarity")
    return value if isinstance(value, str) else ""

_NODE_COLUMNS = (
    "id, schema_version_id, entity_type, name, normalized_name, aliases_json, "
    "properties_json, status, confidence, source_doc_id, source_span, "
    "extractor_engine, extractor_model, prompt_version, created_ts, "
    "verified_ts, verified_by, review_note, embedding, embedding_model, "
    "decode_params, origin"
)


def _status_clause(include_proposed: bool, alias: str = "") -> str:
    """WHERE fragment for the §9.1 safety invariant.

    verified always; proposed only on explicit request; rejected never.
    ``alias`` qualifies the column (e.g. "n" -> "n.status") — this is the
    load-bearing verified-only filter, so it is built parameterized here
    rather than patched up by string surgery at call sites.
    """
    column = f"{alias}.status" if alias else "status"
    if include_proposed:
        return f"{column} IN ('proposed','verified')"
    return f"{column} = 'verified'"


def _node_dict(row: sqlite3.Row) -> dict[str, Any]:
    return kg_records.node_dict(row)


def _edge_dict(row: sqlite3.Row) -> dict[str, Any]:
    return kg_records.edge_dict(row)

