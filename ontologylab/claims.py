"""Claim -> Evidence queries over a read-only pack.

A claim is one edge: (subject, relation, object) plus its polarity. The
evidence is where it came from. These functions return both in the shape
MUNI's Claim->Evidence seam expects, so a caller can ask "what supports or
refutes X" without reassembling it from graph_query and get_entity.

Read-only, and tolerant of packs built before the claim layer: a missing
origin column reads as 'extracted' (the only producer that existed), and a
missing polarity reads as '' (asserted, pre-polarity meaning).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ontologylab.kgstore_base import EDGE_POLARITY_SQL

POLARITIES = ("supports", "refutes", "no_effect")
_OPPOSING = ("refutes", "no_effect")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _status_sql(include_proposed: bool) -> str:
    return (
        "e.status IN ('proposed','verified')" if include_proposed
        else "e.status = 'verified'"
    )


def _time_sql(valid_at: float | None) -> tuple[str, list[Any]]:
    """Current truth by default; with ``valid_at``, what held at that time."""
    if valid_at is None:
        return "e.invalidated_ts IS NULL", []
    return (
        "(e.valid_from IS NULL OR e.valid_from <= ?) "
        "AND (e.invalidated_ts IS NULL OR e.invalidated_ts > ?)",
        [valid_at, valid_at],
    )


def _claim_rows(
    conn: sqlite3.Connection, where: list[str], params: list[Any], limit: int,
) -> list[dict[str, Any]]:
    edge_cols = _columns(conn, "edges")
    node_cols = _columns(conn, "nodes")
    origin = "e.origin" if "origin" in edge_cols else "'extracted'"
    qualifiers = "e.qualifiers_json" if "qualifiers_json" in edge_cols else "'{}'"
    polarity = EDGE_POLARITY_SQL.replace("qualifiers_json", "e.qualifiers_json") \
        if "qualifiers_json" in edge_cols else "''"
    bitemporal = "valid_from" in edge_cols
    valid_from = "e.valid_from" if bitemporal else "NULL"
    invalidated = "e.invalidated_ts" if bitemporal else "NULL"
    src_origin = "s.origin" if "origin" in node_cols else "'extracted'"
    rows = conn.execute(
        "SELECT e.id, e.relation_type, e.src_node_id, e.dst_node_id, "
        f"e.status, {origin} AS origin, {polarity} AS polarity, "
        f"{qualifiers} AS qualifiers_json, e.confidence, e.source_doc_id, "
        f"e.source_span, {valid_from} AS valid_from, "
        f"{invalidated} AS invalidated_ts, e.schema_version_id, "
        "s.name AS src_name, s.entity_type AS src_type, "
        f"{src_origin} AS src_origin, "
        "d.name AS dst_name, d.entity_type AS dst_type, "
        "d.properties_json AS dst_properties, "
        "doc.source_uri, doc.fetched_ts, doc.title, doc.doi "
        "FROM edges e "
        "JOIN nodes s ON s.id = e.src_node_id "
        "JOIN nodes d ON d.id = e.dst_node_id "
        "LEFT JOIN documents doc ON doc.id = e.source_doc_id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY e.relation_type, e.id LIMIT ?",
        [*params, limit],
    ).fetchall()
    claims = []
    for row in rows:
        dst_properties = json.loads(row["dst_properties"] or "{}")
        claims.append({
            "edge_id": row["id"],
            "subject": {"id": row["src_node_id"], "name": row["src_name"],
                        "entity_type": row["src_type"]},
            "relation": row["relation_type"],
            "object": {"id": row["dst_node_id"], "name": row["dst_name"],
                       "entity_type": row["dst_type"]},
            # '' means the claim predates polarity: asserted, not tested null.
            "polarity": row["polarity"] or None,
            "qualifiers": json.loads(row["qualifiers_json"] or "{}"),
            "status": row["status"],
            "origin": row["origin"],
            "confidence": row["confidence"],
            "measurement": dst_properties.get("measurement"),
            "evidence": {
                "source_doc_id": row["source_doc_id"],
                "source_uri": row["source_uri"],
                "title": row["title"],
                "doi": row["doi"],
                "source_span": json.loads(row["source_span"]) if row["source_span"] else None,
                "retrieved_at": row["fetched_ts"],
            },
            "valid_from": row["valid_from"],
            "invalidated_ts": row["invalidated_ts"],
            "schema_version_id": row["schema_version_id"],
        })
    return claims


def _tally(claims: list[dict[str, Any]]) -> dict[str, int]:
    tally = {name: 0 for name in POLARITIES}
    tally["unspecified"] = 0
    for claim in claims:
        tally[claim["polarity"] or "unspecified"] += 1
    return tally


def claims_for(
    conn: sqlite3.Connection,
    *,
    subject_id: str | None = None,
    object_id: str | None = None,
    relation_type: str | None = None,
    polarity: str | None = None,
    origin: str | None = None,
    valid_at: float | None = None,
    include_proposed: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    if subject_id is None and object_id is None:
        raise ValueError("claims_for needs subject_id or object_id")
    if polarity is not None and polarity not in POLARITIES:
        raise ValueError(f"polarity must be one of {', '.join(POLARITIES)}")
    time_sql, params = _time_sql(valid_at)
    where = [_status_sql(include_proposed), time_sql]
    if not include_proposed:
        where.append("s.status = 'verified' AND d.status = 'verified'")
    for column, value in (
        ("e.src_node_id", subject_id), ("e.dst_node_id", object_id),
        ("e.relation_type", relation_type),
    ):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    claims = _claim_rows(conn, where, params, limit)
    if polarity is not None:
        claims = [c for c in claims if c["polarity"] == polarity]
    if origin is not None:
        claims = [c for c in claims if c["origin"] == origin]
    return {"claims": claims, "count": len(claims), "polarity_counts": _tally(claims)}


def find_contradictions(
    conn: sqlite3.Connection,
    *,
    subject_id: str | None = None,
    relation_type: str | None = None,
    include_proposed: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Same (subject, relation, object) asserted by one claim and refuted or
    found null by another. Only polarity conflicts are reported: two
    different objects under one relation are not a contradiction."""
    where = [_status_sql(include_proposed), "e.invalidated_ts IS NULL"]
    params: list[Any] = []
    if not include_proposed:
        where.append("s.status = 'verified' AND d.status = 'verified'")
    if subject_id is not None:
        where.append("e.src_node_id = ?")
        params.append(subject_id)
    if relation_type is not None:
        where.append("e.relation_type = ?")
        params.append(relation_type)
    claims = _claim_rows(conn, where, params, 10_000)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for claim in claims:
        key = (claim["subject"]["id"], claim["relation"], claim["object"]["id"])
        groups.setdefault(key, []).append(claim)
    conflicts = []
    for group in groups.values():
        supporting = [c for c in group if c["polarity"] in (None, "supports")]
        opposing = [c for c in group if c["polarity"] in _OPPOSING]
        if supporting and opposing:
            conflicts.append({
                "subject": group[0]["subject"],
                "relation": group[0]["relation"],
                "object": group[0]["object"],
                "supporting": supporting,
                "opposing": opposing,
            })
    return {"contradictions": conflicts[:limit], "count": min(len(conflicts), limit),
            "total": len(conflicts)}


