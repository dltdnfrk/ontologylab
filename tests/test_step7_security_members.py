"""Active member citation digest and current-decision pointer."""

from __future__ import annotations

from pathlib import Path

import pytest

from ontologylab.citation import list_citation_receipts
from ontologylab.grounded_review import (
    ReviewAction,
    ReviewRequest,
    WaiverRequest,
    apply_review,
    list_review_decisions,
)
from ontologylab.kgstore import GroundingPreflightError, KGStore
from tests.step7_integration_support import plant_and_extract, probe_node_id
from tests.step7_sec2_support import plant_colliding
from tests.step7_valid_stale import plant_valid_stale_citation, plant_valid_stale_run
from tests.test_step7_tampered_non_approval import _tamper


def test_waiver_binds_active_member_citations_when_stale_extra_exists(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    try:
        fact_id = probe_node_id(store)
        cites = list_citation_receipts(store.conn, "node", fact_id)
        live_ids = {item.receipt_id for item in cites}
        stale_run = plant_valid_stale_run(store, pmc_id)
        stale_cite = plant_valid_stale_citation(
            store, live=cites[0], stale_run_id=stale_run,
        )
        store.approve_with_grounding_waiver(
            WaiverRequest(
                item_id=fact_id,
                actor="integrator",
                reason="named scoped waiver",
                member_ids=(fact_id,),
                citation_ids=(),
                scoped_defects=(f"node:{fact_id}:operator",),
            )
        )
        decision = list_review_decisions(store.conn, "node", fact_id)[0]
        assert set(decision.citation_receipt_ids) == live_ids
        assert stale_cite not in decision.citation_receipt_ids
        assert decision.pack_ineligible is True
    finally:
        store.close()


def test_tampered_reject_digest_excludes_stale_citation_rows(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    try:
        fact_id = probe_node_id(store)
        cites = list_citation_receipts(store.conn, "node", fact_id)
        live_ids = {item.receipt_id for item in cites}
        stale_run = plant_valid_stale_run(store, pmc_id)
        stale_cite = plant_valid_stale_citation(
            store, live=cites[0], stale_run_id=stale_run,
        )
        _tamper(store, pmc_id)
        with pytest.raises(GroundingPreflightError):
            store.approve(fact_id, by="integrator", note="no")
        result = store.reject(fact_id, by="integrator", note="bad bytes")
        decision = list_review_decisions(store.conn, "node", fact_id)[0]
        assert decision.receipt_id == result["decision_receipt_ids"][0]
        assert set(decision.citation_receipt_ids) == live_ids
        assert stale_cite not in decision.citation_receipt_ids
        assert decision.pack_ineligible is True
    finally:
        store.close()


def test_compensate_predecessor_is_pointer_when_stale_row_sorts_later(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, _pmc = plant_and_extract(live)
    try:
        fact_id = probe_node_id(store)
        cites = list_citation_receipts(store.conn, "node", fact_id)
        live_ids = tuple(item.receipt_id for item in cites)
        waived = store.approve_with_grounding_waiver(
            WaiverRequest(
                item_id=fact_id,
                actor="integrator",
                reason="named scoped waiver",
                member_ids=(fact_id,),
                citation_ids=(),
                scoped_defects=(f"node:{fact_id}:operator",),
            )
        )
        waiver_id = waived["decision_receipt_ids"][0]
        live_dec = list_review_decisions(store.conn, "node", fact_id)[0]
        stale = plant_colliding(
            store, live_dec, action=ReviewAction.APPROVE, cite_ids=live_ids,
            pack=False, selection=live_dec.selection_receipt_id,
            policy=live_dec.policy_identity or "",
            run=live_dec.run_receipt_id or "",
            larger_than=waiver_id,
        )
        assert stale > waiver_id
        result = store.compensate_review(fact_id, by="integrator", note="correct")
        decision = list_review_decisions(store.conn, "node", fact_id)[-1]
        assert decision.receipt_id == result["decision_receipt_ids"][0]
        assert decision.predecessor_receipt_id == waiver_id
        assert decision.predecessor_receipt_id != stale
    finally:
        store.close()


def test_current_pointer_rolls_back_with_review_savepoint(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, _pmc = plant_and_extract(live)
    try:
        fact_id = probe_node_id(store)
        if not store.conn.in_transaction:
            store.conn.execute("BEGIN")
        apply_review(
            store.conn,
            ReviewRequest(
                item_id=fact_id,
                actor="tester",
                reason="ok",
                action=ReviewAction.APPROVE,
                require_citations=True,
            ),
        )
        store.conn.rollback()
        row = store.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'grounded_review_current'"
        ).fetchone()
        if row is not None:
            pointed = store.conn.execute(
                "SELECT receipt_id FROM grounded_review_current "
                "WHERE fact_kind = 'node' AND fact_id = ?",
                (fact_id,),
            ).fetchone()
            assert pointed is None
        assert list_review_decisions(store.conn, "node", fact_id) == ()
    finally:
        store.close()
