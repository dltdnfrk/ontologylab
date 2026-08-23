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

TARGET_MIGRATION_RECEIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / ".omo"
    / "evidence"
    / "ulw"
    / "wave21-step5-migration-core-20260821"
    / "G004-goal-4-produce-the-first-measured-ta"
    / "a1"
    / "perf-receipt.json"
)
FROZEN_MANIFEST_SHA256 = (
    "019a986f878bcba5b2ba8c67a1451d8fc19af021988e28bdd9f7e2287f82f0b1"
)
REQUIRED_BUDGET_FIELDS = ("cpu_s", "max_rss_bytes", "disk_bytes", "wall_s")


def load_target_migration_receipt(
    path: Path = TARGET_MIGRATION_RECEIPT_PATH,
) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"measured receipt cannot resolve: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_target_migration_receipt(receipt: dict) -> dict:
    if receipt.get("operation") != "target_v2_migration":
        raise ValueError("unexpected operation")
    if receipt.get("dataset_documents") != 10000:
        raise ValueError("dataset_documents must be 10000")
    for field in ("n", "mean_ms", "p95_ms", "max_ms"):
        if field not in receipt:
            raise ValueError(f"missing metric {field}")
    if int(receipt["n"]) <= 0:
        raise ValueError("n must be positive")
    if float(receipt["p95_ms"]) < float(receipt["mean_ms"]):
        raise ValueError("p95_ms must be >= mean_ms")
    if float(receipt["max_ms"]) < float(receipt["p95_ms"]):
        raise ValueError("max_ms must be >= p95_ms")
    environment = receipt.get("environment")
    if not isinstance(environment, dict) or not {
        "python",
        "platform",
        "machine",
    } <= set(environment):
        raise ValueError("environment must include python/platform/machine")
    digest = receipt.get("receipt_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("receipt_sha256 must be a 64-char hex digest")
    budget = receipt.get("budget")
    if not isinstance(budget, dict):
        raise ValueError("missing budget")
    for field in REQUIRED_BUDGET_FIELDS:
        if field not in budget:
            raise ValueError(f"missing budget field: {field}")
        if not isinstance(budget[field], (int, float)) or budget[field] <= 0:
            raise ValueError(f"budget field {field} must be positive")
    anchor = receipt.get("recipe_anchor")
    if not isinstance(anchor, dict):
        raise ValueError("missing recipe_anchor")
    if anchor.get("manifest_sha256") != FROZEN_MANIFEST_SHA256:
        raise ValueError("recipe_anchor.manifest_sha256 does not match frozen recipe")
    if anchor.get("manifest_sha256") != manifest_sha256():
        raise ValueError("recipe_anchor.manifest_sha256 does not match manifest bytes")
    return receipt


def _synthetic_target_migration_receipt() -> dict:
    return {
        "operation": "target_v2_migration",
        "dataset_documents": 10000,
        "n": 1,
        "mean_ms": 10.0,
        "p95_ms": 10.0,
        "max_ms": 10.0,
        "environment": {
            "python": "3.12.12",
            "platform": "macOS",
            "machine": "arm64",
        },
        "receipt_sha256": "a" * 64,
        "budget": {
            "cpu_s": 1.0,
            "max_rss_bytes": 1024,
            "disk_bytes": 2048,
            "wall_s": 1.0,
        },
        "recipe_anchor": {
            "recipe_id": "wave21-perf-v1",
            "manifest_sha256": FROZEN_MANIFEST_SHA256,
        },
    }


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


def test_target_migration_contract_requires_measured_receipt() -> None:
    receipt = validate_target_migration_receipt(
        load_target_migration_receipt(TARGET_MIGRATION_RECEIPT_PATH)
    )
    assert receipt["operation"] == "target_v2_migration"
    assert receipt["dataset_documents"] == 10000
    assert receipt["recipe_anchor"]["manifest_sha256"] == FROZEN_MANIFEST_SHA256
    # Retirement of forbidden_now is the receipt's existence; the frozen
    # manifest list itself stays untouched.
    manifest = load_manifest()
    assert "target_v2_migration" in manifest["forbidden"]


def test_target_migration_receipt_rejects_wrong_anchor_hash(
    tmp_path: Path,
) -> None:
    payload = _synthetic_target_migration_receipt()
    payload["recipe_anchor"]["manifest_sha256"] = "0" * 64
    mutated = tmp_path / "wrong-anchor.json"
    mutated.write_bytes(
        json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    )
    loaded = load_target_migration_receipt(mutated)
    with pytest.raises(ValueError, match="recipe_anchor"):
        validate_target_migration_receipt(loaded)


def test_target_migration_receipt_rejects_missing_budget_field(
    tmp_path: Path,
) -> None:
    payload = _synthetic_target_migration_receipt()
    del payload["budget"]["cpu_s"]
    mutated = tmp_path / "missing-budget.json"
    mutated.write_bytes(
        json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    )
    loaded = load_target_migration_receipt(mutated)
    with pytest.raises(ValueError, match="missing budget field"):
        validate_target_migration_receipt(loaded)
