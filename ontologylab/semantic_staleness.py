"""Versioned semantic fact snapshots and stable-id deltas.

The fingerprint covers material fields exposed by MCP, including aliases and
citation provenance. Review lifecycle fields, embeddings, and ingestion/review
timestamps are intentionally excluded so operational churn is not a semantic
replacement.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

BASELINE_VERSION = 1
FINGERPRINT_ALGORITHM = "sha256-canonical-json-v1"


def _json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _fingerprint(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _citations(conn: sqlite3.Connection) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in conn.execute(
        "SELECT kind, item_id, source_doc_id, source_span FROM citations"
    ):
        citation = {
            "source_doc_id": row[2],
            "source_span": _json(row[3], None),
        }
        result.setdefault((row[0], row[1]), []).append(citation)
    for values in result.values():
        values.sort(key=lambda value: json.dumps(value, sort_keys=True))
    return result


def fact_baseline(conn: sqlite3.Connection) -> dict[str, Any]:
    """Snapshot current verified facts using deterministic semantic hashes."""
    citations = _citations(conn)
    nodes: dict[str, dict[str, str]] = {}
    names: dict[str, str] = {}
    for row in conn.execute(
        "SELECT id, entity_type, name, aliases_json, properties_json, confidence, "
        "source_doc_id, source_span FROM nodes WHERE status='verified' ORDER BY id"
    ):
        item_id, name = row[0], row[2]
        names[item_id] = name
        material = {
            "entity_type": row[1],
            "name": name,
            "aliases": sorted(set(map(str, _json(row[3], [])))),
            "properties": _json(row[4], {}),
            "confidence": row[5],
            "source_doc_id": row[6],
            "source_span": _json(row[7], None),
            "citations": citations.get(("node", item_id), []),
        }
        nodes[item_id] = {"fingerprint": _fingerprint(material), "label": name}

    edges: dict[str, dict[str, str]] = {}
    for row in conn.execute(
        "SELECT e.id, e.relation_type, e.src_node_id, e.dst_node_id, "
        "e.properties_json, e.confidence, e.source_doc_id, e.source_span "
        "FROM edges e "
        "JOIN nodes s ON s.id=e.src_node_id AND s.status='verified' "
        "JOIN nodes d ON d.id=e.dst_node_id AND d.status='verified' "
        "WHERE e.status='verified' AND e.invalidated_ts IS NULL ORDER BY e.id"
    ):
        item_id = row[0]
        material = {
            "relation_type": row[1],
            "source_id": row[2],
            "target_id": row[3],
            "properties": _json(row[4], {}),
            "confidence": row[5],
            "source_doc_id": row[6],
            "source_span": _json(row[7], None),
            "citations": citations.get(("edge", item_id), []),
        }
        label = (
            f"{names.get(row[2], row[2])} -[{row[1]}]-> "
            f"{names.get(row[3], row[3])}"
        )
        edges[item_id] = {"fingerprint": _fingerprint(material), "label": label}
    return {
        "version": BASELINE_VERSION,
        "fingerprint_algorithm": FINGERPRINT_ALGORITHM,
        "nodes": nodes,
        "edges": edges,
    }


def semantic_baseline_marker() -> dict[str, Any]:
    """Small manifest capability marker; fact data remains in pack.sqlite."""
    return {
        "version": BASELINE_VERSION,
        "fingerprint_algorithm": FINGERPRINT_ALGORITHM,
        "source": "pack.sqlite",
    }


def baseline_compatible(marker: Any) -> bool:
    return bool(
        isinstance(marker, dict)
        and marker.get("version") == BASELINE_VERSION
        and marker.get("fingerprint_algorithm") == FINGERPRINT_ALGORITHM
        and marker.get("source") == "pack.sqlite"
    )


def semantic_deltas(
    packed_conn: sqlite3.Connection, live_conn: sqlite3.Connection
) -> dict[str, dict[str, Any]]:
    """Return disjoint live-only, pack-only, and changed-same-id categories."""
    packed = fact_baseline(packed_conn)
    live = fact_baseline(live_conn)

    def category(mode: str) -> dict[str, Any]:
        details: dict[str, list[dict[str, str]]] = {"nodes": [], "edges": []}
        for kind in ("nodes", "edges"):
            packed_items, live_items = packed[kind], live[kind]
            if mode == "added":
                ids = set(live_items) - set(packed_items)
                source = live_items
            elif mode == "removed":
                ids = set(packed_items) - set(live_items)
                source = packed_items
            else:
                ids = {
                    item_id for item_id in set(packed_items) & set(live_items)
                    if packed_items[item_id]["fingerprint"]
                    != live_items[item_id]["fingerprint"]
                }
                source = live_items
            details[kind] = [
                {"id": item_id, "label": source[item_id]["label"]}
                for item_id in sorted(ids)
            ]
        return {
            "count": len(details["nodes"]) + len(details["edges"]),
            **details,
        }

    return {
        "semantic_additions": category("added"),
        "semantic_invalidations": category("removed"),
        "semantic_replacements": category("changed"),
    }


__all__ = [
    "BASELINE_VERSION", "FINGERPRINT_ALGORITHM", "baseline_compatible",
    "fact_baseline", "semantic_baseline_marker", "semantic_deltas",
]
