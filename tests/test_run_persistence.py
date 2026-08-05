"""Durable job history (GAP-O2): the jobs screen survives a server restart.

The registry used to be pure memory, so every restart emptied the jobs
list. Each job is now mirrored into the runs table on creation and on
state changes; at startup the table becomes the history. A row still
marked running is a zombie — its worker died with the old process — and
is relabelled failed before the dashboard sees it.
"""

from __future__ import annotations

import time
from pathlib import Path

from ontologylab import paths
from ontologylab.kgstore import KGStore
from ontologylab.server.jobs import MAX_RETAINED_JOBS, Job, JobRegistry


def _register(registry: JobRegistry, name: str, status: str) -> Job:
    """Insert a job directly, as test_job_bounds does: no worker thread."""
    job = Job(
        job_id=name,
        kind="extract",
        engine="mock",
        model=None,
        started_ts=time.time(),
        _registry=registry,
    )
    job.status = status
    with registry._lock:
        registry._jobs[job.job_id] = job
        registry._order.append(job.job_id)
        registry._evict_locked()
    return job


def test_run_row_survives_registry_recreation(tmp_path: Path) -> None:
    registry = JobRegistry(tmp_path)
    job = _register(registry, "research-20260805-100000", "complete")
    job.phase = "extract"
    job.finished_ts = time.time()
    job.totals = {
        "nodes_new": 3, "nodes_merged": 0, "edges_new": 2, "edges_merged": 0,
    }
    registry.persist(job)

    restarted = JobRegistry(tmp_path)
    listed = {j.job_id: j for j in restarted.list()}

    assert "research-20260805-100000" in listed
    got = listed["research-20260805-100000"]
    assert got.status == "complete"
    assert got.phase == "extract"
    assert got.totals["nodes_new"] == 3
    assert got.persisted


def test_a_running_row_becomes_failed_on_restart(tmp_path: Path) -> None:
    store = KGStore.open(paths.kg_db_path(tmp_path))
    store.run_upsert({
        "id": "research-20260805-090000",
        "kind": "research",
        "status": "running",
        "phase": "collect",
        "engine": "mock",
        "model": None,
        "started_ts": time.time(),
    })
    store.close()

    restarted = JobRegistry(tmp_path)
    job = restarted.get("research-20260805-090000")

    assert job is not None
    assert job.status == "failed"
    assert job.error == "interrupted by server restart"
    # the relabel is written back so a second restart does not re-report it
    check = KGStore.open(paths.kg_db_path(tmp_path))
    assert check.list_runs()[0]["status"] == "failed"
    check.close()


def test_persisted_history_is_not_evicted(tmp_path: Path) -> None:
    registry = JobRegistry(tmp_path)
    first = _register(registry, "hist-oldest", "complete")
    last = _register(registry, "hist-newest", "complete")
    registry.persist(first)
    registry.persist(last)

    restarted = JobRegistry(tmp_path)
    for index in range(MAX_RETAINED_JOBS + 15):
        _register(restarted, f"live-{index:03d}", "complete")

    ids = {j.job_id for j in restarted.list()}
    assert "hist-oldest" in ids
    assert "hist-newest" in ids


def test_the_real_spawn_path_writes_history(tmp_path: Path) -> None:
    """Drive create() itself: mock job finishes instantly against an empty store."""
    registry = JobRegistry(tmp_path)
    job = registry.create(
        engine="mock",
        model=None,
        doc_ids=[],
        max_engine_calls=1,
        time_budget=1.0,
        seed=0,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and job.status == "running":
        time.sleep(0.05)

    assert job.status == "complete"
    restarted = JobRegistry(tmp_path)
    got = restarted.get(job.job_id)
    assert got is not None
    assert got.status == "complete"
