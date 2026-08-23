"""Classify, materialize, and persist one H1 unit in a SAVEPOINT."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Final, assert_never

from ontologylab.h1_classify import classify_anchor
from ontologylab.h1_decisions import quarantine, with_family_receipt
from ontologylab.h1_materialize import (
    lookup_chunk_receipt,
    materialize_citation,
    materialize_run,
)
from ontologylab.h1_materialize_review import materialize_review
from ontologylab.h1_store import checkpoint, persist_decision
from ontologylab.h1_types import (
    H1Anchor,
    H1ChunkAnchor,
    H1CitationAnchor,
    H1Classification,
    H1Decision,
    H1Failpoint,
    H1QuarantineReason,
    H1ReviewAnchor,
    H1RunAnchor,
)


_SP: Final = "h1_anchor"


def _in_savepoint(
    conn: sqlite3.Connection, body: Callable[[], None],
) -> None:
    conn.execute(f"SAVEPOINT {_SP}")
    try:
        body()
        conn.execute(f"RELEASE SAVEPOINT {_SP}")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SP}")
        conn.execute(f"RELEASE SAVEPOINT {_SP}")
        raise


def bind_family(
    conn: sqlite3.Connection, anchor: H1Anchor, decision: H1Decision,
) -> H1Decision:
    if decision.classification is not H1Classification.VERIFIED:
        return decision
    match anchor:
        case H1RunAnchor():
            return decision
        case H1ChunkAnchor():
            family_id = lookup_chunk_receipt(conn, anchor, decision)
        case H1CitationAnchor():
            family_id = materialize_citation(conn, decision)
        case H1ReviewAnchor():
            review = materialize_review(conn, anchor)
            family_id = None if review is None else review.receipt_id
        case unreachable:
            assert_never(unreachable)
    if family_id is None:
        return quarantine(
            anchor,
            H1QuarantineReason.MISSING_CHUNK,
            representation_id=decision.representation_id,
            evidence={"legacy_pk": anchor.legacy_pk},
        )
    return with_family_receipt(decision, family_id)


def commit_one(
    conn: sqlite3.Connection,
    anchor: H1Anchor,
    fingerprint: str,
    failpoint: H1Failpoint | None,
) -> None:
    classified = classify_anchor(conn, anchor)

    def _write() -> None:
        persist_decision(conn, bind_family(conn, anchor, classified))
        checkpoint(conn, anchor.anchor_id, fingerprint)

    _in_savepoint(conn, _write)
    if failpoint is not None:
        failpoint(anchor.anchor_id)


def commit_run_unit(
    conn: sqlite3.Connection,
    run: H1RunAnchor,
    chunks: tuple[H1ChunkAnchor, ...],
    fingerprint: str,
    failpoint: H1Failpoint | None,
) -> None:
    run_decision = classify_anchor(conn, run)
    chunk_pairs = tuple((chunk, classify_anchor(conn, chunk)) for chunk in chunks)

    def _write_run() -> None:
        persist_decision(
            conn, _bound_run(conn, run, run_decision, chunk_pairs),
        )
        checkpoint(conn, run.anchor_id, fingerprint)

    _in_savepoint(conn, _write_run)
    if failpoint is not None:
        failpoint(run.anchor_id)
    for chunk, decision in chunk_pairs:
        def _write_chunk(current=chunk, classified=decision) -> None:
            persist_decision(conn, bind_family(conn, current, classified))
            checkpoint(conn, current.anchor_id, fingerprint)

        _in_savepoint(conn, _write_chunk)
        if failpoint is not None:
            failpoint(chunk.anchor_id)


def _bound_run(
    conn: sqlite3.Connection,
    run: H1RunAnchor,
    run_decision: H1Decision,
    chunk_pairs: tuple[tuple[H1ChunkAnchor, H1Decision], ...],
) -> H1Decision:
    ready = (
        run_decision.classification is H1Classification.VERIFIED
        and bool(chunk_pairs)
        and all(
            decision.classification is H1Classification.VERIFIED
            for _chunk, decision in chunk_pairs
        )
    )
    if not ready:
        if run_decision.classification is H1Classification.VERIFIED:
            return quarantine(
                run,
                H1QuarantineReason.MISSING_CHUNK,
                representation_id=run.representation_id,
                evidence={"run_id": run.run_id},
            )
        return run_decision
    receipts = materialize_run(conn, run, chunk_pairs)
    if receipts is None:
        return quarantine(
            run,
            H1QuarantineReason.MISSING_CHUNK,
            representation_id=run.representation_id,
            evidence={"run_id": run.run_id},
        )
    return with_family_receipt(run_decision, receipts.run.receipt_id)
