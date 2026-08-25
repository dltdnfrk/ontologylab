"""F9 preferred-representation selection receipts."""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from pathlib import Path
from types import SimpleNamespace

from ontologylab.engines import MockEngine
from ontologylab.extractor import TOTALS_KEYS, run_extraction
from ontologylab.file_lifecycle import content_hash_for, finalize_representation
from ontologylab.ingestion_service import IngestItem, RepresentationInput, ingest_item
from ontologylab.kgstore import KGStore
from ontologylab.preferred import preferred_representation
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps
from ontologylab.work_view import work_snapshot


PUBLISHER_TOKEN = "PublisherAbstractGateway"
PMC_TOKEN = "PmcFulltextProbe"
PUBLISHER_BODY = (f"{PUBLISHER_TOKEN} published abstract. " * 8).encode("utf-8")
PMC_BODY = (f"{PMC_TOKEN} unknown-stage ready full text. " * 40).encode("utf-8")
DOI = "10.1000/c024.fixture"


def caps() -> Caps:
    return Caps(
        SimpleNamespace(iterations=0, time_budget_s=60.0, max_engine_calls=40)
    )


def plant_c024(
    tmp_path: Path,
    *,
    reverse: bool = False,
    publisher_ready: bool = True,
    pmc_ready: bool = True,
) -> tuple[KGStore, str, str, str]:
    store = KGStore.open(tmp_path / "kg.sqlite")
    specs = (
        ("publisher", "published", "abstract", PUBLISHER_BODY, publisher_ready),
        ("pmc", "unknown", "fulltext", PMC_BODY, pmc_ready),
    )
    if reverse:
        specs = tuple(reversed(specs))
    work_id: str | None = None
    ids: dict[str, str] = {}
    for source, stage, kind, body, ready in specs:
        receipt = ingest_item(
            store.conn,
            IngestItem(
                idempotency_key=f"op-{source}-{kind}",
                scheme="doi",
                normalized_value=DOI,
                source=source,
                evidence_grade="A",
                work_id=work_id,
                representation=RepresentationInput(
                    source_kind="paper_api",
                    source_uri=f"https://example.invalid/{source}/c024",
                    title="C024",
                    content_hash=content_hash_for(body),
                    raw_text=body,
                ),
                stage=stage,
                content_kind=kind,
            ),
        )
        assert receipt.work_id is not None
        assert receipt.representation_id is not None
        work_id = receipt.work_id
        ids[source] = receipt.representation_id
        store.conn.commit()
        if ready:
            finalize_representation(store.conn, tmp_path, receipt.representation_id)
            store.conn.commit()
    assert work_id is not None
    return store, work_id, ids["publisher"], ids["pmc"]


def node_names(store: KGStore) -> set[str]:
    return {
        str(row["name"])
        for row in store.conn.execute("SELECT name FROM nodes")
    }


def source_doc_ids(store: KGStore) -> set[str]:
    return {
        str(row["source_doc_id"])
        for row in store.conn.execute("SELECT DISTINCT source_doc_id FROM nodes")
    }


def test_identifierless_ready_fulltext_remains_selectable(
    tmp_path: Path,
) -> None:
    from ontologylab.selection import put_selection_receipt
    from ontologylab.selection_types import PolicyVersion

    # Given a ready full-text Representation without an external identifier
    store = KGStore.open(tmp_path / "identifierless.sqlite")
    try:
        body = b"IdentifierlessReadyFullText " * 40
        ingested = ingest_item(
            store.conn,
            IngestItem(
                idempotency_key="identifierless-fulltext",
                scheme="",
                normalized_value="",
                source="upload",
                evidence_grade="A",
                representation=RepresentationInput(
                    source_kind="upload",
                    source_uri="file:///identifierless.txt",
                    title="Identifierless",
                    content_hash=content_hash_for(body),
                    raw_text=body,
                ),
                stage="unknown",
                content_kind="fulltext",
            ),
        )
        assert ingested.work_id is not None
        assert ingested.representation_id is not None
        store.conn.commit()
        finalize_representation(
            store.conn,
            tmp_path,
            ingested.representation_id,
        )
        store.conn.commit()

        # When F9 selects evidence for the Work
        selected = put_selection_receipt(
            store.conn,
            ingested.work_id,
            PolicyVersion.V1,
        )

        # Then the identifier-less full text retains its metadata and wins
        assert selected.selected_representation_id == ingested.representation_id
        assert selected.inventory[0].usable_full_text_rank == 0
    finally:
        store.close()


def test_baseline_stage_first_projection_picks_published_abstract() -> None:
    publisher = {
        "doc_id": "rep-pub",
        "stage": "published",
        "kind": "abstract",
        "evidence_grade": "A",
        "source": "publisher",
        "byte_length": len(PUBLISHER_BODY),
        "content_hash": content_hash_for(PUBLISHER_BODY),
    }
    pmc = {
        "doc_id": "rep-pmc",
        "stage": "unknown",
        "kind": "fulltext",
        "evidence_grade": "A",
        "source": "pmc",
        "byte_length": len(PMC_BODY),
        "content_hash": content_hash_for(PMC_BODY),
    }
    assert preferred_representation([publisher, pmc])["doc_id"] == "rep-pub"
    assert preferred_representation([pmc, publisher])["doc_id"] == "rep-pub"


def test_baseline_work_view_prefers_published_abstract_on_c024(
    tmp_path: Path,
) -> None:
    store, work_id, publisher_id, _pmc_id = plant_c024(tmp_path)
    try:
        snap = work_snapshot(store.conn, work_id)
        assert snap["preferred_representation_id"] == publisher_id
    finally:
        store.close()


