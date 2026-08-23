"""H1 links the current scoped waiver, never an eligible twin."""

from __future__ import annotations

from pathlib import Path

from ontologylab.citation import list_citation_receipts
from ontologylab.grounded_review import WaiverRequest, list_review_decisions
from ontologylab.grounded_review_types import ReviewAction
from ontologylab.h1 import run_h1_operator
from ontologylab.kgstore import KGStore
from tests.step7_integration_support import plant_and_extract, probe_node_id
from tests.step7_sec2_support import (
    drop_pointer,
    eligible_approve_ids,
    plant_colliding,
)
from tests.step7_valid_stale import plant_valid_stale_citation, plant_valid_stale_run
from tests.test_step7_h1_existing import _linked


def test_h1_links_current_waiver_not_colliding_stale_twins(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    cites = list_citation_receipts(store.conn, "node", fact_id)
    live_ids = tuple(item.receipt_id for item in cites)
    stale_run = plant_valid_stale_run(store, pmc_id)
    stale_cite = plant_valid_stale_citation(
        store, live=cites[0], stale_run_id=stale_run,
    )
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
    stale_approve = plant_colliding(
        store, live_dec, action=ReviewAction.APPROVE, cite_ids=live_ids,
        pack=True, selection=live_dec.selection_receipt_id,
        policy=live_dec.policy_identity or "",
        run=live_dec.run_receipt_id or stale_run,
        smaller_than=waiver_id,
    )
    stale_waiver = plant_colliding(
        store, live_dec,
        action=ReviewAction.APPROVE_WITH_GROUNDING_WAIVER,
        cite_ids=(stale_cite,),
        scoped=(f"node:{fact_id}:stale",),
        waived=(fact_id,),
        pack=True,
        run=stale_run,
        smaller_than=waiver_id,
    )
    assert stale_approve < waiver_id
    assert stale_waiver < waiver_id
    store.close()
    dest = tmp_path / "h1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        assert _linked(copy, "review") == {waiver_id}
        assert stale_approve not in _linked(copy, "review")
        assert stale_waiver not in _linked(copy, "review")
        assert eligible_approve_ids(copy, fact_id) == []
    finally:
        copy.close()


def test_h1_same_cite_different_scope_does_not_mint_eligible(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, _pmc = plant_and_extract(live)
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
    other = plant_colliding(
        store, live_dec,
        action=ReviewAction.APPROVE_WITH_GROUNDING_WAIVER,
        cite_ids=live_ids,
        scoped=(f"node:{fact_id}:other",),
        waived=(fact_id, "extra"),
        pack=True,
        selection=live_dec.selection_receipt_id,
        policy=live_dec.policy_identity or "",
        run=live_dec.run_receipt_id or "",
        smaller_than=waiver_id,
    )
    assert other < waiver_id
    store.close()
    dest = tmp_path / "h1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        linked = _linked(copy, "review")
        assert linked == {waiver_id}
        assert other not in linked
        assert eligible_approve_ids(copy, fact_id) == []
    finally:
        copy.close()


def test_h1_links_historical_unique_waiver_when_pointer_missing(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, _pmc = plant_and_extract(live)
    fact_id = probe_node_id(store)
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
    drop_pointer(store)
    store.close()
    dest = tmp_path / "h1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        assert _linked(copy, "review") == {waiver_id}
        assert eligible_approve_ids(copy, fact_id) == []
    finally:
        copy.close()


def test_h1_quarantines_when_current_tips_are_indistinguishable(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, _pmc = plant_and_extract(live)
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
    other = plant_colliding(
        store, live_dec,
        action=ReviewAction.APPROVE_WITH_GROUNDING_WAIVER,
        cite_ids=live_ids,
        scoped=(f"node:{fact_id}:other",),
        waived=(fact_id, "extra"),
        pack=True,
        selection=live_dec.selection_receipt_id,
        policy=live_dec.policy_identity or "",
        run=live_dec.run_receipt_id or "",
    )
    drop_pointer(store)
    store.close()
    dest = tmp_path / "h1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        assert waiver_id not in _linked(copy, "review")
        assert other not in _linked(copy, "review")
        assert eligible_approve_ids(copy, fact_id) == []
        rows = copy.conn.execute(
            "SELECT classification, quarantine_reason FROM h1_anchor_receipts "
            "WHERE family = 'review'",
        ).fetchall()
        assert rows
        assert all(str(row[0]) == "quarantined" for row in rows)
    finally:
        copy.close()
