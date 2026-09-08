"""Pure SQLite-row conversions used by the KGStore facade."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ontologylab import evidence
from ontologylab.models import Document


def node_dict(row: sqlite3.Row) -> dict[str, Any]:
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


def edge_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {
        "id": row["id"],
        "relation_type": row["relation_type"],
        "source_id": row["src_node_id"],
        "target_id": row["dst_node_id"],
        "properties": json.loads(row["properties_json"]),
        "qualifiers": (
            json.loads(row["qualifiers_json"])
            if "qualifiers_json" in keys and row["qualifiers_json"]
            else {}
        ),
        "status": row["status"],
        "confidence": row["confidence"],
        "source_doc_id": row["source_doc_id"],
        # W13 bitemporal fields; absent on pre-W13 read-only packs.
        "valid_from": row["valid_from"] if "valid_from" in keys else None,
        "invalidated_ts": (
            row["invalidated_ts"] if "invalidated_ts" in keys else None
        ),
    }


def document_from_row(row: sqlite3.Row) -> Document:
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
        doi=row["doi"] if "doi" in row.keys() else None,
    )
