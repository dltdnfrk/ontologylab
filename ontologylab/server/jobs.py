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
from contextlib import suppress
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from ontologylab import paths
from ontologylab.connectors.allowlist import loggable_collect_inputs
from ontologylab.connectors.base import collapse_duplicates
from ontologylab.connectors.fulltext import enrich_with_fulltext
from ontologylab.connectors.paper_api import SOURCE_ORDER, fetch_sources
from ontologylab.engines import EngineError, get_engine
from ontologylab.extraction_state import (
    effective_extractor_model,
    recover_running_once,
)
from ontologylab.extractor import (
    extraction_decode_params,
    extraction_doc_ids,
    run_extraction,
)
from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.paths import NetworkBlocked
from ontologylab.provenance import Provenance
from ontologylab.searchquery import formulate_search_query
from ontologylab.safety import Caps
from ontologylab.trace import Step, source_step

_PROGRESS_MAXLEN = 50

# How many finished jobs stay listed. The dashboard shows recent work, and
# every retained job is re-serialized into the SSE payload on each progress
# line, so this bounds both memory and per-line bandwidth. Running jobs are
# never evicted regardless of this number.
MAX_RETAINED_JOBS = 20

# A job in one of these is done and may be evicted. `cancelled` belongs here:
# the worker has stopped, so retaining it forever would defeat the bound.
TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled"})


class JobAlreadyRunning(Exception):
    """Raised when an exclusive job is asked for while one is still running.

    Carries the running job's id so the caller can point the user at it.
    """

    def __init__(self, job_id: str) -> None:
        super().__init__(f"a job is already running: {job_id}")
        self.job_id = job_id


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
    # Per-source status of a research run's collect fan-out: source name ->
    # {"status": "running"|"ok"|"failed", "detail": ...}. Fed by the same
    # on_event callback that records steps, so the screen can summarise
    # "4 of 7 sources answered" instead of burying it in log lines.
    sources: dict[str, dict[str, str]] = field(default_factory=dict)
    progress: deque = field(default_factory=lambda: deque(maxlen=_PROGRESS_MAXLEN))
    # The same events as `progress`, still structured. Same bound: these two
    # are written together by `record()`, so letting one outlive the other
    # would make the screen and the log disagree about how far back a run
    # can be read.
    steps: deque = field(default_factory=lambda: deque(maxlen=_PROGRESS_MAXLEN))
    error: Optional[str] = None
    # The question that started a research run (topic), kept on the durable
    # run row so history can say *why* a run ran. Extract jobs leave it None.
    ask: Optional[str] = None
    # True when this Job was restored from the runs table at registry startup:
    # dead, no worker, empty progress — the history GAP-O2 exists to keep,
    # exempt from eviction so a restart never re-empties the jobs screen.
    persisted: bool = field(default=False, repr=False)
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

    def record(self, step: Step) -> None:
        """Announce one step, structured and as a line.

        The only writer of both lists. Appending to `steps` directly (or
        calling `log()` with a hand-spelled string) would make two writers
        for one event, which is the shape of bug this repo keeps finding —
        nothing fails when the two disagree, they just drift.
        """
        with self._lock:
            self.steps.append(step)
        self.log(step.line)

    def set_phase(self, phase: str) -> None:
        """Move to a new phase and announce it on the progress log.

        Logging rather than only assigning is what makes the change visible:
        `log()` is the only writer that calls `touch()`, so a phase set in
        silence would sit in the SSE payload until some other event happened
        to push it.
        """
        with self._lock:
            self.phase = phase
        self.record(Step("ontologylab", "phase", "running", phase))
        if self._registry is not None:
            self._registry.persist(self)

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
                "sources": [
                    {"name": name, **state}
                    for name, state in self.sources.items()
                ],
                "progress": list(self.progress),
                # The browser reads this to draw the trace. Without it the
                # structure stops at the server and the screen is back to
                # re-parsing English prose.
                "steps": [step.as_dict() for step in self.steps],
                "error": self.error,
            }


