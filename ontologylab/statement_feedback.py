"""Transactional human-review receipts, separate from adjudicated gold."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from collections.abc import Sequence

from ontologylab.kgstore_base import (
    EDGE_POLARITY_SQL,
    EDGE_QUALIFIERS_SQL,
    edge_polarity,
    normalize_name,
)
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.statement_qualifiers import (
    canonical_qualifiers,
    normalize_statement_qualifiers,
)


@dataclass(frozen=True, slots=True)
class ReviewEvent:
    action: str
    actor: str
    item_ids: tuple[str, ...]
    before: tuple[dict[str, str | None], ...]
    after: tuple[dict[str, str | None], ...]
    source_doc_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    reason: str | None = None
    split_assignment: str = "unassigned"


def existing_curated_ids(
    conn: sqlite3.Connection,
    entities: Sequence[ProposedEntity],
    relations: Sequence[ProposedRelation],
) -> tuple[str, ...]:
    """Find existing rows an insertion will resolve or cite, without writing."""
    schema = conn.execute(
        "SELECT id, label FROM schema_version WHERE is_active = 1 "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    resolved: dict[str, str] = {}
    affected: list[str] = []
    for entity in entities:
        key = normalize_name(entity.name)
        row = conn.execute(
            "SELECT id FROM nodes WHERE schema_version_id = ? AND entity_type = ? "
            "AND normalized_name = ? AND status IN ('proposed','verified')",
            (schema["id"], entity.entity_type, key),
        ).fetchone()
        if row is None:
            aliases = conn.execute(
                "SELECT n.id FROM node_aliases a JOIN nodes n ON n.id = a.node_id "
                "WHERE a.normalized_alias = ? AND n.schema_version_id = ? "
                "AND n.entity_type = ? AND n.status IN ('proposed','verified')",
                (key, schema["id"], entity.entity_type),
            ).fetchall()
            row = aliases[0] if len(aliases) == 1 else None
        if row is not None:
            resolved[entity.id] = row["id"]
            affected.append(row["id"])

    for relation in relations:
        src = resolved.get(relation.src_entity_id)
        dst = resolved.get(relation.dst_entity_id)
        if src is None or dst is None:
            continue
        qualifiers = (
            normalize_statement_qualifiers(relation.qualifiers)
            if schema["label"] == "agrochem-v2" else relation.qualifiers
        )
        row = conn.execute(
            "SELECT id FROM edges WHERE schema_version_id = ? AND "
            "relation_type = ? AND src_node_id = ? AND dst_node_id = ? AND "
            f"{EDGE_POLARITY_SQL} = ? AND {EDGE_QUALIFIERS_SQL} = ? AND "
            "status IN ('proposed','verified') AND invalidated_ts IS NULL",
            (
                schema["id"], relation.relation_type, src, dst,
                edge_polarity(qualifiers), canonical_qualifiers(qualifiers),
            ),
        ).fetchone()
        if row is not None:
            affected.append(row["id"])
    return tuple(dict.fromkeys(affected))


def review_snapshot(
    conn: sqlite3.Connection, item_ids: tuple[str, ...],
) -> tuple[dict[str, str | None], ...]:
    """Capture review-relevant row state before or after one HTTP command."""
    snapshot: list[dict[str, str | None]] = []
    pending = list(dict.fromkeys(item_ids))
    for item_id in pending:
        for kind, table in (
            ("node", "nodes"),
            ("edge", "edges"),
            ("merge_candidate", "merge_candidates"),
            ("document", "documents"),
        ):
            row = conn.execute(
                f"SELECT * FROM {table} WHERE id = ?", (item_id,),
            ).fetchone()
            if row is None:
                continue
            if kind == "edge":
                pending.extend(
                    endpoint for endpoint in (row["src_node_id"], row["dst_node_id"])
                    if endpoint not in pending
                )
            if kind == "merge_candidate":
                pending.extend(
                    endpoint for endpoint in (row["node_a_id"], row["node_b_id"])
                    if endpoint not in pending
                )
            source_doc_id = (
                row["id"] if kind == "document"
                else row["source_doc_id"] if kind in ("node", "edge")
                else None
            )
            source = (
                conn.execute(
                    "SELECT content_hash FROM documents WHERE id = ?",
                    (source_doc_id,),
                ).fetchone()
                if source_doc_id else None
            )
            item = {
                "kind": kind,
                "id": item_id,
                "status": row["status"] if kind != "document" else None,
                "source_doc_id": source_doc_id,
                "source_hash": source["content_hash"] if source else None,
                "source_span": row["source_span"] if kind in ("node", "edge") else None,
                "qualifiers": row["qualifiers_json"] if kind == "edge" else None,
                "verified_by": row["verified_by"] if kind in ("node", "edge") else None,
                "invalidated_ts": (
                    str(row["invalidated_ts"]) if row["invalidated_ts"] is not None
                    else None
                ) if kind == "edge" else None,
            }
            if kind == "node":
                item["aliases_json"] = row["aliases_json"]
            if kind in ("node", "edge"):
                item["properties_json"] = row["properties_json"]
            snapshot.append(item)
            break
    return tuple(snapshot)


def record_review_event(conn: sqlite3.Connection, event: ReviewEvent) -> str:
    """Append one event using the caller's open transaction; never commit."""
    event_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO statement_review_events "
        "(id, version, created_ts, action, actor, reason, item_ids_json, "
        "before_json, after_json, source_doc_ids_json, source_hashes_json, "
        "split_assignment) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id, time.time(), event.action, event.actor, event.reason,
            json.dumps(event.item_ids),
            json.dumps(event.before, sort_keys=True),
            json.dumps(event.after, sort_keys=True),
            json.dumps(event.source_doc_ids),
            json.dumps(event.source_hashes),
            event.split_assignment,
        ),
    )
    return event_id


def export_feedback(
    conn: sqlite3.Connection, *, development_ids: set[str],
) -> tuple[dict[str, str | tuple[str, ...] | tuple[dict[str, str | None], ...]], ...]:
    """Export only known development sources; held-out and unknown stay quarantined."""
    exported = []
    for row in conn.execute(
        "SELECT * FROM statement_review_events ORDER BY created_ts, id"
    ):
        source_ids = tuple(json.loads(row["source_doc_ids_json"]))
        source_hashes = tuple(json.loads(row["source_hashes_json"]))
        if (
            row["split_assignment"] == "held_out"
            or not source_hashes
            or not set(source_hashes).issubset(development_ids)
        ):
            continue
        exported.append({
            "id": row["id"],
            "action": row["action"],
            "actor": row["actor"],
            "reason": row["reason"],
            "item_ids": tuple(json.loads(row["item_ids_json"])),
            "before": tuple(json.loads(row["before_json"])),
            "after": tuple(json.loads(row["after_json"])),
            "source_doc_ids": source_ids,
            "source_hashes": source_hashes,
        })
    return tuple(exported)