def compare_claims(
    conn: sqlite3.Connection,
    entity_a: str,
    entity_b: str,
    *,
    include_proposed: bool = False,
    limit: int = 500,
) -> dict[str, Any]:
    """What A and B are each claimed to do, aligned by (relation, object).

    One (relation, object) can hold several claims of different polarity, so
    each side carries a list. ``shared`` pairs are ``agree`` only when both
    sides report the same polarity set; ``only_a`` / ``only_b`` hold the rest."""
    def outgoing(entity: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
        result = claims_for(
            conn, subject_id=entity, include_proposed=include_proposed, limit=limit,
        )
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for claim in result["claims"]:
            grouped.setdefault((claim["relation"], claim["object"]["id"]), []).append(claim)
        return grouped

    def polarities(group: list[dict[str, Any]]) -> set[str]:
        return {claim["polarity"] or "supports" for claim in group}

    a, b = outgoing(entity_a), outgoing(entity_b)
    shared = [
        {"relation": key[0], "object": a[key][0]["object"], "a": a[key], "b": b[key],
         "agree": polarities(a[key]) == polarities(b[key])}
        for key in sorted(a.keys() & b.keys())
    ]
    return {
        "entity_a": entity_a,
        "entity_b": entity_b,
        "shared": shared,
        "only_a": [c for key in sorted(a.keys() - b.keys()) for c in a[key]],
        "only_b": [c for key in sorted(b.keys() - a.keys()) for c in b[key]],
        "disagreements": sum(1 for item in shared if not item["agree"]),
    }


__all__ = ["POLARITIES", "claims_for", "compare_claims", "find_contradictions"]
