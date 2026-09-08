from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import resource
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from ontologylab.engines import MockEngine
from ontologylab.extraction_state import effective_extractor_model
from ontologylab.extractor import extraction_decode_params, run_extraction
from ontologylab.ingestion import MAX_INGEST_BATCH, ingest_raw_documents_and_finalize
from ontologylab.kgstore import KGStore
from ontologylab.packbuilder import build_pack
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps
from .perf_fixture import (
    create_populated_legacy_fixture,
    deterministic_documents,
)


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "wave21" / "perf-v1.json"
REQUIRED_OPERATIONS = {
    "fixture_create_open_noop",
    "legacy_noop_migration_open",
    "current_ingest_create_and_duplicate",
    "current_pack_build",
}
FORBIDDEN_OPERATION = "target_v2_migration"


@dataclass(frozen=True)
class PerfReceipt:
    operation: str
    dataset_documents: int
    n: int
    mean_ms: float
    p95_ms: float
    max_ms: float
    environment: dict[str, str]
    receipt_sha256: str


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("recipe_id") != "wave21-perf-v1":
        raise ValueError("unexpected performance recipe")
    if data.get("seed") != 20260820:
        raise ValueError("unexpected performance seed")
    if data.get("dataset", {}).get("documents") != 10000:
        raise ValueError("wave21-perf-v1 must name 10,000 documents")
    operations = {item.get("id") for item in data.get("operations", [])}
    if operations != REQUIRED_OPERATIONS:
        raise ValueError(f"unexpected operations: {sorted(operations)}")
    if FORBIDDEN_OPERATION in operations or FORBIDDEN_OPERATION not in data.get("forbidden", []):
        raise ValueError("target migration must be forbidden and absent")
    return data


def manifest_sha256(path: Path = MANIFEST_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timed(
    operation: str,
    n: int,
    dataset_documents: int,
    fn: Callable[[int], None],
) -> PerfReceipt:
    samples: list[float] = []
    for sample_index in range(n):
        started = time.perf_counter()
        fn(sample_index)
        samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples)
    p95_index = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
    payload = {
        "operation": operation,
        "dataset_documents": dataset_documents,
        "n": n,
        "mean_ms": statistics.fmean(samples),
        "p95_ms": ordered[p95_index],
        "max_ms": max(samples),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return PerfReceipt(**payload, receipt_sha256=digest)


def write_receipts(path: Path, receipts: list[PerfReceipt]) -> str:
    payload = [asdict(receipt) for receipt in receipts]
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def measure_existing_operations(
    root: Path,
    *,
    document_count: int = 10000,
) -> list[PerfReceipt]:
    root.mkdir(parents=True, exist_ok=True)
    docs = deterministic_documents(document_count)
    manifest = load_manifest()
    samples = {
        item["id"]: int(item["n"])
        for item in manifest["operations"]
    }

    def create_open_noop(sample_index: int) -> None:
        db_path = root / f"fixture-create-{sample_index}" / "kg.sqlite"
        create_populated_legacy_fixture(db_path, docs)
        store = KGStore.open(db_path)
        store.close()
        store = KGStore.open(db_path)
        store.close()

    legacy_db_path = root / "legacy-noop" / "kg.sqlite"
    create_populated_legacy_fixture(legacy_db_path, docs)
    migrated_store = KGStore.open(legacy_db_path)
    migrated_store.close()

    def legacy_noop_open(_sample_index: int) -> None:
        store = KGStore.open(legacy_db_path)
        store.close()

    def ingest_create_duplicate(sample_index: int) -> None:
        data_dir = root / f"ingest-data-{sample_index}"
        db_path = data_dir / "kg.sqlite"
        store = KGStore.open(db_path)
        provenance = Provenance(
            str(data_dir / "jobs" / "perf"),
            seed=20260820,
        )
        for offset in range(0, len(docs), MAX_INGEST_BATCH):
            ingest_raw_documents_and_finalize(
                store,
                docs[offset : offset + MAX_INGEST_BATCH],
                provenance,
            )
        for offset in range(0, len(docs), MAX_INGEST_BATCH):
            ingest_raw_documents_and_finalize(
                store,
                docs[offset : offset + MAX_INGEST_BATCH],
                provenance,
            )
        store.close()

    pack_data_dir = root / "pack-source"
    pack_db_path = pack_data_dir / "kg.sqlite"
    create_populated_legacy_fixture(pack_db_path, docs)
    pack_store = KGStore.open(pack_db_path)
    first_doc_id = "perf-doc-00000"
    engine = MockEngine(seed=20260820)
    provenance = Provenance(
        str(pack_data_dir / "jobs" / "extract"),
        seed=20260820,
    )
    caps = Caps(
        type(
            "PerfCaps",
            (),
            {"iterations": 0, "time_budget_s": 60.0, "max_engine_calls": 100},
        )
    )
    asyncio.run(
        run_extraction(
            pack_store,
            engine,
            provenance,
            caps,
            [first_doc_id],
            extractor_engine="mock",
            extractor_model=effective_extractor_model(engine, None),
            on_progress=lambda _line: None,
            on_stats=lambda _stats: None,
            decode_params=extraction_decode_params(engine),
        )
    )
    pack_store.close()

    def pack_build(sample_index: int) -> None:
        build_pack(
            pack_db_path,
            root / "packs",
            f"wave21-perf-{sample_index}",
            allow_incomplete_extraction=True,
            incomplete_extraction_intent=(
                "Step 1 existing-operation performance baseline"
            ),
        )

    return [
        timed(
            "fixture_create_open_noop",
            samples["fixture_create_open_noop"],
            document_count,
            create_open_noop,
        ),
        timed(
            "legacy_noop_migration_open",
            samples["legacy_noop_migration_open"],
            document_count,
            legacy_noop_open,
        ),
        timed(
            "current_ingest_create_and_duplicate",
            samples["current_ingest_create_and_duplicate"],
            document_count,
            ingest_create_duplicate,
        ),
        timed(
            "current_pack_build",
            samples["current_pack_build"],
            document_count,
            pack_build,
        ),
    ]


TARGET_MIGRATION_RECEIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / ".omo"
    / "evidence"
    / "ulw"
    / "wave21-step5-migration-core-20260821"
    / "G004-goal-4-produce-the-first-measured-ta"
    / "a1"
    / "perf-receipt.json"
)


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _max_rss_bytes(usage: resource.struct_rusage) -> int:
    rss = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        return rss
    return rss * 1024


