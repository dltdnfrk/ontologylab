"""Deterministic concurrent-ingest fixture for Wave 2.1 Step 6 F2.

Writers share a disposable WAL store, start on a barrier, and optionally
resynchronize on a named service failpoint. Completions are bounded joins;
this module does not sleep, poll, bind ports, or touch live data.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ontologylab.ingestion_service import IngestItem, IngestReceipt, ingest_item
from ontologylab.kgstore import KGStore
from tests.wave21.harness import ConcurrencyBarrier, Failpoint


FAMILY_DOI = "10.1000/f2.family"
SECOND_DOI = "10.1000/f2.second"
SENTINEL_DOI = "10.1000/f2.sentinel"
JOIN_TIMEOUT_S = 5.0

FAMILY_TRUTH: dict[str, int] = {
    "works": 1,
    "documents": 0,
    "work_identifiers": 1,
    "document_observations": 2,
    "identifier_assertions": 2,
    "dangling_assertions": 0,
    "orphan_identifiers": 0,
    "observations_without_assertion": 0,
}

SECOND_DOI_TRUTH: dict[str, int] = {
    "works": 1,
    "documents": 0,
    "work_identifiers": 1,
    "document_observations": 1,
    "identifier_assertions": 1,
    "dangling_assertions": 0,
    "orphan_identifiers": 0,
    "observations_without_assertion": 0,
}


def family_item(
    operation: str,
    *,
    source: str = "crossref",
    work_id: str | None = None,
) -> IngestItem:
    return IngestItem(
        idempotency_key=operation,
        scheme="doi",
        normalized_value=FAMILY_DOI,
        source=source,
        evidence_grade="A",
        work_id=work_id,
        stage="version_of_record",
        content_kind="metadata_only",
    )


def second_doi_item(
    operation: str,
    doi: str,
    *,
    work_id: str,
) -> IngestItem:
    return IngestItem(
        idempotency_key=operation,
        scheme="doi",
        normalized_value=doi,
        source="crossref",
        evidence_grade="A",
        work_id=work_id,
        stage="version_of_record",
        content_kind="metadata_only",
    )


def table_counts(conn: Any) -> dict[str, int]:
    def count(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    return {
        "works": count("SELECT COUNT(*) FROM works"),
        "documents": count("SELECT COUNT(*) FROM documents"),
        "work_identifiers": count("SELECT COUNT(*) FROM work_identifiers"),
        "document_observations": count(
            "SELECT COUNT(*) FROM document_observations"
        ),
        "identifier_assertions": count(
            "SELECT COUNT(*) FROM identifier_assertions"
        ),
        "dangling_assertions": count(
            "SELECT COUNT(*) FROM identifier_assertions ia "
            "WHERE NOT EXISTS (SELECT 1 FROM document_observations o "
            "WHERE o.id = ia.observation_id)"
        ),
        "orphan_identifiers": count(
            "SELECT COUNT(*) FROM work_identifiers wi "
            "WHERE NOT EXISTS (SELECT 1 FROM identifier_assertions ia "
            "WHERE ia.identifier_id = wi.id)"
        ),
        "observations_without_assertion": count(
            "SELECT COUNT(*) FROM document_observations o "
            "WHERE NOT EXISTS (SELECT 1 FROM identifier_assertions ia "
            "WHERE ia.observation_id = o.id)"
        ),
    }


def stable_projection(conn: Any) -> dict[str, tuple[tuple[object, ...], ...]]:
    def rows(sql: str) -> tuple[tuple[object, ...], ...]:
        return tuple(tuple(row) for row in conn.execute(sql))

    return {
        "identifiers": rows(
            "SELECT scheme, normalized_value, status FROM work_identifiers "
            "ORDER BY scheme, normalized_value"
        ),
        "observations": rows(
            "SELECT idempotency_key, source, evidence_grade, stage, "
            "content_kind FROM document_observations ORDER BY idempotency_key"
        ),
        "bindings": rows(
            "SELECT o.idempotency_key, wi.scheme, wi.normalized_value "
            "FROM identifier_assertions ia "
            "JOIN document_observations o ON o.id = ia.observation_id "
            "JOIN work_identifiers wi ON wi.id = ia.identifier_id "
            "ORDER BY o.idempotency_key"
        ),
    }


@dataclass(frozen=True, slots=True)
class ConcurrentIngestReport:
    receipts: tuple[IngestReceipt, ...]
    counts: dict[str, int]
    projection: dict[str, tuple[tuple[object, ...], ...]]
    observation_ids: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConcurrentIngestFixture:
    db_path: Path
    family_doi: str = FAMILY_DOI
    second_doi: str = SECOND_DOI
    sentinel_doi: str = SENTINEL_DOI

    @classmethod
    def open(cls, root: Path) -> ConcurrentIngestFixture:
        db_path = Path(root) / "kg.sqlite"
        seed = KGStore.open(db_path)
        seed.close()
        return cls(db_path=db_path)

    def seed_sentinel(self) -> str:
        store = KGStore.open(self.db_path)
        try:
            receipt = ingest_item(
                store.conn,
                IngestItem(
                    idempotency_key="op-sentinel",
                    scheme="doi",
                    normalized_value=self.sentinel_doi,
                    source="crossref",
                    evidence_grade="A",
                    stage="version_of_record",
                    content_kind="metadata_only",
                ),
            )
            if receipt.status != "created" or receipt.work_id is None:
                raise RuntimeError(f"sentinel ingest failed: {receipt}")
            store.conn.commit()
            return receipt.work_id
        finally:
            store.close()

    def run_writers(
        self,
        items: tuple[IngestItem, ...],
        *,
        sync_stage: str | None = None,
        failpoints: tuple[Failpoint | None, ...] | None = None,
        timeout: float = JOIN_TIMEOUT_S,
    ) -> ConcurrentIngestReport:
        n = len(items)
        if n < 2:
            raise ValueError("concurrent ingest requires at least two writers")
        if failpoints is not None and len(failpoints) != n:
            raise ValueError("failpoints must align with writers")

        start_barrier = ConcurrencyBarrier(n)
        stage_barrier = ConcurrencyBarrier(n) if sync_stage is not None else None
        receipts: list[IngestReceipt | None] = [None] * n
        errors: list[str | None] = [None] * n

        def worker(index: int, item: IngestItem) -> None:
            seen_stages: set[str] = set()
            store = KGStore.open(self.db_path)
            try:
                start_barrier.wait(timeout=timeout)

                def hooked(stage: str) -> None:
                    if (
                        stage_barrier is not None
                        and stage == sync_stage
                        and stage not in seen_stages
                    ):
                        seen_stages.add(stage)
                        stage_barrier.wait(timeout=timeout)
                    armed = None if failpoints is None else failpoints[index]
                    if armed is not None:
                        armed.hit(stage)

                receipts[index] = ingest_item(
                    store.conn, item, failpoint=hooked
                )
                store.conn.commit()
            except BaseException as exc:
                errors[index] = f"{type(exc).__name__}: {exc}"
                if store.conn.in_transaction:
                    store.conn.rollback()
            finally:
                store.close()

        threads = [
            threading.Thread(
                target=worker,
                args=(index, item),
                name=f"f2-writer-{index}",
            )
            for index, item in enumerate(items)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=timeout)
            if thread.is_alive():
                raise RuntimeError(f"writer join timed out: {thread.name}")

        finished = tuple(
            receipt for receipt in receipts if receipt is not None
        )
        check = KGStore.open(self.db_path)
        try:
            counts = table_counts(check.conn)
            projection = stable_projection(check.conn)
        finally:
            check.close()
        return ConcurrentIngestReport(
            receipts=finished,
            counts=counts,
            projection=projection,
            observation_ids=tuple(
                receipt.observation_id
                for receipt in finished
                if receipt.observation_id is not None
            ),
            errors=tuple(message for message in errors if message is not None),
        )
