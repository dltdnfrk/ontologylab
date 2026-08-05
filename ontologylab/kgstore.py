"""sqlite knowledge-graph store for ontologylab (successor to drylab's memory.py).

One sqlite file holds the ontology schema tables, collected documents, and
the graph itself (``nodes`` / ``edges``), each row carrying a status in
``proposed | verified | rejected``. The load-bearing invariant, carried over
from drylab's ``Finding.verified``: **nothing is ever verified except by an
explicit human approval call.** The write API is split so the extraction path
(``insert_proposed``) is physically incapable of writing ``verified``; only
``approve()`` may set it.

The same ``KGStore`` class serves the mutable working DB (read-write, WAL)
and immutable knowledge packs. Read-only callers explicitly distinguish an
immutable finalized database from a mutable WAL-backed live store so live
reads participate in SQLite's normal WAL snapshot semantics.

Entity resolution (ARCHITECTURE.md §5.5) runs inside ``insert_proposed``:
nodes are deduped by ``(schema_version_id, entity_type, normalized_name)``
across proposed+verified rows (plus an alias lookup), and every relation
endpoint is bound to the resolved node id — so the KG is one connected graph,
not per-chunk stars.

Search is tier-1 FTS5 **lexical** search (not vector/semantic); the raw BM25
rank is normalized to a 0..1 higher-is-better ``match_score`` (§5.4).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Optional

from ontologylab import evidence
from ontologylab import ontology_schema as default_schema
from ontologylab.paths import DEFAULT_ACTOR
from ontologylab.models import Document, ProposedEntity, ProposedRelation

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


class KGStoreError(Exception):
    """Generic store-level error (unknown item, bad filter, misuse)."""


class EndpointNotVerified(KGStoreError):
    """Raised when approving an edge whose endpoints are not both verified."""


class UnknownItem(KGStoreError):
    """Raised when an id matches neither a node nor an edge."""


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


_SCHEMA = """
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
    decode_params     TEXT
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
    decode_params         TEXT
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
-- invalidated one (bitemporal history, no unique-key collision).
CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_dedup
    ON edges (schema_version_id, relation_type, src_node_id, dst_node_id)
    WHERE status IN ('proposed','verified') AND invalidated_ts IS NULL;

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
"""

_NODE_COLUMNS = (
    "id, schema_version_id, entity_type, name, normalized_name, aliases_json, "
    "properties_json, status, confidence, source_doc_id, source_span, "
    "extractor_engine, extractor_model, prompt_version, created_ts, "
    "verified_ts, verified_by, review_note, embedding, embedding_model, "
    "decode_params"
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
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "name": row["name"],
        "aliases": json.loads(row["aliases_json"]),
        "properties": json.loads(row["properties_json"]),
        "status": row["status"],
        "confidence": row["confidence"],
        "source_doc_id": row["source_doc_id"],
        "source_span": json.loads(row["source_span"]) if row["source_span"] else None,
    }


def _edge_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {
        "id": row["id"],
        "relation_type": row["relation_type"],
        "source_id": row["src_node_id"],
        "target_id": row["dst_node_id"],
        "properties": json.loads(row["properties_json"]),
        "status": row["status"],
        "confidence": row["confidence"],
        "source_doc_id": row["source_doc_id"],
        # W13 bitemporal fields; absent on pre-W13 read-only packs.
        "valid_from": row["valid_from"] if "valid_from" in keys else None,
        "invalidated_ts": (
            row["invalidated_ts"] if "invalidated_ts" in keys else None
        ),
    }


class KGStore:
    """Owns one sqlite connection to a working KG or an immutable pack.

    Construct via :meth:`KGStore.open` — a real rewrite of drylab's
    ``memory.open()``: takes an explicit **file** path (not a directory) and
    a ``read_only`` flag. Read-write mode enables WAL; read-only mode executes
    no DDL and defaults to immutable pack semantics. Mutable live stores pass
    ``immutable=False`` to retain normal read-only WAL behavior.
    """

    def __init__(self, conn: sqlite3.Connection, db_path: Path, read_only: bool) -> None:
        self.conn = conn
        self.db_path = db_path
        self.read_only = read_only
        self._edges_bitemporal_cache: bool | None = None
        self._vec_loaded: bool | None = None

    def _vec_available(self) -> bool:
        """Whether sqlite-vec is loaded on this connection (probed once).

        Opt-in acceleration: absent extension -> brute-force cosine, same
        results. Loading is attempted lazily so a store never pays for it
        unless a vector query actually needs it.
        """
        if self._vec_loaded is None:
            from ontologylab.embeddings import load_sqlite_vec

            self._vec_loaded = load_sqlite_vec(self.conn)
        return self._vec_loaded

    def _edges_bitemporal(self) -> bool:
        """Whether this store's edges carry the W13 bitemporal columns.

        Writable stores always do (migrated on open); read-only packs built
        before W13 do not, and their edge queries must not reference them.
        """
        if self._edges_bitemporal_cache is None:
            columns = {
                row["name"]
                for row in self.conn.execute("PRAGMA table_info(edges)")
            }
            self._edges_bitemporal_cache = "invalidated_ts" in columns
        return self._edges_bitemporal_cache

    def _edge_current_sql(self, alias: str = "") -> str:
        """WHERE fragment excluding invalidated edges from current truth."""
        if not self._edges_bitemporal():
            return "1=1"
        column = f"{alias}.invalidated_ts" if alias else "invalidated_ts"
        return f"{column} IS NULL"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        file_path: str | Path,
        *,
        read_only: bool = False,
        immutable: bool = True,
    ) -> "KGStore":
        """Open the KG sqlite file.

        ``immutable=True`` is for finalized packs. A mutable live database must
        use ``read_only=True, immutable=False`` so committed WAL frames remain
        visible and SQLite can maintain a normal read snapshot.
        """
        db_path = Path(file_path)
        if read_only:
            uri = f"{db_path.resolve().as_uri()}?mode=ro"
            if immutable:
                uri += "&immutable=1"
            conn = sqlite3.connect(uri, uri=True, timeout=30.0)
            conn.row_factory = sqlite3.Row
            return cls(conn, db_path, read_only=True)

        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        # The KG holds a user's private research; default umask leaves it
        # group/world-readable on a multi-user host. Owner-only, and the
        # WAL sidecars sqlite creates get the same treatment.
        for sidecar in (db_path, *db_path.parent.glob(db_path.name + "-*")):
            if sidecar.is_file():
                sidecar.chmod(0o600)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.executescript(_SCHEMA)
        cls._migrate(conn)
        from ontologylab.extraction_state import ensure_schema

        ensure_schema(conn)
        conn.commit()
        store = cls(conn, db_path, read_only=False)
        store._seed_default_schema()
        return store

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Bring a pre-existing writable DB up to the current schema.

        ``executescript(_SCHEMA)`` only creates MISSING tables/indexes; it
        never adds columns to an existing table or changes an existing
        index's predicate — both are handled here. Read-only packs are
        never migrated: query paths degrade instead (see _edge_current_sql
        / _table_exists).
        """
        # Documents predate `source` / `evidence_grade`; an existing store
        # has rows without them. They read back as "" and normalize to
        # `unknown`, which is the honest answer for a document collected
        # before anyone recorded where it came from.
        document_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(documents)")
        }
        for column in ("source", "evidence_grade"):
            if column not in document_columns:
                conn.execute(
                    f"ALTER TABLE documents ADD COLUMN {column} "
                    f"TEXT NOT NULL DEFAULT ''"
                )

        edge_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(edges)")
        }
        for column, ddl in (
            ("valid_from", "ALTER TABLE edges ADD COLUMN valid_from REAL"),
            ("invalidated_ts", "ALTER TABLE edges ADD COLUMN invalidated_ts REAL"),
            ("invalidated_by", "ALTER TABLE edges ADD COLUMN invalidated_by TEXT"),
            (
                "invalidation_reason",
                "ALTER TABLE edges ADD COLUMN invalidation_reason TEXT",
            ),
            (
                "decode_params",
                "ALTER TABLE edges ADD COLUMN decode_params TEXT",
            ),
        ):
            if column not in edge_columns:
                conn.execute(ddl)
        node_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(nodes)")
        }
        if "decode_params" not in node_columns:
            conn.execute("ALTER TABLE nodes ADD COLUMN decode_params TEXT")
        citation_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(citations)")
        }
        for column in (
            "extractor_engine",
            "extractor_model",
            "prompt_version",
            "decode_params",
        ):
            if column not in citation_columns:
                conn.execute(f"ALTER TABLE citations ADD COLUMN {column} TEXT")
        if "valid_from" not in edge_columns:
            # Backfill: assertion time defaults to ingestion time.
            conn.execute(
                "UPDATE edges SET valid_from = created_ts WHERE valid_from IS NULL"
            )
        # The dedup index predicate gained "invalidated_ts IS NULL" in W13;
        # IF NOT EXISTS keeps an old-predicate index alive, so rebuild it.
        index_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_edges_dedup'"
        ).fetchone()
        if index_sql_row and "invalidated_ts" not in (index_sql_row["sql"] or ""):
            conn.execute("DROP INDEX idx_edges_dedup")
            conn.execute(
                "CREATE UNIQUE INDEX idx_edges_dedup "
                "ON edges (schema_version_id, relation_type, src_node_id, "
                "dst_node_id) "
                "WHERE status IN ('proposed','verified') "
                "AND invalidated_ts IS NULL"
            )

        # normalize_name gained the short-symbol carve-out (C vs C++ must
        # not share a key). Rows keyed under the old formula keep the old
        # key until rewritten; a lookup computing the new key would miss
        # them and re-insert duplicates. Rekeying is idempotent and
        # one-directional (new keys are never broader than old ones).
        stale_keys = conn.execute(
            "SELECT id, name, normalized_name FROM nodes"
        ).fetchall()
        for row in stale_keys:
            key = normalize_name(row["name"])
            if row["normalized_name"] != key:
                conn.execute(
                    "UPDATE nodes SET normalized_name = ? WHERE id = ?",
                    (key, row["id"]),
                )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "KGStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Ontology schema
    # ------------------------------------------------------------------

    def _seed_default_schema(self) -> None:
        cur = self.conn.execute("SELECT COUNT(*) AS n FROM schema_version")
        if cur.fetchone()["n"]:
            return
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO schema_version (label, description, created_ts, is_active) "
            "VALUES (?, ?, ?, 1)",
            (
                default_schema.DEFAULT_SCHEMA_LABEL,
                default_schema.DEFAULT_SCHEMA_DESCRIPTION,
                now,
            ),
        )
        sv_id = cur.lastrowid
        for name, (desc, attrs) in default_schema.DEFAULT_ENTITY_TYPES.items():
            self.conn.execute(
                "INSERT INTO entity_type "
                "(schema_version_id, name, description, attributes_json) "
                "VALUES (?, ?, ?, ?)",
                (sv_id, name, desc, json.dumps(attrs)),
            )
        for name, (desc, domain, range_, directed) in (
            default_schema.DEFAULT_RELATION_TYPES.items()
        ):
            self.conn.execute(
                "INSERT INTO relation_type "
                "(schema_version_id, name, description, domain_type, range_type, directed) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sv_id, name, desc, domain, range_, 1 if directed else 0),
            )
        self.conn.commit()

    def active_schema_version(self) -> sqlite3.Row:
        cur = self.conn.execute(
            "SELECT * FROM schema_version WHERE is_active = 1 "
            "ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            raise KGStoreError("no active schema_version row")
        return row

    def install_schema(
        self,
        *,
        label: str,
        description: str,
        entity_types: list[dict[str, Any]],
        relation_types: list[dict[str, Any]],
    ) -> int:
        """Add an ontology and make it the active one. Returns its id.

        The whole design already assumed this would exist — `nodes`,
        `edges` and the type tables all carry `schema_version_id` — but
        nothing could write one, so every install ran on
        `software-docs-v1`: a "neutral default ontology for software /
        technical documentation", used here on p53 papers. Measured on one
        abstract, that mismatch produced five relations, all of them
        `related_to`, and 24 rejected proposals the schema had no shape
        for; the same abstract under a biomedical ontology produced twelve
        relations across five types and nothing rejected.

        Switching is additive. A new row is inserted and the previous one
        deactivated, never edited or deleted, so proposals extracted under
        the old ontology keep pointing at the ontology they were judged
        against — the alternative would silently re-type a review queue
        somebody is halfway through.
        """
        if not entity_types:
            raise KGStoreError("a schema needs at least one entity type")
        if not label.strip():
            raise KGStoreError("a schema needs a label")

        names = {e["name"] for e in entity_types}
        for relation in relation_types:
            for side in ("domain_type", "range_type"):
                declared = relation.get(side, "*")
                # `*` means any. Anything else has to be a type this same
                # schema defines, or the extractor is handed a rule that
                # can never be satisfied and every use is rejected.
                if declared != "*" and declared not in names:
                    raise KGStoreError(
                        f"relation {relation['name']!r} has {side}="
                        f"{declared!r}, which is not an entity type in this "
                        f"schema ({', '.join(sorted(names))})"
                    )

        now = time.time()
        with self.conn:
            self.conn.execute("UPDATE schema_version SET is_active = 0")
            cur = self.conn.execute(
                "INSERT INTO schema_version "
                "(label, description, created_ts, is_active) VALUES (?,?,?,1)",
                (label.strip(), description, now),
            )
            sv_id = int(cur.lastrowid)
            for entity in entity_types:
                self.conn.execute(
                    "INSERT INTO entity_type (schema_version_id, name, "
                    "description, attributes_json) VALUES (?,?,?,?)",
                    (sv_id, entity["name"], entity.get("description", ""),
                     json.dumps(entity.get("attributes", {}))),
                )
            for relation in relation_types:
                self.conn.execute(
                    "INSERT INTO relation_type (schema_version_id, name, "
                    "description, domain_type, range_type, directed) "
                    "VALUES (?,?,?,?,?,?)",
                    (sv_id, relation["name"], relation.get("description", ""),
                     relation.get("domain_type", "*"),
                     relation.get("range_type", "*"),
                     1 if relation.get("directed", True) else 0),
                )
        return sv_id

    def list_schemas(self) -> list[dict[str, Any]]:
        """Every ontology this store has held, newest first."""
        return [
            {
                "id": row["id"],
                "label": row["label"],
                "description": row["description"],
                "created_ts": row["created_ts"],
                "active": bool(row["is_active"]),
                # How much was judged under it. A schema with proposals
                # behind it is one a reviewer's decisions depend on.
                "items": self.conn.execute(
                    "SELECT (SELECT COUNT(*) FROM nodes WHERE "
                    "schema_version_id = ?) + (SELECT COUNT(*) FROM edges "
                    "WHERE schema_version_id = ?) AS n",
                    (row["id"], row["id"]),
                ).fetchone()["n"],
            }
            for row in self.conn.execute(
                "SELECT * FROM schema_version ORDER BY id DESC"
            )
        ]

    def activate_schema(self, schema_id: int) -> None:
        """Switch back to an ontology this store already has."""
        row = self.conn.execute(
            "SELECT id FROM schema_version WHERE id = ?", (schema_id,)
        ).fetchone()
        if row is None:
            raise UnknownItem(f"unknown schema id {schema_id}")
        with self.conn:
            self.conn.execute("UPDATE schema_version SET is_active = 0")
            self.conn.execute(
                "UPDATE schema_version SET is_active = 1 WHERE id = ?",
                (schema_id,),
            )

    def get_schema(self) -> dict[str, Any]:
        """Return the active ontology (entity + relation types) as plain data."""
        sv = self.active_schema_version()
        entity_types = [
            {
                "name": r["name"],
                "description": r["description"],
                "attributes": json.loads(r["attributes_json"]),
            }
            for r in self.conn.execute(
                "SELECT * FROM entity_type WHERE schema_version_id = ? ORDER BY name",
                (sv["id"],),
            )
        ]
        relation_types = [
            {
                "name": r["name"],
                "description": r["description"],
                "domain_type": r["domain_type"],
                "range_type": r["range_type"],
                "directed": bool(r["directed"]),
            }
            for r in self.conn.execute(
                "SELECT * FROM relation_type WHERE schema_version_id = ? ORDER BY name",
                (sv["id"],),
            )
        ]
        return {
            "schema_version_id": sv["id"],
            "schema_label": sv["label"],
            "entity_types": entity_types,
            "relation_types": relation_types,
        }

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def insert_document(
        self,
        *,
        source_kind: str,
        source_uri: str,
        title: str | None,
        raw_text: str,
        content_hash: str,
        source: str = "",
        evidence_grade: str = "",
    ) -> tuple[Document, bool]:
        """Insert a document (deduped by content hash); write raw text to disk.

        Returns (document, created) — ``created`` False means an identical
        document already existed and was returned instead.

        The SELECT below is a fast path, not the guarantee. Two collects that
        overlap — a server job and a CLI run, or a fan-out that produced the
        same paper twice — can both miss it and both reach the INSERT, where
        ``UNIQUE (content_hash)`` refuses the second. That refusal carries
        exactly the fact the SELECT was looking for, so it is recovered from
        rather than raised: discarding a whole run's other documents over a
        duplicate the caller already has would be data loss, not safety.
        """
        self._assert_writable()
        cur = self.conn.execute(
            "SELECT * FROM documents WHERE content_hash = ?", (content_hash,)
        )
        existing = cur.fetchone()
        if existing is not None:
            return self._row_to_document(existing), False

        doc_id = uuid.uuid4().hex
        rel_path = f"documents/{doc_id}/raw.txt"
        abs_path = self.db_path.parent / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(raw_text, encoding="utf-8")

        doc = Document(
            id=doc_id,
            source_kind=source_kind,
            source_uri=source_uri,
            title=title,
            fetched_ts=time.time(),
            content_hash=content_hash,
            raw_text_path=rel_path,
            source=source,
            evidence_grade=evidence.normalize(evidence_grade),
        )
        try:
            self.conn.execute(
                "INSERT INTO documents "
                "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
                "raw_text_path, source, evidence_grade) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc.id,
                    doc.source_kind,
                    doc.source_uri,
                    doc.title,
                    doc.fetched_ts,
                    doc.content_hash,
                    doc.raw_text_path,
                    doc.source,
                    doc.evidence_grade,
                ),
            )
        except sqlite3.IntegrityError:
            # Another writer won the race on UNIQUE (content_hash). Return
            # their row: the caller asked for this document to exist, and it
            # does. The raw text just written is byte-identical (same hash),
            # so the orphan file is inert and the existing row keeps pointing
            # at its own copy.
            self.conn.rollback()
            row = self.conn.execute(
                "SELECT * FROM documents WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if row is None:
                # The constraint fired for something other than the hash.
                raise
            return self._row_to_document(row), False
        self.conn.commit()
        return doc, True

    @staticmethod
    def _row_to_document(row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            source_kind=row["source_kind"],
            source_uri=row["source_uri"],
            title=row["title"],
            fetched_ts=row["fetched_ts"],
            content_hash=row["content_hash"],
            raw_text_path=row["raw_text_path"],
            # `.keys()` rather than indexing: a pack built before these
            # columns existed is opened read-only and never migrated, so the
            # row genuinely does not have them.
            source=row["source"] if "source" in row.keys() else "",
            evidence_grade=evidence.normalize(
                row["evidence_grade"] if "evidence_grade" in row.keys() else ""
            ),
        )

    def get_document(self, doc_id: str) -> Document:
        cur = self.conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cur.fetchone()
        if row is None:
            raise UnknownItem(f"unknown document id {doc_id!r}")
        return self._row_to_document(row)

    def list_documents(self) -> list[Document]:
        cur = self.conn.execute("SELECT * FROM documents ORDER BY fetched_ts ASC")
        return [self._row_to_document(r) for r in cur.fetchall()]

    def document_raw_text(self, doc_id: str) -> str:
        doc = self.get_document(doc_id)
        return (self.db_path.parent / doc.raw_text_path).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Proposed writes (extraction path — physically cannot write 'verified')
    # ------------------------------------------------------------------

    def insert_proposed(
        self,
        entities: Iterable[ProposedEntity],
        relations: Iterable[ProposedRelation],
        *,
        source_doc_id: str,
        extractor_engine: str,
        extractor_model: str | None = None,
        prompt_version: str | None = None,
        decode_params: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Insert extraction output as ``proposed`` rows, resolving entities.

        Every entity is deduped by ``(schema_version_id, entity_type,
        normalized_name)`` (then by alias) against existing proposed+verified
        nodes; a hit reuses that node id and merges aliases/properties
        non-destructively, a miss inserts the minted id. Relation endpoints
        are then bound to resolved ids; duplicate triples append a citation
        instead of a second edge. Returns per-batch stats.
        """
        self._assert_writable()
        sv_id = self.active_schema_version()["id"]
        now = time.time()
        # Canonical JSON (keys sorted, no spaces): one setting must store as
        # one string regardless of the caller's dict order, or scoping a
        # score to a sampler would split it into two streams.
        decode_json = (
            json.dumps(decode_params, sort_keys=True, separators=(",", ":"))
            if decode_params is not None
            else None
        )
        stats = {
            "nodes_new": 0,
            "nodes_merged": 0,
            "edges_new": 0,
            "edges_merged": 0,
            "synthesized_endpoints": 0,
        }
        id_map: dict[str, str] = {}

        for ent in entities:
            resolved = self._resolve_node(sv_id, ent.entity_type, ent.name)
            span_json = ent.source_span.as_json() if ent.source_span else None
            if resolved is not None:
                node_id = resolved["id"]
                self._merge_mention(resolved, ent)
                stats["nodes_merged"] += 1
            else:
                node_id = ent.id
                self.conn.execute(
                    "INSERT INTO nodes "
                    "(id, schema_version_id, entity_type, name, normalized_name, "
                    " aliases_json, properties_json, status, confidence, "
                    " source_doc_id, source_span, extractor_engine, extractor_model, "
                    " prompt_version, created_ts, decode_params) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        node_id,
                        sv_id,
                        ent.entity_type,
                        ent.name,
                        normalize_name(ent.name),
                        json.dumps(ent.aliases),
                        json.dumps(ent.properties),
                        ent.confidence,
                        source_doc_id,
                        span_json,
                        extractor_engine,
                        extractor_model,
                        prompt_version,
                        now,
                        decode_json,
                    ),
                )
                for alias in ent.aliases:
                    self._add_alias(node_id, alias)
                stats["nodes_new"] += 1
            if ent.synthesized:
                stats["synthesized_endpoints"] += 1
            id_map[ent.id] = node_id
            self._add_citation(
                "node",
                node_id,
                source_doc_id,
                span_json,
                now,
                extractor_engine,
                extractor_model,
                prompt_version,
                decode_json,
            )

        for rel in relations:
            try:
                src = id_map[rel.src_entity_id]
                dst = id_map[rel.dst_entity_id]
            except KeyError as exc:
                raise KGStoreError(
                    f"relation {rel.id} references unknown entity id {exc}"
                ) from exc
            span_json = rel.source_span.as_json() if rel.source_span else None
            cur = self.conn.execute(
                "SELECT id FROM edges WHERE schema_version_id = ? AND "
                "relation_type = ? AND src_node_id = ? AND dst_node_id = ? AND "
                "status IN ('proposed','verified') AND "
                f"{self._edge_current_sql()}",
                (sv_id, rel.relation_type, src, dst),
            )
            dup = cur.fetchone()
            if dup is not None:
                edge_id = dup["id"]
                stats["edges_merged"] += 1
            else:
                edge_id = rel.id
                self.conn.execute(
                    "INSERT INTO edges "
                    "(id, schema_version_id, relation_type, src_node_id, dst_node_id, "
                    " properties_json, status, confidence, source_doc_id, source_span, "
                    " extractor_engine, extractor_model, prompt_version, created_ts, "
                    " valid_from, decode_params) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        edge_id,
                        sv_id,
                        rel.relation_type,
                        src,
                        dst,
                        json.dumps(rel.properties),
                        rel.confidence,
                        source_doc_id,
                        span_json,
                        extractor_engine,
                        extractor_model,
                        prompt_version,
                        now,
                        now,  # valid_from: assertion time defaults to ingestion
                        decode_json,
                    ),
                )
                stats["edges_new"] += 1
            self._add_citation(
                "edge",
                edge_id,
                source_doc_id,
                span_json,
                now,
                extractor_engine,
                extractor_model,
                prompt_version,
                decode_json,
            )

        if commit:
            self.conn.commit()
        stats["id_map"] = id_map
        return stats

    def _resolve_node(
        self, sv_id: int, entity_type: str, name: str
    ) -> Optional[sqlite3.Row]:
        """Exact-key resolution over proposed+verified nodes, then aliases."""
        key = normalize_name(name)
        cur = self.conn.execute(
            "SELECT * FROM nodes WHERE schema_version_id = ? AND entity_type = ? "
            "AND normalized_name = ? AND status IN ('proposed','verified')",
            (sv_id, entity_type, key),
        )
        row = cur.fetchone()
        if row is not None:
            return row
        cur = self.conn.execute(
            "SELECT n.* FROM node_aliases a JOIN nodes n ON n.id = a.node_id "
            "WHERE a.normalized_alias = ? AND n.schema_version_id = ? "
            "AND n.entity_type = ? AND n.status IN ('proposed','verified') LIMIT 1",
            (key, sv_id, entity_type),
        )
        return cur.fetchone()

    def _merge_mention(self, existing: sqlite3.Row, ent: ProposedEntity) -> None:
        """Non-destructive merge of a re-mention into an existing node.

        Union aliases (the new surface name too, if it differs), fill only
        absent property keys, keep the earliest created_ts (already the case:
        created_ts is never touched).
        """
        aliases = json.loads(existing["aliases_json"])
        known = {normalize_name(a) for a in aliases}
        known.add(existing["normalized_name"])
        new_surfaces = [ent.name] + list(ent.aliases)
        changed_aliases = False
        for surface in new_surfaces:
            key = normalize_name(surface)
            if key and key not in known:
                aliases.append(surface)
                known.add(key)
                changed_aliases = True
            self._add_alias(existing["id"], surface)

        properties = json.loads(existing["properties_json"])
        changed_props = False
        for prop_key, value in ent.properties.items():
            if prop_key not in properties:
                properties[prop_key] = value
                changed_props = True

        if changed_aliases or changed_props:
            self.conn.execute(
                "UPDATE nodes SET aliases_json = ?, properties_json = ? WHERE id = ?",
                (json.dumps(aliases), json.dumps(properties), existing["id"]),
            )

    def _add_alias(self, node_id: str, surface: str) -> None:
        key = normalize_name(surface)
        if not key:
            return
        self.conn.execute(
            "INSERT OR IGNORE INTO node_aliases (node_id, normalized_alias, surface) "
            "VALUES (?, ?, ?)",
            (node_id, key, surface),
        )

    def _add_citation(
        self,
        kind: str,
        item_id: str,
        source_doc_id: str,
        span_json: str | None,
        ts: float,
        extractor_engine: str,
        extractor_model: str | None,
        prompt_version: str | None,
        decode_params: str | None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO citations "
            "(kind, item_id, source_doc_id, source_span, created_ts, "
            "extractor_engine, extractor_model, prompt_version, decode_params) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                item_id,
                source_doc_id,
                span_json,
                ts,
                extractor_engine,
                extractor_model,
                prompt_version,
                decode_params,
            ),
        )

    def citations(self, kind: str, item_id: str) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT source_doc_id, source_span, created_ts FROM citations "
            "WHERE kind = ? AND item_id = ? ORDER BY created_ts ASC",
            (kind, item_id),
        )
        return [
            {
                "source_doc_id": r["source_doc_id"],
                "source_span": json.loads(r["source_span"]) if r["source_span"] else None,
            }
            for r in cur.fetchall()
        ]

    # ------------------------------------------------------------------
    # Human approval gate (the only path to status='verified')
    # ------------------------------------------------------------------

    def _find_kind(self, item_id: str) -> tuple[str, sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is not None:
            return "node", row
        cur = self.conn.execute("SELECT * FROM edges WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is not None:
            return "edge", row
        raise UnknownItem(f"no node or edge with id {item_id!r}")

    def approve(
        self,
        item_id: str,
        *,
        by: str = DEFAULT_ACTOR,
        note: str | None = None,
        cascade: bool = False,
    ) -> dict[str, Any]:
        """Flip one proposed row to verified (human action, never automatic).

        For an edge, both endpoint nodes must already be verified, else
        EndpointNotVerified is raised. ``cascade=True`` approves an edge
        together with its endpoints in one explicit command — the endpoints
        get real approvals (verified_by/verified_ts), no invariant bypass.
        """
        self._assert_writable()
        kind, row = self._find_kind(item_id)
        approved: list[str] = []
        if kind == "edge":
            for endpoint_id in (row["src_node_id"], row["dst_node_id"]):
                _, endpoint = self._find_kind(endpoint_id)
                if endpoint["status"] != "verified":
                    if cascade:
                        self._set_status(
                            "node", endpoint_id, "verified", by=by, note=note
                        )
                        approved.append(endpoint_id)
                    else:
                        raise EndpointNotVerified(
                            f"edge {item_id} endpoint {endpoint_id} is "
                            f"{endpoint['status']!r}; approve endpoints first"
                        )
        self._set_status(kind, item_id, "verified", by=by, note=note)
        approved.append(item_id)
        self.conn.commit()
        return {"kind": kind, "approved_ids": approved}

    def reject(
        self, item_id: str, *, by: str = DEFAULT_ACTOR, note: str | None = None
    ) -> dict[str, Any]:
        """Flip one proposed row to rejected (kept for audit, never served)."""
        self._assert_writable()
        kind, _ = self._find_kind(item_id)
        self._set_status(kind, item_id, "rejected", by=by, note=note)
        self.conn.commit()
        return {"kind": kind, "rejected_ids": [item_id]}

    def reopen(
        self, item_id: str, *, by: str = DEFAULT_ACTOR, note: str | None = None
    ) -> dict[str, Any]:
        """Put a decided row back in the review queue (undo of approve/reject).

        Review is keyboard-driven and 'a'/'r' sit next to the 'j'/'k' cursor
        keys, so a decision made a keystroke too early was previously
        permanent — there was no way back to the queue at all.

        Reopening a NODE is refused while a current verified edge still points
        at it: approve() guarantees a verified edge has verified endpoints,
        and silently unapproving one of them would leave that invariant broken
        with nothing to notice it. Reject the edge (or invalidate it) first.
        Edges have no dependents, so they always reopen.

        Already-proposed rows are a no-op rather than an error — pressing undo
        twice should not punish you.
        """
        self._assert_writable()
        kind, row = self._find_kind(item_id)
        if row["status"] == "proposed":
            return {"kind": kind, "reopened_ids": [], "already_open": True}

        if kind == "node":
            blockers = self.conn.execute(
                "SELECT id FROM edges WHERE status = 'verified' "
                f"AND (src_node_id = ? OR dst_node_id = ?) "
                f"AND {self._edge_current_sql()} LIMIT 5",
                (item_id, item_id),
            ).fetchall()
            if blockers:
                ids = ", ".join(b["id"][:10] for b in blockers)
                raise KGStoreError(
                    f"node {item_id} is an endpoint of verified edge(s) {ids} "
                    "— reject or invalidate those first"
                )

        self.conn.execute(
            ("UPDATE nodes SET " if kind == "node" else "UPDATE edges SET ")
            + "status = 'proposed', verified_ts = NULL, verified_by = NULL, "
            "review_note = COALESCE(?, review_note) WHERE id = ?",
            (note, item_id),
        )
        self.conn.commit()
        return {"kind": kind, "reopened_ids": [item_id], "already_open": False}

    def _set_status(
        self, kind: str, item_id: str, status: str, *, by: str, note: str | None
    ) -> None:
        table = "nodes" if kind == "node" else "edges"
        self.conn.execute(
            f"UPDATE {table} SET status = ?, verified_ts = ?, verified_by = ?, "
            "review_note = COALESCE(?, review_note) WHERE id = ?",
            (status, time.time(), by, note, item_id),
        )

    def invalidate_edge(
        self,
        edge_id: str,
        *,
        by: str = DEFAULT_ACTOR,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """W13: mark a VERIFIED edge as no-longer-current (human action).

        Invalidation is the history-preserving alternative to deletion: the
        row keeps its status and audit trail but stops being served as
        current truth (queries, packs, traversals all exclude it), and its
        triple key is freed so a later re-assertion becomes a fresh proposed
        row coexisting with this one. A proposed edge has no history worth
        preserving — reject it instead.
        """
        self._assert_writable()
        kind, row = self._find_kind(edge_id)
        if kind != "edge":
            raise KGStoreError("invalidate_edge operates on edges only")
        if row["status"] != "verified":
            raise KGStoreError(
                f"edge {edge_id} is {row['status']!r}; only verified edges "
                "can be invalidated (reject proposed ones instead)"
            )
        if row["invalidated_ts"] is not None:
            raise KGStoreError(f"edge {edge_id} is already invalidated")
        now = time.time()
        self.conn.execute(
            "UPDATE edges SET invalidated_ts = ?, invalidated_by = ?, "
            "invalidation_reason = ? WHERE id = ?",
            (now, by, reason, edge_id),
        )
        self.conn.commit()
        return {
            "id": edge_id,
            "invalidated_ts": now,
            "invalidated_by": by,
            "reason": reason,
        }

    def bulk_approve(
        self,
        *,
        entity_type: str | None = None,
        relation_type: str | None = None,
        source_doc_id: str | None = None,
        min_confidence: float | None = None,
        by: str = DEFAULT_ACTOR,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Approve a filtered batch: nodes first, then edges whose endpoints
        are verified after the node pass; blocked edges are reported as
        skipped, never silently approved and never auto-approving endpoints.
        """
        self._assert_writable()
        node_where = ["status = 'proposed'"]
        node_args: list[Any] = []
        if entity_type:
            node_where.append("entity_type = ?")
            node_args.append(entity_type)
        if source_doc_id:
            node_where.append("source_doc_id = ?")
            node_args.append(source_doc_id)
        if min_confidence is not None:
            node_where.append("confidence >= ?")
            node_args.append(min_confidence)

        nodes_approved: list[str] = []
        if not relation_type:  # a relation_type filter targets edges only
            cur = self.conn.execute(
                f"SELECT id FROM nodes WHERE {' AND '.join(node_where)}", node_args
            )
            for row in cur.fetchall():
                self._set_status("node", row["id"], "verified", by=by, note=note)
                nodes_approved.append(row["id"])

        edge_where = ["e.status = 'proposed'"]
        edge_args: list[Any] = []
        if relation_type:
            edge_where.append("e.relation_type = ?")
            edge_args.append(relation_type)
        if entity_type:
            # Keep the edge pass inside the human's stated batch scope: only
            # edges BOTH of whose endpoints are of the filtered entity type.
            # Without this, any proposed edge between previously-verified
            # nodes of unrelated types would be silently over-approved.
            edge_where.append(
                "(SELECT entity_type FROM nodes WHERE id = e.src_node_id) = ? AND "
                "(SELECT entity_type FROM nodes WHERE id = e.dst_node_id) = ?"
            )
            edge_args.extend([entity_type, entity_type])
        if source_doc_id:
            edge_where.append("e.source_doc_id = ?")
            edge_args.append(source_doc_id)
        if min_confidence is not None:
            edge_where.append("e.confidence >= ?")
            edge_args.append(min_confidence)

        edges_approved: list[str] = []
        edges_skipped: list[str] = []
        cur = self.conn.execute(
            "SELECT e.*, s.status AS src_status, d.status AS dst_status "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.src_node_id "
            "JOIN nodes d ON d.id = e.dst_node_id "
            f"WHERE {' AND '.join(edge_where)}",
            edge_args,
        )
        for row in cur.fetchall():
            if row["src_status"] == "verified" and row["dst_status"] == "verified":
                self._set_status("edge", row["id"], "verified", by=by, note=note)
                edges_approved.append(row["id"])
            else:
                edges_skipped.append(row["id"])
        self.conn.commit()
        return {
            "nodes_approved": nodes_approved,
            "edges_approved": edges_approved,
            "edges_skipped": edges_skipped,
        }

    # ------------------------------------------------------------------
    # W7 entity-merge review (candidates proposed by scan, decided by human)
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_pair(node_a_id: str, node_b_id: str) -> tuple[str, str]:
        """Order a pair canonically so (a,b) and (b,a) are one candidate."""
        return (node_a_id, node_b_id) if node_a_id < node_b_id else (node_b_id, node_a_id)

    def record_merge_candidate(
        self, node_a_id: str, node_b_id: str, *, score: float, reasons: list[str]
    ) -> bool:
        """Store one fuzzy-duplicate pair for human review.

        Returns True if a new candidate row was created. A pair that already
        has a row in ANY status is left untouched — in particular a dismissed
        pair is never re-proposed (the human already said "not a duplicate").
        """
        self._assert_writable()
        if node_a_id == node_b_id:
            raise KGStoreError("a merge candidate needs two distinct nodes")
        a, b = self._canonical_pair(node_a_id, node_b_id)
        existing = self.conn.execute(
            "SELECT id FROM merge_candidates WHERE node_a_id = ? AND node_b_id = ?",
            (a, b),
        ).fetchone()
        if existing is not None:
            return False
        self.conn.execute(
            "INSERT INTO merge_candidates "
            "(id, node_a_id, node_b_id, score, reasons_json, status, created_ts) "
            "VALUES (?, ?, ?, ?, ?, 'proposed', ?)",
            (uuid.uuid4().hex, a, b, score, json.dumps(reasons), time.time()),
        )
        self.conn.commit()
        return True

    def _merge_candidate_row(self, candidate_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM merge_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise UnknownItem(f"unknown merge candidate id {candidate_id!r}")
        return row

    # ---------------------------------------------------------------
    # Annotations — curated-resource records, awaiting a human decision
    # ---------------------------------------------------------------

    def upsert_annotation(
        self,
        *,
        node_id: str,
        resource: str,
        external_id: str,
        record_url: str,
        matched_name: str,
        facts: dict[str, Any],
    ) -> tuple[str, bool]:
        """Propose one resource record for one node. Returns (id, created).

        Re-running a lookup REFRESHES the pending row rather than adding a
        second one: a resource that revises a record should not cost the
        reviewer an extra rejection, and two rows for one (node, resource)
        would let a reviewer approve a record the resource has since
        replaced.

        A decided annotation is never silently overwritten. Approval is the
        thing this whole table exists to record; discarding it because a
        refresh ran later would make the decision unstable.
        """
        now = time.time()
        existing = self.conn.execute(
            "SELECT id, status FROM annotations WHERE node_id = ? AND resource = ?",
            (node_id, resource),
        ).fetchone()
        if existing is not None:
            if existing["status"] != "proposed":
                return existing["id"], False
            self.conn.execute(
                "UPDATE annotations SET external_id = ?, record_url = ?, "
                "matched_name = ?, facts_json = ?, created_ts = ? WHERE id = ?",
                (
                    external_id,
                    record_url,
                    matched_name,
                    json.dumps(facts, ensure_ascii=False),
                    now,
                    existing["id"],
                ),
            )
            self.conn.commit()
            return existing["id"], False

        annotation_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO annotations (id, node_id, resource, external_id, "
            "record_url, matched_name, facts_json, status, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?)",
            (
                annotation_id,
                node_id,
                resource,
                external_id,
                record_url,
                matched_name,
                json.dumps(facts, ensure_ascii=False),
                now,
            ),
        )
        self.conn.commit()
        return annotation_id, True

    def annotations_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Pending annotations, each carrying the node name it would attach to.

        The node's own name travels with the row because it is the evidence:
        the reviewer's job is to compare "what we called it" with "what the
        resource calls it", and a queue that showed only the latter would be
        asking them to confirm a match they cannot see.
        """
        if not self._table_exists("annotations"):
            return []
        rows = self.conn.execute(
            "SELECT a.*, n.name AS node_name, n.entity_type AS node_type, "
            "       n.status AS node_status "
            "FROM annotations a JOIN nodes n ON n.id = a.node_id "
            "WHERE a.status = 'proposed' "
            "ORDER BY a.created_ts ASC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["facts"] = json.loads(row["facts_json"])
            except (TypeError, ValueError):
                item["facts"] = {}
            item.pop("facts_json", None)
            out.append(item)
        return out

    def decide_annotation(
        self,
        annotation_id: str,
        *,
        accept: bool,
        by: str = DEFAULT_ACTOR,
        note: str | None = None,
    ) -> bool:
        """Accept or reject one annotation. False when it is already decided.

        Accepting writes the facts onto the node under the resource's name,
        so an approved annotation becomes part of the node while staying
        attributable — `properties_json` gains one key per resource, never a
        flat merge, because a flat merge would lose which resource said what
        and let two resources silently overwrite each other.
        """
        row = self.conn.execute(
            "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
        ).fetchone()
        if row is None or row["status"] != "proposed":
            return False
        now = time.time()
        status = "verified" if accept else "rejected"
        self.conn.execute(
            "UPDATE annotations SET status = ?, decided_ts = ?, decided_by = ?, "
            "decision_note = ? WHERE id = ?",
            (status, now, by, note, annotation_id),
        )
        if accept:
            node = self.conn.execute(
                "SELECT properties_json FROM nodes WHERE id = ?", (row["node_id"],)
            ).fetchone()
            if node is not None:
                try:
                    props = json.loads(node["properties_json"] or "{}")
                except (TypeError, ValueError):
                    props = {}
                if not isinstance(props, dict):
                    props = {}
                try:
                    facts = json.loads(row["facts_json"])
                except (TypeError, ValueError):
                    facts = {}
                props[row["resource"]] = {
                    "external_id": row["external_id"],
                    "record_url": row["record_url"],
                    "matched_name": row["matched_name"],
                    **(facts if isinstance(facts, dict) else {}),
                }
                self.conn.execute(
                    "UPDATE nodes SET properties_json = ? WHERE id = ?",
                    (json.dumps(props, ensure_ascii=False), row["node_id"]),
                )
        self.conn.commit()
        return True

    def annotation_counts(self) -> dict[str, int]:
        if not self._table_exists("annotations"):
            return {"proposed": 0, "verified": 0, "rejected": 0}
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM annotations GROUP BY status"
        ).fetchall()
        counts = {"proposed": 0, "verified": 0, "rejected": 0}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts

    def merge_candidates_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Pending merge candidates, hydrated with both nodes side-by-side."""
        if not self._table_exists("merge_candidates"):
            return []  # pre-W7 read-only store: no queue, not an error
        rows = self.conn.execute(
            "SELECT * FROM merge_candidates WHERE status = 'proposed' "
            "ORDER BY score DESC, created_ts ASC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            nodes = {}
            for key in ("node_a_id", "node_b_id"):
                node_row = self.conn.execute(
                    "SELECT * FROM nodes WHERE id = ?", (row[key],)
                ).fetchone()
                if node_row is None:
                    continue
                item = _node_dict(node_row)
                item["citation_count"] = len(self.citations("node", node_row["id"]))
                nodes[key] = item
            # A candidate whose node has since been rejected/merged away is
            # noise: hide it (and mark it stale so it stops coming back).
            hydrated = list(nodes.values())
            if len(hydrated) != 2 or any(
                n["status"] not in ("proposed", "verified") for n in hydrated
            ):
                if not self.read_only:
                    self.conn.execute(
                        "UPDATE merge_candidates SET status = 'stale', "
                        "decided_ts = ?, decided_by = 'system:hydrate' WHERE id = ?",
                        (time.time(), row["id"]),
                    )
                    self.conn.commit()
                continue
            out.append(
                {
                    "id": row["id"],
                    "score": row["score"],
                    "reasons": json.loads(row["reasons_json"]),
                    "created_ts": row["created_ts"],
                    "node_a": nodes["node_a_id"],
                    "node_b": nodes["node_b_id"],
                }
            )
        return out

    def dismiss_merge_candidate(
        self, candidate_id: str, *, by: str = DEFAULT_ACTOR, note: str | None = None
    ) -> dict[str, Any]:
        """Human decision: this pair is NOT a duplicate. Never re-proposed."""
        self._assert_writable()
        row = self._merge_candidate_row(candidate_id)
        if row["status"] != "proposed":
            raise KGStoreError(
                f"merge candidate {candidate_id} already decided ({row['status']})"
            )
        self.conn.execute(
            "UPDATE merge_candidates SET status = 'dismissed', decided_ts = ?, "
            "decided_by = ?, decision_note = ? WHERE id = ?",
            (time.time(), by, note, candidate_id),
        )
        self.conn.commit()
        return {"id": candidate_id, "status": "dismissed"}

    def merge_nodes(
        self,
        target_id: str,
        source_id: str,
        *,
        by: str = DEFAULT_ACTOR,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Merge ``source`` into ``target`` — an explicit human action.

        Aliases/properties union non-destructively into the target, citations
        and edges are re-pointed (duplicate triples collapse into a citation,
        would-be self-loops are rejected), and the source row becomes a
        ``rejected`` tombstone with ``review_note='merged-into:<target>'`` so
        it can never be served (§9.1) while staying auditable. The source's
        surfaces are registered as target aliases, so future extractions of
        the old name resolve to the merged node.

        Merging never verifies anything: the target keeps its own status.
        A verified source cannot merge into a proposed target (that would
        leave verified edges pointing at an unverified node) — merge in the
        other direction, or approve the target first.
        """
        self._assert_writable()
        if target_id == source_id:
            raise KGStoreError("cannot merge a node into itself")
        target_kind, target = self._find_kind(target_id)
        source_kind, source = self._find_kind(source_id)
        if target_kind != "node" or source_kind != "node":
            raise KGStoreError("merge_nodes operates on nodes only")
        for label, row in (("target", target), ("source", source)):
            if row["status"] not in ("proposed", "verified"):
                raise KGStoreError(
                    f"{label} node {row['id']} is {row['status']!r}; "
                    "only proposed/verified nodes can be merged"
                )
        if target["entity_type"] != source["entity_type"]:
            raise KGStoreError(
                f"cannot merge across entity types "
                f"({source['entity_type']!r} -> {target['entity_type']!r})"
            )
        if source["status"] == "verified" and target["status"] != "verified":
            raise KGStoreError(
                "cannot merge a verified node into a proposed one — merge in "
                "the other direction, or approve the target first"
            )

        now = time.time()
        report: dict[str, Any] = {
            "target_id": target_id,
            "source_id": source_id,
            "edges_repointed": 0,
            "edges_deduplicated": 0,
            "edges_self_loop_rejected": 0,
        }

        # 1) Alias/property union into the target (non-destructive).
        aliases = json.loads(target["aliases_json"])
        known = {normalize_name(a) for a in aliases}
        known.add(target["normalized_name"])
        source_surfaces = [source["name"], *json.loads(source["aliases_json"])]
        source_surfaces.extend(
            r["surface"]
            for r in self.conn.execute(
                "SELECT surface FROM node_aliases WHERE node_id = ?", (source_id,)
            )
        )
        changed = False
        for surface in source_surfaces:
            key = normalize_name(surface)
            if key and key not in known:
                aliases.append(surface)
                known.add(key)
                changed = True
            self._add_alias(target_id, surface)

        properties = json.loads(target["properties_json"])
        for prop_key, value in json.loads(source["properties_json"]).items():
            if prop_key not in properties:
                properties[prop_key] = value
                changed = True

        if changed:
            # The embedding no longer matches the merged text: clear it so the
            # next `ontologylab embed` refreshes it (never silently stale).
            self.conn.execute(
                "UPDATE nodes SET aliases_json = ?, properties_json = ?, "
                "embedding = NULL, embedding_model = NULL WHERE id = ?",
                (json.dumps(aliases), json.dumps(properties), target_id),
            )

        # 2) Citations follow the surviving node.
        self.conn.execute(
            "UPDATE citations SET item_id = ? WHERE kind = 'node' AND item_id = ?",
            (target_id, source_id),
        )

        # 3) Re-point edges, collapsing duplicates and dropping self-loops.
        sv_id = source["schema_version_id"]
        edge_rows = self.conn.execute(
            "SELECT * FROM edges WHERE (src_node_id = ? OR dst_node_id = ?) "
            f"AND status IN ('proposed','verified') AND {self._edge_current_sql()}",
            (source_id, source_id),
        ).fetchall()
        for edge in edge_rows:
            new_src = target_id if edge["src_node_id"] == source_id else edge["src_node_id"]
            new_dst = target_id if edge["dst_node_id"] == source_id else edge["dst_node_id"]
            if new_src == new_dst:
                self._set_status(
                    "edge", edge["id"], "rejected",
                    by=by, note=f"self-loop after merge into {target_id}",
                )
                report["edges_self_loop_rejected"] += 1
                continue
            dup = self.conn.execute(
                "SELECT id FROM edges WHERE schema_version_id = ? AND "
                "relation_type = ? AND src_node_id = ? AND dst_node_id = ? AND "
                "status IN ('proposed','verified') AND id != ? AND "
                f"{self._edge_current_sql()}",
                (sv_id, edge["relation_type"], new_src, new_dst, edge["id"]),
            ).fetchone()
            if dup is not None:
                self.conn.execute(
                    "UPDATE citations SET item_id = ? "
                    "WHERE kind = 'edge' AND item_id = ?",
                    (dup["id"], edge["id"]),
                )
                self._set_status(
                    "edge", edge["id"], "rejected",
                    by=by, note=f"duplicate of {dup['id']} after merge",
                )
                report["edges_deduplicated"] += 1
            else:
                self.conn.execute(
                    "UPDATE edges SET src_node_id = ?, dst_node_id = ? WHERE id = ?",
                    (new_src, new_dst, edge["id"]),
                )
                report["edges_repointed"] += 1

        # 4) Tombstone the source (rejected = never served, kept for audit).
        self._set_status(
            "node", source_id, "rejected", by=by,
            note=note or f"merged-into:{target_id}",
        )
        self.conn.execute("DELETE FROM node_aliases WHERE node_id = ?", (source_id,))

        # 5) Bookkeeping on the candidate queue: the decided pair is 'merged';
        #    other pending pairs referencing the tombstoned source are 'stale'
        #    (bookkeeping only — no graph fact is auto-decided by this).
        a, b = self._canonical_pair(target_id, source_id)
        self.conn.execute(
            "UPDATE merge_candidates SET status = 'merged', decided_ts = ?, "
            "decided_by = ?, decision_note = ? "
            "WHERE node_a_id = ? AND node_b_id = ? AND status = 'proposed'",
            (now, by, note, a, b),
        )
        self.conn.execute(
            "UPDATE merge_candidates SET status = 'stale', decided_ts = ?, "
            "decided_by = ? WHERE status = 'proposed' "
            "AND (node_a_id = ? OR node_b_id = ?)",
            (now, f"system:merge-by:{by}", source_id, source_id),
        )
        self.conn.commit()
        return report

    # Queue orderings for pending_review. Confidence orderings put NULLs
    # last; "confidence" (ascending) surfaces the least-certain extractions
    # first — the triage default recommended by the HITL literature.
    # "critic" surfaces the items the critic model scored lowest (unscored
    # items last), for W8 triage.
    # Every ordering ends with a pr.id tiebreak so the sort is total and a
    # keyset cursor can be advanced unambiguously — without it, rows with
    # equal sort keys come back in an arbitrary order and pagination would
    # skip or duplicate them.
    _REVIEW_ORDERINGS = {
        "created": "pr.created_ts ASC, pr.id ASC",
        "confidence": (
            "pr.confidence IS NULL, pr.confidence ASC, "
            "pr.created_ts ASC, pr.id ASC"
        ),
        "confidence_desc": (
            "pr.confidence IS NULL, pr.confidence DESC, "
            "pr.created_ts ASC, pr.id ASC"
        ),
        "critic": "cr.score IS NULL, cr.score ASC, pr.created_ts ASC, pr.id ASC",
    }

    # Keyset key per ordering, as a SQL row-value expression that is
    # strictly ASC under `>` even where the visible ordering mixes
    # directions: NULLs are folded into a leading 0/1 flag (never NULL in
    # a row value) and DESC columns are negated. The extractor below must
    # produce exactly these values from the last row of a page.
    _REVIEW_KEYSET = {
        "created": "(pr.created_ts, pr.id)",
        "confidence": (
            "(pr.confidence IS NULL, COALESCE(pr.confidence, -1), "
            "pr.created_ts, pr.id)"
        ),
        "confidence_desc": (
            "(pr.confidence IS NULL, COALESCE(-pr.confidence, 0), "
            "pr.created_ts, pr.id)"
        ),
        "critic": (
            "(cr.score IS NULL, COALESCE(cr.score, -1), "
            "pr.created_ts, pr.id)"
        ),
    }

    # An extractor-vs-critic gap at/above this flags the row as a
    # disagreement — the highest-value rows for a human to look at.
    CRITIC_DISAGREEMENT_THRESHOLD = 0.35

    def pending_review(
        self,
        *,
        kind: str | None = None,
        type_name: str | None = None,
        source_doc_id: str | None = None,
        order: str = "created",
        limit: int = 100,
        cursor: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            order_sql = self._REVIEW_ORDERINGS[order]
        except KeyError:
            raise KGStoreError(
                f"unknown review order {order!r} "
                f"(allowed: {sorted(self._REVIEW_ORDERINGS)})"
            ) from None
        where = ["1=1"]
        args: list[Any] = []
        if kind:
            where.append("pr.kind = ?")
            args.append(kind)
        if type_name:
            where.append("pr.type_name = ?")
            args.append(type_name)
        if source_doc_id:
            where.append("pr.source_doc_id = ?")
            args.append(source_doc_id)
        if cursor is not None:
            key_sql = self._REVIEW_KEYSET[order]
            if len(cursor) != self._review_keyset_arity(order):
                raise KGStoreError(
                    f"cursor for order {order!r} must have "
                    f"{self._review_keyset_arity(order)} values"
                )
            placeholders = ",".join("?" * len(cursor))
            where.append(f"({key_sql}) > ({placeholders})")
            args.extend(cursor)
        args.append(limit)
        # Latest critic review per item (advisory columns only — approval
        # paths never read this join). Read-only stores built before W8 have
        # no critic_reviews table: degrade to NULL critic columns.
        if self._table_exists("critic_reviews"):
            critic_join = (
                "LEFT JOIN (SELECT kind, item_id, engine, score, rationale, "
                "           MAX(created_ts) AS ts FROM critic_reviews "
                "           GROUP BY kind, item_id) cr "
                "ON cr.kind = pr.kind AND cr.item_id = pr.id "
            )
        else:
            critic_join = (
                "LEFT JOIN (SELECT NULL AS kind, NULL AS item_id, "
                "           NULL AS engine, NULL AS score, NULL AS rationale) cr "
                "ON cr.item_id = pr.id "
            )
        cur = self.conn.execute(
            "SELECT pr.*, cr.score AS critic_score, "
            "cr.rationale AS critic_rationale, cr.engine AS critic_engine "
            "FROM pending_review pr "
            f"{critic_join}"
            f"WHERE {' AND '.join(where)} ORDER BY {order_sql} LIMIT ?",
            args,
        )
        out = []
        for r in cur.fetchall():
            row = dict(r)
            conf, score = row.get("confidence"), row.get("critic_score")
            row["critic_disagreement"] = bool(
                conf is not None
                and score is not None
                and abs(conf - score) >= self.CRITIC_DISAGREEMENT_THRESHOLD
            )
            out.append(row)
        self._label_edge_endpoints(out)
        self._attach_properties(out)
        self._attach_evidence(out)
        return out

    @staticmethod
    def _review_keyset_arity(order: str) -> int:
        return {"created": 2, "confidence": 4, "confidence_desc": 4, "critic": 4}[order]

    def review_cursor_values(self, order: str, row: dict[str, Any]) -> list[Any]:
        """Keyset cursor values for one row, in sort-key order.

        Must mirror ``_REVIEW_KEYSET`` exactly: the list is what the next
        ``pending_review(cursor=...)`` call compares against, so a mismatch
        would silently skip or duplicate rows across pages.
        """
        if order == "created":
            return [row["created_ts"], row["id"]]
        conf = row.get("confidence")
        if order == "confidence":
            return [
                0 if conf is not None else 1,
                conf if conf is not None else -1,
                row["created_ts"],
                row["id"],
            ]
        if order == "confidence_desc":
            return [
                0 if conf is not None else 1,
                -conf if conf is not None else 0,
                row["created_ts"],
                row["id"],
            ]
        if order == "critic":
            score = row.get("critic_score")
            return [
                0 if score is not None else 1,
                score if score is not None else -1,
                row["created_ts"],
                row["id"],
            ]
        raise KGStoreError(f"unknown review order {order!r}")

    def _attach_properties(self, rows: list[dict[str, Any]]) -> None:
        """Expose stored proposal properties on the review-queue surface."""
        for kind, table in (("node", "nodes"), ("edge", "edges")):
            targets = {row["id"]: row for row in rows if row.get("kind") == kind}
            ids = list(targets)
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                placeholders = ",".join("?" * len(chunk))
                for row in self.conn.execute(
                    f"SELECT id, properties_json FROM {table} "
                    f"WHERE id IN ({placeholders})",
                    chunk,
                ):
                    targets[row["id"]]["properties"] = json.loads(
                        row["properties_json"]
                    )

    def _attach_evidence(self, rows: list[dict[str, Any]]) -> None:
        """Attach the source excerpt each proposal was extracted from, in place.

        The reviewer is asked to judge whether an extraction is true, and the
        only thing that settles that is the sentence it came from. The critic
        model has always been handed exactly this (critic.py builds it from
        the same span), while the person holding the decision saw only a label
        and a number — so the queue payload is where that asymmetry lives.

        ``pending_review`` cannot supply it: the view predates spans and is
        created with CREATE VIEW IF NOT EXISTS, so redefining it would leave
        every existing database on the old definition. Spans are fetched here
        instead, the same way endpoint names are.

        Adds ``source_span``, ``excerpt``, ``doc_title``, ``doc_source``
        and ``evidence_grade``. Every step fails
        open to an empty excerpt — a deleted raw.txt must not break review.
        """
        if not rows:
            return

        spans: dict[str, dict | None] = {}
        for kind, table in (("node", "nodes"), ("edge", "edges")):
            ids = [r["id"] for r in rows if r.get("kind") == kind and r.get("id")]
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                placeholders = ",".join("?" * len(chunk))
                for row in self.conn.execute(
                    f"SELECT id, source_span FROM {table} "
                    f"WHERE id IN ({placeholders})",
                    chunk,
                ).fetchall():
                    try:
                        spans[row["id"]] = (
                            json.loads(row["source_span"])
                            if row["source_span"]
                            else None
                        )
                    except (TypeError, ValueError):
                        spans[row["id"]] = None

        raw_cache: dict[str, str] = {}
        # Title, source and grade come from one `get_document` per document —
        # the grade is what tells a reviewer whether the sentence they are
        # about to trust was reviewed by anyone before them.
        doc_cache: dict[str, tuple[str | None, str, str]] = {}

        def _raw(doc_id: str) -> str:
            if doc_id not in raw_cache:
                try:
                    raw_cache[doc_id] = self.document_raw_text(doc_id)
                except (KGStoreError, OSError):
                    raw_cache[doc_id] = ""
            return raw_cache[doc_id]

        def _doc(doc_id: str) -> tuple[str | None, str, str]:
            if doc_id not in doc_cache:
                try:
                    d = self.get_document(doc_id)
                    doc_cache[doc_id] = (
                        d.title, d.source, evidence.normalize(d.evidence_grade)
                    )
                except (UnknownItem, KGStoreError, OSError):
                    doc_cache[doc_id] = (None, "", evidence.UNKNOWN)
            return doc_cache[doc_id]

        for row in rows:
            span = spans.get(row.get("id"))
            row["source_span"] = span
            doc_id = row.get("source_doc_id")
            if not doc_id:
                row["excerpt"], row["doc_title"] = "", None
                row["doc_source"], row["evidence_grade"] = "", evidence.UNKNOWN
                continue
            title, source, grade = _doc(doc_id)
            row["doc_title"] = title
            row["doc_source"] = source
            row["evidence_grade"] = grade
            row["excerpt"] = span_excerpt(_raw(doc_id), span)

    def _label_edge_endpoints(self, rows: list[dict[str, Any]]) -> None:
        """Rewrite edge labels from endpoint ids to endpoint NAMES, in place.

        The ``pending_review`` view can only concatenate the two node ids
        (``src -> dst``), so the review queue asked the user to approve
        rows reading ``74116a11… -> 36d5bf4d…`` — the one screen where the
        decision must be informed was the one screen showing nothing
        decidable. Endpoint names are resolved here, in one batched lookup,
        rather than in the view, so existing databases need no migration and
        read-only packs keep working.

        ``src_label``/``dst_label``/``src_id``/``dst_id`` are added alongside
        so callers that need the raw ids still have them. A node that cannot
        be resolved keeps its short id, which is still better than the full
        hex string.
        """
        edges = [r for r in rows if r.get("kind") == "edge"]
        if not edges:
            return
        endpoints: dict[str, tuple[str, str]] = {}
        wanted: set[str] = set()
        for row in edges:
            label = row.get("label") or ""
            src, sep, dst = label.partition(" -> ")
            if not sep:
                continue
            endpoints[row["id"]] = (src, dst)
            wanted.update((src, dst))
        if not wanted:
            return
        names: dict[str, str] = {}
        ids = list(wanted)
        # Chunked so a large queue cannot exceed SQLite's variable limit.
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            placeholders = ",".join("?" * len(chunk))
            for row in self.conn.execute(
                f"SELECT id, name FROM nodes WHERE id IN ({placeholders})", chunk
            ).fetchall():
                names[row["id"]] = row["name"]
        for row in edges:
            pair = endpoints.get(row["id"])
            if pair is None:
                continue
            src, dst = pair
            src_label = names.get(src, src[:10])
            dst_label = names.get(dst, dst[:10])
            row["src_id"], row["dst_id"] = src, dst
            row["src_label"], row["dst_label"] = src_label, dst_label
            row["label"] = f"{src_label} → {dst_label}"

    def record_critic_review(
        self,
        kind: str,
        item_id: str,
        *,
        engine: str,
        model: str | None,
        prompt_version: str,
        score: float,
        rationale: str | None = None,
    ) -> None:
        """Upsert one advisory critic score. Never touches nodes/edges."""
        self._assert_writable()
        if kind not in ("node", "edge"):
            raise KGStoreError(f"bad critic review kind {kind!r}")
        score = min(1.0, max(0.0, float(score)))
        self.conn.execute(
            "INSERT INTO critic_reviews "
            "(kind, item_id, engine, model, prompt_version, score, rationale, "
            " created_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (kind, item_id, engine, prompt_version) DO UPDATE SET "
            "score = excluded.score, rationale = excluded.rationale, "
            "model = excluded.model, created_ts = excluded.created_ts",
            (kind, item_id, engine, model, prompt_version, score, rationale,
             time.time()),
        )
        self.conn.commit()

    def _table_exists(self, name: str) -> bool:
        """True when ``name`` exists — read-only packs built before a table
        was added to _SCHEMA cannot be migrated, so W7+ features degrade
        gracefully on them instead of failing every open."""
        return self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone() is not None

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for status in REVIEW_STATUSES:
            out[f"nodes_{status}"] = self.conn.execute(
                "SELECT COUNT(*) AS n FROM nodes WHERE status = ?", (status,)
            ).fetchone()["n"]
            out[f"edges_{status}"] = self.conn.execute(
                "SELECT COUNT(*) AS n FROM edges WHERE status = ?", (status,)
            ).fetchone()["n"]
        out["documents"] = self.conn.execute(
            "SELECT COUNT(*) AS n FROM documents"
        ).fetchone()["n"]
        out["merge_candidates_pending"] = (
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM merge_candidates "
                "WHERE status = 'proposed'"
            ).fetchone()["n"]
            if self._table_exists("merge_candidates")
            else 0
        )
        return out

    # ------------------------------------------------------------------
    # Document-centric review: the source text, and what was drawn from it
    # ------------------------------------------------------------------

    def document_review_context(
        self, doc_id: str, *, max_chars: int = DOCUMENT_PANEL_MAX_CHARS
    ) -> dict[str, Any]:
        """One document plus every proposal that cites it.

        The inverse of `entity_review_context`, and the view the product has
        been missing. Approving a proposal means judging whether the source
        actually says it — a question the entity view answers one 160-char
        excerpt at a time, which is enough to check a single mention and not
        enough to notice that eleven proposals all came from the same
        sentence, or that a paper's own hedging ("we did not observe") sits
        just outside every excerpt.

        Returns the text, capped, and the cited spans as offsets into it.
        Nothing is marked up here: the caller decides how to draw a span,
        and a server that shipped HTML would be a server that decides what
        a document looks like — and a path for document text to reach
        innerHTML as markup rather than as text.
        """
        document = self.get_document(doc_id)
        try:
            text = self.document_raw_text(doc_id)
        except (KGStoreError, OSError):
            # The proposals are in sqlite; the raw text is a file beside it.
            # One can be missing without the other, and this panel is how a
            # reviewer would find out — so it must not be the thing that
            # breaks.
            text = ""
        truncated = len(text) > max_chars

        rows = self.conn.execute(
            "SELECT kind, item_id, source_span FROM citations "
            "WHERE source_doc_id = ? ORDER BY created_ts ASC",
            (doc_id,),
        ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            span = json.loads(row["source_span"]) if row["source_span"] else None
            if row["kind"] == "node":
                nrow = self.conn.execute(
                    "SELECT name, entity_type, status FROM nodes WHERE id = ?",
                    (row["item_id"],),
                ).fetchone()
                if nrow is None:
                    continue
                label, kind_label, status = (
                    nrow["name"], nrow["entity_type"], nrow["status"],
                )
            else:
                erow = self.conn.execute(
                    "SELECT e.relation_type, e.status, s.name AS src, "
                    "d.name AS dst FROM edges e "
                    "JOIN nodes s ON s.id = e.src_node_id "
                    "JOIN nodes d ON d.id = e.dst_node_id WHERE e.id = ?",
                    (row["item_id"],),
                ).fetchone()
                if erow is None:
                    continue
                # An edge shown as `related_to` alone cannot be judged.
                label = f"{erow['src']} → {erow['dst']}"
                kind_label, status = erow["relation_type"], erow["status"]
            items.append({
                "kind": row["kind"],
                "id": row["item_id"],
                "label": label,
                "type": kind_label,
                "status": status,
                # A span past the cap is reported as absent rather than as a
                # position the caller would draw in the wrong place —
                # highlighting the wrong sentence asserts evidence that is
                # not there, which is worse than highlighting nothing.
                "span": span if (
                    span and int(span.get("end", 0)) <= max_chars
                ) else None,
            })

        return {
            "doc_id": document.id,
            "title": document.title,
            "source_uri": document.source_uri,
            "source_kind": document.source_kind,
            "fetched_ts": document.fetched_ts,
            "text": text[:max_chars],
            "truncated": truncated,
            "total_chars": len(text),
            "items": items,
        }

    # ------------------------------------------------------------------
    # W11 entity-centric review: everything about ONE entity in one payload
    # ------------------------------------------------------------------

    def entity_review_context(
        self, entity_id: str, *, context_chars: int = SPAN_EXCERPT_CONTEXT_CHARS
    ) -> dict[str, Any]:
        """One entity's full review context: every mention (span excerpt in
        source context), every proposed/verified relation with the other
        endpoint's name+status, the latest critic score, and any pending
        merge candidates involving it.

        Read-only aggregation — approving/rejecting stays per-item through
        the existing gate. Rationale (RESEARCH W11): most of what a reviewer
        needs to judge an entity lives outside the single row being staring
        at — its other mentions and its relations.
        """
        kind, row = self._find_kind(entity_id)
        if kind != "node":
            raise KGStoreError("entity review is for nodes; got an edge id")
        entity = _node_dict(row)

        critic = None
        if self._table_exists("critic_reviews"):
            crow = self.conn.execute(
                "SELECT engine, model, score, rationale, MAX(created_ts) AS ts "
                "FROM critic_reviews WHERE kind = 'node' AND item_id = ? "
                "GROUP BY item_id",
                (entity_id,),
            ).fetchone()
            if crow is not None and crow["score"] is not None:
                critic = {
                    "engine": crow["engine"],
                    "model": crow["model"],
                    "score": crow["score"],
                    "rationale": crow["rationale"],
                }

        mentions = []
        doc_cache: dict[str, str] = {}
        for citation in self.citations("node", entity_id):
            doc_id = citation["source_doc_id"]
            if doc_id not in doc_cache:
                try:
                    doc_cache[doc_id] = self.document_raw_text(doc_id)
                except (KGStoreError, OSError):
                    doc_cache[doc_id] = ""
            try:
                title = self.get_document(doc_id).title
            except UnknownItem:
                title = None
            mentions.append(
                {
                    "source_doc_id": doc_id,
                    "doc_title": title,
                    "source_span": citation["source_span"],
                    "excerpt": span_excerpt(
                        doc_cache[doc_id],
                        citation["source_span"],
                        context_chars=context_chars,
                    ),
                }
            )

        edge_rows = self.conn.execute(
            "SELECT e.*, s.name AS src_name, s.status AS src_status, "
            "d.name AS dst_name, d.status AS dst_status FROM edges e "
            "JOIN nodes s ON s.id = e.src_node_id "
            "JOIN nodes d ON d.id = e.dst_node_id "
            "WHERE (e.src_node_id = ? OR e.dst_node_id = ?) "
            "AND e.status IN ('proposed','verified') "
            f"AND {self._edge_current_sql('e')} "
            "ORDER BY e.status DESC, e.created_ts ASC",
            (entity_id, entity_id),
        ).fetchall()
        edge_critic: dict[str, float] = {}
        if edge_rows and self._table_exists("critic_reviews"):
            placeholders = ",".join("?" for _ in edge_rows)
            for crow in self.conn.execute(
                "SELECT item_id, score, MAX(created_ts) AS ts FROM critic_reviews "
                f"WHERE kind = 'edge' AND item_id IN ({placeholders}) "
                "GROUP BY item_id",
                [e["id"] for e in edge_rows],
            ):
                edge_critic[crow["item_id"]] = crow["score"]
        relations = []
        for edge in edge_rows:
            outgoing = edge["src_node_id"] == entity_id
            relations.append(
                {
                    "id": edge["id"],
                    "relation_type": edge["relation_type"],
                    "direction": "out" if outgoing else "in",
                    "other": {
                        "id": edge["dst_node_id"] if outgoing else edge["src_node_id"],
                        "name": edge["dst_name"] if outgoing else edge["src_name"],
                        "status": (
                            edge["dst_status"] if outgoing else edge["src_status"]
                        ),
                    },
                    "status": edge["status"],
                    "confidence": edge["confidence"],
                    "critic_score": edge_critic.get(edge["id"]),
                    "source_doc_id": edge["source_doc_id"],
                }
            )

        merge_candidates = []
        if self._table_exists("merge_candidates"):
            for mrow in self.conn.execute(
                "SELECT m.*, n.name AS other_name, n.status AS other_status "
                "FROM merge_candidates m JOIN nodes n ON n.id = "
                "  (CASE WHEN m.node_a_id = ? THEN m.node_b_id "
                "        ELSE m.node_a_id END) "
                "WHERE (m.node_a_id = ? OR m.node_b_id = ?) "
                "AND m.status = 'proposed' ORDER BY m.score DESC",
                (entity_id, entity_id, entity_id),
            ):
                merge_candidates.append(
                    {
                        "id": mrow["id"],
                        "score": mrow["score"],
                        "reasons": json.loads(mrow["reasons_json"]),
                        "other": {
                            "id": (
                                mrow["node_b_id"]
                                if mrow["node_a_id"] == entity_id
                                else mrow["node_a_id"]
                            ),
                            "name": mrow["other_name"],
                            "status": mrow["other_status"],
                        },
                    }
                )

        return {
            "entity": entity,
            "critic": critic,
            "mentions": mentions,
            "relations": relations,
            "merge_candidates": merge_candidates,
            "counts": {
                "mentions": len(mentions),
                "relations_proposed": sum(
                    1 for r in relations if r["status"] == "proposed"
                ),
                "relations_verified": sum(
                    1 for r in relations if r["status"] == "verified"
                ),
                "merge_candidates": len(merge_candidates),
            },
        }

    # ------------------------------------------------------------------
    # W12 communities (read side; rows are written by the pack builder)
    # ------------------------------------------------------------------

    def list_communities(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Communities of this store, largest first. Empty when the store
        predates W12 or no build has computed them (never an error)."""
        if not self._table_exists("communities"):
            return []
        rows = self.conn.execute(
            "SELECT * FROM communities ORDER BY member_count DESC, id LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "member_count": r["member_count"],
                "top_members": json.loads(r["top_members_json"]),
                "summary": r["summary"],
                "summary_method": r["summary_method"],
            }
            for r in rows
        ]

    def community_members(self, community_id: str) -> list[dict[str, Any]]:
        """Member nodes of one community (id/name/type/status)."""
        if not self._table_exists("communities"):
            raise UnknownItem(f"unknown community id {community_id!r}")
        exists = self.conn.execute(
            "SELECT 1 FROM communities WHERE id = ?", (community_id,)
        ).fetchone()
        if exists is None:
            raise UnknownItem(f"unknown community id {community_id!r}")
        rows = self.conn.execute(
            "SELECT n.id, n.name, n.entity_type, n.status "
            "FROM community_members m JOIN nodes n ON n.id = m.node_id "
            "WHERE m.community_id = ? ORDER BY n.name",
            (community_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def write_communities(self, rows: list[dict[str, Any]]) -> None:
        """Replace this store's community rows (pack build time only)."""
        self._assert_writable()
        now = time.time()
        self.conn.execute("DELETE FROM community_members")
        self.conn.execute("DELETE FROM communities")
        for row in rows:
            self.conn.execute(
                "INSERT INTO communities (id, member_count, top_members_json, "
                "summary, summary_method, created_ts) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["id"],
                    len(row["members"]),
                    json.dumps(row["top_members"]),
                    row["summary"],
                    row["summary_method"],
                    now,
                ),
            )
            for node_id in row["members"]:
                self.conn.execute(
                    "INSERT INTO community_members (community_id, node_id) "
                    "VALUES (?, ?)",
                    (row["id"], node_id),
                )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Verified-only reads (pack build + ground-truth queries)
    # ------------------------------------------------------------------

    def verified_subgraph(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return (nodes, edges) with status='verified' only; an edge is
        included only when both endpoints are in the verified node set."""
        nodes = [
            _node_dict(r)
            for r in self.conn.execute("SELECT * FROM nodes WHERE status = 'verified'")
        ]
        edges = [
            _edge_dict(r)
            for r in self.conn.execute(
                "SELECT e.* FROM edges e "
                "JOIN nodes s ON s.id = e.src_node_id AND s.status = 'verified' "
                "JOIN nodes d ON d.id = e.dst_node_id AND d.status = 'verified' "
                f"WHERE e.status = 'verified' AND {self._edge_current_sql('e')}"
            )
        ]
        return nodes, edges

    # ------------------------------------------------------------------
    # Query surface (shared by dashboard, CLI, and the MCP server)
    # ------------------------------------------------------------------

    def entity_lookup(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        entity_type: str | None = None,
        fuzzy: bool = True,
        include_proposed: bool = False,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Resolve a node by id or by (normalized/alias/fuzzy) name."""
        status_sql = _status_clause(include_proposed)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(row: sqlite3.Row, score: float) -> None:
            if row["id"] in seen:
                return
            seen.add(row["id"])
            item = _node_dict(row)
            item["match_score"] = round(score, MATCH_SCORE_PRECISION)
            item["source_document_ids"] = sorted(
                {c["source_doc_id"] for c in self.citations("node", row["id"])}
                or {row["source_doc_id"]}
            )
            results.append(item)

        if id is not None:
            cur = self.conn.execute(
                f"SELECT * FROM nodes WHERE id = ? AND {status_sql}", (id,)
            )
            row = cur.fetchone()
            if row is not None:
                add(row, 1.0)
            return results[:limit]

        if name is None:
            raise KGStoreError("entity_lookup requires id or name")

        key = normalize_name(name)
        type_sql = " AND entity_type = ?" if entity_type else ""
        type_args = [entity_type] if entity_type else []

        cur = self.conn.execute(
            f"SELECT * FROM nodes WHERE normalized_name = ? AND {status_sql}{type_sql}",
            [key, *type_args],
        )
        for row in cur.fetchall():
            add(row, 1.0)

        aliased_type_sql = " AND n.entity_type = ?" if entity_type else ""
        cur = self.conn.execute(
            "SELECT n.* FROM node_aliases a JOIN nodes n ON n.id = a.node_id "
            f"WHERE a.normalized_alias = ? AND {_status_clause(include_proposed, 'n')}"
            f"{aliased_type_sql}",
            [key, *type_args],
        )
        for row in cur.fetchall():
            add(row, 0.95)

        if fuzzy and len(results) < limit:
            for item in self.semantic_search(
                name,
                top_k=limit,
                entity_type=entity_type,
                include_proposed=include_proposed,
            ):
                if item["id"] not in seen:
                    seen.add(item["id"])
                    results.append(item)
        return results[:limit]

    def provenance(self, kind: str, item_id: str) -> dict[str, Any]:
        """Everything known about where one node or edge came from.

        The columns have been carried since the first schema — extractor
        engine and model, prompt version, the source document and span, who
        approved it and when — and none of them left the database. The
        review screen showed the evidence excerpt and nothing else, so the
        question this tool exists to answer ("why does the graph believe
        this?") could only be answered by opening sqlite.

        Returned as one record rather than assembled by the caller, because
        a lineage split across three requests is a lineage nobody reads.
        """
        if kind not in ("node", "edge"):
            raise KGStoreError(f"unknown kind {kind!r}: expected node or edge")
        table = "nodes" if kind == "node" else "edges"
        row = self.conn.execute(
            f"SELECT * FROM {table} WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise UnknownItem(f"unknown {kind} id {item_id!r}")

        keys = row.keys()
        record: dict[str, Any] = {
            "kind": kind,
            "id": row["id"],
            "status": row["status"],
            "confidence": row["confidence"],
            "extraction": {
                "engine": row["extractor_engine"],
                "model": row["extractor_model"] if "extractor_model" in keys else None,
                "prompt_version": row["prompt_version"] if "prompt_version" in keys else None,
                "created_ts": row["created_ts"],
            },
            "review": {
                "verified_by": row["verified_by"] if "verified_by" in keys else None,
                "verified_ts": row["verified_ts"] if "verified_ts" in keys else None,
                "note": row["review_note"] if "review_note" in keys else None,
            },
        }
        record["label"] = (
            row["name"] if kind == "node" else row["relation_type"]
        )

        # The document is the anchor of the whole claim; without its title
        # and URI the engine/model line is trivia.
        doc_row = self.conn.execute(
            "SELECT id, title, source_uri, source_kind, fetched_ts "
            "FROM documents WHERE id = ?",
            (row["source_doc_id"],),
        ).fetchone()
        record["document"] = dict(doc_row) if doc_row is not None else None

        span = json.loads(row["source_span"]) if row["source_span"] else None
        record["source_span"] = span
        record["excerpt"] = (
            span_excerpt(self.document_raw_text(row["source_doc_id"]), span)
            if span else None
        )

        # Advisory only, and labelled as such wherever it surfaces: the
        # critic never approved anything and its score is not part of the
        # lineage, only of the queue's ordering.
        record["critic"] = None
        if self._table_exists("critic_reviews"):
            critic = self.conn.execute(
                "SELECT engine, model, score, rationale, created_ts "
                "FROM critic_reviews WHERE kind = ? AND item_id = ? "
                "ORDER BY created_ts DESC LIMIT 1",
                (kind, item_id),
            ).fetchone()
            if critic is not None:
                record["critic"] = dict(critic)
        return record

    def name_search(
        self,
        query: str,
        *,
        limit: int = 8,
        include_proposed: bool = True,
    ) -> list[dict[str, Any]]:
        """Substring name search, ranked exact → prefix → contained.

        `entity_lookup` resolves an identity: it wants the node the caller
        already means, so it matches the normalized name exactly, then
        aliases, then falls back to FTS. That is the wrong shape for a
        finder. FTS tokenizes on word boundaries, so `Cas9` does not match
        `HiFiCas9` — typing three letters of a name a user can see on screen
        returned nothing, which makes a command palette useless for the one
        thing it exists to do.

        This matches on the same `normalized_name` key entity resolution
        uses, so the palette and the store agree on what "the same name"
        means, and the ranking puts an exact hit above a prefix above a
        substring — the order a person scanning a dropdown expects.
        """
        key = normalize_name(query)
        if not key:
            return []
        status_sql = _status_clause(include_proposed)
        # The normalized key may now CONTAIN % or _ (short symbols keep
        # punctuation), so LIKE patterns must escape them — normalization
        # was never a sanitizer, and widening a literal keystroke into a
        # wildcard match returns the whole graph.
        escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.conn.execute(
            f"""
            SELECT *,
                   CASE WHEN normalized_name = ?      THEN 0
                        WHEN normalized_name LIKE ? ESCAPE '\\'   THEN 1
                        ELSE 2 END AS rank_bucket
            FROM nodes
            WHERE {status_sql} AND normalized_name LIKE ? ESCAPE '\\'
            ORDER BY rank_bucket, LENGTH(name), name
            LIMIT ?
            """,
            (key, escaped + "%", "%" + escaped + "%", limit),
        ).fetchall()
        return [_node_dict(row) for row in rows]

    def semantic_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        entity_type: str | None = None,
        min_score: float = 0.0,
        include_proposed: bool = False,
    ) -> list[dict[str, Any]]:
        """Tier-1 **lexical** (FTS5/BM25) search over node names/aliases/properties.

        Not vector search. The raw sqlite bm25() rank (negative,
        smaller-is-better) is normalized rank-preservingly into the stable
        0..1 higher-is-better ``match_score`` contract of §5.4:
        ``relevance = max(0, -bm25_raw)``, ``match_score = relevance / (1 + relevance)``.
        """
        terms = [t for t in re.findall(r"\w+", query) if t]
        if not terms:
            return []
        match_expr = " OR ".join(f'"{t}"' for t in terms)
        status_sql = _status_clause(include_proposed, "n")
        type_sql = " AND n.entity_type = ?" if entity_type else ""
        args: list[Any] = [match_expr]
        if entity_type:
            args.append(entity_type)
        args.append(top_k * 4)  # over-fetch before status/type/score filtering
        cur = self.conn.execute(
            "SELECT n.*, bm25(nodes_fts) AS raw_rank FROM nodes_fts "
            "JOIN nodes n ON n.rowid = nodes_fts.rowid "
            f"WHERE nodes_fts MATCH ? AND {status_sql}{type_sql} "
            "ORDER BY raw_rank ASC LIMIT ?",
            args,
        )
        results = []
        for row in cur.fetchall():
            relevance = max(0.0, -float(row["raw_rank"]))
            score = relevance / (1.0 + relevance)
            if score < min_score:
                continue
            item = _node_dict(row)
            item["match_score"] = round(score, MATCH_SCORE_PRECISION)
            item["source_document_ids"] = sorted(
                {c["source_doc_id"] for c in self.citations("node", row["id"])}
                or {row["source_doc_id"]}
            )
            results.append(item)
            if len(results) >= top_k:
                break
        return results

    # ------------------------------------------------------------------
    # Tier-2 embeddings: backfill, cosine search, hybrid RRF fusion (§5.4)
    # ------------------------------------------------------------------

    def _embedding_text(self, row: sqlite3.Row) -> str:
        """The text an embedder sees for a node: name + aliases + properties."""
        aliases = json.loads(row["aliases_json"])
        properties = json.loads(row["properties_json"])
        parts = [row["name"], *aliases]
        parts.extend(f"{k}: {v}" for k, v in properties.items())
        return " | ".join(str(p) for p in parts)

    def embed_nodes(self, embedder, *, batch_size: int = 64) -> dict[str, int]:
        """Backfill embeddings for nodes missing one from this embedder.

        Covers proposed + verified rows (so the review UI can search pending
        items too); rejected rows are never embedded. Idempotent: rows whose
        embedding_model already matches are skipped.
        """
        self._assert_writable()
        from ontologylab.embeddings import pack_vector

        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE status IN ('proposed','verified') "
            "AND (embedding IS NULL OR embedding_model IS NOT ?)",
            (embedder.name(),),
        ).fetchall()
        embedded = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            texts = [self._embedding_text(r) for r in batch]
            vectors = embedder.embed(texts)
            for row, vec in zip(batch, vectors):
                self.conn.execute(
                    "UPDATE nodes SET embedding = ?, embedding_model = ? WHERE id = ?",
                    (pack_vector(vec), embedder.name(), row["id"]),
                )
                embedded += 1
        self.conn.commit()
        # Keep the optional sqlite-vec index in step with the embeddings it
        # accelerates (no-op when the extension isn't available).
        if embedded and self._vec_available():
            self._rebuild_vec_index(embedder)
        return {"embedded": embedded, "skipped": self.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE embedding_model = ?",
            (embedder.name(),),
        ).fetchone()[0] - embedded}

    def _rebuild_vec_index(self, embedder) -> None:
        """(Re)build the vec0 KNN index over this store's embeddings.

        Sized to the embedder's dimension and populated from the existing
        ``embedding`` BLOBs (byte-identical to sqlite-vec's own encoding).
        Working-DB only — packs stay portable (no extension needed to serve
        them), so a pack simply has no vec index and uses brute force.
        """
        self._assert_writable()
        dim = embedder.dim
        self.conn.execute("DROP TABLE IF EXISTS vec_nodes")
        self.conn.execute(
            f"CREATE VIRTUAL TABLE vec_nodes USING vec0("
            f"node_id TEXT PRIMARY KEY, embedding float[{dim}])"
        )
        self.conn.execute(
            "INSERT INTO vec_nodes(node_id, embedding) "
            "SELECT id, embedding FROM nodes "
            "WHERE embedding_model = ? AND embedding IS NOT NULL "
            "AND status IN ('proposed','verified')",
            (embedder.name(),),
        )
        self.conn.commit()

    def embedding_model(self) -> str | None:
        """The embedding model present on this store's nodes (if any)."""
        row = self.conn.execute(
            "SELECT embedding_model FROM nodes "
            "WHERE embedding_model IS NOT NULL LIMIT 1"
        ).fetchone()
        return row["embedding_model"] if row else None

    def vector_search(
        self,
        query: str,
        embedder,
        *,
        top_k: int = 10,
        entity_type: str | None = None,
        include_proposed: bool = False,
    ) -> list[dict[str, Any]]:
        """Cosine over stored embeddings, sqlite-vec-accelerated when present.

        Only compares against vectors produced by the SAME embedder
        (embedding_model match) — a model-A pack is never scored with a
        model-B query. match_score = (cosine+1)/2 per the §5.4 contract.

        When sqlite-vec is loaded and a vec index exists for this embedder,
        a KNN prefilter narrows the candidate set; every candidate is then
        rescored with the exact cosine, so the accelerated path returns the
        SAME results as brute force — it just examines fewer rows.
        """
        query_vec = embedder.embed([query])[0]
        candidates = self._vector_candidates(
            query_vec, embedder, top_k, entity_type, include_proposed
        )
        return self._score_vector_candidates(query_vec, candidates, top_k)

    def _vector_candidates(
        self, query_vec, embedder, top_k, entity_type, include_proposed
    ) -> list[sqlite3.Row]:
        """Node rows to cosine-rank: a KNN shortlist when vec0 is available
        (over-fetched so status/type filtering can't starve the top_k), else
        every embedded row for this embedder (brute force)."""
        status_sql = _status_clause(include_proposed)
        type_sql = " AND entity_type = ?" if entity_type else ""
        use_vec = (
            self._vec_available()
            and self._table_exists("vec_nodes")
            and self.embedding_model() == embedder.name()
        )
        if use_vec:
            from ontologylab.embeddings import pack_vector

            # Over-fetch generously: KNN is global, so status/type filters are
            # applied after; a wide shortlist keeps results identical to brute
            # force at local scale.
            shortlist = max(
                top_k * VEC_SHORTLIST_FACTOR, top_k + VEC_SHORTLIST_MIN_MARGIN
            )
            try:
                knn = self.conn.execute(
                    "SELECT node_id FROM vec_nodes WHERE embedding MATCH ? "
                    "ORDER BY distance LIMIT ?",
                    (pack_vector(query_vec), shortlist),
                ).fetchall()
            except sqlite3.OperationalError:
                use_vec = False  # index shape mismatch etc. -> brute force
            else:
                ids = [r["node_id"] for r in knn]
                if not ids:
                    return []
                placeholders = ",".join("?" for _ in ids)
                rows = self.conn.execute(
                    f"SELECT * FROM nodes WHERE id IN ({placeholders}) "
                    f"AND embedding_model = ? AND {status_sql}{type_sql}",
                    [*ids, embedder.name(), *([entity_type] if entity_type else [])],
                ).fetchall()
                # preserve KNN order isn't needed — we rescore exactly below.
                return rows
        args: list[Any] = [embedder.name()]
        if entity_type:
            args.append(entity_type)
        return self.conn.execute(
            f"SELECT * FROM nodes WHERE embedding_model = ? AND {status_sql}{type_sql}",
            args,
        ).fetchall()

    def _score_vector_candidates(
        self, query_vec, rows, top_k
    ) -> list[dict[str, Any]]:
        from ontologylab.embeddings import cosine, unpack_vector

        scored = [
            (cosine(query_vec, unpack_vector(row["embedding"])), row) for row in rows
        ]
        # Deterministic tie-break by id so the ranking is identical whether the
        # candidate rows arrived in rowid order (brute force) or PK-index order
        # (the sqlite-vec KNN shortlist) — equal-cosine ties can't reorder.
        scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        results = []
        for sim, row in scored[:top_k]:
            item = _node_dict(row)
            item["match_score"] = round((sim + 1.0) / 2.0, MATCH_SCORE_PRECISION)
            item["source_document_ids"] = sorted(
                {c["source_doc_id"] for c in self.citations("node", row["id"])}
                or {row["source_doc_id"]}
            )
            results.append(item)
        return results

    def hybrid_search(
        self,
        query: str,
        embedder,
        *,
        top_k: int = 10,
        entity_type: str | None = None,
        min_score: float = 0.0,
        include_proposed: bool = False,
        extra_lexical_queries: list[str] | None = None,
        reranker: Any | None = None,
    ) -> list[dict[str, Any]]:
        """BM25 + vector fused with Reciprocal Rank Fusion (§5.4 tier-2).

        ``reranker`` (anything with ``score(query, texts) -> list[float]``)
        adds a second stage: the fused shortlist (3×top_k) is re-scored
        jointly against the query and re-ordered. RRF alone never reads the
        query against a candidate — it only merges ranks — which is the gap
        second-stage rerankers exist to close. With a reranker,
        ``match_score`` is the sigmoid of the cross-encoder logit (still
        0..1, higher is better); ties break by id, so the ordering stays a
        pure function of the store.

        All backends run status-filtered, their ranked id lists are fused
        with RRF (k=60), and match_score carries the normalized 0..1 fused
        score (rank-based relevance, higher is better — documented meaning
        consistent across tiers).

        ``extra_lexical_queries`` adds one ranked list per entry (e.g. the
        LLM-expanded variant query) as an INDEPENDENT fusion signal — the
        vector leg always embeds the original ``query`` only, so expansion
        terms never pollute the semantic embedding. This is the 3-signal
        hybrid: plain lexical + expanded lexical + vector.
        """
        from ontologylab.embeddings import rrf_fuse

        lexical = self.semantic_search(
            query,
            top_k=top_k * 2,
            entity_type=entity_type,
            include_proposed=include_proposed,
        )
        extra_lists: list[list[dict[str, Any]]] = []
        for extra_query in extra_lexical_queries or []:
            if not extra_query or extra_query == query:
                continue
            extra_lists.append(
                self.semantic_search(
                    extra_query,
                    top_k=top_k * 2,
                    entity_type=entity_type,
                    include_proposed=include_proposed,
                )
            )
        vector = self.vector_search(
            query,
            embedder,
            top_k=top_k * 2,
            entity_type=entity_type,
            include_proposed=include_proposed,
        )
        all_lists = [lexical, *extra_lists, vector]
        # dict 채우기는 역순 — 기존 [*vector, *lexical] 규약대로 lexical
        # 행이 같은 id의 vector 행을 덮어쓴다
        by_id = {
            item["id"]: item
            for ranked in reversed(all_lists)
            for item in ranked
        }
        fused = rrf_fuse([[i["id"] for i in ranked] for ranked in all_lists])
        shortlist_size = top_k * 3 if reranker is not None else top_k
        results = []
        for item_id, fused_score in fused:
            if fused_score < min_score:
                continue
            item = dict(by_id[item_id])
            item["match_score"] = round(fused_score, MATCH_SCORE_PRECISION)
            results.append(item)
            if len(results) >= shortlist_size:
                break
        if reranker is None or not results:
            return results

        from ontologylab.rerankers import sigmoid

        texts = [
            " | ".join(
                str(part)
                for part in (
                    item["name"],
                    item["entity_type"],
                    *item.get("aliases", []),
                    *(f"{k}: {v}" for k, v in item.get("properties", {}).items()),
                )
            )
            for item in results
        ]
        scores = reranker.score(query, texts)
        order = sorted(
            range(len(results)),
            key=lambda i: (-scores[i], results[i]["id"]),
        )
        reranked = []
        for i in order[:top_k]:
            item = results[i]
            item["match_score"] = round(sigmoid(scores[i]), MATCH_SCORE_PRECISION)
            reranked.append(item)
        return reranked

    def graph_query(
        self,
        *,
        entity_type: str | None = None,
        relation_type: str | None = None,
        property_filters: dict[str, Any] | None = None,
        include_proposed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Filtered subgraph: matching nodes plus the edges among them."""
        status_sql = _status_clause(include_proposed)
        where = [status_sql]
        args: list[Any] = []
        if entity_type:
            where.append("entity_type = ?")
            args.append(entity_type)
        for prop_key, value in (property_filters or {}).items():
            where.append("json_extract(properties_json, ?) = ?")
            args.extend([f"$.{prop_key}", value])
        args.extend([limit, offset])
        node_rows = self.conn.execute(
            f"SELECT * FROM nodes WHERE {' AND '.join(where)} "
            "ORDER BY name LIMIT ? OFFSET ?",
            args,
        ).fetchall()
        nodes = [_node_dict(r) for r in node_rows]
        node_ids = {n["id"] for n in nodes}
        edges: list[dict[str, Any]] = []
        if node_ids:
            # id 집합은 json_each로 한 번만 바인딩 — IN (?,?,…) 확장은 2×N
            # 파라미터라 sqlite<3.32의 host-param 한도(999)를 limit≈500에서
            # 넘어선다 (JSON1의 json_each는 3.9+라 안전).
            ids_json = json.dumps(sorted(node_ids))
            id_set = "(SELECT value FROM json_each(?))"
            edge_where = [
                status_sql,
                self._edge_current_sql(),
                f"src_node_id IN {id_set}",
                f"dst_node_id IN {id_set}",
            ]
            edge_args: list[Any] = [ids_json, ids_json]
            if relation_type:
                edge_where.insert(1, "relation_type = ?")
                edge_args.insert(0, relation_type)
            edges = [
                _edge_dict(r)
                for r in self.conn.execute(
                    f"SELECT * FROM edges WHERE {' AND '.join(edge_where)}", edge_args
                )
            ]
        return {"nodes": nodes, "edges": edges}

    def _neighbors(
        self,
        node_id: str,
        relation_types: list[str] | None,
        direction: str,
        include_proposed: bool,
    ) -> list[sqlite3.Row]:
        status_sql = _status_clause(include_proposed, "e")
        rel_sql = ""
        rel_args: list[Any] = []
        if relation_types:
            rel_sql = (
                " AND e.relation_type IN ("
                + ",".join("?" for _ in relation_types)
                + ")"
            )
            rel_args = list(relation_types)
        clauses = []
        if direction in ("out", "both"):
            clauses.append(("e.src_node_id = ?", "e.dst_node_id"))
        if direction in ("in", "both"):
            clauses.append(("e.dst_node_id = ?", "e.src_node_id"))
        rows: list[sqlite3.Row] = []
        node_status_sql = _status_clause(include_proposed, "n")
        current_sql = self._edge_current_sql("e")
        for where_col, other_col in clauses:
            rows.extend(
                self.conn.execute(
                    f"SELECT e.*, {other_col} AS other_id FROM edges e "
                    f"JOIN nodes n ON n.id = {other_col} "
                    f"WHERE {where_col} AND {status_sql} AND {current_sql} "
                    f"AND {node_status_sql}{rel_sql}",
                    [node_id, *rel_args],
                ).fetchall()
            )
        return rows

    def traverse_relations(
        self,
        start_ids: list[str],
        *,
        relation_types: list[str] | None = None,
        direction: str = "both",
        max_hops: int = 2,
        include_proposed: bool = False,
        limit: int = 200,
    ) -> dict[str, Any]:
        """N-hop BFS neighborhood from seed nodes (naive, local-scale)."""
        if direction not in ("in", "out", "both"):
            raise KGStoreError("direction must be 'in', 'out', or 'both'")
        visited: dict[str, int] = {}
        edge_ids: set[str] = set()
        edges: list[dict[str, Any]] = []
        frontier = deque()
        # Seeds obey the same §9.1 status filter as discovered nodes — a
        # rejected/proposed seed id must not leak through the traversal.
        for node_id in self._filter_ids_by_status(start_ids, include_proposed):
            visited[node_id] = 0
            frontier.append((node_id, 0))
        while frontier:
            node_id, depth = frontier.popleft()
            if depth >= max_hops or len(visited) >= limit:
                continue
            for row in self._neighbors(
                node_id, relation_types, direction, include_proposed
            ):
                if row["id"] not in edge_ids:
                    edge_ids.add(row["id"])
                    edges.append(_edge_dict(row))
                other = row["other_id"]
                if other not in visited and len(visited) < limit:
                    visited[other] = depth + 1
                    frontier.append((other, depth + 1))
        nodes = []
        if visited:
            placeholders = ",".join("?" for _ in visited)
            hydrated = {
                row["id"]: row
                for row in self.conn.execute(
                    f"SELECT * FROM nodes WHERE id IN ({placeholders})",
                    list(visited),
                )
            }
            for node_id, depth in visited.items():
                row = hydrated.get(node_id)
                if row is not None:
                    item = _node_dict(row)
                    item["hop"] = depth
                    nodes.append(item)
        return {"nodes": nodes, "edges": edges}

    def _filter_ids_by_status(
        self, node_ids: list[str], include_proposed: bool
    ) -> list[str]:
        """Return the subset of ``node_ids`` visible under the status filter."""
        if not node_ids:
            return []
        placeholders = ",".join("?" for _ in node_ids)
        visible = {
            row["id"]
            for row in self.conn.execute(
                f"SELECT id FROM nodes WHERE id IN ({placeholders}) "
                f"AND {_status_clause(include_proposed)}",
                list(node_ids),
            )
        }
        return [node_id for node_id in node_ids if node_id in visible]

    def find_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_hops: int = 6,
        relation_types: list[str] | None = None,
        include_proposed: bool = False,
    ) -> dict[str, Any]:
        """Shortest relation path between two nodes (BFS, undirected walk)."""
        not_found = {"found": False, "hop_count": None, "path": [], "path_edges": []}
        if source_id == target_id:
            # The trivial self-path only exists if the node itself exists AND
            # is visible under the §9.1 status filter.
            row = self.conn.execute(
                f"SELECT id, name FROM nodes WHERE id = ? "
                f"AND {_status_clause(include_proposed)}",
                (source_id,),
            ).fetchone()
            if row is None:
                return not_found
            return {
                "found": True,
                "hop_count": 0,
                "path": [{"node_id": source_id, "name": row["name"]}],
                "path_edges": [],
            }
        if len(self._filter_ids_by_status([source_id, target_id], include_proposed)) != 2:
            return not_found
        parents: dict[str, tuple[str, sqlite3.Row]] = {}
        visited = {source_id}
        frontier = deque([(source_id, 0)])
        while frontier:
            node_id, depth = frontier.popleft()
            if depth >= max_hops:
                continue
            for row in self._neighbors(
                node_id, relation_types, "both", include_proposed
            ):
                other = row["other_id"]
                if other in visited:
                    continue
                visited.add(other)
                parents[other] = (node_id, row)
                if other == target_id:
                    return self._materialize_path(source_id, target_id, parents)
                frontier.append((other, depth + 1))
        return {"found": False, "hop_count": None, "path": [], "path_edges": []}

    def _materialize_path(
        self,
        source_id: str,
        target_id: str,
        parents: dict[str, tuple[str, sqlite3.Row]],
    ) -> dict[str, Any]:
        path_edges: list[dict[str, Any]] = []
        node_ids = [target_id]
        cursor = target_id
        while cursor != source_id:
            prev, edge_row = parents[cursor]
            path_edges.append(_edge_dict(edge_row))
            node_ids.append(prev)
            cursor = prev
        node_ids.reverse()
        path_edges.reverse()
        path = []
        for node_id in node_ids:
            row = self.conn.execute(
                "SELECT id, name FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            path.append({"node_id": node_id, "name": row["name"] if row else None})
        return {
            "found": True,
            "hop_count": len(path_edges),
            "path": path,
            "path_edges": path_edges,
        }

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def rebuild_fts(self) -> None:
        """Rebuild the FTS5 index from the nodes content table."""
        self._assert_writable()
        self.conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
        self.conn.commit()

    def _assert_writable(self) -> None:
        if self.read_only:
            raise KGStoreError("store is read-only (immutable pack)")


__all__ = [
    "KGStore",
    "KGStoreError",
    "EndpointNotVerified",
    "UnknownItem",
    "normalize_name",
    "span_excerpt",
]
