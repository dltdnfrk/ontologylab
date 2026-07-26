"""Two bounds a research run needs: on the path, and on the job list.

M1 — `new_job_dir` interpolated `stage` straight into a path. Every caller
passes a literal today, so nothing escapes; the reason to close it now is
that a research run makes a user-supplied topic a first-class concept, and
naming runs `research-<topic>-...` is the obvious next step.

M5 — `JobRegistry` never removed anything, and `routes` re-serializes the
whole list on every progress line. A research run logs two phases, raising
the line rate and the job count at once.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ontologylab import paths
from ontologylab.server.jobs import MAX_RETAINED_JOBS, Job, JobRegistry

# --------------------------------------------------------------------------
# M1
# --------------------------------------------------------------------------


def test_the_stages_this_repo_actually_uses_are_accepted(tmp_path) -> None:
    for stage in ("collect", "extract", "build-pack", "research"):
        job_dir = paths.new_job_dir(tmp_path, stage)
        assert job_dir.is_dir()
        assert job_dir.parent == paths.jobs_dir(tmp_path)


def test_a_traversal_stage_is_refused(tmp_path) -> None:
    """The reproduction from the plan: four levels above the store."""
    before = set(tmp_path.rglob("*"))

    with pytest.raises(ValueError):
        paths.new_job_dir(tmp_path, "../../../../escaped-research")

    assert set(tmp_path.rglob("*")) == before, "a refused stage wrote something"


@pytest.mark.parametrize(
    "stage",
    [
        "",
        ".",
        "..",
        "/absolute",
        "with/slash",
        "with\\backslash",
        "-leading-dash",
        "Upper",
        "has space",
        "한국어주제",
        "topic\x00null",
        "topic\nnewline",
    ],
)
def test_anything_that_is_not_a_stage_token_is_refused(tmp_path, stage) -> None:
    with pytest.raises(ValueError):
        paths.new_job_dir(tmp_path, stage)


def test_a_topic_string_cannot_become_a_directory_name(tmp_path) -> None:
    """The mistake this guard exists to make impossible.

    A Korean research topic is exactly what a developer would reach for when
    labelling runs in a job listing. It must fail at the call site so the
    topic goes into a Job field instead.
    """
    with pytest.raises(ValueError):
        paths.new_job_dir(tmp_path, "research-형광 프로브 스펙트럼")


def test_two_jobs_in_the_same_second_get_separate_directories(tmp_path) -> None:
    first = paths.new_job_dir(tmp_path, "collect")
    second = paths.new_job_dir(tmp_path, "collect")
    assert first != second
    assert first.is_dir() and second.is_dir()


# --------------------------------------------------------------------------
# M5
# --------------------------------------------------------------------------


def _register(registry: JobRegistry, name: str, status: str) -> Job:
    """Insert a job directly: `create` would spawn a worker thread."""
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


def test_finished_jobs_are_bounded(tmp_path) -> None:
    registry = JobRegistry(tmp_path)
    for index in range(MAX_RETAINED_JOBS + 15):
        _register(registry, f"job-{index:03d}", "complete")

    listed = registry.list()

    assert len(listed) == MAX_RETAINED_JOBS


def test_the_jobs_kept_are_the_newest(tmp_path) -> None:
    registry = JobRegistry(tmp_path)
    for index in range(MAX_RETAINED_JOBS + 5):
        _register(registry, f"job-{index:03d}", "complete")

    ids = [job.job_id for job in registry.list()]

    assert ids[0] == f"job-{MAX_RETAINED_JOBS + 4:03d}", "newest first"
    assert "job-000" not in ids, "the oldest must have been evicted"


def test_a_running_job_is_never_evicted(tmp_path) -> None:
    """Its worker keeps writing; dropping it would orphan a live record."""
    registry = JobRegistry(tmp_path)
    running = _register(registry, "job-running", "running")
    for index in range(MAX_RETAINED_JOBS + 20):
        _register(registry, f"job-{index:03d}", "complete")

    assert registry.get("job-running") is running
    assert any(job.job_id == "job-running" for job in registry.list())


def test_many_running_jobs_may_exceed_the_bound(tmp_path) -> None:
    """The bound governs retention, not concurrency."""
    registry = JobRegistry(tmp_path)
    for index in range(MAX_RETAINED_JOBS + 10):
        _register(registry, f"job-{index:03d}", "running")

    assert len(registry.list()) == MAX_RETAINED_JOBS + 10


def test_an_evicted_job_is_gone_from_both_structures(tmp_path) -> None:
    """`_jobs` and `_order` must not drift: a stale id would KeyError."""
    registry = JobRegistry(tmp_path)
    for index in range(MAX_RETAINED_JOBS + 5):
        _register(registry, f"job-{index:03d}", "complete")

    with registry._lock:
        assert set(registry._order) == set(registry._jobs)
        assert len(registry._order) == len(registry._jobs)
    assert registry.get("job-000") is None
    # `list()` indexes `_jobs` by every id in `_order`; drift would raise.
    assert len(registry.list()) == MAX_RETAINED_JOBS


def test_the_real_registration_path_evicts(tmp_path) -> None:
    """Drive `create` itself, not the helper.

    Every test above reaches `_evict_locked` directly, so none of them can
    tell whether it is wired into the path that actually registers a job.
    This one spawns real workers against an empty store — they find nothing
    to extract and finish immediately — and checks the bound holds.
    """
    registry = JobRegistry(tmp_path)
    total = MAX_RETAINED_JOBS + 5
    for _ in range(total):
        registry.create(
            engine="mock",
            model=None,
            doc_ids=[],
            max_engine_calls=1,
            time_budget=1.0,
            seed=0,
        )
        # Job ids carry a second-resolution timestamp, and `create` derives
        # the id from the directory name, so let each one settle rather than
        # racing the suffix logic.
        time.sleep(0.01)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if all(job.status != "running" for job in registry.list()):
            break
        time.sleep(0.05)

    finished = [job for job in registry.list() if job.status != "running"]
    assert finished, "the workers never finished; the bound was not exercised"
    assert len(registry.list()) <= MAX_RETAINED_JOBS + 1, (
        f"{total} jobs registered, {len(registry.list())} retained: "
        f"eviction is not wired into create()"
    )


def test_a_run_that_finishes_later_is_still_evictable(tmp_path) -> None:
    """Eviction happens on insert, so a job that finishes afterwards is only
    reconsidered when the next job arrives — and then it must be dropped."""
    registry = JobRegistry(tmp_path)
    first = _register(registry, "job-first", "running")
    for index in range(MAX_RETAINED_JOBS + 5):
        _register(registry, f"job-{index:03d}", "complete")
    assert registry.get("job-first") is first

    first.status = "complete"
    _register(registry, "job-trigger", "complete")

    assert registry.get("job-first") is None
