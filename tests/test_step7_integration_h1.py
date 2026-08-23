"""Step 7 H1 handoff: family receipts agree with the live chain."""

from __future__ import annotations

from pathlib import Path

import pytest

from ontologylab.citation import list_citation_receipts
from ontologylab.grounded_review import list_review_decisions
from ontologylab.kgstore import KGStore
from tests.step7_integration_support import plant_and_extract, probe_node_id
from tests.test_h1_migration import _tree_hashes


def test_h1_on_reviewed_chain_links_family_receipts_and_is_idempotent(
    tmp_path: Path,
) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1Classification
    from ontologylab.migration_rehearsal import canonical_db_hash

    live = tmp_path / "live"
    store, _work_id, _publisher_id, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    live_cite = {
        item.receipt_id
        for item in list_citation_receipts(store.conn, "node", fact_id)
    }
    store.approve(fact_id, by="integrator", note="fully grounded")
    live_review = {
        item.receipt_id
        for item in list_review_decisions(store.conn, "node", fact_id)
    }
    live_run = {
        str(row[0])
        for row in store.conn.execute(
            "SELECT receipt_id FROM extraction_run_receipts "
            "WHERE representation_id = ?",
            (pmc_id,),
        )
    }
    store.close()
    source = live / "kg.sqlite"
    before = _tree_hashes(live)
    dest = tmp_path / "h1-dest"
    dest.mkdir()
    first = run_h1_operator(source, dest)
    assert first.inventory.pending == 0
    assert first.complete is True
    copy = KGStore.open(dest / source.name)
    try:
        families = {
            item.family.value: item for item in first.inventory.families
        }
        assert set(families) == {"run", "chunk", "citation", "review"}
        for family, table in (
            ("run", "extraction_run_receipts"),
            ("chunk", "extraction_chunk_receipts"),
            ("citation", "citation_receipts"),
            ("review", "grounded_review_decisions"),
        ):
            rows = copy.conn.execute(
                "SELECT classification, family_receipt_id, quarantine_reason "
                "FROM h1_anchor_receipts WHERE family = ?",
                (family,),
            ).fetchall()
            assert rows
            for classification, family_id, reason in rows:
                if classification == H1Classification.QUARANTINED.value:
                    assert family_id is None
                    assert not (family == "citation" and reason == "missing_chunk")
                    continue
                assert classification == H1Classification.VERIFIED.value
                assert family_id
                found = copy.conn.execute(
                    f"SELECT 1 FROM {table} WHERE receipt_id = ?",
                    (family_id,),
                ).fetchone()
                assert found is not None
        linked_cites = {
            str(row[0])
            for row in copy.conn.execute(
                "SELECT family_receipt_id FROM h1_anchor_receipts "
                "WHERE family = 'citation' AND classification = 'verified'"
            )
        }
        assert live_cite <= linked_cites
        linked_reviews = {
            str(row[0])
            for row in copy.conn.execute(
                "SELECT family_receipt_id FROM h1_anchor_receipts "
                "WHERE family = 'review' AND classification = 'verified'"
            )
        }
        assert live_review <= linked_reviews
        linked_runs = {
            str(row[0])
            for row in copy.conn.execute(
                "SELECT family_receipt_id FROM h1_anchor_receipts "
                "WHERE family = 'run' AND classification = 'verified'"
            )
        }
        assert live_run <= linked_runs
        reps = {
            str(row[0])
            for row in copy.conn.execute(
                "SELECT representation_id FROM citation_receipts "
                "WHERE fact_id = ?",
                (fact_id,),
            )
        }
        assert reps == {pmc_id}
        dump = canonical_db_hash(copy.conn)
    finally:
        copy.close()
    second = run_h1_operator(source, dest)
    assert second.receipt_sha256 == first.receipt_sha256
    assert second.dump_sha256 == first.dump_sha256 == dump
    assert _tree_hashes(live) == before


def test_h1_malformed_source_writes_zero(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1RefusalCode, H1SourceRefused

    bad = tmp_path / "not.sqlite"
    bad.write_text("not sqlite", encoding="utf-8")
    dest = tmp_path / "h1-bad"
    with pytest.raises(H1SourceRefused) as refused:
        run_h1_operator(bad, dest)
    assert refused.value.code is H1RefusalCode.NOT_SQLITE
    assert not dest.exists() or not any(dest.rglob("*.sqlite"))


def test_h1_source_overlap_writes_zero(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1RefusalCode, H1SourceRefused

    store, *_rest = plant_and_extract(tmp_path / "live")
    source = Path(store.db_path)
    store.close()
    before = _tree_hashes(source.parent)
    with pytest.raises(H1SourceRefused) as overlap:
        run_h1_operator(source, source.parent)
    assert overlap.value.code is H1RefusalCode.SOURCE_OVERLAP
    assert _tree_hashes(source.parent) == before
