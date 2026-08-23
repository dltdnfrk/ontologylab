"""Step 7 integration: C-024 select/extract/cite/review across surfaces."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ontologylab.citation import list_citation_receipts
from ontologylab.file_lifecycle import content_hash_for, store_root_from_conn
from ontologylab.grounded_review import list_review_decisions
from ontologylab.kgstore import GroundingPreflightError, KGStore
from ontologylab.selection import list_selection_receipts
from tests.step7_integration_support import (
    decision_count,
    plant_and_extract,
    probe_node_id,
    research_session,
    table_count,
)
from tests.test_preferred_selection import (
    PMC_BODY,
    PMC_TOKEN,
    PUBLISHER_TOKEN,
    node_names,
    plant_c024,
    source_doc_ids,
)


def _ready_path(store: KGStore, representation_id: str) -> Path:
    row = store.conn.execute(
        "SELECT raw_text_path FROM documents WHERE id = ?",
        (representation_id,),
    ).fetchone()
    assert row is not None
    return store_root_from_conn(store.conn) / str(row["raw_text_path"])


def test_c024_chain_receipts_agree_on_representation(tmp_path: Path) -> None:
    store, work_id, publisher_id, pmc_id = plant_and_extract(tmp_path / "live")
    try:
        selections = list_selection_receipts(store.conn, work_id)
        assert len(selections) == 1
        selection = selections[0]
        assert selection.selected_representation_id == pmc_id
        inventoried = {entry.representation_id for entry in selection.inventory}
        assert inventoried == {publisher_id, pmc_id}
        assert selection.policy_version == "preferred-representation-v1"
        run = store.conn.execute(
            "SELECT representation_id, document_content_hash, receipt_id "
            "FROM extraction_run_receipts"
        ).fetchone()
        assert run is not None
        assert run["representation_id"] == pmc_id
        assert run["document_content_hash"] == content_hash_for(PMC_BODY)
        assert PMC_TOKEN in node_names(store)
        assert PUBLISHER_TOKEN not in node_names(store)
        assert source_doc_ids(store) == {pmc_id}
        fact_id = probe_node_id(store)
        citations = list_citation_receipts(store.conn, "node", fact_id)
        assert citations
        ready = _ready_path(store, pmc_id).read_text(encoding="utf-8")
        for item in citations:
            assert item.representation_id == pmc_id
            assert item.run_receipt_id == run["receipt_id"]
            assert item.selection_receipt_id == selection.receipt_id
            assert item.policy_identity == selection.policy_hash
            assert ready[item.start_offset:item.end_offset] == item.selected_text
            assert PUBLISHER_TOKEN not in item.selected_text
        result = store.approve(fact_id, by="integrator", note="fully grounded")
        receipts = result["decision_receipt_ids"]
        assert receipts
        decisions = list_review_decisions(store.conn, "node", fact_id)
        assert len(decisions) == 1
        decision = decisions[0]
        assert decision.receipt_id == receipts[0]
        assert decision.representation_id == pmc_id
        assert decision.selection_receipt_id == selection.receipt_id
        assert decision.run_receipt_id == run["receipt_id"]
        assert tuple(decision.citation_receipt_ids) == tuple(
            item.receipt_id for item in citations
        )
        assert decision.fact_id == fact_id
        assert decision.fact_revision == citations[0].fact_revision
    finally:
        store.close()


def test_staged_only_refuses_without_abstract_or_partial_writes(
    tmp_path: Path,
) -> None:
    import asyncio  # noqa: ANYIO_OK

    from ontologylab.research_extract import extract_research_documents
    from ontologylab.selection_types import SelectionRefusalCode, SelectionRefused

    live = tmp_path / "staged"
    store, _work_id, publisher_id, pmc_id = plant_c024(live, pmc_ready=False)
    try:
        with pytest.raises(SelectionRefused) as refused:
            asyncio.run(
                extract_research_documents(
                    store,
                    (publisher_id, pmc_id),
                    research_session(live / "job"),
                )
            )
        assert refused.value.code is SelectionRefusalCode.NO_ELIGIBLE_READY_FULL_TEXT
        assert node_names(store) == set()
        assert table_count(store, "citation_receipts") == 0
        assert table_count(store, "extraction_run_receipts") == 0
        leaked = " ".join(
            str(row[0])
            for row in store.conn.execute("SELECT name FROM nodes")
        )
        assert PUBLISHER_TOKEN not in leaked
    finally:
        store.close()


def test_tampered_ready_bytes_block_review_with_zero_decisions(
    tmp_path: Path,
) -> None:
    store, _work_id, _publisher_id, pmc_id = plant_and_extract(tmp_path / "live")
    try:
        fact_id = probe_node_id(store)
        path = _ready_path(store, pmc_id)
        path.write_bytes(path.read_bytes() + b"X")
        before = decision_count(store)
        with pytest.raises(GroundingPreflightError):
            store.approve(fact_id, by="integrator", note="should fail")
        assert decision_count(store) == before == 0
        assert store.conn.execute(
            "SELECT status FROM nodes WHERE id = ?", (fact_id,),
        ).fetchone()[0] == "proposed"
    finally:
        store.close()


def test_generic_waiver_refused_scoped_waiver_pack_ineligible(
    tmp_path: Path,
) -> None:
    from ontologylab.grounded_review import WaiverRequest
    from ontologylab.kgstore import KGStoreError

    store, _work_id, _publisher_id, _pmc_id = plant_and_extract(tmp_path / "live")
    try:
        fact_id = probe_node_id(store)
        with pytest.raises(KGStoreError):
            store.approve_with_grounding_waiver(
                WaiverRequest(
                    item_id=fact_id,
                    actor="integrator",
                    reason="ship it",
                    member_ids=(),
                    citation_ids=(),
                    scoped_defects=(),
                )
            )
        assert decision_count(store) == 0
        result = store.approve_with_grounding_waiver(
            WaiverRequest(
                item_id=fact_id,
                actor="integrator",
                reason="named scoped waiver",
                member_ids=(fact_id,),
                citation_ids=(),
                scoped_defects=(f"node:{fact_id}:operator",),
            )
        )
        assert result["decision_receipt_ids"]
        decisions = list_review_decisions(store.conn, "node", fact_id)
        assert len(decisions) == 1
        assert decisions[0].pack_ineligible is True
        assert fact_id in decisions[0].waived_fact_ids
    finally:
        store.close()


def test_http_approve_returns_stored_decision_receipt_ids(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    live = tmp_path / "live"
    store, _work_id, _publisher_id, _pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    store.close()
    posted = TestClient(create_app(data_dir=live)).post(
        "/api/proposals/approve",
        json={"id": fact_id, "by": "http-actor", "note": "http grounded"},
    )
    assert posted.status_code == 200, posted.text
    http_ids = posted.json()["decision_receipt_ids"]
    assert http_ids and all(item.startswith("sha256:") for item in http_ids)
    store = KGStore.open(live / "kg.sqlite")
    try:
        stored = list_review_decisions(store.conn, "node", fact_id)
        assert [item.receipt_id for item in stored] == http_ids
    finally:
        store.close()


def test_cli_reject_returns_stored_decision_receipt_ids(tmp_path: Path) -> None:
    from contextlib import redirect_stdout

    from ontologylab.main import main

    live = tmp_path / "live"
    store, _work_id, _publisher_id, _pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    store.close()
    buf = StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exited:
        main([
            "reject", "--id", fact_id, "--by", "cli-actor",
            "--note", "cli reject", "--data-dir", str(live),
        ])
    assert exited.value.code == 0
    out = buf.getvalue()
    store = KGStore.open(live / "kg.sqlite")
    try:
        latest = list_review_decisions(store.conn, "node", fact_id)[-1]
        assert latest.receipt_id.startswith("sha256:")
        assert f"decision_receipt_ids {latest.receipt_id}" in out
    finally:
        store.close()