def _source_event_line(kind: str, source: str, detail: object) -> str:
    """One human-readable line per per-source event.

    The job log is what the dashboard streams, so these strings are the
    progress display — not debug output. `source_start` matters most: it is
    the only signal that anything is happening during a fan-out that can sit
    silent for thirty seconds.

    Derived from the step rather than spelled here. These same words used to
    exist only as string literals in this function, which was fine until the
    browser also needed the structure behind them; keeping both would be two
    writers for one event.
    """
    return source_step(kind, source, detail).line


class JobRegistry:
    """Per-app registry of extraction jobs, newest first.

    Created by ``app.create_app()`` and owned by that FastAPI app's state.
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

        # App creation is the process-restart boundary.  Claims left by a
        # dead daemon become explicit and resumable before requests arrive.
        store = KGStore.open(paths.kg_db_path(self.data_dir))
        try:
            recover_running_once(store.conn)
        finally:
            store.close()

        # ... and the jobs screen is refilled from the runs table. The
        # registry used to be pure memory, so every restart emptied it.
        self._load_persisted()

    def _load_persisted(self) -> None:
        """Restore job history from the runs table, oldest first.

        A row still marked `running` is a zombie — its worker died with the
        old process — so it is relabelled failed here and written back before
        it is ever served to the dashboard. Telling the operator a run is
        still going when nothing is working on it is a worse lie than an
        honest interruption.
        """
        store = KGStore.open(paths.kg_db_path(self.data_dir))
        try:
            rows = store.list_runs()
            for row in reversed(rows):  # oldest first, matching _order
                status, error = row["status"], row.get("error")
                if status == "running":
                    status = "failed"
                    error = "interrupted by server restart"
                    row["status"], row["error"] = status, error
                    store.run_upsert(row)
                job = Job(
                    job_id=row["id"],
                    kind=row["kind"],
                    engine=row.get("engine"),
                    model=row.get("model"),
                    started_ts=row["started_ts"],
                    phase=row.get("phase", ""),
                    status=status,
                    finished_ts=row.get("finished_ts"),
                    totals=dict(row.get("totals") or {}),
                    error=error,
                    ask=row.get("ask"),
                    persisted=True,
                )
                with self._lock:
                    self._jobs[job.job_id] = job
                    self._order.append(job.job_id)
        finally:
            store.close()

    def persist(self, job: Job) -> None:
        """Mirror one job's current snapshot into the runs table.

        Best-effort: a store write failure must not kill the job or its
        worker — the run keeps going, only its history row is stale. Each
        call opens its own store because sqlite connections are thread-bound
        and this runs from both the request thread (spawn) and the worker
        (phase/terminal transitions).
        """
        with job._lock:
            snapshot = {
                "id": job.job_id,
                "kind": job.kind,
                "status": job.status,
                "phase": job.phase,
                "engine": job.engine,
                "model": job.model,
                "started_ts": job.started_ts,
                "finished_ts": job.finished_ts,
                "error": job.error,
                "totals": dict(job.totals),
                "ask": job.ask,
            }
        try:
            store = KGStore.open(paths.kg_db_path(self.data_dir))
            try:
                store.run_upsert(snapshot)
            finally:
                store.close()
        except (KGStoreError, OSError):
            pass

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
        exclusive: bool = False,
        **params: Any,
    ) -> Job:
        """Register a job of any kind, start its worker, and return it.

        ``exclusive`` refuses the job when one of the same ``kind`` is already
        running, raising `JobAlreadyRunning`. The check happens under this
        registry's lock together with the registration — see the comment
        inside.

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
            ask=params.get("topic"),
            _registry=self,
        )
        with self._lock:
            # `exclusive` is checked HERE, not by the caller. The route used
            # to call `running_research()` and then `create_research()` —
            # two separate acquisitions of this lock, so two concurrent
            # requests both saw "nothing running" and both started. Measured:
            # 4 simultaneous POSTs, 4 accepted, 0 refused. Check-and-register
            # has to be one critical section or it is decoration.
            running = self._running_locked(kind) if exclusive else None
            if running is not None:
                # Nothing has started, so drop the directory we just claimed
                # rather than leaving an empty one for `cost_summary` to walk.
                with suppress(OSError):
                    job_dir.rmdir()
                raise JobAlreadyRunning(running.job_id)
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            self._evict_locked()
        self.touch()  # new job appears in streams immediately
        self.persist(job)  # ... and in history after a restart
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
        fulltext: bool = True,
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
            exclusive=True,
            topic=topic,
            sources=list(sources),
            limit=limit,
            fulltext=fulltext,
            max_engine_calls=max_engine_calls,
            time_budget=time_budget,
            seed=seed,
        )

    def _running_locked(self, kind: str) -> Job | None:
        """A running job of this kind, if any. Caller must hold `self._lock`."""
        for job_id in reversed(self._order):
            job = self._jobs.get(job_id)
            if job is not None and job.kind == kind and job.status == "running":
                return job
        return None

    def running_research(self) -> Job | None:
        """A research run already in flight, if any.

        Read-only: for reporting. It must NOT be used to decide whether to
        start one — that decision has to be made inside the same lock
        acquisition that registers the new job, which is what `_spawn`'s
        `exclusive` flag does. Calling this and then calling `create_research`
        is a time-of-check/time-of-use gap, and it measured as one: four
        concurrent requests, four accepted.

        Two runs on one topic pay twice for the same extraction. This bounds
        the server's own duplicates only: a concurrent `python -m ontologylab
        collect` is not registered here and is not blocked — mitigation, not
        closure, which is why `insert_document` also recovers from the
        `IntegrityError` that a genuine race produces.
        """
        with self._lock:
            return self._running_locked("research")

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
        thread would keep writing to an object no reader can reach. Persisted
        (restored) jobs are exempt: they carry no progress and are exactly
        the history a restart must not re-empty. Callers must hold
        `self._lock`.
        """
        if len(self._order) <= MAX_RETAINED_JOBS:
            return
        surplus = len(self._order) - MAX_RETAINED_JOBS
        keep: list[str] = []
        for job_id in self._order:  # oldest first
            job = self._jobs.get(job_id)
            if job is None:
                # No backing entry: drop the id instead of carrying it. Kept,
                # it would make `list()` raise forever and every later pass
                # would re-append it, so the registry could never heal.
                continue
            finished = job.status in TERMINAL_STATUSES
            if surplus > 0 and finished and not job.persisted:
                surplus -= 1
                self._jobs.pop(job_id, None)
                continue
            keep.append(job_id)
        self._order = keep

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """All jobs, newest first.

        `.get`, not `[...]`: an id in `_order` with no entry in `_jobs` would
        otherwise raise KeyError here, and this is the single read path behind
        both `GET /api/jobs` and the SSE stream — so one desync would take the
        dashboard's push *and* its polling fallback down until a restart. The
        desync that produced it is fixed at the source (unique job dirs), but
        a listing is the wrong place to discover that something else broke.
        """
        with self._lock:
            jobs = [self._jobs.get(job_id) for job_id in reversed(self._order)]
        return [job for job in jobs if job is not None]

    # ------------------------------------------------------------------
    # Worker (daemon thread)
    # ------------------------------------------------------------------

    def _source_event(self, job: Job):
        """The collect fan-out's reporter: one step + one structured status.

        A lambda cannot do both without duplicating the step construction;
        the step and the sources entry must agree on status and detail or
        the badge row and the log would drift apart.
        """

        def report(kind: str, source: str, detail: object) -> None:
            step = source_step(kind, source, detail)
            job.record(step)
            with job._lock:
                job.sources[source] = {
                    "status": step.status,
                    "detail": step.detail,
                }

        return report

    def _run(self, job: Job, job_dir: Path, coroutine_factory, **params: Any) -> None:
        stopped_reason = ""
        try:
            stopped_reason = asyncio.run(coroutine_factory(job, job_dir, **params)) or ""
        except Exception as exc:  # noqa: BLE001 — job must record any failure
            # `job.error` and the progress log both reach the browser through
            # `as_status()` and the SSE stream, so neither may carry the
            # exception text. Today this boundary touches no network I/O, but
            # a research run moves collection inside it: five paper APIs whose
            # exceptions carry request URLs and response fragments, and a URL
            # is where a publisher key would sit. The full exception goes to
            # provenance, which stays on disk.
            summary = summarize_failure(exc)
            # Terminal status FIRST, before any I/O that could itself fail.
            # It used to be set after the provenance write, so an OSError
            # there (full disk, or the data dir moved out from under the
            # server) left `status` at "running" forever: the thread was
            # dead, `_evict_locked` would never reclaim it because it is not
            # terminal, and an exclusive research run stayed permanently
            # "busy" until a process restart.
            with job._lock:
                job.status = "failed"
                job.error = summary
                job.finished_ts = time.time()
            with suppress(Exception):
                Provenance(str(job_dir), seed=0).log(
                    "job.failed",
                    {"job_id": job.job_id, "type": type(exc).__name__,
                     "error": str(exc)},
                )
            job.log(f"[ontologylab] {job.kind} failed: {summary}")  # log() touches
            self.persist(job)
        else:
            with job._lock:
                # Derived from what the worker actually did, not from the
                # flag. Reading the flag reported `cancelled` for a run that
                # had already extracted every chunk — cancel arriving in the
                # window between the last abort check and this line made a
                # complete run look truncated, inviting the reviewer to pay
                # for the same documents twice. `stopped_reason` is non-empty
                # only when the loop really stopped early.
                job.status = "cancelled" if stopped_reason else "complete"
                job.finished_ts = time.time()
            self.touch()  # running → terminal transition
            self.persist(job)

    async def _extract_async(
        self,
        job: Job,
        job_dir: Path,
        *,
        doc_ids: list[str],
        max_engine_calls: int,
        time_budget: float,
        seed: int,
    ) -> str:
        """Mirror of ``main._extract_async`` minus CLI printing/kill switch.

        Returns why extraction stopped early, or "" when it ran to the end —
        `_run` derives the terminal status from this rather than from the
        cancellation flag, which can be set after the last unit of work.
        """
        provenance = Provenance(str(job_dir), seed=seed)
        caps = Caps(
            SimpleNamespace(
                iterations=0,  # no iteration cap; time/call budgets govern
                time_budget_s=time_budget,
                max_engine_calls=max_engine_calls,
            )
        )
        engine = get_engine(job.engine, job.model, seed=seed, data_dir=self.data_dir)
        effective_model = effective_extractor_model(engine, job.model)
        with job._lock:
            job.model = effective_model

        # sqlite connections are thread-bound: open fresh INSIDE the worker.
        store = KGStore.open(paths.kg_db_path(self.data_dir))
        try:
            if not doc_ids:
                doc_ids = extraction_doc_ids(store)
            if not doc_ids:
                job.log("[ontologylab] no unprocessed documents to extract")
                return ""

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
                extractor_model=effective_model,
                on_progress=job.log,
                on_stats=_accumulate,
                # The seam `run_extraction` exposes for exactly this: the CLI
                # passes its kill switch here, the server passes the job's
                # cancellation. Checked between chunks and before each engine
                # call, so a cancelled run stops without a partial write.
                should_abort=job.cancel_reason,
                decode_params=extraction_decode_params(engine),
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
            return stopped_reason
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
        fulltext: bool = True,
    ) -> str:
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
        # both phases. Route stores belong to their request's application.
        store = KGStore.open(paths.kg_db_path(self.data_dir))
        try:
            # ---------------- phase 1: collect ----------------
            job.set_phase("collect")
            if job._cancelled.is_set():
                job.log("[ontologylab] cancelled before collecting")
                return job.cancel_reason()

            # The topic is what a person typed; the query is what a keyword
            # index can answer. Sending the former verbatim is what returned
            # Muon g-2 papers for an apple-rootstock question — arXiv matched
            # "G-11" as "g"+"11", Crossref matched the Korean ending
            # "에 대해서". Ask the engine to write the query first.
            try:
                query_engine = get_engine(
                    job.engine, job.model, seed=seed, data_dir=self.data_dir
                )
                with job._lock:
                    job.model = effective_extractor_model(query_engine, job.model)
            except EngineError as exc:
                # Not fatal here. The extract phase resolves the engine again
                # and will fail loudly if it is genuinely unusable; the search
                # just goes ahead unformulated rather than the run dying at
                # the first step.
                query_engine = None
                job.log(f"[ontologylab] engine unavailable for query: {exc}")
            search_query, query_usage = await formulate_search_query(
                topic, query_engine, model=job.model
            )
            provenance.log(
                "research.query",
                {"topic": topic, "query": search_query, "usage": query_usage},
            )
            if query_usage.get("error"):
                # Say so rather than let a raw-topic search look like a
                # formulated one. A silent fallback is how the old behaviour
                # stayed invisible for so long.
                job.log(
                    f"[ontologylab] query not reformulated "
                    f"({query_usage['error']}); searching the topic as typed"
                )
            else:
                job.log(f"[ontologylab] searching for: {search_query}")
                if query_usage.get("notes"):
                    job.log(f"[ontologylab] {query_usage['notes']}")

            # `data_dir` reaches the connector so a keyed publisher source can
            # resolve its credential; the keyless five ignore it.
            batches, failures = await fetch_sources(
                sources, search_query, limit, self.data_dir,
                on_event=self._source_event(job),
            )
            for failure in failures:
                # The source name and the kind of failure are safe to show;
                # the exception text is not (H2) — it goes to provenance.
                #
                # No job log line here: `on_event` already announced this
                # failure as it happened. Writing it again put every failed
                # source in the log twice — invisible while the log was
                # prose scrolling past, one duplicated row per failure the
                # moment a screen drew one row per step.
                provenance.log(
                    "research.source_failed",
                    {"source": failure.source, "kind": failure.kind,
                     "error": failure.error},
                )
            if not batches and failures:
                job.log("[ontologylab] no source answered; nothing to extract")
                provenance.log("research.end", {"documents": 0, "created": 0})
                return ""

            raw_docs = collapse_duplicates(batches, SOURCE_ORDER)
            job.log(
                f"[ontologylab] collected {len(raw_docs)} document(s) from "
                f"{len(batches)} source(s)"
            )

            if fulltext:
                # After de-duplication, so one request per surviving work
                # rather than one per source that mentioned it.
                enriched, ft_stats = await asyncio.to_thread(
                    enrich_with_fulltext, raw_docs
                )
                raw_docs = enriched
                provenance.log("collect.fulltext", ft_stats)
                if ft_stats["eligible"]:
                    job.log(
                        f"[ontologylab] full text for {ft_stats['fetched']}"
                        f"/{ft_stats['eligible']} open-access document(s)"
                    )

            if job._cancelled.is_set():
                # Stop before writing: nothing is extracted yet, so the run
                # costs nothing and leaves the store as it was.
                job.log("[ontologylab] cancelled before storing documents")
                return job.cancel_reason()

            doc_ids: list[str] = []
            created_count = 0
            for raw in raw_docs:
                doc, created = store.insert_document(
                    source_kind=raw.source_kind,
                    source_uri=raw.source_uri,
                    title=raw.title,
                    raw_text=raw.raw_text,
                    content_hash=raw.content_hash,
                    source=raw.source,
                    evidence_grade=raw.evidence_grade,
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
                return ""

            # ---------------- phase 2: extract ----------------
            job.set_phase("extract")
            if job._cancelled.is_set():
                job.log("[ontologylab] cancelled before extracting")
                return job.cancel_reason()

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
            effective_model = effective_extractor_model(engine, job.model)
            with job._lock:
                job.model = effective_model
            provenance.log(
                "extract.start",
                {"engine": job.engine, "model": effective_model, "doc_ids": doc_ids},
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
                extractor_model=effective_model,
                on_progress=job.log,
                on_stats=_accumulate,
                should_abort=job.cancel_reason,
                decode_params=extraction_decode_params(engine),
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
            return stopped_reason
        finally:
            store.close()


__all__ = ["Job", "JobAlreadyRunning", "JobRegistry"]
