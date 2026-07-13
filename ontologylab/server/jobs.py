"""In-memory extraction-job registry for the ontologylab local web layer.

POST /api/extract returns 202 immediately; the extraction loop itself runs
in a daemon thread (one per job) reusing the exact building blocks of
``main._extract_async`` (chunk -> engine.generate ->
parse_and_validate_extraction -> insert_proposed) with the same Caps
budgets and the same provenance events, so ``cost_summary()`` picks server
jobs up identically to CLI jobs. The dashboard polls GET /api/jobs — the
same status-polling pattern as ``tui.py`` — instead of SSE streaming.

sqlite objects are not shareable across threads, so the worker opens a
FRESH KGStore inside the thread. Kill-switch file handling is a CLI
concern and is intentionally skipped here (budgets still govern).
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from ontologylab import paths
from ontologylab.engines import EngineError, get_engine
from ontologylab.extractor import (
    PROMPT_VERSION,
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
)
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps

_PROGRESS_MAXLEN = 50


def _new_totals() -> dict[str, int]:
    return {"nodes_new": 0, "nodes_merged": 0, "edges_new": 0, "edges_merged": 0}


@dataclass
class Job:
    """One background extraction job (status snapshot lives in memory)."""

    job_id: str
    kind: str
    engine: str
    model: Optional[str]
    started_ts: float
    status: str = "running"  # running | complete | failed
    finished_ts: Optional[float] = None
    totals: dict[str, int] = field(default_factory=_new_totals)
    progress: deque = field(default_factory=lambda: deque(maxlen=_PROGRESS_MAXLEN))
    error: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def log(self, line: str) -> None:
        with self._lock:
            self.progress.append(line)

    def as_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "job_id": self.job_id,
                "kind": self.kind,
                "status": self.status,
                "engine": self.engine,
                "model": self.model,
                "started_ts": self.started_ts,
                "finished_ts": self.finished_ts,
                "totals": dict(self.totals),
                "progress": list(self.progress),
                "error": self.error,
            }


class JobRegistry:
    """Per-app registry of extraction jobs, newest first.

    Created by ``app.create_app()`` and bound into routes via
    ``routes.attach_jobs_registry`` (same pattern as ``attach_data_dir``).
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []  # insertion order (oldest first)
        self._lock = threading.Lock()

    def create(
        self,
        *,
        engine: str,
        model: Optional[str],
        doc_ids: list[str],
        max_engine_calls: int,
        time_budget: float,
        seed: int,
    ) -> Job:
        """Register a job, spawn its worker thread, and return it."""
        # The provenance job dir doubles as the job id: server jobs land in
        # data/jobs/extract-<ts>/ exactly like CLI jobs.
        job_dir = paths.new_job_dir(self.data_dir, "extract")
        job = Job(
            job_id=job_dir.name,
            kind="extract",
            engine=engine,
            model=model,
            started_ts=time.time(),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
        thread = threading.Thread(
            target=self._run,
            args=(job, job_dir),
            kwargs={
                "doc_ids": list(doc_ids),
                "max_engine_calls": max_engine_calls,
                "time_budget": time_budget,
                "seed": seed,
            },
            name=f"ontologylab-{job.job_id}",
            daemon=True,
        )
        thread.start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """All jobs, newest first."""
        with self._lock:
            return [self._jobs[job_id] for job_id in reversed(self._order)]

    # ------------------------------------------------------------------
    # Worker (daemon thread)
    # ------------------------------------------------------------------

    def _run(self, job: Job, job_dir: Path, **params: Any) -> None:
        try:
            asyncio.run(self._extract_async(job, job_dir, **params))
        except Exception as exc:  # noqa: BLE001 — job must record any failure
            with job._lock:
                job.status = "failed"
                job.error = str(exc)
                job.finished_ts = time.time()
            job.log(f"[ontologylab] extraction failed: {exc}")
        else:
            with job._lock:
                job.status = "complete"
                job.finished_ts = time.time()

    async def _extract_async(
        self,
        job: Job,
        job_dir: Path,
        *,
        doc_ids: list[str],
        max_engine_calls: int,
        time_budget: float,
        seed: int,
    ) -> None:
        """Mirror of ``main._extract_async`` minus CLI printing/kill switch."""
        provenance = Provenance(str(job_dir), seed=seed)
        caps = Caps(
            SimpleNamespace(
                iterations=0,  # no iteration cap; time/call budgets govern
                time_budget_s=time_budget,
                max_engine_calls=max_engine_calls,
            )
        )
        engine = get_engine(job.engine, job.model, seed=seed)

        # sqlite connections are thread-bound: open fresh INSIDE the worker.
        store = KGStore.open(paths.kg_db_path(self.data_dir))
        try:
            schema = store.get_schema()
            if not doc_ids:
                # default: every document with no extracted rows yet
                doc_ids = [
                    r["id"]
                    for r in store.conn.execute(
                        "SELECT id FROM documents WHERE id NOT IN "
                        "(SELECT DISTINCT source_doc_id FROM nodes)"
                    )
                ]
            if not doc_ids:
                job.log("[ontologylab] no unprocessed documents to extract")
                return

            provenance.log(
                "extract.start",
                {"engine": job.engine, "model": job.model, "doc_ids": doc_ids},
            )
            stopped_reason = ""
            for doc_id in doc_ids:
                raw_text = store.document_raw_text(doc_id)
                chunks = chunk_document(raw_text)
                provenance.log("extract.doc", {"doc_id": doc_id, "chunks": len(chunks)})
                for chunk in chunks:
                    stop, reason = caps.should_stop(
                        {
                            "elapsed": provenance.elapsed_s,
                            "engine_calls": provenance.engine_calls,
                        }
                    )
                    if stop:
                        stopped_reason = reason
                        break
                    prompt = build_extraction_prompt(schema, chunk.text)
                    try:
                        raw_response, usage = await engine.generate(
                            prompt, model=job.model
                        )
                    except EngineError as exc:
                        provenance.log(
                            "extract.engine_error",
                            {
                                "doc_id": doc_id,
                                "chunk": chunk.index,
                                "error": str(exc),
                            },
                        )
                        job.log(
                            f"[ontologylab] engine error on "
                            f"{doc_id}#{chunk.index}: {exc}"
                        )
                        continue
                    provenance.track_engine_call(
                        "extract", float(usage.get("elapsed") or 0.0), usage
                    )
                    try:
                        result = parse_and_validate_extraction(
                            raw_response, schema, chunk
                        )
                    except EngineError as exc:
                        # malformed/off-schema response: rejected + logged,
                        # never inserted, never a crash
                        provenance.log(
                            "extract.parse_rejected",
                            {
                                "doc_id": doc_id,
                                "chunk": chunk.index,
                                "error": str(exc),
                            },
                        )
                        continue
                    for warning in result.warnings:
                        provenance.log(
                            "extract.warning",
                            {
                                "doc_id": doc_id,
                                "chunk": chunk.index,
                                "warning": warning,
                            },
                        )
                    stats = store.insert_proposed(
                        result.entities,
                        result.relations,
                        source_doc_id=doc_id,
                        extractor_engine=job.engine,
                        extractor_model=job.model,
                        prompt_version=PROMPT_VERSION,
                    )
                    with job._lock:
                        for key in job.totals:
                            job.totals[key] += stats[key]
                    job.log(
                        f"[ontologylab] {doc_id}#{chunk.index}: "
                        f"+{stats['nodes_new']} nodes "
                        f"(+{stats['nodes_merged']} merged), "
                        f"+{stats['edges_new']} edges"
                    )
                if stopped_reason:
                    break

            with job._lock:
                totals = dict(job.totals)
            provenance.log("extract.end", {"totals": totals, "stopped": stopped_reason})
            if stopped_reason:
                job.log(f"[ontologylab] extraction stopped early: {stopped_reason}")
            job.log(
                f"[ontologylab] extraction done: {totals['nodes_new']} new nodes, "
                f"{totals['edges_new']} new edges (proposed; review to verify)"
            )
        finally:
            store.close()


__all__ = ["Job", "JobRegistry"]
