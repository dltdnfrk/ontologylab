"""Wave 2.1 Step 6 (F2/6C): fixture-bound concurrent ingest under a barrier."""

from __future__ import annotations

from pathlib import Path

from ontologylab.authority_repo import create_work
from ontologylab.ingestion_service import ingest_item
from ontologylab.kgstore import KGStore
from tests.wave21.harness import Failpoint
from tests.wave21.ingest_concurrency import (
    FAMILY_TRUTH,
    SECOND_DOI_TRUTH,
    ConcurrentIngestFixture,
    family_item,
    second_doi_item,
    stable_projection,
    table_counts,
)


def test_identical_family_one_work_both_observations(tmp_path: Path) -> None:
    fixture = ConcurrentIngestFixture.open(tmp_path)
    report = fixture.run_writers(
        (
            family_item("op-a", source="crossref"),
            family_item("op-b", source="openalex"),
        )
    )

    assert {receipt.status for receipt in report.receipts} == {"created"}
    assert len({receipt.work_id for receipt in report.receipts}) == 1
    assert sum(receipt.work_created for receipt in report.receipts) == 1
    assert {receipt.observation_id for receipt in report.receipts} == set(
        report.observation_ids
    )
    assert len(report.observation_ids) == 2
    assert report.counts == FAMILY_TRUTH
    assert report.errors == ()


def test_observed_order_changes_only_observation_data(tmp_path: Path) -> None:
    fixture = ConcurrentIngestFixture.open(tmp_path)
    items = (
        family_item("op-a", source="crossref"),
        family_item("op-b", source="openalex"),
    )
    concurrent = fixture.run_writers(items)

    sequential_root = tmp_path / "sequential"
    sequential_root.mkdir()
    sequential = ConcurrentIngestFixture.open(sequential_root)
    store = KGStore.open(sequential.db_path)
    try:
        for item in items:
            receipt = ingest_item(store.conn, item)
            assert receipt.status == "created"
        store.conn.commit()
        sequential_projection = stable_projection(store.conn)
        sequential_counts = table_counts(store.conn)
    finally:
        store.close()

    assert concurrent.counts == sequential_counts == FAMILY_TRUTH
    assert concurrent.projection == sequential_projection
    assert concurrent.observation_ids[0] != concurrent.observation_ids[1]


def test_concurrent_second_doi_exactly_one_typed_conflict_no_merge(
    tmp_path: Path,
) -> None:
    fixture = ConcurrentIngestFixture.open(tmp_path)
    store = KGStore.open(fixture.db_path)
    try:
        work_id = create_work(store.conn)
        store.conn.commit()
    finally:
        store.close()

    report = fixture.run_writers(
        (
            second_doi_item("op-first", fixture.family_doi, work_id=work_id),
            second_doi_item("op-second", fixture.second_doi, work_id=work_id),
        )
    )

    statuses = sorted(receipt.status for receipt in report.receipts)
    assert statuses == ["conflict", "created"]
    created = next(
        receipt for receipt in report.receipts if receipt.status == "created"
    )
    conflict = next(
        receipt for receipt in report.receipts if receipt.status == "conflict"
    )
    assert created.work_id == work_id
    assert conflict.conflict is not None
    assert conflict.conflict.kind == "second_doi"
    assert conflict.conflict.work_id == work_id
    assert {conflict.conflict.existing_value, conflict.conflict.incoming_value} == {
        fixture.family_doi,
        fixture.second_doi,
    }
    assert report.counts == SECOND_DOI_TRUTH
    assert report.errors == ()


def test_concurrent_ingest_has_no_partial_observation_or_assertion(
    tmp_path: Path,
) -> None:
    fixture = ConcurrentIngestFixture.open(tmp_path)
    report = fixture.run_writers(
        (
            family_item("op-a"),
            family_item("op-b"),
        )
    )

    assert report.counts["document_observations"] == 2
    assert report.counts["identifier_assertions"] == 2
    assert report.counts["dangling_assertions"] == 0
    assert report.counts["orphan_identifiers"] == 0
    assert report.counts["observations_without_assertion"] == 0


