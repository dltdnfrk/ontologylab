"""M6: a running job can be stopped, and stopping it means something.

`run_extraction` grew a `should_abort` seam for exactly this — the CLI passed
its kill switch there, the server had nothing to pass. `JobRegistry.create`
also built a worker thread and dropped the handle, so nothing could wait for
one to notice.

Cancellation is a request, not a kill. The worker checks before each engine
call, so it stops at a chunk boundary rather than mid-write. An engine call
already in flight is the floor on how long that takes.

Every test drives the real `create()` → `_run` → `run_extraction` path. The
only thing faked is the engine, and only to hold it still: a mock extraction
finishes in milliseconds, which would leave no window to cancel in and would
turn every test here green whether or not the seam is wired. What proves the
wiring is `engine.calls` — a cancelled run must not spend the next chunk's
call. Status alone would still read `cancelled` with `should_abort` removed,
because the worker sets it from the same flag the request thread set.
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab.engines import MockEngine
from ontologylab.kgstore import KGStore
from ontologylab.server import jobs as jobs_module
from ontologylab.server import routes
from ontologylab.server.app import create_app
from ontologylab.server.jobs import TERMINAL_STATUSES, JobRegistry

# Chunking targets 1500 tokens × 4 chars; this clears 6000 chars several
# times over, so a run has more than one engine call to skip.
SENTENCE = "The PaymentGateway validates cards through the FraudDetector. "
TEXT = SENTENCE * 220


class _GatedEngine:
    """The real mock engine, held at its first call until the test lets go.

    Wrapping rather than replacing keeps the responses real, so insertion,
    provenance and totals all behave as they do in production. The gate only
    buys the test a moment in which the job is unambiguously running.
    """

    def __init__(self) -> None:
        self._inner = MockEngine(seed=0)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def name(self) -> str:
        return self._inner.name()

    async def generate(self, prompt: str, *, model: str | None = None):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            self.release.wait(20)
        return await self._inner.generate(prompt, model=model)


def _seed(data_dir: Path, text: str = TEXT) -> None:
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        store.insert_document(
            source_kind="upload",
            source_uri="file:///notes.md",
            title="notes",
            raw_text=text,
            content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        )
    finally:
        store.close()


def _gate(monkeypatch) -> _GatedEngine:
    engine = _GatedEngine()
    monkeypatch.setattr(jobs_module, "get_engine", lambda *a, **k: engine)
    return engine


def _start(registry: JobRegistry):
    return registry.create(
        engine="mock",
        model=None,
        doc_ids=[],
        max_engine_calls=100000,
        time_budget=600.0,
        seed=0,
    )


def _await_terminal(job, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and job.status not in TERMINAL_STATUSES:
        time.sleep(0.02)


# --------------------------------------------------------------------------
# The seam: does cancelling actually stop work?
# --------------------------------------------------------------------------


def test_a_cancelled_run_stops_spending_engine_calls(tmp_path, monkeypatch) -> None:
    """The test that fails if `should_abort` is not passed to `run_extraction`.

    The job is held inside its first engine call. Cancelling and then letting
    that call return means the loop reaches the next chunk with the flag
    already set. If the seam is wired it stops there; if it is not, it works
    through every remaining chunk and the call count climbs.
    """
    data_dir = tmp_path / "data"
    _seed(data_dir)
    engine = _gate(monkeypatch)
    registry = JobRegistry(data_dir)

    job = _start(registry)
    assert engine.entered.wait(20), "the worker never reached the engine"

    assert job.cancel() is True
    engine.release.set()
    _await_terminal(job)

    assert engine.calls == 1, (
        f"the run made {engine.calls} engine calls after being cancelled; "
        f"should_abort is not reaching run_extraction"
    )
    assert job.status == "cancelled"


def test_an_uncancelled_run_of_the_same_document_spends_more(
    tmp_path, monkeypatch
) -> None:
    """The control.

    Without it, `engine.calls == 1` above could just mean the document has
    one chunk, and the assertion would hold with cancellation ripped out.
    """
    data_dir = tmp_path / "data"
    _seed(data_dir)
    engine = _gate(monkeypatch)
    registry = JobRegistry(data_dir)

    job = _start(registry)
    assert engine.entered.wait(20)
    engine.release.set()  # never cancelled
    _await_terminal(job)

    assert job.status == "complete"
    assert engine.calls > 1, "this document must have more than one chunk"


def test_a_cancelled_job_says_so_in_its_log(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    _seed(data_dir)
    engine = _gate(monkeypatch)
    registry = JobRegistry(data_dir)

    job = _start(registry)
    engine.entered.wait(20)
    job.cancel()
    engine.release.set()
    _await_terminal(job)

    lines = list(job.progress)
    assert any("cancellation requested" in line for line in lines)
    assert any("stopped early" in line for line in lines), (
        "the run must report that it did not finish the document set"
    )


def test_cancellation_is_not_a_failure(tmp_path, monkeypatch) -> None:
    """`failed` would send a reviewer looking for a bug that is not there."""
    data_dir = tmp_path / "data"
    _seed(data_dir)
    engine = _gate(monkeypatch)
    registry = JobRegistry(data_dir)

    job = _start(registry)
    engine.entered.wait(20)
    job.cancel()
    engine.release.set()
    _await_terminal(job)

    assert job.status == "cancelled"
    assert job.error is None


def test_what_was_extracted_before_the_stop_is_kept(tmp_path, monkeypatch) -> None:
    """Stopping between chunks, not mid-write.

    The first chunk's insertion had already committed, so a cancelled run is
    a partial result, not a discarded one.
    """
    data_dir = tmp_path / "data"
    _seed(data_dir)
    engine = _gate(monkeypatch)
    registry = JobRegistry(data_dir)

    job = _start(registry)
    engine.entered.wait(20)
    job.cancel()
    engine.release.set()
    _await_terminal(job)

    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        nodes = store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    finally:
        store.close()
    assert nodes > 0, "the completed chunk's extraction was rolled back"
    assert job.totals["nodes_new"] == nodes


# --------------------------------------------------------------------------
# The flag itself
# --------------------------------------------------------------------------


def test_cancelling_a_finished_job_is_refused(tmp_path) -> None:
    """An empty store finishes at once, so this job is genuinely terminal."""
    registry = JobRegistry(tmp_path / "data")
    job = _start(registry)
    _await_terminal(job)
    assert job.status == "complete"

    assert job.cancel() is False


def test_a_refused_cancel_does_not_relabel_a_finished_job(tmp_path) -> None:
    registry = JobRegistry(tmp_path / "data")
    job = _start(registry)
    _await_terminal(job)

    job.cancel()

    assert job.status == "complete", "a late cancel rewrote a terminal status"


def test_cancelling_twice_is_harmless(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    _seed(data_dir)
    engine = _gate(monkeypatch)
    registry = JobRegistry(data_dir)

    job = _start(registry)
    engine.entered.wait(20)
    first = job.cancel()
    second = job.cancel()
    engine.release.set()
    _await_terminal(job)

    assert first is True and second is True
    assert job.status == "cancelled"


def test_the_worker_thread_is_kept_so_it_can_be_joined(tmp_path, monkeypatch) -> None:
    """`create` used to build the thread and drop the handle."""
    data_dir = tmp_path / "data"
    _seed(data_dir)
    engine = _gate(monkeypatch)
    registry = JobRegistry(data_dir)

    job = _start(registry)
    assert job._thread is not None
    engine.entered.wait(20)
    job.cancel()
    engine.release.set()

    job._thread.join(timeout=30)
    assert not job._thread.is_alive()
    assert job.status in TERMINAL_STATUSES, "joined, so the status must be settled"


def test_cancelling_an_unknown_job_is_a_plain_no(tmp_path) -> None:
    registry = JobRegistry(tmp_path / "data")
    assert registry.cancel("no-such-job") is False


def test_one_cancellation_does_not_touch_another_job(tmp_path, monkeypatch) -> None:
    """Two registries, two workers: the flag is per job, not per process."""
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    _seed(left_dir)
    _seed(right_dir)
    engine = _gate(monkeypatch)  # shared, but only gates the first call
    left = JobRegistry(left_dir)
    right = JobRegistry(right_dir)

    left_job = _start(left)
    engine.entered.wait(20)
    left_job.cancel()
    engine.release.set()
    _await_terminal(left_job)

    right_job = _start(right)
    _await_terminal(right_job)

    assert left_job.status == "cancelled"
    assert right_job.status == "complete"


# --------------------------------------------------------------------------
# Through the HTTP surface
# --------------------------------------------------------------------------


def test_the_endpoint_cancels_a_running_job(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    _seed(data_dir)
    engine = _gate(monkeypatch)
    client = TestClient(create_app(data_dir=data_dir))

    started = client.post("/api/extract", json={"engine": "mock"})
    job_id = started.json()["job_id"]
    assert engine.entered.wait(20)

    body = client.post(f"/api/jobs/{job_id}/cancel").json()
    engine.release.set()

    assert body["ok"] is True
    assert body["cancelled"] is True
    job = routes._registry().get(job_id)
    _await_terminal(job)
    assert job.status == "cancelled"
    assert engine.calls == 1


def test_the_endpoint_answers_200_for_an_unknown_job(tmp_path) -> None:
    """Not an error the caller can act on, so not a 4xx."""
    client = TestClient(create_app(data_dir=tmp_path / "data"))

    response = client.post("/api/jobs/no-such-job/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["cancelled"] is False


def test_the_endpoint_reports_a_finished_job_as_not_cancelled(tmp_path) -> None:
    data_dir = tmp_path / "data"
    client = TestClient(create_app(data_dir=data_dir))
    job_id = client.post("/api/extract", json={"engine": "mock"}).json()["job_id"]
    _await_terminal(routes._registry().get(job_id))

    body = client.post(f"/api/jobs/{job_id}/cancel").json()

    assert body["cancelled"] is False
    assert "complete" in body["reason"]


def test_the_cancel_response_carries_no_engine_or_failure_text(
    tmp_path, monkeypatch
) -> None:
    """H2 applies here too: this response embeds a full job status."""
    import json

    data_dir = tmp_path / "data"
    _seed(data_dir)
    engine = _gate(monkeypatch)
    client = TestClient(create_app(data_dir=data_dir))
    job_id = client.post("/api/extract", json={"engine": "mock"}).json()["job_id"]
    engine.entered.wait(20)

    body = client.post(f"/api/jobs/{job_id}/cancel").json()
    engine.release.set()

    assert json.dumps(body).count("http") == 0, "a URL reached the cancel response"


# --------------------------------------------------------------------------
# Interaction with M5 retention
# --------------------------------------------------------------------------


def test_a_cancelled_job_is_evictable(tmp_path) -> None:
    """Its worker has stopped, so retaining it forever would defeat M5."""
    from ontologylab.server.jobs import MAX_RETAINED_JOBS, Job

    registry = JobRegistry(tmp_path / "data")
    for index in range(MAX_RETAINED_JOBS + 5):
        job = Job(
            job_id=f"job-{index:03d}",
            kind="extract",
            engine="mock",
            model=None,
            started_ts=time.time(),
            _registry=registry,
        )
        job.status = "cancelled"
        with registry._lock:
            registry._jobs[job.job_id] = job
            registry._order.append(job.job_id)
            registry._evict_locked()

    assert len(registry.list()) == MAX_RETAINED_JOBS
    assert registry.get("job-000") is None
