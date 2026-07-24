"""Knowledge-pack build: verified-only export into an immutable directory.

A pack is the single deployable unit the MCP server serves:

    packs/<pack_id>/
      pack.sqlite       verified-only copy (same schema as the working DB)
      schema.json       active ontology export
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

import hashlib
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from ontologylab import __version__
from ontologylab.kgstore import _SCHEMA, KGStore
from ontologylab.models import PackManifest


class PackBuildError(Exception):
    """Raised when a pack cannot be built."""


# A pack id/name becomes a directory segment under packs_dir. Restrict it to a
# safe charset so a caller-supplied value (HTTP build request, MCP tool arg)
# cannot contain "/" or ".." and escape packs_dir — either to drop files into
# an arbitrary write location or to read a pack.sqlite from outside the store.
_SAFE_PACK_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


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


def build_pack(
    kg_db_path: str | Path,
    packs_dir: str | Path,
    name: str,
    *,
    source_job_id: str | None = None,
    provenance_jsonl: str | Path | None = None,
    summarizer=None,
    summary_method: str = "extractive",
) -> PackManifest:
    """Snapshot the verified subgraph into a new immutable pack directory.

    W12: communities are detected (deterministic label propagation) and
    summarized ONCE here, so the shipped pack answers corpus-level "main
    themes" questions without recomputation. ``summarizer`` optionally
    replaces the extractive summaries (e.g. LLM-backed, fail-open); pass
    ``summary_method`` to label how those summaries were made.
    """
    safe_pack_component(name, kind="pack name")
    kg_db_path = Path(kg_db_path)
    if not kg_db_path.is_file():
        raise PackBuildError(f"working KG not found: {kg_db_path}")
    # Ensure the source DB carries the current schema (e.g. W13 bitemporal
    # columns) before the column-order-sensitive INSERT..SELECT * below.
    KGStore.open(kg_db_path).close()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    pack_id = f"{name}-{stamp}"
    pack_dir = Path(packs_dir) / pack_id
    if pack_dir.exists():
        raise PackBuildError(f"pack directory already exists: {pack_dir}")
    pack_dir.mkdir(parents=True)
    pack_sqlite = pack_dir / "pack.sqlite"

    conn = sqlite3.connect(str(pack_sqlite))
    try:
        conn.executescript(_SCHEMA)
        # The pack is immutable once built: its FTS index comes from the
        # single 'rebuild' below, so the working-DB sync triggers are dropped
        # up front (avoids indexing every row twice during the bulk INSERT,
        # and a read-only file never fires them anyway).
        for trigger in ("nodes_fts_ai", "nodes_fts_ad", "nodes_fts_au"):
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        conn.execute("ATTACH DATABASE ? AS live", (str(kg_db_path),))

        # Verified subgraph and everything it cites, in dependency order.
        conn.execute(
            "INSERT INTO main.schema_version SELECT * FROM live.schema_version"
        )
        conn.execute("INSERT INTO main.entity_type SELECT * FROM live.entity_type")
        conn.execute(
            "INSERT INTO main.relation_type SELECT * FROM live.relation_type"
        )
        conn.execute(
            "INSERT INTO main.documents SELECT * FROM live.documents WHERE id IN ("
            "  SELECT source_doc_id FROM live.nodes WHERE status='verified'"
            "  UNION SELECT source_doc_id FROM live.edges WHERE status='verified'"
            "  UNION SELECT c.source_doc_id FROM live.citations c"
            ")"
        )
        conn.execute(
            "INSERT INTO main.nodes SELECT * FROM live.nodes WHERE status='verified'"
        )
        # W13: invalidated edges are history, not current truth — a pack
        # ships only what is currently valid.
        conn.execute(
            "INSERT INTO main.edges SELECT e.* FROM live.edges e "
            "JOIN live.nodes s ON s.id = e.src_node_id AND s.status='verified' "
            "JOIN live.nodes d ON d.id = e.dst_node_id AND d.status='verified' "
            "WHERE e.status='verified' AND e.invalidated_ts IS NULL"
        )
        conn.execute(
            "INSERT INTO main.node_aliases SELECT a.* FROM live.node_aliases a "
            "JOIN main.nodes n ON n.id = a.node_id"
        )
        conn.execute(
            "INSERT INTO main.citations SELECT c.* FROM live.citations c WHERE "
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

        counts = {
            "documents": _count(conn, "documents"),
            "nodes_verified": _count(conn, "nodes"),
            "edges_verified": _count(conn, "edges"),
            "entity_types": _count(conn, "entity_type"),
            "relation_types": _count(conn, "relation_type"),
            "communities": _count(conn, "communities"),
        }
    finally:
        conn.close()

    content_hash = "sha256:" + hashlib.sha256(pack_sqlite.read_bytes()).hexdigest()

    # schema.json: ontology export readable without opening sqlite.
    pack_store = KGStore.open(pack_sqlite, read_only=True)
    try:
        schema = pack_store.get_schema()
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
    )
    (pack_dir / "manifest.json").write_text(
        json.dumps(manifest.__dict__, indent=2), encoding="utf-8"
    )

    if provenance_jsonl and Path(provenance_jsonl).is_file():
        shutil.copyfile(provenance_jsonl, pack_dir / "provenance.jsonl")
    else:
        (pack_dir / "provenance.jsonl").write_text(
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
    return manifest


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def list_packs(packs_dir: str | Path) -> list[dict[str, Any]]:
    """Discover packs by directory scan + manifest.json (no packs table —
    the filesystem is the single source of truth)."""
    packs: list[dict[str, Any]] = []
    packs_path = Path(packs_dir)
    if not packs_path.is_dir():
        return packs
    for entry in sorted(packs_path.iterdir()):
        manifest_path = entry / "manifest.json"
        if not (entry.is_dir() and manifest_path.is_file()):
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (entry / "pack.sqlite").is_file():
            packs.append(manifest)
    return packs


def pack_sqlite_path(packs_dir: str | Path, pack_id: str) -> Path:
    # pack_id arrives from callers including MCP tool args and HTTP params;
    # validate it as a single safe segment so "../../x" cannot read a
    # pack.sqlite from outside packs_dir (path traversal).
    safe_pack_component(pack_id, kind="pack id")
    path = Path(packs_dir) / pack_id / "pack.sqlite"
    if not path.is_file():
        raise PackBuildError(f"pack {pack_id!r} not found under {packs_dir}")
    return path
