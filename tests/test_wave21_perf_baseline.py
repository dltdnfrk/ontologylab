from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.wave21.perf import (
    MANIFEST_PATH,
    deterministic_documents,
    load_manifest,
    manifest_sha256,
    measure_existing_operations,
    write_receipts,
)


def test_recipe_generator_matches_frozen_collision_ratios() -> None:
    documents = deterministic_documents(10000)

    assert len(documents) == 10000
    assert len(documents) - len({document.doi for document in documents}) == 500
    assert (
        len(documents)
        - len({document.raw_text for document in documents})
        == 500
    )

    dois_by_text: dict[str, set[str | None]] = {}
    for document in documents:
        dois_by_text.setdefault(document.raw_text, set()).add(document.doi)
    assert all(
        len(dois) == 2
        for dois in dois_by_text.values()
        if len(dois) > 1
    )


def test_target_migration_contract_is_anchored_and_not_yet_measured() -> None:
    """Step 2 prepares the measured target-migration harness CONTRACT only:
    it anchors the frozen wave21-perf-v1 manifest by hash and names Step 5
    as the measuring owner, while the manifest keeps the operation
    forbidden now."""
    contract_path = (
        MANIFEST_PATH.parent / "target-migration-contract-v1.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    manifest = load_manifest()

    anchor = contract["recipe_anchor"]
    assert anchor["recipe_id"] == manifest["recipe_id"] == "wave21-perf-v1"
    assert anchor["manifest_sha256"] == manifest_sha256(MANIFEST_PATH)

    operation = contract["operation"]
    assert operation["id"] == "target_v2_migration"
    assert operation["measured_at_step"] == 5
    assert contract["forbidden_now"] is True
    assert set(contract["required_metrics"]) == {
        "n", "mean_ms", "p95_ms", "max_ms",
    }
    assert set(contract["required_receipt_fields"]) >= {
        "dataset_documents", "environment", "receipt_sha256",
    }
    # The manifest itself still forbids the operation: preparing the
    # contract must not sneak the measurement into Step 2.
    assert "target_v2_migration" in manifest["forbidden"]
    assert "target_v2_migration" not in {
        item["id"] for item in manifest["operations"]
    }


def test_manifest_validates_and_has_stable_hash() -> None:
    manifest = load_manifest()
    digest = manifest_sha256()

    assert manifest["recipe_id"] == "wave21-perf-v1"
    assert manifest["dataset"]["documents"] == 10000
    assert len(digest) == 64
    assert digest == manifest_sha256(MANIFEST_PATH)
    operation_ids = {
        operation["id"] for operation in manifest["operations"]
    }
    assert operation_ids == {
        "fixture_create_open_noop",
        "legacy_noop_migration_open",
        "current_ingest_create_and_duplicate",
        "current_pack_build",
    }
    assert "target_v2_migration" not in operation_ids


def test_manifest_rejects_a_byte_mutation(tmp_path: Path) -> None:
    mutated = tmp_path / "perf-v1-mutated.json"
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["operations"].append({"id": "target_v2_migration", "kind": "forbidden"})
    mutated.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected operations"):
        load_manifest(mutated)


def test_existing_operation_baseline_receipts(tmp_path: Path) -> None:
    perf_root = tmp_path / "perf"
    receipts = measure_existing_operations(perf_root, document_count=24)
    receipt_hash = write_receipts(tmp_path / "receipts.json", receipts)

    assert {receipt.operation for receipt in receipts} == {
        "fixture_create_open_noop",
        "legacy_noop_migration_open",
        "current_ingest_create_and_duplicate",
        "current_pack_build",
    }
    assert all(receipt.dataset_documents == 24 for receipt in receipts)
    assert all(receipt.n > 0 for receipt in receipts)
    assert all(receipt.p95_ms >= receipt.mean_ms for receipt in receipts)
    assert all(receipt.max_ms >= receipt.p95_ms for receipt in receipts)
    assert all(len(receipt.receipt_sha256) == 64 for receipt in receipts)
    assert len(receipt_hash) == 64

    stored = json.loads((tmp_path / "receipts.json").read_text(encoding="utf-8"))
    assert [item["operation"] for item in stored] == [
        "fixture_create_open_noop",
        "legacy_noop_migration_open",
        "current_ingest_create_and_duplicate",
        "current_pack_build",
    ]
    assert all(item["dataset_documents"] == 24 for item in stored)
    assert all("target_v2_migration" != item["operation"] for item in stored)

    for db_path in (
        perf_root / "fixture-create-0" / "kg.sqlite",
        perf_root / "legacy-noop" / "kg.sqlite",
        perf_root / "pack-source" / "kg.sqlite",
    ):
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT count(*) FROM documents").fetchone() == (24,)
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(documents)")
            }
            assert "doi" in columns
