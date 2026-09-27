"""Carry reviewed facts into another ontology as new, unreviewed proposals."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass

from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.kgstore_base import _execute_sql_script, edge_polarity
from ontologylab.models import ProposedEntity
from ontologylab.paths import DEFAULT_ACTOR
from ontologylab.statement_qualifiers import canonical_qualifiers
from ontologylab.unit_normalization import normalize_measurement


_SCHEMA = """
CREATE TABLE IF NOT EXISTS carry_forward (
    kind TEXT NOT NULL CHECK (kind IN ('node', 'edge')),
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    operator TEXT NOT NULL,
    ts REAL NOT NULL,
    field_hash TEXT NOT NULL,
    PRIMARY KEY (kind, from_id, to_id),
    UNIQUE (kind, to_id)
);
"""


class CarryForwardError(KGStoreError):
    """A carry-forward precondition failed; no proposals were committed."""


@dataclass(frozen=True, slots=True)
class CarryForwardResult:
    nodes: int
    edges: int
    skipped_nodes: int
    skipped_edges: int
    dry_run: bool
    event_id: str | None


def _field_hash(store: KGStore, kind: str, row: sqlite3.Row) -> str:
    """Bind the source snapshot, including every citation and alias."""
    fields = dict(row)
    if kind == "node" and fields["embedding"] is not None:
        fields["embedding"] = fields["embedding"].hex()
    citations = sorted(
        json.dumps(dict(c), sort_keys=True)
        for c in store.conn.execute(
            "SELECT * FROM citations WHERE kind = ? AND item_id = ?",
            (kind, row["id"]),
        )
    )
    aliases = [
        tuple(a) for a in store.conn.execute(
            "SELECT normalized_alias, surface FROM node_aliases "
            "WHERE node_id = ? ORDER BY normalized_alias", (row["id"],),
        )
    ] if kind == "node" else []
    payload = json.dumps([fields, citations, aliases], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def carry_forward(
    store: KGStore,
    from_schema: int,
    to_schema: int,
    *,
    operator: str = DEFAULT_ACTOR,
    dry_run: bool = False,
) -> CarryForwardResult:
    """Preflight a stable snapshot, then atomically insert proposals and audit.

    This owns its transaction: accepting a caller's pending writes would let
    atomic() commit unrelated changes. A real run reserves the writer before
    reading; dry runs use a read snapshot and never perform DDL or DML.
    """
    if from_schema == to_schema:
        raise CarryForwardError("source and target schemas must differ")
    if not operator.strip():
        raise CarryForwardError("operator must not be empty")
    if store.conn.in_transaction or store._tx_depth:
        raise CarryForwardError("carry-forward requires its own transaction")
    if not dry_run:
        store._assert_writable()
    with store.atomic():
        store.conn.execute("BEGIN" if dry_run else "BEGIN IMMEDIATE")
        store._schema_definition(from_schema)
        schema = store._schema_definition(to_schema)
        id_map: dict[str, str] = {}
        node_types: dict[str, str] = {}
        pending: list[tuple[str, str, sqlite3.Row, str, str, str]] = []
        counts = {"node": 0, "edge": 0}
        skipped = {"node": 0, "edge": 0}
        for kind, table in (("node", "nodes"), ("edge", "edges")):
            ledger = {}
            if store._table_exists("carry_forward"):
                ledger = {
                    r["from_id"]: r for r in store.conn.execute(
                        f"SELECT c.* FROM carry_forward c JOIN {table} t "
                        "ON t.id = c.to_id WHERE c.kind = ? "
                        "AND t.schema_version_id = ?", (kind, to_schema),
                    )
                }
            # Check ledgered sources even if they are no longer eligible.
            for source_id, entry in ledger.items():
                source = store.conn.execute(
                    f"SELECT * FROM {table} WHERE id = ?", (source_id,),
                ).fetchone()
                if source is None or _field_hash(store, kind, source) != entry["field_hash"]:
                    raise CarryForwardError(f"stale source {kind} {source_id}: field_hash changed")
            rows = store.conn.execute(
                f"SELECT * FROM {table} WHERE schema_version_id = ? "
                "AND status = 'verified' "
                + ("AND invalidated_ts IS NULL " if kind == "edge" else "")
                + "ORDER BY id", (from_schema,),
            ).fetchall()
            for row in rows:
                source_id = row["id"]
                properties = json.loads(row["properties_json"])
                qualifiers_json = ""
                if kind == "node":
                    store._validate_properties(
                        schema_version_id=to_schema, entity_type=row["entity_type"],
                        properties=properties, schema=schema,
                    )
                    proposal = normalize_measurement(ProposedEntity(
                        id=source_id, entity_type=row["entity_type"],
                        name=row["name"], properties=properties,
                    ))
                    properties = proposal.properties
                    store._validate_properties(
                        schema_version_id=to_schema, entity_type=row["entity_type"],
                        properties=properties, schema=schema,
                    )
                    node_types[source_id] = row["entity_type"]
                else:
                    for endpoint in (row["src_node_id"], row["dst_node_id"]):
                        if endpoint not in id_map:
                            raise CarryForwardError(
                                f"edge {source_id}: endpoint {endpoint} did not carry"
                            )
                    qualifiers = json.loads(row["qualifiers_json"])
                    if edge_polarity(qualifiers):
                        raise CarryForwardError(f"edge {source_id}: source polarity must be empty")
                    store._validate_relation(
                        schema_version_id=to_schema, relation_type=row["relation_type"],
                        src_type=node_types[row["src_node_id"]],
                        dst_type=node_types[row["dst_node_id"]],
                        properties=properties, qualifiers=qualifiers, schema=schema,
                    )
                    qualifiers_json = row["qualifiers_json"]
                entry = ledger.get(source_id)
                if entry is not None:
                    id_map[source_id] = entry["to_id"]
                    skipped[kind] += 1
                    continue
                new_id = uuid.uuid5(
                    uuid.NAMESPACE_URL, f"ontologylab:carry:{kind}:{source_id}:{to_schema}",
                ).hex
                if kind == "node" and store.conn.execute(
                    "SELECT 1 FROM nodes WHERE schema_version_id = ? "
                    "AND entity_type = ? AND normalized_name = ? "
                    "AND status IN ('proposed', 'verified')",
                    (to_schema, row["entity_type"], row["normalized_name"]),
                ).fetchone():
                    raise CarryForwardError(f"target identity already exists for node {source_id}")
                id_map[source_id] = new_id
                pending.append((
                    kind, table, row, json.dumps(properties),
                    qualifiers_json, _field_hash(store, kind, row),
                ))
                counts[kind] += 1
        event_id = None
        if not dry_run and pending:
            _execute_sql_script(store.conn, _SCHEMA)
            now = time.time()
            for kind, table, row, properties_json, qualifiers_json, digest in pending:
                # Explicit columns exclude all verification, invalidation and
                # embedding state. Stream values remain byte-for-byte intact.
                columns = [
                    "id", "schema_version_id", "properties_json", "status",
                    "confidence", "source_doc_id", "source_span", "extractor_engine",
                    "extractor_model", "prompt_version", "decode_params", "origin",
                    "created_ts", "review_note",
                ]
                values = [
                    id_map[row["id"]], to_schema, properties_json, "proposed",
                    *(row[c] for c in columns[4:12]), now,
                    f"carried from {row['id']}, verified by "
                    f"{row['verified_by']} at {row['verified_ts']}",
                ]
                if kind == "node":
                    extra = ["entity_type", "name", "normalized_name", "aliases_json"]
                    columns.extend(extra)
                    values.extend(row[c] for c in extra)
                else:
                    columns.extend([
                        "relation_type", "src_node_id", "dst_node_id",
                        "qualifiers_json", "valid_from", "qualifiers_key",
                    ])
                    values.extend([
                        row["relation_type"], id_map[row["src_node_id"]],
                        id_map[row["dst_node_id"]], qualifiers_json, row["valid_from"],
                        canonical_qualifiers(json.loads(qualifiers_json)),
                    ])
                store.conn.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})", values,
                )
                new_id = id_map[row["id"]]
                store.conn.execute(
                    "INSERT INTO citations SELECT kind, ?, source_doc_id, source_span, "
                    "created_ts, extractor_engine, extractor_model, prompt_version, "
                    "decode_params FROM citations WHERE kind = ? AND item_id = ?",
                    (new_id, kind, row["id"]),
                )
                if kind == "node":
                    store.conn.execute(
                        "INSERT INTO node_aliases SELECT ?, normalized_alias, surface "
                        "FROM node_aliases WHERE node_id = ?", (new_id, row["id"]),
                    )
                store.conn.execute(
                    "INSERT INTO carry_forward VALUES (?, ?, ?, ?, ?, ?)",
                    (kind, row["id"], new_id, operator, now, digest),
                )
            # SQLite is the existing provenance authority. Its normal open-time
            # projector mirrors this committed event; no file can outlive rollback.
            event_id = uuid.uuid4().hex
            store.conn.execute(
                "INSERT INTO provenance_outbox (event_id, step, payload_json, created_ts) "
                "VALUES (?, 'schema.carry_forward', ?, ?)",
                (event_id, json.dumps({
                    "event_id": event_id, "step": "schema.carry_forward",
                    "from_schema": from_schema, "to_schema": to_schema,
                    "operator": operator, "nodes": counts["node"], "edges": counts["edge"],
                }, sort_keys=True), now),
            )
    return CarryForwardResult(
        counts["node"], counts["edge"], skipped["node"], skipped["edge"],
        dry_run, event_id,
    )
