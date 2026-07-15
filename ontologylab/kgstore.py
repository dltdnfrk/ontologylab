"""sqlite knowledge-graph store for ontologylab (successor to drylab's memory.py).

One sqlite file holds the ontology schema tables, collected documents, and
the graph itself (``nodes`` / ``edges``), each row carrying a status in
``proposed | verified | rejected``. The load-bearing invariant, carried over
from drylab's ``Finding.verified``: **nothing is ever verified except by an
explicit human approval call.** The write API is split so the extraction path
(``insert_proposed``) is physically incapable of writing ``verified``; only
``approve()`` may set it.

The same ``KGStore`` class serves the mutable working DB (read-write, WAL)
and an immutable knowledge pack (``read_only=True``, opened via
``file:...?mode=ro&immutable=1`` so no ``-wal`` sidecar is ever created).

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
    """
    return re.sub(r"[^0-9a-z]+", "", name.casefold())


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
    embedding_model   TEXT
);
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
    invalidation_reason   TEXT
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
    kind          TEXT NOT NULL CHECK (kind IN ('node','edge')),
    item_id       TEXT NOT NULL,
    source_doc_id TEXT NOT NULL REFERENCES documents(id),
    source_span   TEXT,
    created_ts    REAL NOT NULL
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
    "verified_ts, verified_by, review_note, embedding, embedding_model"
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
    a ``read_only`` flag. Read-write mode enables WAL; ``read_only=True``
    opens ``file:...?mode=ro&immutable=1`` and executes no DDL.
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
    def open(cls, file_path: str | Path, *, read_only: bool = False) -> "KGStore":
        """Open (creating if needed, unless read_only) the KG sqlite file."""
        db_path = Path(file_path)
        if read_only:
            uri = f"file:{db_path}?mode=ro&immutable=1"
            conn = sqlite3.connect(uri, uri=True, timeout=30.0)
            conn.row_factory = sqlite3.Row
            return cls(conn, db_path, read_only=True)

        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.executescript(_SCHEMA)
        cls._migrate(conn)
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
        ):
            if column not in edge_columns:
                conn.execute(ddl)
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
    ) -> tuple[Document, bool]:
        """Insert a document (deduped by content hash); write raw text to disk.

        Returns (document, created) — ``created`` False means an identical
        document already existed and was returned instead.
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
        )
        self.conn.execute(
            "INSERT INTO documents "
            "(id, source_kind, source_uri, title, fetched_ts, content_hash, raw_text_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                doc.id,
                doc.source_kind,
                doc.source_uri,
                doc.title,
                doc.fetched_ts,
                doc.content_hash,
                doc.raw_text_path,
            ),
        )
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
                    " prompt_version, created_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?)",
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
                    ),
                )
                for alias in ent.aliases:
                    self._add_alias(node_id, alias)
                stats["nodes_new"] += 1
            if ent.synthesized:
                stats["synthesized_endpoints"] += 1
            id_map[ent.id] = node_id
            self._add_citation("node", node_id, source_doc_id, span_json, now)

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
                    " valid_from) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    ),
                )
                stats["edges_new"] += 1
            self._add_citation("edge", edge_id, source_doc_id, span_json, now)

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
    ) -> None:
        self.conn.execute(
            "INSERT INTO citations (kind, item_id, source_doc_id, source_span, created_ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, item_id, source_doc_id, span_json, ts),
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
    _REVIEW_ORDERINGS = {
        "created": "pr.created_ts ASC",
        "confidence": "pr.confidence IS NULL, pr.confidence ASC, pr.created_ts ASC",
        "confidence_desc": (
            "pr.confidence IS NULL, pr.confidence DESC, pr.created_ts ASC"
        ),
        "critic": "cr.score IS NULL, cr.score ASC, pr.created_ts ASC",
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
        return out

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
    ) -> list[dict[str, Any]]:
        """BM25 + vector fused with Reciprocal Rank Fusion (§5.4 tier-2).

        Both backends run status-filtered, their ranked id lists are fused
        with RRF (k=60), and match_score carries the normalized 0..1 fused
        score (rank-based relevance, higher is better — documented meaning
        consistent across tiers).
        """
        from ontologylab.embeddings import rrf_fuse

        lexical = self.semantic_search(
            query,
            top_k=top_k * 2,
            entity_type=entity_type,
            include_proposed=include_proposed,
        )
        vector = self.vector_search(
            query,
            embedder,
            top_k=top_k * 2,
            entity_type=entity_type,
            include_proposed=include_proposed,
        )
        by_id = {item["id"]: item for item in [*vector, *lexical]}
        fused = rrf_fuse([[i["id"] for i in lexical], [i["id"] for i in vector]])
        results = []
        for item_id, fused_score in fused:
            if fused_score < min_score:
                continue
            item = dict(by_id[item_id])
            item["match_score"] = round(fused_score, MATCH_SCORE_PRECISION)
            results.append(item)
            if len(results) >= top_k:
                break
        return results

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
            placeholders = ",".join("?" for _ in node_ids)
            edge_where = [
                status_sql,
                self._edge_current_sql(),
                f"src_node_id IN ({placeholders})",
                f"dst_node_id IN ({placeholders})",
            ]
            edge_args: list[Any] = [*node_ids, *node_ids]
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
