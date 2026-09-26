"""Lifecycle: open/close, transactions, migrations, capability probes.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

from pathlib import Path
import contextlib
import sqlite3
import time
from typing import Any

from ontologylab import ontology_schema as default_schema
from ontologylab.storage_compatibility import require_writer_compatible

from ontologylab.kgstore_base import (
    KGStoreError,
    _SCHEMA,
    _execute_sql_script,
    normalize_name,
)

class LifecycleMixin:

    def __init__(self, conn: sqlite3.Connection, db_path: Path, read_only: bool) -> None:
        self.conn = conn
        self.db_path = db_path
        self.read_only = read_only
        self._tx_depth = 0
        self._edges_bitemporal_cache: bool | None = None
        self._edges_qualifiers_cache: bool | None = None
        self._vec_loaded: bool | None = None

    @contextlib.contextmanager
    def _write_tx(self):
        """One commit/rollback boundary around a write.

        Nests as a no-op inside :meth:`atomic` — an inner method's plain
        ``with self.conn`` would otherwise commit the caller's multi-step
        write halfway through (that is how a failed ontology apply used to
        leave a half-built term).
        """
        if self._tx_depth > 0:
            yield
            return
        self._tx_depth += 1
        try:
            with self.conn:
                yield
        finally:
            self._tx_depth -= 1

    @contextlib.contextmanager
    def atomic(self):
        """Group several store writes into a single commit/rollback."""
        self._tx_depth += 1
        try:
            with self.conn:
                yield
        finally:
            self._tx_depth -= 1

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

    def _edges_have_qualifiers(self) -> bool:
        """Whether edge rows carry first-class qualifiers.

        Historical packs are immutable and therefore intentionally lack the
        column; read paths expose an empty qualifier object for those rows.
        """
        if self._edges_qualifiers_cache is None:
            columns = {
                row["name"] for row in self.conn.execute("PRAGMA table_info(edges)")
            }
            self._edges_qualifiers_cache = "qualifiers_json" in columns
        return self._edges_qualifiers_cache

    def _edge_current_sql(self, alias: str = "") -> str:
        """WHERE fragment excluding invalidated edges from current truth."""
        if not self._edges_bitemporal():
            return "1=1"
        column = f"{alias}.invalidated_ts" if alias else "invalidated_ts"
        return f"{column} IS NULL"

    def _current_critic_stream(
        self, kind: str
    ) -> tuple[str, str | None, str] | None:
        """The newest (engine, model, prompt_version) scored for ``kind``.

        `conformal` calibrates on this stream alone — a cheap critic's 0.1 and
        a frontier critic's 0.95 are not one measurement — and answers "not
        yet" after a switch. Every surface that shows a score scopes to it too,
        so a retired stream's number never sits beside a proposal reading as
        "the critic judged this" while the threshold reports nothing judged.

        Resolved once and bound as parameters. The same restriction written as
        a correlated subquery re-scans `critic_reviews` for every candidate
        row: measured at 5,000 proposals and 12,500 reviews, that turned a
        6.6 ms review queue into a 17.5 s one.
        """
        row = self.conn.execute(
            "SELECT engine, model, prompt_version FROM critic_reviews "
            "WHERE kind = ? ORDER BY created_ts DESC LIMIT 1",
            (kind,),
        ).fetchone()
        if row is None:
            return None
        return row["engine"], row["model"], row["prompt_version"]

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
            from ontologylab.method_store import prepare_method_connection

            prepare_method_connection(conn)
            return cls(conn, db_path, read_only=True)

        require_writer_compatible(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        # The KG holds a user's private research; default umask leaves it
        # group/world-readable on a multi-user host. Owner-only, and the
        # WAL sidecars sqlite creates get the same treatment.
        for sidecar in (db_path, *db_path.parent.glob(db_path.name + "-*")):
            if sidecar.is_file():
                try:
                    sidecar.chmod(0o600)
                except FileNotFoundError:
                    # SQLite may checkpoint and remove a WAL sidecar between
                    # the directory scan and chmod.
                    pass
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            conn.execute("BEGIN IMMEDIATE")
            _execute_sql_script(conn, _SCHEMA)
            cls._migrate(conn)
            from ontologylab import authority, extraction_state

            _execute_sql_script(conn, extraction_state._SCHEMA)
            _execute_sql_script(conn, authority._SCHEMA)
            from ontologylab.grounded_review_schema import (
                ensure_grounded_review_schema,
            )

            ensure_grounded_review_schema(conn)
            for table, column in (
                ("extraction_runs", "owner_token"),
                ("extraction_chunks", "owner_token"),
            ):
                columns = {
                    row["name"]
                    for row in conn.execute(f"PRAGMA table_info({table})")
                }
                if column not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            conn.close()
            raise
        store = cls(conn, db_path, read_only=False)
        try:
            store._seed_default_schema()
            from ontologylab.file_lifecycle import reconcile_files
            from ontologylab.provenance_outbox import project_outbox

            reconcile_files(store.conn, db_path.parent)
            project_outbox(store.conn, db_path.parent)
            if store.conn.in_transaction:
                store.conn.commit()
        except BaseException:
            if store.conn.in_transaction:
                store.conn.rollback()
            store.close()
            raise
        return store

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Bring a pre-existing writable DB up to the current schema.

        The base schema only creates MISSING tables/indexes; it
        never adds columns to an existing table or changes an existing
        index's predicate — both are handled here. Read-only packs are
        never migrated: query paths degrade instead (see _edge_current_sql
        / _table_exists).
        """
        # Documents predate `doi` / `source` / `evidence_grade`; an existing store
        # has rows without them. They read back as "" and normalize to
        # `unknown`, which is the honest answer for a document collected
        # before anyone recorded where it came from.
        document_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(documents)")
        }
        if "doi" not in document_columns:
            conn.execute("ALTER TABLE documents ADD COLUMN doi TEXT")
        for column in ("source", "evidence_grade"):
            if column not in document_columns:
                conn.execute(
                    f"ALTER TABLE documents ADD COLUMN {column} "
                    f"TEXT NOT NULL DEFAULT ''"
                )
        # Wave 2.1 Step 3 (3A): Representation linkage/state are additive;
        # pre-existing rows stay unlinked (NULL work_id) and ready.
        if "work_id" not in document_columns:
            conn.execute("ALTER TABLE documents ADD COLUMN work_id TEXT")
        if "representation_state" not in document_columns:
            conn.execute(
                "ALTER TABLE documents ADD COLUMN representation_state "
                "TEXT NOT NULL DEFAULT 'ready'"
            )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_doi "
            "ON documents (doi) WHERE doi IS NOT NULL"
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
            (
                "qualifiers_json",
                "ALTER TABLE edges ADD COLUMN qualifiers_json "
                "TEXT NOT NULL DEFAULT '{}'",
            ),
        ):
            if column not in edge_columns:
                conn.execute(ddl)
        entity_type_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(entity_type)")
        }
        if "parent_name" not in entity_type_columns:
            conn.execute(
                "ALTER TABLE entity_type ADD COLUMN parent_name TEXT"
            )
        if "extractable" not in entity_type_columns:
            conn.execute(
                "ALTER TABLE entity_type ADD COLUMN extractable INTEGER "
                "NOT NULL DEFAULT 1"
            )
        relation_type_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(relation_type)")
        }
        if "qualifiers_json" not in relation_type_columns:
            conn.execute(
                "ALTER TABLE relation_type ADD COLUMN qualifiers_json "
                "TEXT NOT NULL DEFAULT '{}'"
            )
        node_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(nodes)")
        }
        if "decode_params" not in node_columns:
            conn.execute("ALTER TABLE nodes ADD COLUMN decode_params TEXT")
        # Claim layer O-4: every row records how it came to exist. Every row
        # written before this column existed came from insert_proposed, so
        # 'extracted' is the factual backfill, not a guess.
        for table, columns in (("nodes", node_columns), ("edges", edge_columns)):
            if "origin" not in columns:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN origin TEXT NOT NULL "
                    "DEFAULT 'extracted' "
                    "CHECK (origin IN ('extracted','inferred','curated'))"
                )
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
        # The dedup index predicate gained "invalidated_ts IS NULL" in W13 and
        # the polarity key in the claim layer; IF NOT EXISTS keeps an old
        # index alive, so rebuild it when either is missing.
        index_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_edges_dedup'"
        ).fetchone()
        index_sql = (index_sql_row["sql"] or "") if index_sql_row else ""
        if not ("invalidated_ts" in index_sql and "polarity" in index_sql):
            conn.execute("DROP INDEX IF EXISTS idx_edges_dedup")
            conn.execute(
                "CREATE UNIQUE INDEX idx_edges_dedup "
                "ON edges (schema_version_id, relation_type, src_node_id, "
                "dst_node_id, "
                "COALESCE(json_extract(qualifiers_json, '$.polarity'), '')) "
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

        from ontologylab.kgstore import KGStore
        KGStore._migrate_ontology_terms(conn)
        from ontologylab.method_store import ensure_method_schema

        ensure_method_schema(conn)

    @staticmethod
    def _migrate_ontology_terms(conn: sqlite3.Connection) -> None:
        """Add the ontology identity tables and backfill legacy vocabulary.

        A savepoint owns the whole three-table migration. SQLite DDL is
        transactional inside a savepoint, so an interrupted or rejected
        statement cannot leave only part of the ontology table set behind.
        """
        conn.execute("SAVEPOINT ontology_term_migration")
        succeeded = False
        try:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS ontology_term (
                    id                  TEXT PRIMARY KEY,
                    iri                 TEXT NOT NULL UNIQUE
                                            CHECK (iri = '{default_schema.LOCAL_TERM_IRI_BASE}/' || id),
                    preferred_label     TEXT NOT NULL,
                    language            TEXT NOT NULL,
                    definition          TEXT NOT NULL,
                    lifecycle           TEXT NOT NULL DEFAULT 'active'
                                            CHECK (lifecycle IN ('active','deprecated','replaced')),
                    replacement_term_id TEXT REFERENCES ontology_term(id),
                    change_reason       TEXT,
                    schema_version_id   INTEGER NOT NULL REFERENCES schema_version(id),
                    reviewer            TEXT NOT NULL,
                    provenance          TEXT NOT NULL,
                    created_ts          REAL NOT NULL,
                    updated_ts          REAL NOT NULL,
                    legacy_kind         TEXT CHECK (
                        legacy_kind IN ('entity_type','relation_type')
                    ),
                    legacy_id           INTEGER,
                    CHECK ((legacy_kind IS NULL) = (legacy_id IS NULL)),
                    CHECK (replacement_term_id IS NULL OR replacement_term_id <> id),
                    CHECK (lifecycle = 'active' OR (
                        change_reason IS NOT NULL AND length(trim(change_reason)) > 0
                    )),
                    CHECK (lifecycle <> 'replaced' OR replacement_term_id IS NOT NULL),
                    UNIQUE (legacy_kind, legacy_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS term_alias (
                    id          TEXT PRIMARY KEY,
                    term_id     TEXT NOT NULL REFERENCES ontology_term(id),
                    label       TEXT NOT NULL,
                    language    TEXT NOT NULL,
                    alias_kind  TEXT NOT NULL CHECK (
                        alias_kind IN ('alternative','hidden','former-preferred')
                    ),
                    reviewer    TEXT NOT NULL,
                    provenance  TEXT NOT NULL,
                    created_ts  REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS term_xref (
                    id                  TEXT PRIMARY KEY,
                    term_id             TEXT NOT NULL REFERENCES ontology_term(id),
                    authority           TEXT NOT NULL,
                    external_id         TEXT NOT NULL,
                    mapping_predicate   TEXT NOT NULL CHECK (
                        mapping_predicate IN (
                            'exact','close','broader','narrower','related','advisory'
                        )),
                    source_uri          TEXT NOT NULL,
                    source_version      TEXT,
                    valid_from          REAL,
                    valid_to            REAL,
                    retrieved_at        REAL NOT NULL,
                    confidence          REAL NOT NULL
                                            CHECK (confidence >= 0.0 AND confidence <= 1.0),
                    reviewer            TEXT NOT NULL,
                    lifecycle           TEXT NOT NULL DEFAULT 'active'
                                            CHECK (lifecycle IN ('active','deprecated','replaced')),
                    replacement_xref_id TEXT REFERENCES term_xref(id),
                    change_reason       TEXT,
                    license_gate        TEXT NOT NULL CHECK (
                        license_gate IN ('allow','identifier-only','deny-text')
                    ),
                    created_ts          REAL NOT NULL,
                    updated_ts          REAL NOT NULL,
                    CHECK (source_version IS NOT NULL OR valid_from IS NOT NULL
                           OR valid_to IS NOT NULL),
                    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
                    CHECK (replacement_xref_id IS NULL OR replacement_xref_id <> id),
                    CHECK (lifecycle = 'active' OR (
                        change_reason IS NOT NULL AND length(trim(change_reason)) > 0
                    )),
                    CHECK (lifecycle <> 'replaced' OR replacement_xref_id IS NOT NULL)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_cq (
                    id                  TEXT PRIMARY KEY,
                    schema_version_id   INTEGER NOT NULL REFERENCES schema_version(id),
                    question            TEXT NOT NULL,
                    requires_json       TEXT NOT NULL DEFAULT '[]',
                    reviewer            TEXT NOT NULL,
                    provenance          TEXT NOT NULL,
                    created_ts          REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schema_cq_version "
                "ON schema_cq (schema_version_id, created_ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_term_alias_term "
                "ON term_alias (term_id, created_ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_term_xref_term "
                "ON term_xref (term_id, lifecycle)"
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS ontology_term_identity_immutable
                BEFORE UPDATE OF id, iri ON ontology_term
                WHEN NEW.id IS NOT OLD.id OR NEW.iri IS NOT OLD.iri
                BEGIN
                    SELECT RAISE(ABORT, 'ontology term identity is immutable');
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS term_xref_mapping_immutable
                BEFORE UPDATE OF id, term_id, authority, external_id,
                    mapping_predicate, source_uri, source_version, valid_from,
                    valid_to, retrieved_at, confidence, license_gate, created_ts
                ON term_xref
                BEGIN
                    SELECT RAISE(ABORT, 'term xref mappings are append-oriented');
                END
                """
            )
            from ontologylab.kgstore import KGStore
            KGStore._backfill_legacy_ontology_terms(conn)
            succeeded = True
        finally:
            if not succeeded:
                conn.execute("ROLLBACK TO ontology_term_migration")
            conn.execute("RELEASE ontology_term_migration")

    @staticmethod
    def _backfill_legacy_ontology_terms(
        conn: sqlite3.Connection,
        *,
        reviewer: str = default_schema.LEGACY_TERM_REVIEWER,
        provenance: str = default_schema.LEGACY_TERM_PROVENANCE,
    ) -> None:
        """Give each legacy type one random identity, once."""
        rows = conn.execute(
            """
            SELECT 'entity_type' AS legacy_kind, et.id AS legacy_id,
                   et.schema_version_id, et.name AS preferred_label,
                   COALESCE(et.description, '') AS definition
            FROM entity_type AS et
            LEFT JOIN ontology_term AS ot
              ON ot.legacy_kind = 'entity_type' AND ot.legacy_id = et.id
            WHERE ot.id IS NULL
            UNION ALL
            SELECT 'relation_type', rt.id, rt.schema_version_id, rt.name,
                   COALESCE(rt.description, '')
            FROM relation_type AS rt
            LEFT JOIN ontology_term AS ot
              ON ot.legacy_kind = 'relation_type' AND ot.legacy_id = rt.id
            WHERE ot.id IS NULL
            ORDER BY legacy_kind, legacy_id
            """
        ).fetchall()
        now = time.time()
        for row in rows:
            from ontologylab.kgstore import KGStore
            KGStore._insert_ontology_term_row(
                conn,
                preferred_label=row["preferred_label"],
                language=default_schema.DEFAULT_TERM_LANGUAGE,
                definition=row["definition"],
                schema_version_id=row["schema_version_id"],
                reviewer=reviewer,
                provenance=provenance,
                now=now,
                legacy_kind=row["legacy_kind"],
                legacy_id=row["legacy_id"],
            )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "KGStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _table_exists(self, name: str) -> bool:
        """True when ``name`` exists — read-only packs built before a table
        was added to _SCHEMA cannot be migrated, so W7+ features degrade
        gracefully on them instead of failing every open."""
        return self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone() is not None

    def rebuild_fts(self) -> None:
        """Rebuild the FTS5 index from the nodes content table."""
        self._assert_writable()
        self.conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
        self.conn.commit()

    def _assert_writable(self) -> None:
        if self.read_only:
            raise KGStoreError("store is read-only (immutable pack)")
