"""Caller-owned persistence for append-only review decisions."""

from __future__ import annotations

import json
import sqlite3
import time

from ontologylab.review_decision_ids import review_decision_id
from ontologylab.review_decision_schema import ensure_review_decision_schema
from ontologylab.review_decision_types import (
    DecisionKind,
    GroundingClass,
    PublicationClass,
    ReviewDecision,
    ReviewRefusalCode,
    refuse,
)


def put_decisions(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    decision_kind: DecisionKind,
    actor: str,
    reason: str | None,
    members: tuple[tuple[str, str, str, str, GroundingClass], ...],
    member_ids: tuple[str, ...],
) -> tuple[ReviewDecision, ...]:
    """Append one decision per member and update publication class.

    ``members`` tuples are
    ``(fact_kind, fact_id, fact_revision, citation_set_hash, grounding_class)``.
    """
    ensure_review_decision_schema(conn)
    if decision_kind is DecisionKind.WAIVER and not (reason and reason.strip()):
        refuse(ReviewRefusalCode.MISSING_REASON, "waiver requires a non-empty reason")
    if not members:
        refuse(ReviewRefusalCode.EMPTY_IDS, "review decision requires at least one member")

    written: list[ReviewDecision] = []
    now = time.time()
    member_ids_json = json.dumps(list(member_ids), ensure_ascii=False, separators=(",", ":"))
    publication = (
        PublicationClass.WORKING_ONLY
        if decision_kind is DecisionKind.WAIVER
        else PublicationClass.SOURCED
    )
    for fact_kind, fact_id, fact_revision, cite_hash, grounding in members:
        decision = ReviewDecision(
            decision_id=review_decision_id(
                batch_id=batch_id,
                decision_kind=decision_kind.value,
                fact_kind=fact_kind,
                fact_id=fact_id,
                fact_revision=fact_revision,
                citation_set_hash_value=cite_hash,
                grounding_class=grounding.value,
                actor=actor,
                reason=reason,
            ),
            decision_kind=decision_kind.value,
            fact_kind=fact_kind,
            fact_id=fact_id,
            fact_revision=fact_revision,
            citation_set_hash=cite_hash,
            grounding_class=grounding.value,
            actor=actor,
            reason=reason,
            batch_id=batch_id,
            member_ids=member_ids,
            created=True,
        )
        existing = conn.execute(
            "SELECT decision_id FROM review_decisions WHERE decision_id = ?",
            (decision.decision_id,),
        ).fetchone()
        if existing is not None:
            written.append(
                ReviewDecision(
                    decision_id=decision.decision_id,
                    decision_kind=decision.decision_kind,
                    fact_kind=decision.fact_kind,
                    fact_id=decision.fact_id,
                    fact_revision=decision.fact_revision,
                    citation_set_hash=decision.citation_set_hash,
                    grounding_class=decision.grounding_class,
                    actor=decision.actor,
                    reason=decision.reason,
                    batch_id=decision.batch_id,
                    member_ids=decision.member_ids,
                    created=False,
                )
            )
        else:
            conn.execute(
                "INSERT INTO review_decisions ("
                "decision_id, decision_kind, fact_kind, fact_id, fact_revision, "
                "citation_set_hash, grounding_class, actor, reason, batch_id, "
                "member_ids_json, created_ts) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    decision.decision_id,
                    decision.decision_kind,
                    decision.fact_kind,
                    decision.fact_id,
                    decision.fact_revision,
                    decision.citation_set_hash,
                    decision.grounding_class,
                    decision.actor,
                    decision.reason,
                    decision.batch_id,
                    member_ids_json,
                    now,
                ),
            )
            written.append(decision)
        conn.execute(
            "INSERT INTO review_publication ("
            "fact_kind, fact_id, publication_class, decision_id, updated_ts) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(fact_kind, fact_id) DO UPDATE SET "
            "publication_class = excluded.publication_class, "
            "decision_id = excluded.decision_id, "
            "updated_ts = excluded.updated_ts",
            (
                fact_kind,
                fact_id,
                publication.value,
                decision.decision_id,
                now,
            ),
        )
    return tuple(written)


def list_decisions_for_fact(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> tuple[ReviewDecision, ...]:
    ensure_review_decision_schema(conn)
    rows = conn.execute(
        "SELECT * FROM review_decisions WHERE fact_kind = ? AND fact_id = ? "
        "ORDER BY created_ts, decision_id",
        (fact_kind, fact_id),
    ).fetchall()
    return tuple(_row_decision(row) for row in rows)


def latest_decision(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> ReviewDecision | None:
    ensure_review_decision_schema(conn)
    row = conn.execute(
        "SELECT * FROM review_decisions WHERE fact_kind = ? AND fact_id = ? "
        "ORDER BY created_ts DESC, decision_id DESC LIMIT 1",
        (fact_kind, fact_id),
    ).fetchone()
    if row is None:
        return None
    return _row_decision(row)


def _row_decision(row: sqlite3.Row) -> ReviewDecision:
    members = tuple(json.loads(str(row["member_ids_json"])))
    reason = row["reason"]
    return ReviewDecision(
        decision_id=str(row["decision_id"]),
        decision_kind=str(row["decision_kind"]),
        fact_kind=str(row["fact_kind"]),
        fact_id=str(row["fact_id"]),
        fact_revision=str(row["fact_revision"]),
        citation_set_hash=str(row["citation_set_hash"]),
        grounding_class=str(row["grounding_class"]),
        actor=str(row["actor"]),
        reason=None if reason is None else str(reason),
        batch_id=str(row["batch_id"]),
        member_ids=members,
        created=False,
    )
