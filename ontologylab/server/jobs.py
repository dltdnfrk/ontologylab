"""In-memory extraction-job registry for the ontologylab local web layer.

POST /api/extract returns 202 immediately; the extraction loop itself runs
in a daemon thread (one per job) reusing the exact building blocks of
``main._extract_async`` (chunk -> engine.generate ->
parse_and_validate_extraction -> insert_proposed) with the same Caps
budgets and the same provenance events, so ``cost_summary()`` picks server
jobs up identically to CLI jobs. The dashboard subscribes to
GET /api/jobs/stream (SSE, change-driven via a registry condition variable)
and falls back to polling GET /api/jobs — the same status-polling pattern
as ``tui.py`` — when the stream is unavailable.

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
from ontologylab.connectors.allowlist import loggable_collect_inputs
from ontologylab.connectors.base import collapse_duplicates
from ontologylab.connectors.paper_api import SOURCE_ORDER, fetch_sources
from ontologylab.engines import EngineError, get_engine
from ontologylab.extractor import run_extraction, unprocessed_doc_ids
from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.paths import NetworkBlocked
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps

_PROGRESS_MAXLEN = 50

# How many finished jobs stay listed. The dashboard shows recent work, and
# every retained job is re-serialized into the SSE payload on each progress
# line, so this bounds both memory and per-line bandwidth. Running jobs are
# never evicted regardless of this number.
MAX_RETAINED_JOBS = 20

# A job in one of these is done and may be evicted. `cancelled` belongs here:
# the worker has stopped, so retaining it forever would defeat the bound.
TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled"})


def summarize_failure(exc: BaseException) -> str:
    """Describe a failure without quoting it.

    Whatever this returns reaches the browser through `as_status()` and the
    SSE stream, so it names the kind of failure and nothing more — the same
    discipline `engines._ApiEngine` already applies to provider errors, where
    only the status code escapes. The exception text itself goes to
    provenance, which stays on disk.

    The distinction matters because an exception message is written by
    whoever raised it: a paper API's error can carry the request URL, and a
    URL is where a publisher key would sit.
    """
    if isinstance(exc, NetworkBlocked):
        # The operator turned egress off; saying so is not a leak and is the
        # one message that is actionable on its own.
        return "offline mode blocked network egress"
    if isinstance(exc, EngineError):
        return "extraction engine failed"
    if isinstance(exc, KGStoreError):
        return "knowledge store rejected a write"
    if isinstance(exc, TimeoutError):
        return "a request timed out"
    if isinstance(exc, OSError):
        return "a network or filesystem operation failed"
    return f"unexpected {type(exc).__name__}"


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
    # Which half of a research run is executing: "collect" | "extract" | "".
    # Deliberately NOT a fourth `status` value. The dashboard detects a
    # finished job by the `prev === "running"` edge in `applyJobs`, so adding
    # a "collecting" status would silently stop the completion banner and the
    # automatic review-queue refresh from ever firing again.
    phase: str = ""
    status: str = "running"  # running | complete | failed | cancelled
    finished_ts: Optional[float] = None
    totals: dict[str, int] = field(default_factory=_new_totals)
    progress: deque = field(default_factory=lambda: deque(maxlen=_PROGRESS_MAXLEN))
    error: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # Set by `cancel()`, read by the worker between units of work. An Event
    # rather than a bool because it is written from the request thread and
    # read from the worker thread.
    _cancelled: threading.Event = field(
        default_factory=threading.Event, repr=False
    )
    # The worker, kept so a caller can wait for it to notice a cancellation.
    # `create` used to build this and drop it, leaving nothing to join.
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    # Registry back-reference so every visible change can wake SSE waiters.
    # Optional: a bare Job (unit tests) works without a registry.
    _registry: Optional["JobRegistry"] = field(default=None, repr=False)

    def cancel(self) -> bool:
        """Ask the worker to stop; return False if it already finished.

        This is a request, not a kill. The worker checks between chunks and
        before each engine call, so it stops at the next boundary rather than
        mid-write — a half-inserted extraction is worse than a slow stop.

        A blocking fetch already in flight is not interrupted: the socket
        timeout is the floor on how long a cancellation can take.
        """
        with self._lock:
            if self.status != "running":
                return False
        self._cancelled.set()
        self.log("[ontologylab] cancellation requested")  # log() touches
        return True

    def cancel_reason(self) -> str:
        """The abort reason for `run_extraction`, or "" to keep going."""
        return "cancelled by request" if self._cancelled.is_set() else ""

    def log(self, line: str) -> None:
        with self._lock:
            self.progress.append(line)
        if self._registry is not None:
            self._registry.touch()

    def set_phase(self, phase: str) -> None:
        """Move to a new phase and announce it on the progress log.

        Logging rather than only assigning is what makes the change visible:
        `log()` is the only writer that calls `touch()`, so a phase set in
        silence would sit in the SSE payload until some other event happened
        to push it.
        """
        with self._lock:
            self.phase = phase
        self.log(f"[ontologylab] {phase} phase started")

    def as_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "job_id": self.job_id,
                "kind": self.kind,
                "status": self.status,
                "phase": self.phase,
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
        # Monotonic change counter + condition for SSE push (jobs/stream).
        # Workers touch() on every visible change; each connected stream
        # client parks one threadpool thread in wait_version() — the pool
        # is anyio's default (40, shared with sync routes) and a parked
        # wait is non-cancellable, so a disconnected client's thread can
        # linger up to JOBS_STREAM_WAIT_S. Fine for the local single-user
        # dashboard this server is scoped to; revisit before multi-user.
        self._version = 0
        self._cond = threading.Condition()

    def touch(self) -> None:
        """Record a visible change and wake any waiting stream clients."""
        with self._cond:
            self._version += 1
            self._cond.notify_all()

    def wait_version(self, last_seen: int, timeout: float) -> int:
        """Block until the version moves past ``last_seen`` (or timeout).

        Returns the current version either way; callers treat an unchanged
        value as "send keepalive".
        """
        with self._cond:
            self._cond.wait_for(lambda: self._version != last_seen, timeout)
            return self._version

    def _spawn(
        self,
        kind: str,
        coroutine_factory,
        *,
        engine: str,
        model: Optional[str],
        **params: Any,
    ) -> Job:
        """Register a job of any kind, start its worker, and return it.

        `create` and `create_research` differ only in which coroutine the
        worker awaits; everything around it — the job dir that doubles as the
        job id, registration under the lock, eviction, the initial `touch`,
        and keeping the thread handle — is identical and belongs in one
        place. `kind` is also the job-dir stage, so a research run lands in
        `data/jobs/research-<ts>/` and `cost_summary()` picks it up with no
        change: it globs every job dir and does not care about the name.
        """
        job_dir = paths.new_job_dir(self.data_dir, kind)
        job = Job(
            job_id=job_dir.name,
            kind=kind,
            engine=engine,
            model=model,
            started_ts=time.time(),
            _registry=self,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            self._evict_locked()
        self.touch()  # new job appears in streams immediately
        thread = threading.Thread(
            target=self._run,
            args=(job, job_dir, coroutine_factory),
            kwargs=params,
            name=f"ontologylab-{job.job_id}",
            daemon=True,
        )
        job._thread = thread
        thread.start()
        return job

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
        """Register an extraction job, spawn its worker thread, return it."""
        return self._spawn(
            "extract",
            self._extract_async,
            engine=engine,
            model=model,
            doc_ids=list(doc_ids),
            max_engine_calls=max_engine_calls,
            time_budget=time_budget,
            seed=seed,
        )

    def create_research(
        self,
        *,
        topic: str,
        sources: list[str],
        limit: Optional[int],
        engine: str,
        model: Optional[str],
        max_engine_calls: int,
        time_budget: float,
        seed: int,
    ) -> Job:
        """Register a collect-then-extract run over one topic.

        Collect and extract were two screens with no decision between them —
        extraction always ran over every document — so joining them costs the
        operator nothing and saves them a step. Joining them also lets phase
        two extract *exactly* what phase one collected, which is where the
        token saving comes from.
        """
        return self._spawn(
            "research",
            self._research_async,
            engine=engine,
            model=model,
            topic=topic,
            sources=list(sources),
            limit=limit,
            max_engine_calls=max_engine_calls,
            time_budget=time_budget,
            seed=seed,
        )

    def running_research(self) -> Job | None:
        """A research run already in flight, if any.

        Two runs on one topic pay twice for the same extraction. This bounds
        the server's own duplicates only: a concurrent `python -m ontologylab
        collect` is not registered here and is not blocked — mitigation, not
        closure, which is why `insert_document` also recovers from the
        `IntegrityError` that a genuine race produces.
        """
        with self._lock:
            for job_id in reversed(self._order):
                job = self._jobs.get(job_id)
                if job is not None and job.kind == "research":
                    if job.status == "running":
                        return job
        return None

    def cancel(self, job_id: str) -> bool:
        """Ask one running job to stop. False if unknown or already finished."""
        job = self.get(job_id)
        return job is not None and job.cancel()

    def _evict_locked(self) -> None:
        """Drop the oldest finished jobs past the retention bound.

        Nothing removed from `_jobs`/`_order` before this, so a long-lived
        server grew them for its whole lifetime — and `routes` re-serializes
        the entire list on every `job.log()` line, so the SSE payload grew
        with it. A research run logs both a collect and an extract phase,
        which raises the line rate and the job count together.

        Only finished jobs are candidates. Evicting a running one would drop
        the record a stream client is currently watching, and its worker
        thread would keep writing to an object no reader can reach. Callers
        must hold `self._lock`.
        """
        if len(self._order) <= MAX_RETAINED_JOBS:
            return
        surplus = len(self._order) - MAX_RETAINED_JOBS
        keep: list[str] = []
        for job_id in self._order:  # oldest first
            job = self._jobs.get(job_id)
            finished = job is not None and job.status in TERMINAL_STATUSES
            if surplus > 0 and finished:
                surplus -= 1
                self._jobs.pop(job_id, None)
                continue
            keep.append(job_id)
        self._order = keep

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

    def _run(self, job: Job, job_dir: Path, coroutine_factory, **params: Any) -> None:
        try:
            asyncio.run(coroutine_factory(job, job_dir, **params))
        except Exception as exc:  # noqa: BLE001 — job must record any failure
            # `job.error` and the progress log both reach the browser through
            # `as_status()` and the SSE stream, so neither may carry the
            # exception text. Today this boundary touches no network I/O, but
            # a research run moves collection inside it: five paper APIs whose
            # exceptions carry request URLs and response fragments, and a URL
            # is where a publisher key would sit. The full exception goes to
            # provenance, which stays on disk.
            summary = summarize_failure(exc)
            Provenance(str(job_dir), seed=0).log(
                "job.failed",
                {"job_id": job.job_id, "type": type(exc).__name__, "error": str(exc)},
            )
            with job._lock:
                job.status = "failed"
                job.error = summary
                job.finished_ts = time.time()
            job.log(f"[ontologylab] extraction failed: {summary}")  # log() touches
        else:
            with job._lock:
                # A cancelled run did not complete its work, and reporting it
                # as `complete` would tell the reviewer the document set was
                # fully extracted. It is not a failure either — nothing broke
                # — so it gets its own terminal state.
                job.status = (
                    "cancelled" if job._cancelled.is_set() else "complete"
                )
                job.finished_ts = time.time()
            self.touch()  # running → terminal transition

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
        engine = get_engine(job.engine, job.model, seed=seed, data_dir=self.data_dir)

        # sqlite connections are thread-bound: open fresh INSIDE the worker.
        store = KGStore.open(paths.kg_db_path(self.data_dir))
        try:
            if not doc_ids:
                doc_ids = unprocessed_doc_ids(store)
            if not doc_ids:
                job.log("[ontologylab] no unprocessed documents to extract")
                return

            provenance.log(
                "extract.start",
                {"engine": job.engine, "model": job.model, "doc_ids": doc_ids},
            )

            def _accumulate(stats: dict[str, int]) -> None:
                # `job.totals` is read by the SSE thread, so every write to it
                # takes the job's lock. Accumulation stays here rather than in
                # `run_extraction` precisely so the shared loop never has to
                # know one caller's locking discipline.
                with job._lock:
                    for key in job.totals:
                        # `.get`, not `stats[key]`: a missing key would raise
                        # KeyError inside the worker, where `_run`'s broad
                        # except turns any exception into a failed job. The
                        # collect phase's documents would already be in the
                        # store, so a bookkeeping mismatch would discard a
                        # run's real work — loud data loss, not a silent bug.
                        job.totals[key] += stats.get(key, 0)

            stopped_reason = await run_extraction(
                store,
                engine,
                provenance,
                caps,
                doc_ids,
                extractor_engine=job.engine,
                extractor_model=job.model,
                on_progress=job.log,
                on_stats=_accumulate,
                # The seam `run_extraction` exposes for exactly this: the CLI
                # passes its kill switch here, the server passes the job's
                # cancellation. Checked between chunks and before each engine
                # call, so a cancelled run stops without a partial write.
                should_abort=job.cancel_reason,
            )

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

    async def _research_async(
        self,
        job: Job,
        job_dir: Path,
        *,
        topic: str,
        sources: list[str],
        limit: Optional[int],
        max_engine_calls: int,
        time_budget: float,
        seed: int,
    ) -> None:
        """Collect a topic across sources, then extract exactly what arrived.

        The two phases share one provenance run, so `cost_summary()` reports
        a research run's cost as one number — which is what it costs.
        """
        provenance = Provenance(str(job_dir), seed=seed)
        provenance.log(
            "research.start",
            {
                "topic": loggable_collect_inputs([topic]),
                "sources": sources,
                "limit": limit,
            },
        )

        # sqlite connections are thread-bound: the worker owns this one for
        # both phases. `routes._open_store()` belongs to the request thread.
        store = KGStore.open(paths.kg_db_path(self.data_dir))
        try:
            # ---------------- phase 1: collect ----------------
            job.set_phase("collect")
            if job._cancelled.is_set():
                job.log("[ontologylab] cancelled before collecting")
                return

            # `data_dir` reaches the connector so a keyed publisher source can
            # resolve its credential; the keyless five ignore it.
            batches, failures = await fetch_sources(
                sources, topic, limit, self.data_dir
            )
            for failure in failures:
                # The source name and the kind of failure are safe to show;
                # the exception text is not (H2) — it goes to provenance.
                provenance.log(
                    "research.source_failed",
                    {"source": failure.source, "kind": failure.kind,
                     "error": failure.error},
                )
                job.log(
                    f"[ontologylab] {failure.source} did not answer "
                    f"({failure.kind})"
                )
            if not batches and failures:
                job.log("[ontologylab] no source answered; nothing to extract")
                provenance.log("research.end", {"documents": 0, "created": 0})
                return

            raw_docs = collapse_duplicates(batches, SOURCE_ORDER)
            job.log(
                f"[ontologylab] collected {len(raw_docs)} document(s) from "
                f"{len(batches)} source(s)"
            )

            if job._cancelled.is_set():
                # Stop before writing: nothing is extracted yet, so the run
                # costs nothing and leaves the store as it was.
                job.log("[ontologylab] cancelled before storing documents")
                return

            doc_ids: list[str] = []
            created_count = 0
            for raw in raw_docs:
                doc, created = store.insert_document(
                    source_kind=raw.source_kind,
                    source_uri=raw.source_uri,
                    title=raw.title,
                    raw_text=raw.raw_text,
                    content_hash=raw.content_hash,
                )
                doc_ids.append(doc.id)
                created_count += 1 if created else 0
                provenance.log(
                    "collect.doc",
                    {"doc_id": doc.id, "source_uri": doc.source_uri,
                     "created": created, "chars": len(raw.raw_text)},
                )
            provenance.log(
                "collect.end",
                {"documents": len(raw_docs), "created": created_count},
            )
            job.log(
                f"[ontologylab] stored {created_count} new document(s), "
                f"{len(raw_docs) - created_count} already known"
            )

            if not doc_ids:
                job.log("[ontologylab] nothing collected; no extraction to run")
                return

            # ---------------- phase 2: extract ----------------
            job.set_phase("extract")
            if job._cancelled.is_set():
                job.log("[ontologylab] cancelled before extracting")
                return

            # `doc_ids` is passed explicitly and is never allowed to fall back
            # to `unprocessed_doc_ids(store)`. That query is global: it would
            # pull in documents from older runs and from any run executing
            # right now, spending this topic's budget on them.
            #
            # The time budget is measured from the extraction's own start.
            # `Caps` reads the clock from `provenance.elapsed_s`, which runs
            # from the job's creation — five paper APIs at a 30s timeout
            # could otherwise consume the extraction budget before the first
            # chunk, and the run would report itself budget-exhausted having
            # extracted nothing.
            caps = Caps(
                SimpleNamespace(
                    iterations=0,
                    time_budget_s=time_budget + provenance.elapsed_s,
                    max_engine_calls=max_engine_calls,
                )
            )
            engine = get_engine(
                job.engine, job.model, seed=seed, data_dir=self.data_dir
            )
            provenance.log(
                "extract.start",
                {"engine": job.engine, "model": job.model, "doc_ids": doc_ids},
            )

            def _accumulate(stats: dict[str, int]) -> None:
                with job._lock:
                    for key in job.totals:
                        job.totals[key] += stats.get(key, 0)

            stopped_reason = await run_extraction(
                store,
                engine,
                provenance,
                caps,
                doc_ids,
                extractor_engine=job.engine,
                extractor_model=job.model,
                on_progress=job.log,
                on_stats=_accumulate,
                should_abort=job.cancel_reason,
            )

            with job._lock:
                totals = dict(job.totals)
            provenance.log(
                "research.end",
                {"documents": len(raw_docs), "created": created_count,
                 "totals": totals, "stopped": stopped_reason},
            )
            if stopped_reason:
                job.log(f"[ontologylab] extraction stopped early: {stopped_reason}")
            job.log(
                f"[ontologylab] research done: {totals['nodes_new']} new nodes, "
                f"{totals['edges_new']} new edges (proposed; review to verify)"
            )
        finally:
            store.close()


__all__ = ["Job", "JobRegistry"]