def test_baseline_run_extraction_extracts_every_collected_id(
    tmp_path: Path,
) -> None:
    store, _work_id, publisher_id, pmc_id = plant_c024(tmp_path)
    try:
        totals = dict.fromkeys(TOTALS_KEYS, 0)

        def _stats(stats: dict[str, int]) -> None:
            for key in totals:
                totals[key] += stats.get(key, 0)

        asyncio.run(
            run_extraction(
                store,
                MockEngine(),
                Provenance(str(tmp_path / "job-baseline"), seed=0),
                caps(),
                [publisher_id, pmc_id],
                extractor_engine="mock",
                extractor_model=None,
                on_progress=lambda _line: None,
                on_stats=_stats,
            )
        )
        assert PUBLISHER_TOKEN in node_names(store)
        assert PMC_TOKEN in node_names(store)
        assert source_doc_ids(store) == {publisher_id, pmc_id}
    finally:
        store.close()


def test_c024_selection_receipt_selects_pmc_and_binds_inventory(
    tmp_path: Path,
) -> None:
    from ontologylab.selection import put_selection_receipt
    from ontologylab.selection_types import PolicyVersion

    store, work_id, publisher_id, pmc_id = plant_c024(tmp_path)
    try:
        receipt = put_selection_receipt(store.conn, work_id, PolicyVersion.V1)
        assert receipt.selected_representation_id == pmc_id
        assert receipt.selected_content_hash == content_hash_for(PMC_BODY)
        assert receipt.work_id == work_id
        assert receipt.policy_version == PolicyVersion.V1
        assert receipt.policy_hash.startswith("sha256:")
        inventoried = {
            entry.representation_id: entry for entry in receipt.inventory
        }
        assert set(inventoried) == {publisher_id, pmc_id}
        assert inventoried[pmc_id].rejection_reason is None
        assert inventoried[publisher_id].rejection_reason is None
        assert receipt.receipt_id.startswith("sha256:")
    finally:
        store.close()


def test_c024_selection_is_stable_when_insertion_reverses(
    tmp_path: Path,
) -> None:
    from ontologylab.selection import put_selection_receipt
    from ontologylab.selection_types import PolicyVersion

    forward = plant_c024(tmp_path / "fwd")
    reverse = plant_c024(tmp_path / "rev", reverse=True)
    try:
        first = put_selection_receipt(
            forward[0].conn, forward[1], PolicyVersion.V1,
        )
        second = put_selection_receipt(
            reverse[0].conn, reverse[1], PolicyVersion.V1,
        )
        assert first.selected_representation_id == forward[3]
        assert second.selected_representation_id == reverse[3]
        assert first.policy_hash == second.policy_hash
        assert first.selected_content_hash == content_hash_for(PMC_BODY)
        assert second.selected_content_hash == content_hash_for(PMC_BODY)
    finally:
        forward[0].close()
        reverse[0].close()


def test_c024_receipt_row_binds_inventory_policy_and_selected(
    tmp_path: Path,
) -> None:
    from ontologylab.selection import put_selection_receipt
    from ontologylab.selection_types import PolicyVersion

    store, work_id, publisher_id, pmc_id = plant_c024(tmp_path)
    try:
        receipt = put_selection_receipt(store.conn, work_id, PolicyVersion.V1)
        row = store.conn.execute(
            "SELECT work_id, policy_version, policy_hash, "
            "selected_representation_id, selected_content_hash, inventory_json "
            "FROM preferred_selection_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
        assert row is not None
        assert row["work_id"] == work_id
        assert row["policy_version"] == str(PolicyVersion.V1)
        assert row["policy_hash"] == receipt.policy_hash
        assert row["selected_representation_id"] == pmc_id
        assert publisher_id in row["inventory_json"]
        assert pmc_id in row["inventory_json"]
    finally:
        store.close()


def test_policy_v2_does_not_recompute_historical_v1_receipt(
    tmp_path: Path,
) -> None:
    from ontologylab.selection import get_selection_receipt, put_selection_receipt
    from ontologylab.selection_types import PolicyVersion

    store, work_id, publisher_id, pmc_id = plant_c024(tmp_path)
    try:
        first = put_selection_receipt(store.conn, work_id, PolicyVersion.V1)
        assert first.selected_representation_id == pmc_id
        second = put_selection_receipt(store.conn, work_id, PolicyVersion.V2)
        assert second.selected_representation_id == publisher_id
        assert second.receipt_id != first.receipt_id
        loaded = get_selection_receipt(store.conn, first.receipt_id)
        assert loaded is not None
        assert loaded.receipt_id == first.receipt_id
        assert loaded.selected_representation_id == pmc_id
        assert loaded.policy_version == str(PolicyVersion.V1)
        assert loaded.policy_hash == first.policy_hash
        assert loaded.inventory == first.inventory
    finally:
        store.close()


def test_work_candidates_include_ready_state_for_selection_seam(
    tmp_path: Path,
) -> None:
    from ontologylab.work_view import work_candidates

    store, work_id, publisher_id, pmc_id = plant_c024(
        tmp_path, pmc_ready=False,
    )
    try:
        candidates = work_candidates(store.conn, work_id)
        by_id = {item.representation_id: item for item in candidates}
        assert by_id[publisher_id].state == "ready"
        assert by_id[pmc_id].state == "staged"
        assert by_id[pmc_id].kind == "fulltext"
        assert by_id[publisher_id].kind == "abstract"
    finally:
        store.close()
