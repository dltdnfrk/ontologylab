"""ReviewDecision identity binds grounding fields and rejects silent aliasing."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ontologylab.grounded_review_ids import build_decision, citation_set_digest
from ontologylab.grounded_review_store import persist_decision
from ontologylab.grounded_review_types import (
    GroundedReviewRefusalCode,
    GroundedReviewRefused,
    ReviewAction,
)
from ontologylab.kgstore import KGStore


def test_distinct_grounding_identities_mint_distinct_receipt_ids() -> None:
    left = build_decision(
        fact_kind="node",
        fact_id="fact-a",
        fact_revision="rev-a",
        action=ReviewAction.APPROVE,
        actor="reviewer",
        reason="grounded",
        now=10.0,
        citation_ids=("cite-a",),
        representation_id="rep-a",
        selection_receipt_id="sel-a",
        policy_identity="policy-a",
        run_receipt_id="run-a",
        predecessor_receipt_id=None,
        pack_ineligible=False,
    )
    right = build_decision(
        fact_kind="node",
        fact_id="fact-a",
        fact_revision="rev-a",
        action=ReviewAction.APPROVE,
        actor="reviewer",
        reason="grounded",
        now=10.0,
        citation_ids=("cite-a",),
        representation_id="rep-b",
        selection_receipt_id="sel-a",
        policy_identity="policy-b",
        run_receipt_id="run-b",
        predecessor_receipt_id=None,
        pack_ineligible=False,
    )
    assert left.receipt_id != right.receipt_id
    assert left.citation_set_digest == citation_set_digest(("cite-a",))
    same_policy = build_decision(
        fact_kind="node",
        fact_id="fact-a",
        fact_revision="rev-a",
        action=ReviewAction.APPROVE,
        actor="reviewer",
        reason="grounded",
        now=10.0,
        citation_ids=("cite-a",),
        representation_id="rep-b",
        selection_receipt_id="sel-a",
        policy_identity="policy-a",
        run_receipt_id="run-a",
        predecessor_receipt_id=None,
        pack_ineligible=False,
    )
    assert left.receipt_id != same_policy.receipt_id


def test_decided_and_as_of_time_change_review_decision_id() -> None:
    first = build_decision(
        fact_kind="node",
        fact_id="fact-a",
        fact_revision="rev-a",
        action=ReviewAction.APPROVE,
        actor="reviewer",
        reason="grounded",
        now=10.0,
        citation_ids=("cite-a",),
        representation_id="rep-a",
        selection_receipt_id="sel-a",
        policy_identity="policy-a",
        run_receipt_id="run-a",
        predecessor_receipt_id=None,
        pack_ineligible=False,
    )
    second = build_decision(
        fact_kind="node",
        fact_id="fact-a",
        fact_revision="rev-a",
        action=ReviewAction.APPROVE,
        actor="reviewer",
        reason="grounded",
        now=99.0,
        citation_ids=("cite-a",),
        representation_id="rep-a",
        selection_receipt_id="sel-a",
        policy_identity="policy-a",
        run_receipt_id="run-a",
        predecessor_receipt_id=None,
        pack_ineligible=False,
    )
    assert first.receipt_id != second.receipt_id


def _time_id(*, decided_ts: float, as_of_ts: float) -> str:
    from ontologylab.grounded_review_ids import review_decision_id

    return review_decision_id(
        fact_kind="node",
        fact_id="fact-a",
        fact_revision="rev-a",
        action=ReviewAction.APPROVE,
        digest_value="sha256:cite",
        actor="reviewer",
        reason="grounded",
        predecessor_receipt_id=None,
        representation_id="rep-a",
        selection_receipt_id="sel-a",
        policy_identity="policy-a",
        run_receipt_id="run-a",
        pack_ineligible=False,
        decided_ts=decided_ts,
        as_of_ts=as_of_ts,
        waived_fact_ids=(),
        waived_citation_ids=(),
        scoped_defects=(),
    )


def test_decided_ts_alone_changes_review_decision_id() -> None:
    assert _time_id(decided_ts=10.0, as_of_ts=10.0) != _time_id(
        decided_ts=99.0, as_of_ts=10.0,
    )


def test_as_of_ts_alone_changes_review_decision_id() -> None:
    assert _time_id(decided_ts=10.0, as_of_ts=10.0) != _time_id(
        decided_ts=10.0, as_of_ts=99.0,
    )


def test_same_id_different_payload_is_typed_conflict(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        first = build_decision(
            fact_kind="node",
            fact_id="fact-a",
            fact_revision="rev-a",
            action=ReviewAction.APPROVE,
            actor="reviewer",
            reason="grounded",
            now=10.0,
            citation_ids=("cite-a",),
            representation_id="rep-a",
            selection_receipt_id="sel-a",
            policy_identity="policy-a",
            run_receipt_id="run-a",
            predecessor_receipt_id=None,
            pack_ineligible=False,
        )
        persist_decision(store.conn, first)
        colliding = build_decision(
            fact_kind="node",
            fact_id="fact-a",
            fact_revision="rev-a",
            action=ReviewAction.APPROVE,
            actor="reviewer",
            reason="grounded",
            now=10.0,
            citation_ids=("cite-a",),
            representation_id="rep-b",
            selection_receipt_id="sel-a",
            policy_identity="policy-b",
            run_receipt_id="run-b",
            predecessor_receipt_id=None,
            pack_ineligible=False,
        )
        colliding = replace(colliding, receipt_id=first.receipt_id)
        with pytest.raises(GroundedReviewRefused) as refused:
            persist_decision(store.conn, colliding)
        assert refused.value.code is GroundedReviewRefusalCode.CONFLICT
        count = store.conn.execute(
            "SELECT COUNT(*) FROM grounded_review_decisions"
        ).fetchone()[0]
        assert count == 1
        stored = store.conn.execute(
            "SELECT representation_id, policy_identity FROM "
            "grounded_review_decisions WHERE receipt_id = ?",
            (first.receipt_id,),
        ).fetchone()
        assert tuple(stored) == ("rep-a", "policy-a")
    finally:
        store.close()


def test_same_id_same_payload_is_idempotent(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        decision = build_decision(
            fact_kind="node",
            fact_id="fact-a",
            fact_revision="rev-a",
            action=ReviewAction.APPROVE,
            actor="reviewer",
            reason="grounded",
            now=10.0,
            citation_ids=("cite-a",),
            representation_id="rep-a",
            selection_receipt_id="sel-a",
            policy_identity="policy-a",
            run_receipt_id="run-a",
            predecessor_receipt_id=None,
            pack_ineligible=False,
        )
        persist_decision(store.conn, decision)
        persist_decision(store.conn, decision)
        count = store.conn.execute(
            "SELECT COUNT(*) FROM grounded_review_decisions"
        ).fetchone()[0]
        assert count == 1
    finally:
        store.close()
