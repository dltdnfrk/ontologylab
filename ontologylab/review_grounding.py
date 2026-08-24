"""Classify fact grounding from citation receipts or legacy spans."""

from __future__ import annotations

import json
import sqlite3

from ontologylab.citation import list_citation_receipts
from ontologylab.citation_schema import ensure_citation_schema
from ontologylab.citation_types import CitationRefused
from ontologylab.review_decision_ids import (
    citation_set_hash,
    fact_revision_hash,
    legacy_span_token,
)
from ontologylab.review_decision_types import GroundingClass, MemberGrounding


def classify_member(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> MemberGrounding:
    """Return grounding for one node/edge against receipts or legacy spans."""
    row = _fact_row(conn, fact_kind, fact_id)
    revision = _fact_revision(fact_kind, fact_id, row)

    ensure_citation_schema(conn)
    receipt_ids: list[str] = []
    try:
        receipts = list_citation_receipts(conn, fact_kind, fact_id)
    except CitationRefused:
        # Tampered/unverifiable receipts never count as grounded.
        return MemberGrounding(
            fact_kind=fact_kind,
            fact_id=fact_id,
            fact_revision=revision,
            grounding_class=GroundingClass.UNGROUNDED,
            citation_set_hash=citation_set_hash(()),
            citation_receipt_ids=(),
        )
    if receipts:
        receipt_ids = [r.receipt_id for r in receipts]
        return MemberGrounding(
            fact_kind=fact_kind,
            fact_id=fact_id,
            fact_revision=revision,
            grounding_class=GroundingClass.GROUNDED,
            citation_set_hash=citation_set_hash(receipt_ids),
            citation_receipt_ids=tuple(sorted(receipt_ids)),
        )

    legacy_tokens = _legacy_grounding_tokens(conn, fact_kind, fact_id, row)
    if legacy_tokens:
        return MemberGrounding(
            fact_kind=fact_kind,
            fact_id=fact_id,
            fact_revision=revision,
            grounding_class=GroundingClass.GROUNDED,
            citation_set_hash=citation_set_hash(legacy_tokens),
            citation_receipt_ids=tuple(sorted(legacy_tokens)),
        )
    return MemberGrounding(
        fact_kind=fact_kind,
        fact_id=fact_id,
        fact_revision=revision,
        grounding_class=GroundingClass.UNGROUNDED,
        citation_set_hash=citation_set_hash(()),
        citation_receipt_ids=(),
    )


def default_publication_allows(conn: sqlite3.Connection, fact_kind: str, fact_id: str) -> bool:
    """True when the fact may enter the default sourced pack."""
    from ontologylab.review_decision_schema import ensure_review_decision_schema

    ensure_review_decision_schema(conn)
    row = conn.execute(
        "SELECT publication_class FROM review_publication "
        "WHERE fact_kind = ? AND fact_id = ?",
        (fact_kind, fact_id),
    ).fetchone()
    if row is None:
        return True
    return str(row["publication_class"]) == "sourced"


def _fact_row(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> sqlite3.Row:
    table = "nodes" if fact_kind == "node" else "edges"
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?", (fact_id,),
    ).fetchone()
    if row is None:
        raise KeyError(fact_id)
    return row


def _fact_revision(
    fact_kind: str, fact_id: str, row: sqlite3.Row,
) -> str:
    if fact_kind == "node":
        body = json.dumps(
            {
                "entity_type": row["entity_type"],
                "name": row["name"],
                "normalized_name": row["normalized_name"],
                "properties_json": row["properties_json"],
                "source_doc_id": row["source_doc_id"],
                "source_span_json": row["source_span_json"],
                "status": row["status"],
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        body = json.dumps(
            {
                "relation_type": row["relation_type"],
                "src_node_id": row["src_node_id"],
                "dst_node_id": row["dst_node_id"],
                "properties_json": row["properties_json"],
                "qualifiers_json": row["qualifiers_json"],
                "source_doc_id": row["source_doc_id"],
                "source_span_json": row["source_span_json"],
                "status": row["status"],
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return fact_revision_hash(
        fact_kind=fact_kind, fact_id=fact_id, body_fingerprint=body,
    )


def _legacy_grounding_tokens(
    conn: sqlite3.Connection,
    fact_kind: str,
    fact_id: str,
    row: sqlite3.Row,
) -> list[str]:
    tokens: list[str] = []
    span = row["source_span_json"]
    if span:
        tokens.append(
            legacy_span_token(
                fact_kind=fact_kind,
                fact_id=fact_id,
                source_doc_id=row["source_doc_id"],
                source_span_json=str(span),
            )
        )
    try:
        cites = conn.execute(
            "SELECT source_doc_id, source_span_json FROM citations "
            "WHERE kind = ? AND item_id = ?",
            (fact_kind, fact_id),
        ).fetchall()
    except sqlite3.OperationalError:
        cites = []
    for cite in cites:
        cite_span = cite["source_span_json"]
        if not cite_span:
            continue
        tokens.append(
            legacy_span_token(
                fact_kind=fact_kind,
                fact_id=fact_id,
                source_doc_id=cite["source_doc_id"],
                source_span_json=str(cite_span),
            )
        )
    return tokens