def test_reservation_loser_receives_typed_conflict_with_zero_partial_rows(
    tmp_path: Path,
) -> None:
    fixture = ConcurrentIngestFixture.open(tmp_path)
    store = KGStore.open(fixture.db_path)
    try:
        winner_work = create_work(store.conn)
        loser_work = create_work(store.conn)
        store.conn.commit()
    finally:
        store.close()

    report = fixture.run_writers(
        (
            second_doi_item("op-win", fixture.family_doi, work_id=winner_work),
            second_doi_item("op-lose", fixture.family_doi, work_id=loser_work),
        )
    )

    statuses = sorted(receipt.status for receipt in report.receipts)
    assert statuses == ["conflict", "created"]
    created = next(
        receipt for receipt in report.receipts if receipt.status == "created"
    )
    conflict = next(
        receipt for receipt in report.receipts if receipt.status == "conflict"
    )
    assert created.status == "created"
    assert conflict.status == "conflict"
    assert conflict.conflict is not None
    assert conflict.conflict.kind == "identifier_owned"
    assert conflict.conflict.existing_work_id == created.work_id
    assert conflict.work_id in {winner_work, loser_work}
    assert created.work_id != conflict.work_id
    assert report.counts == {
        "works": 2,
        "documents": 0,
        "work_identifiers": 1,
        "document_observations": 1,
        "identifier_assertions": 1,
        "dangling_assertions": 0,
        "orphan_identifiers": 0,
        "observations_without_assertion": 0,
    }
    assert report.errors == ()


def test_same_work_family_records_both_observations(tmp_path: Path) -> None:
    fixture = ConcurrentIngestFixture.open(tmp_path)
    store = KGStore.open(fixture.db_path)
    try:
        work_id = create_work(store.conn)
        store.conn.commit()
    finally:
        store.close()

    report = fixture.run_writers(
        (
            second_doi_item("op-a", fixture.family_doi, work_id=work_id),
            second_doi_item("op-b", fixture.family_doi, work_id=work_id),
        )
    )

    assert {receipt.status for receipt in report.receipts} == {"created"}
    assert {receipt.work_id for receipt in report.receipts} == {work_id}
    assert len({receipt.observation_id for receipt in report.receipts}) == 2
    assert report.counts == {
        "works": 1,
        "documents": 0,
        "work_identifiers": 1,
        "document_observations": 2,
        "identifier_assertions": 2,
        "dangling_assertions": 0,
        "orphan_identifiers": 0,
        "observations_without_assertion": 0,
    }


def test_failpoint_between_reservation_and_assertion_leaves_no_dangling_assertion(
    tmp_path: Path,
) -> None:
    fixture = ConcurrentIngestFixture.open(tmp_path)
    armed = Failpoint()
    armed.arm("after_identifier_reservation")
    report = fixture.run_writers(
        (
            family_item("op-ok"),
            family_item("op-boom"),
        ),
        failpoints=(None, armed),
    )

    statuses = sorted(receipt.status for receipt in report.receipts)
    assert statuses == ["created", "failed"]
    failed = next(
        receipt for receipt in report.receipts if receipt.status == "failed"
    )
    assert failed.error == "FailpointArmed: after_identifier_reservation"
    assert report.counts["dangling_assertions"] == 0
    assert report.counts["orphan_identifiers"] == 0
    assert report.counts["document_observations"] == report.counts[
        "identifier_assertions"
    ]
    assert report.counts["works"] == 1
    assert report.counts["work_identifiers"] == 1
    assert report.counts["document_observations"] == 1
    assert report.errors == ()


def test_unrelated_sentinel_survives_barrier_writers(tmp_path: Path) -> None:
    fixture = ConcurrentIngestFixture.open(tmp_path)
    sentinel_work = fixture.seed_sentinel()
    report = fixture.run_writers(
        (
            family_item("op-a"),
            family_item("op-b"),
        )
    )

    assert sentinel_work not in {receipt.work_id for receipt in report.receipts}
    assert report.counts["works"] == 2
    assert report.counts["work_identifiers"] == 2
    assert report.counts["document_observations"] == 3
    assert report.counts["identifier_assertions"] == 3
    assert report.counts["dangling_assertions"] == 0
    store = KGStore.open(fixture.db_path)
    try:
        row = store.conn.execute(
            "SELECT work_id FROM work_identifiers "
            "WHERE scheme = 'doi' AND normalized_value = ?",
            (fixture.sentinel_doi,),
        ).fetchone()
        assert row is not None
        assert row[0] == sentinel_work
    finally:
        store.close()
