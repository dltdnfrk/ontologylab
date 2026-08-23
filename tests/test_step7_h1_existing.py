"""H1 links only exact classified identities, not valid stale policies."""

from __future__ import annotations

from pathlib import Path

from ontologylab.citation import list_citation_receipts
from ontologylab.citation_ids import fact_revision_id
from ontologylab.extraction_receipt_ids import digest
from ontologylab.grounded_review import list_review_decisions
from ontologylab.grounded_review_ids import citation_set_digest
from ontologylab.h1 import run_h1_operator
from ontologylab.h1_ids import LEGACY_POLICY
from ontologylab.kgstore import KGStore
from tests.step7_integration_support import plant_and_extract, probe_node_id
from tests.step7_valid_stale import (
    plant_valid_stale_citation,
    plant_valid_stale_review,
    plant_valid_stale_run,
)
from tests.test_h1_migration import _single_rep_source


def _linked(copy: KGStore, family: str) -> set[str]:
    return {
        str(row[0])
        for row in copy.conn.execute(
            "SELECT family_receipt_id FROM h1_anchor_receipts "
            "WHERE family = ? AND classification = 'verified' "
            "AND family_receipt_id IS NOT NULL",
            (family,),
        )
    }


def test_valid_stale_run_only_is_not_linked(tmp_path: Path) -> None:
    source, _gateway, _service, _edge = _single_rep_source(tmp_path)
    store = KGStore.open(source)
    try:
        doc = store.conn.execute(
            "SELECT id, content_hash FROM documents"
        ).fetchone()
        assert doc is not None
        stale_run = plant_valid_stale_run(store, str(doc[0]))
        live_hash = str(doc[1])
    finally:
        store.close()
    dest = tmp_path / "h1-only"
    dest.mkdir()
    receipt = run_h1_operator(source, dest)
    assert receipt.inventory.pending == 0
    copy = KGStore.open(dest / Path(source).name)
    try:
        linked = _linked(copy, "run")
        assert stale_run not in linked
        minted = copy.conn.execute(
            "SELECT receipt_id, policy_identity, document_content_hash "
            "FROM extraction_run_receipts WHERE receipt_id != ?",
            (stale_run,),
        ).fetchone()
        assert minted is not None
        assert minted[0] in linked
        assert minted[1] == LEGACY_POLICY
        assert minted[2] == live_hash
        assert linked == {str(minted[0])}
    finally:
        copy.close()


def test_live_run_wins_over_valid_stale_without_third_id(tmp_path: Path) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    live_run = {
        str(row[0])
        for row in store.conn.execute(
            "SELECT receipt_id FROM extraction_run_receipts "
            "WHERE representation_id = ? AND policy_identity != ?",
            (pmc_id, "wrong-policy-v0"),
        )
    }
    stale_run = plant_valid_stale_run(store, pmc_id)
    store.close()
    dest = tmp_path / "h1-run"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        linked = _linked(copy, "run")
        assert linked == live_run
        assert stale_run not in linked
        third = copy.conn.execute(
            "SELECT COUNT(*) FROM extraction_run_receipts "
            "WHERE representation_id = ?",
            (pmc_id,),
        ).fetchone()[0]
        assert third == 2
        assert fact_id
    finally:
        copy.close()


def test_valid_stale_citation_is_not_linked(tmp_path: Path) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    cites = list_citation_receipts(store.conn, "node", fact_id)
    assert cites
    live_cite = {item.receipt_id for item in cites}
    stale_run = plant_valid_stale_run(store, pmc_id)
    stale_cite = plant_valid_stale_citation(
        store, live=cites[0], stale_run_id=stale_run,
    )
    store.close()
    dest = tmp_path / "h1-cite"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        linked = _linked(copy, "citation")
        assert live_cite <= linked
        assert stale_cite not in linked
        assert linked == live_cite
    finally:
        copy.close()


def test_valid_stale_review_is_not_linked(tmp_path: Path) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    cites = list_citation_receipts(store.conn, "node", fact_id)
    assert cites
    store.approve(fact_id, by="integrator", note="fully grounded")
    live_review = {
        item.receipt_id
        for item in list_review_decisions(store.conn, "node", fact_id)
    }
    live_dec = list_review_decisions(store.conn, "node", fact_id)[0]
    stale_run = plant_valid_stale_run(store, pmc_id)
    stale_cite = plant_valid_stale_citation(
        store, live=cites[0], stale_run_id=stale_run,
    )
    stale_review = plant_valid_stale_review(
        store, live=live_dec, stale_cite_id=stale_cite, stale_run_id=stale_run,
    )
    store.close()
    dest = tmp_path / "h1-rev"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        linked = _linked(copy, "review")
        assert linked == live_review
        assert stale_review not in linked
    finally:
        copy.close()


def test_h1_reuses_exact_compatible_v1_review_row(tmp_path: Path) -> None:
    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    cites = list_citation_receipts(store.conn, "node", fact_id)
    assert cites
    citation_ids = tuple(item.receipt_id for item in cites)
    revision = fact_revision_id("node", fact_id)
    v1_id = digest((
        "grounded-review-v1",
        "node",
        fact_id,
        revision,
        "approve",
        citation_set_digest(citation_ids),
        "integrator",
        "fully grounded",
        "",
    ))
    store.conn.execute(
        "INSERT INTO grounded_review_decisions ("
        "receipt_id, fact_kind, fact_id, proposal_id, fact_revision, "
        "action, actor, reason, decided_ts, as_of_ts, citation_set_digest, "
        "citation_receipt_ids_json, representation_id, selection_receipt_id, "
        "policy_identity, run_receipt_id, predecessor_receipt_id, "
        "pack_ineligible, waived_fact_ids_json, waived_citation_ids_json, "
        "scoped_defects_json) "
        "VALUES (?,?,?,?,?,?,?,?,15,15,?,?,?,?,?,?,?,0,'[]','[]','[]')",
        (
            v1_id, "node", fact_id, fact_id, revision, "approve",
            "integrator", "fully grounded", citation_set_digest(citation_ids),
            "[\"" + "\",\"".join(citation_ids) + "\"]",
            pmc_id, cites[0].selection_receipt_id, cites[0].policy_identity,
            cites[0].run_receipt_id, None,
        ),
    )
    store.conn.execute(
        "UPDATE nodes SET status = 'verified', verified_by = ?, "
        "review_note = ?, verified_ts = 15 WHERE id = ?",
        ("integrator", "fully grounded", fact_id),
    )
    store.conn.commit()
    store.close()
    dest = tmp_path / "h1-v1"
    dest.mkdir()
    run_h1_operator(live / "kg.sqlite", dest)
    copy = KGStore.open(dest / "kg.sqlite")
    try:
        assert v1_id in _linked(copy, "review")
    finally:
        copy.close()
