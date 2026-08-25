"""Knowledge-pack build: verified-only export into an immutable directory.

A pack is the single deployable unit the MCP server serves:

    packs/<pack_id>/
      pack.sqlite       verified-only copy (same schema as the working DB)
      schema.json       ontology export (active alias + per-version schemas)
      manifest.json     identity, counts, content hash
      provenance.jsonl  build-job audit log copy

Build physics (ARCHITECTURE.md §6): copy the verified subgraph and
everything it cites across an ATTACHed pair in dependency order, rebuild the
FTS5 index INTO the pack (a row-copy would lose the virtual table's shadow
tables), finalize as a WAL-free, checkpointed, VACUUMed file, then content-
hash the bytes. ``proposed``/``rejected`` rows never leave the working
database. Packs are immutable and additive: a rebuild produces a new
pack_id, never mutates one in place.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from ontologylab import __version__
from ontologylab.kgstore import _SCHEMA, KGStore
from ontologylab.models import PackManifest
from ontologylab.method_pack import (
    MethodPackError,
    MethodPackSql,
    copy_method_releases,
    methodology_manifest,
    reject_duplicate_release_ids,
    validate_method_pack,
)
from ontologylab.pack_completeness import extraction_completeness, with_override
from ontologylab.paths import MAX_JOB_DIR_ATTEMPTS
from ontologylab.semantic_staleness import semantic_baseline_marker
from ontologylab.verified_pack_reader import (
    PackIntegrityError,
    inspect_verified_manifest,
)


class PackBuildError(Exception):
    """Raised when a pack cannot be built."""


class IncompleteExtractionError(PackBuildError):
    """Typed default refusal for incomplete or unknown shipped streams."""

    code = "incomplete_extraction"

    def __init__(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        runs = ", ".join(
            f"{status}={count}"
            for status, count in summary["run_status_counts"].items()
        ) or "none"
        chunks = ", ".join(
            f"{status}={count}"
            for status, count in summary["chunk_status_counts"].items()
        ) or "none"
        super().__init__(
            "pack build refused: extraction incomplete for shipped fact streams "
            f"(unknown={len(summary['unknown_streams'])}; runs: {runs}; "
            f"chunks: {chunks}). Use an explicit incomplete-extraction override "
            "with operator intent to proceed."
        )


# A pack id/name becomes a directory segment under packs_dir. Restrict it to a
# safe charset so a caller-supplied value (HTTP build request, MCP tool arg)
# cannot contain "/" or ".." and escape packs_dir — either to drop files into
# an arbitrary write location or to read a pack.sqlite from outside the store.
_SAFE_PACK_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")

# ATTACH copies must bind by column name, never by physical table order.
# Additive SQLite migrations append columns while fresh CREATE TABLE schemas
# can place the same column elsewhere; SELECT * would then silently shift data
# (or fail a NOT NULL constraint) when packing an existing user database.
_PACK_COPY_COLUMNS: dict[str, tuple[str, ...]] = {
    "schema_version": ("id", "label", "description", "created_ts", "is_active"),
    "entity_type": (
        "id", "schema_version_id", "name", "description", "attributes_json",
    ),
    "relation_type": (
        "id", "schema_version_id", "name", "description", "domain_type",
        "range_type", "directed", "qualifiers_json",
    ),
    "documents": (
        "id", "source_kind", "source_uri", "title", "fetched_ts",
        "content_hash", "raw_text_path", "doi", "source", "evidence_grade",
    ),
    "nodes": (
        "id", "schema_version_id", "entity_type", "name", "normalized_name",
        "aliases_json", "properties_json", "status", "confidence",
        "source_doc_id", "source_span", "extractor_engine", "extractor_model",
        "prompt_version", "created_ts", "verified_ts", "verified_by",
        "review_note", "embedding", "embedding_model", "decode_params",
    ),
    "edges": (
        "id", "schema_version_id", "relation_type", "src_node_id",
        "dst_node_id", "properties_json", "qualifiers_json", "status",
        "confidence", "source_doc_id", "source_span", "extractor_engine",
        "extractor_model", "prompt_version", "created_ts", "verified_ts",
        "verified_by", "review_note", "valid_from", "invalidated_ts",
        "invalidated_by", "invalidation_reason", "decode_params",
    ),
    "node_aliases": ("node_id", "normalized_alias", "surface"),
    "citations": (
        "kind", "item_id", "source_doc_id", "source_span", "created_ts",
        "extractor_engine", "extractor_model", "prompt_version", "decode_params",
    ),
    "ontology_term": (
        "id", "iri", "preferred_label", "language", "definition", "lifecycle",
        "replacement_term_id", "change_reason", "schema_version_id", "reviewer",
        "provenance", "created_ts", "updated_ts", "legacy_kind", "legacy_id",
    ),
    "term_alias": (
        "id", "term_id", "label", "language", "alias_kind", "reviewer",
        "provenance", "created_ts",
    ),
    "term_xref": (
        "id", "term_id", "authority", "external_id", "mapping_predicate",
        "source_uri", "source_version", "valid_from", "valid_to", "retrieved_at",
        "confidence", "reviewer", "lifecycle", "replacement_xref_id",
        "change_reason", "license_gate", "created_ts", "updated_ts",
    ),
}


def _copy_columns(table: str, *, alias: str | None = None) -> str:
    columns = _PACK_COPY_COLUMNS[table]
    prefix = f"{alias}." if alias else ""
    return ", ".join(f"{prefix}{column}" for column in columns)


def _prepare_publishable_ontology(conn: sqlite3.Connection) -> None:
    """Materialize the explicit P1-A review and xref publication boundary.

    P1-A has no review-status column. A term is reviewed exactly when its
    current reviewer and provenance are non-empty; lifecycle is independent
    audit state. Xrefs additionally need the complete committed source,
    confidence, lifecycle, and license contract. Replacement chains fail
    closed rather than shipping a logically dangling predecessor.
    """
    conn.execute(
        "CREATE TEMP TABLE publishable_ontology_term_id "
        "(id TEXT PRIMARY KEY) WITHOUT ROWID"
    )
    conn.execute(
        "INSERT INTO publishable_ontology_term_id (id) "
        "SELECT id FROM live.ontology_term "
        "WHERE typeof(reviewer) = 'text' AND length(trim(reviewer)) > 0 "
        "AND typeof(provenance) = 'text' AND length(trim(provenance)) > 0 "
        "ORDER BY id"
    )
    dangling_term = conn.execute(
        "SELECT t.id, t.replacement_term_id FROM live.ontology_term AS t "
        "JOIN publishable_ontology_term_id AS published ON published.id = t.id "
        "WHERE t.replacement_term_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM publishable_ontology_term_id AS replacement "
        "WHERE replacement.id = t.replacement_term_id) ORDER BY t.id LIMIT 1"
    ).fetchone()
    if dangling_term is not None:
        raise PackBuildError(
            "ontology publication refused: publishable term replacement "
            f"{dangling_term['id']!r} targets non-publishable "
            f"{dangling_term['replacement_term_id']!r}"
        )

    conn.execute(
        "CREATE TEMP TABLE publishable_term_xref_id "
        "(id TEXT PRIMARY KEY) WITHOUT ROWID"
    )
    conn.execute(
        """
        INSERT INTO publishable_term_xref_id (id)
        SELECT x.id FROM live.term_xref AS x
        JOIN publishable_ontology_term_id AS term ON term.id = x.term_id
        WHERE typeof(x.authority) = 'text' AND length(trim(x.authority)) > 0
          AND typeof(x.external_id) = 'text' AND length(trim(x.external_id)) > 0
          AND x.mapping_predicate IN (
                'exact', 'close', 'broader', 'narrower', 'related', 'advisory')
          AND typeof(x.source_uri) = 'text' AND length(trim(x.source_uri)) > 0
          AND ((typeof(x.source_version) = 'text'
                AND length(trim(x.source_version)) > 0)
               OR typeof(x.valid_from) IN ('integer', 'real')
               OR typeof(x.valid_to) IN ('integer', 'real'))
          AND (x.valid_to IS NULL OR x.valid_from IS NULL
               OR x.valid_to >= x.valid_from)
          AND typeof(x.retrieved_at) IN ('integer', 'real')
          AND typeof(x.confidence) IN ('integer', 'real')
          AND x.confidence >= 0.0 AND x.confidence <= 1.0
          AND typeof(x.reviewer) = 'text' AND length(trim(x.reviewer)) > 0
          AND x.lifecycle IN ('active', 'deprecated', 'replaced')
          AND (x.lifecycle = 'active' OR (
                typeof(x.change_reason) = 'text'
                AND length(trim(x.change_reason)) > 0))
          AND (x.lifecycle <> 'replaced' OR x.replacement_xref_id IS NOT NULL)
          AND (x.replacement_xref_id IS NULL OR x.replacement_xref_id <> x.id)
          AND x.license_gate IN ('allow', 'identifier-only', 'deny-text')
        ORDER BY x.id
        """
    )
    dangling_xref = conn.execute(
        "SELECT x.id, x.replacement_xref_id FROM live.term_xref AS x "
        "JOIN publishable_term_xref_id AS published ON published.id = x.id "
        "LEFT JOIN live.term_xref AS replacement "
        "ON replacement.id = x.replacement_xref_id "
        "LEFT JOIN publishable_term_xref_id AS published_replacement "
        "ON published_replacement.id = x.replacement_xref_id "
        "WHERE x.replacement_xref_id IS NOT NULL AND ("
        "published_replacement.id IS NULL OR replacement.term_id <> x.term_id) "
        "ORDER BY x.id LIMIT 1"
    ).fetchone()
    if dangling_xref is not None:
        raise PackBuildError(
            "ontology publication refused: publishable xref replacement "
            f"{dangling_xref['id']!r} has a non-publishable or cross-term target "
            f"{dangling_xref['replacement_xref_id']!r}"
        )


def safe_pack_component(value: str, *, kind: str = "pack name") -> str:
    """Return ``value`` if it is a safe single path segment, else raise.

    Rejects empty strings, ``.``/``..``, and anything with a path separator or
    character outside ``[A-Za-z0-9._-]``.
    """
    if not value or value in (".", "..") or not _SAFE_PACK_COMPONENT.match(value):
        raise PackBuildError(
            f"invalid {kind} {value!r}: use only letters, digits, '.', '_', '-' "
            "(no path separators)"
        )
    return value


# The documented default staleness policy, embedded in every manifest so a
# consumer has a shipped baseline instead of inventing its own. Advisory and
# overridable: a threshold of 0 reads "any verified item the pack does not
# reflect is a reason to consider rebuilding".
DEFAULT_STALENESS_POLICY: dict[str, Any] = {
    "pending_verified_count_threshold": 0,
    "description": (
        "pending_verified_count is a backward-compatible count-difference "
        "advisory, not semantic truth. Semantic additions, invalidations, and "
        "replacements are authoritative; any nonzero delta recommends rebuilding."
    ),
}

# Stable sentinels distinguish the explicit P1-A boundary from a guessed
# status heuristic. All license modes retain the exact identifier/provenance
# row; external descriptive text is not a field in the term_xref schema.
ONTOLOGY_PUBLICATION_POLICY: dict[str, Any] = {
    "version": 1,
    "review_boundary": "explicit-current-review-fields-v1",
    "xref_verification": "complete-source-license-contract-v1",
    "license_modes": ["allow", "identifier-only", "deny-text"],
    "external_descriptive_text": "not-in-term-xref-schema",
}


def _git_head() -> str | None:
    """HEAD of the repository this code runs from, or None when there is none.

    A pack must say what it was built against so an agent can judge how much
    has happened since. The candidate is the package's parent directory,
    which is the repo in a checkout and site-packages in an install — git
    answers for us, and any failure (not a repo, no git, timeout) is None,
    never a fabricated hash.
    """
    candidate = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head if len(head) == 40 else None


def _build_pack_unlocked(
    kg_db_path: str | Path,
    packs_dir: str | Path,
    name: str,
    *,
    source_job_id: str | None = None,
    provenance_jsonl: str | Path | None = None,
    summarizer=None,
    summary_method: str = "extractive",
    allow_incomplete_extraction: bool = False,
    incomplete_extraction_intent: str | None = None,
    method_release_ids: Sequence[str] = (),
    evidence_mode: str | None = None,
    owned_stages: list[Path],
) -> PackManifest:
    """Snapshot the verified subgraph into a new immutable pack directory.

    W12: communities are detected (deterministic label propagation) and
    summarized ONCE here, so the shipped pack answers corpus-level "main
    themes" questions without recomputation. ``summarizer`` optionally
    replaces the extractive summaries (e.g. LLM-backed, fail-open); pass
    ``summary_method`` to label how those summaries were made.
    """
    safe_pack_component(name, kind="pack name")
    try:
        method_release_ids = reject_duplicate_release_ids(
            method_release_ids
        )
    except MethodPackError as exc:
        raise PackBuildError(str(exc)) from exc
    kg_db_path = Path(kg_db_path)
    if not kg_db_path.is_file():
        raise PackBuildError(f"working KG not found: {kg_db_path}")
    intent = (incomplete_extraction_intent or "").strip() or None
    if allow_incomplete_extraction and intent is None:
        raise PackBuildError(
            "incomplete-extraction override requires non-empty operator intent"
        )
    if intent is not None and not allow_incomplete_extraction:
        raise PackBuildError(
            "operator intent was supplied without enabling the "
            "incomplete-extraction override"
        )

    # Migrate the working database first, then take one SQLite-consistent
    # snapshot. Both the completeness gate and every exported source row read
    # these exact bytes, so a concurrent write cannot pass one view and ship
    # from another.
    source_store = KGStore.open(kg_db_path)
    snapshot_tmp = tempfile.TemporaryDirectory(prefix="ontologylab-pack-")
    snapshot_path = Path(snapshot_tmp.name) / "source.sqlite"
    snapshot_conn = sqlite3.connect(snapshot_path)
    snapshot_conn.row_factory = sqlite3.Row
    try:
        source_store.conn.backup(snapshot_conn)
    finally:
        source_store.close()
    completeness = extraction_completeness(snapshot_conn)
    override_used = completeness["status"] == "incomplete" and allow_incomplete_extraction
    completeness = with_override(
        completeness,
        used=override_used,
        operator_intent=intent if override_used else None,
    )
    v2_closure = None
    snapshot_ready = False
    try:
        if evidence_mode is not None:
            from ontologylab.pack_v2_closure import (
                PackV2ClosureCode,
                PackV2ClosureRefused,
                collect_v2_closure,
                parse_evidence_mode,
            )
            v2_mode = parse_evidence_mode(evidence_mode)
            if completeness["status"] == "incomplete":
                raise PackV2ClosureRefused(
                    PackV2ClosureCode.INCOMPLETE_STREAM, "stream",
                )
            v2_closure = collect_v2_closure(
                snapshot_conn,
                evidence_mode=v2_mode,
                source_root=kg_db_path.parent,
            )
        elif completeness["status"] == "incomplete" and not override_used:
            raise IncompleteExtractionError(completeness)
        snapshot_ready = True
    finally:
        if not snapshot_ready:
            snapshot_conn.close()
            snapshot_tmp.cleanup()
    preflight = sqlite3.connect(":memory:")
    try:
        try:
            method_selection = copy_method_releases(
                MethodPackSql(
                    snapshot_conn,
                    preflight,
                    source_root=kg_db_path.parent,
                    snapshot_path=snapshot_path,
                ),
                method_release_ids,
            )
            if method_selection.release_ids:
                validate_method_pack(preflight, method_selection)
        except MethodPackError as exc:
            raise PackBuildError(str(exc)) from exc
    except BaseException:
        snapshot_conn.close()
        snapshot_tmp.cleanup()
        raise
    finally:
        preflight.close()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    packs_path = Path(packs_dir)
    packs_path.mkdir(parents=True, exist_ok=True)
    for suffix in range(1, MAX_JOB_DIR_ATTEMPTS + 1):
        pack_id = (
            f"{name}-{stamp}" if suffix == 1
            else f"{name}-{stamp}-{suffix}"
        )
        final_pack_dir = packs_path / pack_id
        if not final_pack_dir.exists():
            break
    else:
        snapshot_conn.close()
        snapshot_tmp.cleanup()
        raise PackBuildError(
            f"could not allocate a pack directory for {name!r} after "
            f"{MAX_JOB_DIR_ATTEMPTS} attempts"
        )
    # Build every byte in a sibling staging directory outside packs_path, so
    # even a concurrent list_packs scan cannot discover it. TemporaryDirectory
    # removes it on any exception; only the final same-filesystem atomic rename
    # makes the complete pack visible to list_packs or MCP.
    staging_tmp = tempfile.TemporaryDirectory(
        prefix=f".{packs_path.name}-{pack_id}-staging-", dir=packs_path.parent
    )
    pack_dir = Path(staging_tmp.name)
    owned_stages.append(pack_dir)
    pack_sqlite = pack_dir / "pack.sqlite"

    conn = sqlite3.connect(str(pack_sqlite))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        if v2_closure is not None:
            from ontologylab.pack_v2_closure import install_v2_pack_schema

            install_v2_pack_schema(conn)
        # P1-A adds these tables through the writable-store migration rather
        # than _SCHEMA. Create the same committed schema in the empty pack;
        # backfill sees no type rows yet, so only DDL is materialized here.
        KGStore._migrate_ontology_terms(conn)
        # The pack is immutable once built: its FTS index comes from the
        # single 'rebuild' below, so the working-DB sync triggers are dropped
        # up front (avoids indexing every row twice during the bulk INSERT,
        # and a read-only file never fires them anyway).
        for trigger in ("nodes_fts_ai", "nodes_fts_ad", "nodes_fts_au"):
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        conn.execute("ATTACH DATABASE ? AS live", (str(snapshot_path),))

        # Verified subgraph and everything it cites, in dependency order.
        # Both sides name columns explicitly: migrated stores can have a
        # different physical order from the current fresh-create schema.
        for table in ("schema_version", "entity_type", "relation_type"):
            columns = _copy_columns(table)
            conn.execute(
                f"INSERT INTO main.{table} ({columns}) "
                f"SELECT {columns} FROM live.{table}"
            )

        # Reviewed ontology publication follows its FK dependency order.
        # Exact named projections preserve every local term audit field and
        # every xref identifier/provenance field. P1-A term_xref deliberately
        # has no external descriptive-text column to redact or reinterpret.
        _prepare_publishable_ontology(conn)
        term_columns = _copy_columns("ontology_term")
        term_projection = _copy_columns("ontology_term", alias="t")
        conn.execute(
            f"INSERT INTO main.ontology_term ({term_columns}) "
            f"SELECT {term_projection} FROM live.ontology_term AS t "
            "JOIN publishable_ontology_term_id AS published ON published.id = t.id "
            "ORDER BY t.id"
        )
        alias_columns = _copy_columns("term_alias")
        alias_projection = _copy_columns("term_alias", alias="a")
        conn.execute(
            f"INSERT INTO main.term_alias ({alias_columns}) "
            f"SELECT {alias_projection} FROM live.term_alias AS a "
            "JOIN publishable_ontology_term_id AS term ON term.id = a.term_id "
            "WHERE typeof(a.reviewer) = 'text' AND length(trim(a.reviewer)) > 0 "
            "AND typeof(a.provenance) = 'text' AND length(trim(a.provenance)) > 0 "
            "ORDER BY a.id"
        )
        xref_columns = _copy_columns("term_xref")
        xref_projection = _copy_columns("term_xref", alias="x")
        conn.execute(
            f"INSERT INTO main.term_xref ({xref_columns}) "
            f"SELECT {xref_projection} FROM live.term_xref AS x "
            "JOIN publishable_term_xref_id AS published ON published.id = x.id "
            "ORDER BY x.id"
        )

        document_columns = _copy_columns("documents")
        conn.execute(
            f"INSERT INTO main.documents ({document_columns}) "
            f"SELECT {document_columns} FROM live.documents WHERE id IN ("
            "  SELECT source_doc_id FROM live.nodes WHERE status='verified'"
            "  UNION SELECT source_doc_id FROM live.edges WHERE status='verified'"
            "  UNION SELECT c.source_doc_id FROM live.citations c"
            ")"
        )
        node_columns = _copy_columns("nodes")
        conn.execute(
            f"INSERT INTO main.nodes ({node_columns}) "
            f"SELECT {node_columns} FROM live.nodes WHERE status='verified'"
        )
        # W13: invalidated edges are history, not current truth — a pack
        # ships only what is currently valid.
        edge_columns = _copy_columns("edges")
        edge_projection = _copy_columns("edges", alias="e")
        conn.execute(
            f"INSERT INTO main.edges ({edge_columns}) SELECT {edge_projection} "
            "FROM live.edges e "
            "JOIN live.nodes s ON s.id = e.src_node_id AND s.status='verified' "
            "JOIN live.nodes d ON d.id = e.dst_node_id AND d.status='verified' "
            "WHERE e.status='verified' AND e.invalidated_ts IS NULL"
        )
        alias_columns = _copy_columns("node_aliases")
        alias_projection = _copy_columns("node_aliases", alias="a")
        conn.execute(
            f"INSERT INTO main.node_aliases ({alias_columns}) "
            f"SELECT {alias_projection} FROM live.node_aliases a "
            "JOIN main.nodes n ON n.id = a.node_id"
        )
        citation_columns = _copy_columns("citations")
        citation_projection = _copy_columns("citations", alias="c")
        conn.execute(
            f"INSERT INTO main.citations ({citation_columns}) "
            f"SELECT {citation_projection} FROM live.citations c WHERE "
            "(c.kind='node' AND c.item_id IN (SELECT id FROM main.nodes)) OR "
            "(c.kind='edge' AND c.item_id IN (SELECT id FROM main.edges))"
        )
        # documents copied above may over-include docs cited only by
        # non-verified items; trim to what the pack actually references.
        conn.execute(
            "DELETE FROM main.documents WHERE id NOT IN ("
            "  SELECT source_doc_id FROM main.nodes"
            "  UNION SELECT source_doc_id FROM main.edges"
            "  UNION SELECT source_doc_id FROM main.citations"
            ")"
        )
        if v2_closure is not None:
            from ontologylab.pack_v2_closure import copy_v2_tables

            copy_v2_tables(conn, v2_closure)
        conn.commit()
        conn.execute("DETACH DATABASE live")

        # W12: communities over the (verified-only) pack contents.
        from ontologylab.communities import build_communities

        community_nodes = [
            {"id": r[0], "name": r[1]}
            for r in conn.execute("SELECT id, name FROM nodes")
        ]
        community_edges = [
            {"source_id": r[0], "target_id": r[1], "relation_type": r[2]}
            for r in conn.execute(
                "SELECT src_node_id, dst_node_id, relation_type FROM edges"
            )
        ]
        community_rows = build_communities(
            community_nodes,
            community_edges,
            summarizer=summarizer,
            summary_method=summary_method,
        )
        now = time.time()
        for row in community_rows:
            conn.execute(
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
            conn.executemany(
                "INSERT INTO community_members (community_id, node_id) "
                "VALUES (?, ?)",
                [(row["id"], node_id) for node_id in row["members"]],
            )
        try:
            method_selection = copy_method_releases(
                MethodPackSql(
                    snapshot_conn,
                    conn,
                    source_root=kg_db_path.parent,
                    snapshot_path=snapshot_path,
                ),
                method_release_ids,
            )
        except MethodPackError as exc:
            raise PackBuildError(str(exc)) from exc
        conn.commit()

        # Finalize for read-only serving: WAL off, optimized, vacuumed.
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA optimize")
        conn.execute("VACUUM")
        conn.commit()

        # Rebuild FTS5 INTO the pack AFTER VACUUM: nodes has a TEXT primary
        # key, so its implicit rowids may be renumbered by VACUUM — an index
        # built earlier would join FTS docids against stale rowids. Building
        # last guarantees docid/rowid alignment in the shipped file.
        conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
        conn.commit()
        if method_selection.release_ids:
            validate_method_pack(conn, method_selection)

        counts = {
            "documents": _count(conn, "documents"),
            "nodes_verified": _count(conn, "nodes"),
            "edges_verified": _count(conn, "edges"),
            "entity_types": _count(conn, "entity_type"),
            "relation_types": _count(conn, "relation_type"),
            "communities": _count(conn, "communities"),
            "ontology_terms_reviewed": _count(conn, "ontology_term"),
            "term_aliases_reviewed": _count(conn, "term_alias"),
            "term_xrefs_reviewed": _count(conn, "term_xref"),
        }
    finally:
        conn.close()
        snapshot_conn.close()
        snapshot_tmp.cleanup()

    content_hash = "sha256:" + hashlib.sha256(pack_sqlite.read_bytes()).hexdigest()

    # schema.json: ontology export readable without opening sqlite.
    pack_store = KGStore.open(pack_sqlite, read_only=True)
    try:
        schema = pack_store.get_schema()
        # Every schema version whose verified facts the pack ships. The pack
        # preserves facts judged under historical ontologies, so a consumer
        # must be able to resolve each fact's schema_version_id from pack
        # contents — never a silent fallback to the active schema.
        included_schema_version_ids = [
            row[0]
            for row in pack_store.conn.execute(
                "SELECT schema_version_id FROM nodes "
                "UNION SELECT schema_version_id FROM edges "
                "UNION SELECT schema_version_id FROM ontology_term "
                "ORDER BY schema_version_id"
            )
        ]
        # Version-keyed full definitions, keyed by schema_version_id. The
        # top-level fields stay the ACTIVE schema as compatibility aliases.
        schema["schemas"] = {
            str(version_id): pack_store.get_schema(schema_version_id=version_id)
            for version_id in included_schema_version_ids
        }
        # Honest tier labeling (§5.4): only claim the vector tier when the
        # pack actually carries embeddings, and record which model made them.
        pack_embedding_model = pack_store.embedding_model()
    finally:
        pack_store.close()
    (pack_dir / "schema.json").write_text(
        json.dumps(schema, indent=2), encoding="utf-8"
    )

    manifest = PackManifest(
        pack_id=pack_id,
        created_ts=time.time(),
        schema_version_id=schema["schema_version_id"],
        schema_label=schema["schema_label"],
        source_job_id=source_job_id,
        counts=counts,
        search_tier="fts5+vec-rrf" if pack_embedding_model else "fts5",
        embedding_model=pack_embedding_model,
        ontologylab_version=__version__,
        content_hash=content_hash,
        basis_commit=_git_head(),
        staleness_policy=dict(DEFAULT_STALENESS_POLICY),
        extraction_completeness=completeness,
        semantic_fact_baseline=semantic_baseline_marker(),
        included_schema_version_ids=included_schema_version_ids,
        ontology_publication=dict(ONTOLOGY_PUBLICATION_POLICY),
        methodology=(
            methodology_manifest(method_selection)
            if method_selection.release_ids
            else None
        ),
        capabilities=(
            ["knowledge-graph-v1", "methodology-v1"]
            if method_selection.release_ids
            else ["knowledge-graph-v1"]
        ),
    )
    # The receipt is computed over the finalized payload (schema.json and
    # provenance.jsonl are written below; pack.sqlite is already staged),
    # so the manifest — which carries the receipt — is written LAST.
    pack_provenance = pack_dir / "provenance.jsonl"
    if provenance_jsonl and Path(provenance_jsonl).is_file():
        shutil.copyfile(provenance_jsonl, pack_provenance)
    else:
        pack_provenance.write_text(
            json.dumps(
                {
                    "ts": time.time(),
                    "step": "build_pack",
                    "payload": {"pack_id": pack_id, "counts": counts},
                }
            )
            + "\n",
            encoding="utf-8",
        )
    if override_used:
        with pack_provenance.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ts": time.time(),
                        "step": "build_pack.extraction_override",
                        "payload": {
                            "summary": completeness,
                            "operator_intent": intent,
                        },
                    }
                )
                + "\n"
            )
    if manifest.methodology is not None:
        with pack_provenance.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ts": time.time(),
                        "step": "build_pack.methodology",
                        "payload": manifest.methodology,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    if v2_closure is not None:
        from ontologylab.pack_v2_closure import v2_manifest_fields, write_v2_evidence
        from ontologylab.pack_v2_manifest import finalize_v2_manifest

        write_v2_evidence(pack_dir, v2_closure, kg_db_path.parent)
        manifest.capabilities = list(v2_closure.capabilities)
        manifest.counts.update(dict(v2_closure.counts))
        manifest.tree_hash = _tree_hash(pack_dir)
        manifest_json = manifest.__dict__.copy()
        if manifest.methodology is None:
            manifest_json.pop("methodology")
        manifest_json.update(v2_manifest_fields(v2_closure))
        finalize_v2_manifest(pack_dir, manifest_json)
    else:
        manifest.tree_hash = _tree_hash(pack_dir)
        manifest_json = manifest.__dict__.copy()
        if manifest.methodology is None:
            manifest_json.pop("methodology")
        (pack_dir / "manifest.json").write_text(
            json.dumps(manifest_json, indent=2), encoding="utf-8"
        )

    if final_pack_dir.exists():
        staging_tmp.cleanup()
        raise PackBuildError(f"pack directory already exists: {final_pack_dir}")
    pack_dir.rename(final_pack_dir)
    staging_tmp.cleanup()
    try:
        final_sqlite = final_pack_dir / "pack.sqlite"
        final_hash = (
            "sha256:" + hashlib.sha256(final_sqlite.read_bytes()).hexdigest()
        )
        if final_hash != manifest.content_hash:
            raise PackBuildError("final pack content hash changed after rename")
        if manifest.methodology is not None:
            connection = sqlite3.connect(
                f"{final_sqlite.resolve().as_uri()}?mode=ro",
                uri=True,
            )
            try:
                validate_method_pack(connection, method_selection)
            finally:
                connection.close()
    except BaseException:
        shutil.rmtree(final_pack_dir)
        raise
    return manifest


def build_pack(
    kg_db_path: str | Path,
    packs_dir: str | Path,
    name: str,
    *,
    source_job_id: str | None = None,
    provenance_jsonl: str | Path | None = None,
    summarizer=None,
    summary_method: str = "extractive",
    allow_incomplete_extraction: bool = False,
    incomplete_extraction_intent: str | None = None,
    method_release_ids: Sequence[str] = (),
    evidence_mode: str | None = None,
) -> PackManifest:
    """Build one pack while serializing release IDs in its packs directory."""
    safe_pack_component(name, kind="pack name")
    try:
        method_release_ids = reject_duplicate_release_ids(
            method_release_ids
        )
    except MethodPackError as exc:
        raise PackBuildError(str(exc)) from exc
    packs_path = Path(packs_dir)
    owned_stages: list[Path] = []
    lock_path = packs_path.parent
    while not lock_path.exists():
        lock_path = lock_path.parent
    lock_fd = os.open(lock_path, os.O_RDONLY)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return _build_pack_unlocked(
            kg_db_path,
            packs_path,
            name,
            source_job_id=source_job_id,
            provenance_jsonl=provenance_jsonl,
            summarizer=summarizer,
            summary_method=summary_method,
            allow_incomplete_extraction=allow_incomplete_extraction,
            incomplete_extraction_intent=incomplete_extraction_intent,
            method_release_ids=method_release_ids,
            evidence_mode=evidence_mode,
            owned_stages=owned_stages,
        )
    finally:
        os.close(lock_fd)
        for stage in owned_stages:
            if stage.exists():
                shutil.rmtree(stage)


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _pack_sqlite_unusable_reason(path: Path) -> str | None:
    """None when ``path`` opens as a pack database, else why it does not.

    A directory that merely contains bytes named pack.sqlite is not a pack:
    the MCP server has to read nodes/edges/documents out of it. Probing the
    same tables the reader needs is the cheapest honest answer, and it is what
    stops the Connection screen from offering a serve command for a file that
    cannot serve.
    """
    try:
        conn = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro",
            uri=True,
        )
    except sqlite3.Error as exc:
        return f"pack.sqlite cannot be opened: {exc}"
    try:
        for table in ("nodes", "edges", "documents"):
            conn.execute(f"SELECT COUNT(*) FROM {table}")
    except sqlite3.Error as exc:
        return f"pack.sqlite is not a usable pack database: {exc}"
    finally:
        conn.close()
    return None


def scan_packs(packs_dir: str | Path) -> tuple[
    list[dict[str, Any]], list[dict[str, str]]
]:
    """Scan ``packs_dir`` and split it into usable packs and rejects.

    Returns ``(packs, unusable)``. ``packs`` holds validated manifests in
    directory order; ``unusable`` holds ``{"pack_dir", "reason"}`` for every
    directory that carries a manifest.json but is not a servable pack, so an
    operator can be told why a directory they created does not show up.
    Directories with no manifest.json at all are not pack attempts and are
    silently skipped, as before.
    """
    packs: list[dict[str, Any]] = []
    unusable: list[dict[str, str]] = []
    packs_path = Path(packs_dir)
    if not packs_path.is_dir():
        return packs, unusable
    for entry in sorted(packs_path.iterdir()):
        manifest_path = entry / "manifest.json"
        if not (entry.is_dir() and manifest_path.is_file()):
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            unusable.append(
                {"pack_dir": entry.name, "reason": f"manifest.json unreadable: {exc}"}
            )
            continue
        if not isinstance(manifest, dict):
            unusable.append(
                {
                    "pack_dir": entry.name,
                    "reason": "manifest.json must be a JSON object, got "
                    f"{type(manifest).__name__}",
                }
            )
            continue
        pack_id = manifest.get("pack_id")
        if not isinstance(pack_id, str) or not pack_id:
            unusable.append(
                {
                    "pack_dir": entry.name,
                    "reason": "manifest.json has no usable 'pack_id'",
                }
            )
            continue
        try:
            safe_pack_component(pack_id, kind="pack id")
        except PackBuildError as exc:
            unusable.append({"pack_dir": entry.name, "reason": str(exc)})
            continue
        if entry.name != pack_id:
            # load_pack resolves the directory BY pack_id; a directory whose
            # name disagrees with its manifest cannot be served from that
            # id, so discovery must not advertise it as usable.
            unusable.append(
                {
                    "pack_dir": entry.name,
                    "reason": (
                        f"directory name does not match manifest pack_id "
                        f"{pack_id!r}"
                    ),
                }
            )
            continue
        try:
            packs.append(inspect_verified_manifest(entry))
        except PackIntegrityError as exc:
            unusable.append({"pack_dir": entry.name, "reason": str(exc)})
    return packs, unusable


def list_packs(packs_dir: str | Path) -> list[dict[str, Any]]:
    """Discover usable packs by directory scan + manifest.json (no packs
    table — the filesystem is the single source of truth).

    Only validated packs are returned: every element is a manifest object
    with a safe ``pack_id`` backed by a readable pack.sqlite. Callers that
    must explain the skipped directories use :func:`scan_packs`.
    """
    return scan_packs(packs_dir)[0]


# Payload files the tree receipt binds. manifest.json is the receipt root
# and is deliberately not in this list (self-reference).
TREE_HASH_FILES = ("pack.sqlite", "schema.json", "provenance.jsonl")


def _tree_hash(pack_dir: Path) -> str:
    """SHA-256 over (name, file-hash) pairs of the pack payload files.

    A missing payload file hashes as empty, so deleting one changes the
    tree hash and fails verification.
    """
    h = hashlib.sha256()
    for name in TREE_HASH_FILES:
        path = pack_dir / name
        data = path.read_bytes() if path.is_file() else b""
        h.update(name.encode())
        h.update(b"\0")
        h.update(hashlib.sha256(data).hexdigest().encode())
        h.update(b"\n")
    return "sha256:" + h.hexdigest()


def rewrite_existing_pack(packs_dir: str | Path, pack_id: str) -> None:
    """Refuse in-place replacement of an already published pack."""
    from ontologylab.pack_v2_closure import refuse_v1_rewrite

    refuse_v1_rewrite(Path(packs_dir) / pack_id)


def pack_sqlite_path(packs_dir: str | Path, pack_id: str) -> Path:
    # pack_id arrives from callers including MCP tool args and HTTP params;
    # validate it as a single safe segment so "../../x" cannot read a
    # pack.sqlite from outside packs_dir (path traversal).
    safe_pack_component(pack_id, kind="pack id")
    path = Path(packs_dir) / pack_id / "pack.sqlite"
    if not path.is_file():
        raise PackBuildError(f"pack {pack_id!r} not found under {packs_dir}")
    return path
