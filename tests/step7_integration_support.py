"""Shared Step 7 chain driver: C-024 plant plus research extract."""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from pathlib import Path

from ontologylab.engines import MockEngine
from ontologylab.extractor import TOTALS_KEYS
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from ontologylab.research_extract import (
    ResearchExtractSession,
    extract_research_documents,
)
from tests.test_preferred_selection import caps, plant_c024


def research_session(job_dir: Path) -> ResearchExtractSession:
    totals = dict.fromkeys(TOTALS_KEYS, 0)

    def _stats(stats: dict[str, int]) -> None:
        for key in totals:
            totals[key] += stats.get(key, 0)

    job_dir.mkdir(parents=True, exist_ok=True)
    return ResearchExtractSession(
        engine=MockEngine(),
        provenance=Provenance(str(job_dir), seed=0),
        caps=caps(),
        extractor_engine="mock",
        extractor_model="",
        on_progress=lambda _line: None,
        on_stats=_stats,
    )


def plant_and_extract(
    live: Path, *, pmc_ready: bool = True,
) -> tuple[KGStore, str, str, str]:
    """Ingest C-024 publisher+PMC and run the research consumer."""
    live.mkdir(parents=True, exist_ok=True)
    store, work_id, publisher_id, pmc_id = plant_c024(
        live, pmc_ready=pmc_ready,
    )
    asyncio.run(
        extract_research_documents(
            store,
            (publisher_id, pmc_id),
            research_session(live / "job"),
        )
    )
    return store, work_id, publisher_id, pmc_id


def probe_node_id(store: KGStore) -> str:
    row = store.conn.execute(
        "SELECT id FROM nodes WHERE normalized_name = 'pmcfulltextprobe'"
    ).fetchone()
    assert row is not None
    return str(row["id"])


def decision_count(store: KGStore) -> int:
    return table_count(store, "grounded_review_decisions")


_COUNTABLE = frozenset({
    "citation_receipts",
    "extraction_run_receipts",
    "grounded_review_decisions",
})


def table_count(store: KGStore, name: str) -> int:
    if name not in _COUNTABLE:
        raise AssertionError(f"uncountable table {name!r}")
    exists = store.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    if exists is None:
        return 0
    row = store.conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
    return int(row[0])
