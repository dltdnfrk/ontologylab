"""Review-repair: exact chunk/cite/run bind, waiver seal, no ORDER BY."""

from __future__ import annotations

from pathlib import Path

from ontologylab.citation import list_citation_receipts
from ontologylab.extraction_receipts import put_extraction_receipts
from ontologylab.extraction_state import ExtractionRunBinding
from ontologylab.file_lifecycle import (
    content_hash_for,
    read_ready_text,
    store_root_from_conn,
)
from ontologylab.grounded_review import WaiverRequest, list_review_decisions
from ontologylab.h1 import run_h1_operator
from ontologylab.h1_existing import selection_run_receipt
from ontologylab.kgstore import KGStore
from tests.step7_integration_support import plant_and_extract, probe_node_id
from tests.step7_valid_stale import (
    chunk_id_for_run,
    plant_valid_stale_citation,
    plant_valid_stale_run,
    plant_valid_stale_run_before,
)
from tests.test_step7_h1_existing import _linked


def test_h1_chunk_family_links_live_not_smaller_stale(tmp_path: Path) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    live_run = str(
        store.conn.execute(
            "SELECT receipt_id FROM extraction_run_receipts "
            "WHERE representation_id = ? AND policy_identity != ?",
            (pmc_id, "wrong-policy-v0"),
        ).fetchone()[0]
    )
    live_chunk = chunk_id_for_run(store, live_run)
    _stale_run, stale_chunk = plant_valid_stale_run_before(
        store, pmc_id, live_chunk,
    )
    assert stale_chunk < live_chunk
    store.close()
    dest = tmp_path / "h1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        linked = _linked(copy, "chunk")
        assert live_chunk in linked
        assert stale_chunk not in linked
    finally:
        copy.close()


def test_h1_citation_mint_uses_current_run_not_covering_stale(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    cites = list_citation_receipts(store.conn, "node", fact_id)
    live_cite = {item.receipt_id for item in cites}
    live_run = cites[0].run_receipt_id
    stale_run, _stale_chunk = plant_valid_stale_run_before(
        store, pmc_id, live_run,
    )
    stale_cite = plant_valid_stale_citation(
        store, live=cites[0], stale_run_id=stale_run,
    )
    store.close()
    dest = tmp_path / "h1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        linked = _linked(copy, "citation")
        assert linked == live_cite
        assert stale_cite not in linked
    finally:
        copy.close()


def test_selection_run_receipt_refuses_same_policy_two_configs(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    policy = str(
        store.conn.execute(
            "SELECT policy_hash FROM preferred_selection_receipts "
            "WHERE selected_representation_id = ?",
            (pmc_id,),
        ).fetchone()[0]
    )
    text = read_ready_text(
        store.conn, store_root_from_conn(store.conn), pmc_id,
    )
    body_hash = content_hash_for(text.encode("utf-8"))
    from ontologylab.extraction_receipt_types import DOCUMENT_UTF8_V1, ChunkSpan

    put_extraction_receipts(
        store.conn,
        ExtractionRunBinding(
            representation_id=pmc_id,
            policy_identity=policy,
            config_identity="other-engine-config",
            schema_version_id=1,
            extractor_engine="other",
            extractor_model="alt",
            prompt_version="extract-v1",
            decode_params_json="{}",
        ),
        (
            ChunkSpan(
                index=0, start_offset=0, end_offset=len(text),
                text=text, text_hash=body_hash,
                coordinate_profile=DOCUMENT_UTF8_V1,
            ),
        ),
    )
    store.conn.commit()
    assert selection_run_receipt(store.conn, pmc_id, body_hash) is None
    live_run = {
        str(row[0])
        for row in store.conn.execute(
            "SELECT receipt_id FROM extraction_run_receipts "
            "WHERE representation_id = ? AND config_identity != ?",
            (pmc_id, "other-engine-config"),
        )
    }
    extra = str(
        store.conn.execute(
            "SELECT receipt_id FROM extraction_run_receipts "
            "WHERE config_identity = ?",
            ("other-engine-config",),
        ).fetchone()[0]
    )
    store.close()
    dest = tmp_path / "h1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        linked = _linked(copy, "run")
        assert extra not in linked
        assert not (linked == {extra})
    finally:
        copy.close()
    assert live_run


def test_h1_links_scoped_waiver_not_eligible_approve(tmp_path: Path) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    cites = list_citation_receipts(store.conn, "node", fact_id)
    stale_run = plant_valid_stale_run(store, pmc_id)
    plant_valid_stale_citation(store, live=cites[0], stale_run_id=stale_run)
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
    store.close()
    dest = tmp_path / "h1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        linked = _linked(copy, "review")
        assert linked == {waiver_id}
        twins = copy.conn.execute(
            "SELECT action, pack_ineligible FROM grounded_review_decisions "
            "WHERE fact_id = ? ORDER BY receipt_id",
            (fact_id,),
        ).fetchall()
        assert any(
            str(row[0]) == "approve_with_grounding_waiver" and int(row[1]) == 1
            for row in twins
        )
        eligible = [
            row for row in twins
            if str(row[0]) == "approve" and int(row[1]) == 0
        ]
        assert eligible == []
    finally:
        copy.close()


def test_h1_links_plain_approve_as_current_decision(tmp_path: Path) -> None:
    live = tmp_path / "live"
    store, _work, _pub, _pmc = plant_and_extract(live)
    fact_id = probe_node_id(store)
    store.approve(fact_id, by="integrator", note="fully grounded")
    live_id = list_review_decisions(store.conn, "node", fact_id)[0].receipt_id
    store.close()
    dest = tmp_path / "h1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        assert _linked(copy, "review") == {live_id}
    finally:
        copy.close()