def measure_target_v2_migration(
    root: Path,
    *,
    document_count: int = 10000,
    n: int = 1,
) -> dict:
    """Drive Step 5 snapshot + DOI backfill and return a measured receipt.

    Gap: ontologylab.migration / migration_backfill / migration_rehearsal
    expose snapshot_db, prepare_backup_copy, execute_doi_backfill, and
    run_rehearsal, but not a measured target-migration driver or a
    budget/receipt type. This wrapper is the missing measurement surface.
    """
    from ontologylab.migration_backfill import (
        execute_doi_backfill,
        prepare_backup_copy,
    )

    if n <= 0:
        raise ValueError("n must be positive")
    root.mkdir(parents=True, exist_ok=True)
    docs = deterministic_documents(document_count)
    source_dir = root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_db = source_dir / "kg.sqlite"
    create_populated_legacy_fixture(source_db, docs)

    samples: list[float] = []
    last_budget: dict[str, float] | None = None
    for sample_index in range(n):
        copy_dir = root / f"copy-{sample_index}"
        copy_dir.mkdir(parents=True, exist_ok=True)
        usage_before = resource.getrusage(resource.RUSAGE_SELF)
        started = time.perf_counter()
        copied = prepare_backup_copy(source_db, copy_dir)
        store = KGStore.open(copied)
        try:
            execute_doi_backfill(store.conn)
            store.conn.commit()
        finally:
            store.close()
        wall_s = time.perf_counter() - started
        usage_after = resource.getrusage(resource.RUSAGE_SELF)
        samples.append(wall_s * 1000)
        last_budget = {
            "cpu_s": (
                (usage_after.ru_utime - usage_before.ru_utime)
                + (usage_after.ru_stime - usage_before.ru_stime)
            ),
            "max_rss_bytes": _max_rss_bytes(usage_after),
            "disk_bytes": _directory_bytes(copy_dir),
            "wall_s": wall_s,
        }

    assert last_budget is not None
    ordered = sorted(samples)
    p95_index = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
    payload = {
        "operation": FORBIDDEN_OPERATION,
        "dataset_documents": document_count,
        "n": n,
        "mean_ms": statistics.fmean(samples),
        "p95_ms": ordered[p95_index],
        "max_ms": max(samples),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "budget": last_budget,
        "recipe_anchor": {
            "recipe_id": "wave21-perf-v1",
            "manifest_sha256": manifest_sha256(),
        },
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    payload["receipt_sha256"] = digest
    return payload


def write_target_migration_receipt(path: Path, receipt: dict) -> str:
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
