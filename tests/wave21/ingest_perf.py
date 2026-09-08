"""Bounded production-path measurement for Wave 2.1 ingestion."""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from pathlib import Path

from ontologylab.ingestion import (
    MAX_INGEST_BATCH,
    ingest_raw_documents_and_finalize,
)
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from ontologylab.provenance_outbox import load_outbox_events
from tests.wave21.perf_fixture import deterministic_documents


@dataclass(frozen=True, slots=True)
class IngestOutput:
    entries: int
    created: int
    conflicts: int
    failures: int


@dataclass(frozen=True, slots=True)
class IngestSample:
    elapsed_ms: float
    passes: tuple[IngestOutput, IngestOutput]
    document_rows: int
    observation_rows: int
    outbox_rows: int


@dataclass(frozen=True, slots=True)
class IngestPerformanceReceipt:
    operation: str
    dataset_documents: int
    samples_ms: tuple[float, ...]
    p95_ms: float
    environment: dict[str, str]
    outputs: tuple[IngestOutput, IngestOutput]


@dataclass(slots=True)
class PerformanceScratchRootError(RuntimeError):
    """Benchmark scratch is outside the protocol-bound local APFS root."""

    root: Path

    def __str__(self) -> str:
        return f"performance_scratch_root:{self.root}"


def measure_current_ingest(
    root: Path,
    *,
    document_count: int,
    n: int,
) -> IngestPerformanceReceipt:
    """Measure create+duplicate through the real bounded ingestion surface."""
    resolved_root = root.resolve()
    if not resolved_root.is_relative_to(Path("/private/tmp")):
        raise PerformanceScratchRootError(root=resolved_root)
    documents = deterministic_documents(document_count)
    samples: list[IngestSample] = []
    for sample_index in range(n):
        sample_root = root / f"sample-{sample_index}"
        store = KGStore.open(sample_root / "kg.sqlite")
        provenance = Provenance(
            str(sample_root / "jobs" / "perf"), seed=20260820
        )
        passes: list[IngestOutput] = []
        started = time.perf_counter()
        try:
            for _pass_index in range(2):
                entries = created = conflicts = failures = 0
                for offset in range(0, len(documents), MAX_INGEST_BATCH):
                    result = ingest_raw_documents_and_finalize(
                        store,
                        documents[offset : offset + MAX_INGEST_BATCH],
                        provenance,
                    )
                    entries += result.document_count
                    created += result.created_count
                    conflicts += len(result.conflicts)
                    failures += len(result.failures)
                passes.append(IngestOutput(entries, created, conflicts, failures))
            elapsed_ms = (time.perf_counter() - started) * 1000
            samples.append(
                IngestSample(
                    elapsed_ms=elapsed_ms,
                    passes=(passes[0], passes[1]),
                    document_rows=int(
                        store.conn.execute(
                            "SELECT COUNT(*) FROM documents"
                        ).fetchone()[0]
                    ),
                    observation_rows=int(
                        store.conn.execute(
                            "SELECT COUNT(*) FROM document_observations"
                        ).fetchone()[0]
                    ),
                    outbox_rows=len(load_outbox_events(store.conn)),
                )
            )
        finally:
            store.close()
    elapsed = tuple(sample.elapsed_ms for sample in samples)
    ordered = sorted(elapsed)
    p95_index = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
    first = samples[0]
    if any(
        sample.passes != first.passes
        or sample.document_rows != first.document_rows
        or sample.observation_rows != first.observation_rows
        or sample.outbox_rows != first.outbox_rows
        for sample in samples[1:]
    ):
        raise AssertionError("ingestion samples produced different outputs")
    return IngestPerformanceReceipt(
        operation="current_ingest_create_and_duplicate",
        dataset_documents=document_count,
        samples_ms=elapsed,
        p95_ms=ordered[p95_index],
        environment={
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        outputs=first.passes,
    )
