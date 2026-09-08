"""A run has to be able to say what it used.

The pipeline narrated itself into a log for a long time, and a log is a
fine thing for a console and a poor one for a screen: by the time the work
is a sentence, the structure that would let a UI group, colour, or collapse
it is gone. `ontologylab.trace` makes the step the unit and derives the
sentence from it.

The risk that creates is drift — two writers, one of which someone forgets
— which is the bug this repo keeps finding (see
`test_no_duplicated_constants.py`). So most of what is pinned here is that
there is exactly one writer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ontologylab import research_run as research_run_module
from ontologylab.connectors.paper_api import SourceFailure
from ontologylab.server.app import create_app
from ontologylab.server.jobs import Job, JobRegistry
from ontologylab.trace import MAX_DETAIL, Step, source_step
from tests.test_research_run import _fake_fetch

# --------------------------------------------------------------------------
# One writer
# --------------------------------------------------------------------------


def test_the_log_line_is_rendered_from_the_step() -> None:
    """The lines the Jobs screen has always shown, still exactly those.

    Asserted verbatim because a research run's log is the record of what
    happened, and `test_research_run.py` reads it.
    """
    assert source_step("source_start", "arxiv", None).line == (
        "[ontologylab] querying arxiv"
    )
    assert source_step("source_ok", "arxiv", 5).line == (
        "[ontologylab] arxiv returned 5 result(s)"
    )
    assert source_step("source_failed", "arxiv", "fetch_failed").line == (
        "[ontologylab] arxiv did not answer (fetch_failed)"
    )


def test_source_event_records_one_step_and_one_rendered_line(tmp_path) -> None:
    # Given: the job adapter's real structured source reporter
    registry = JobRegistry(tmp_path / "data-source-event")
    job = Job(
        job_id="j", kind="research", engine="mock", model=None, started_ts=0.0,
    )

    # When: one source completes
    registry._source_event(job)("source_ok", "arxiv", 5)

    # Then: one structured event produced exactly one rendered progress line
    assert [step.as_dict() for step in job.steps] == [
        {"tool": "arxiv", "action": "query", "status": "ok", "detail": "5"},
    ]
    assert list(job.progress) == [source_step("source_ok", "arxiv", 5).line]


def test_recording_a_step_writes_both_and_they_agree() -> None:
    """`record()` is the only way both lists are written."""
    job = Job(job_id="j", kind="research", engine="mock", model=None,
              started_ts=0.0)
    job.record(Step("pubmed", "query", "ok", "12"))

    assert list(job.progress) == ["[ontologylab] pubmed returned 12 result(s)"]
    assert [s.as_dict() for s in job.steps] == [
        {"tool": "pubmed", "action": "query", "status": "ok", "detail": "12"}
    ]


def test_a_phase_change_is_a_step_and_still_reads_the_same() -> None:
    job = Job(job_id="j", kind="research", engine="mock", model=None,
              started_ts=0.0)
    job.set_phase("collect")

    assert job.phase == "collect"
    assert "collect phase started" in job.progress[0]
    assert job.steps[0].as_dict()["detail"] == "collect"


def test_the_status_snapshot_carries_the_steps() -> None:
    """The browser reads `steps`; without this the trace never leaves the
    server and the screen is back to re-parsing prose."""
    job = Job(job_id="j", kind="research", engine="mock", model=None,
              started_ts=0.0)
    job.record(Step("arxiv", "query", "running"))

    snapshot = job.as_status()

    assert snapshot["steps"] == [
        {"tool": "arxiv", "action": "query", "status": "running", "detail": ""}
    ]
    assert snapshot["progress"] == ["[ontologylab] querying arxiv"]


def test_the_response_model_does_not_filter_the_steps_out() -> None:
    """`JobStatus` is a pydantic model, so a field missing from it is
    dropped silently — the job would build the list and the browser would
    never see it, with nothing anywhere reporting a problem."""
    from ontologylab.server.schemas import JobStatus

    assert "steps" in JobStatus.model_fields


def test_a_failed_source_is_recorded_once(tmp_path, monkeypatch) -> None:
    # Given: a source that reports its live failure and returns provenance detail
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _fake_fetch(
            (),
            (SourceFailure("crossref", "private provider detail", "fetch_failed"),),
        ),
    )
    app = create_app(data_dir=tmp_path / "data-failed-source")
    client = TestClient(app)

    # When: the Research API runs to its existing no-source terminal mapping
    started = client.post(
        "/api/research",
        json={
            "topic": "failed source trace",
            "sources": ["crossref"],
            "engine": "mock",
            "fulltext": False,
            "citation_expansion": False,
        },
    ).json()
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)

    # Then: the live failure appears once; provenance replay did not duplicate it
    failed_steps = [step for step in job.steps if step.status == "failed"]
    assert [step.as_dict() for step in failed_steps] == [
        {
            "tool": "crossref",
            "action": "query",
            "status": "failed",
            "detail": "fetch_failed",
        },
    ]


# --------------------------------------------------------------------------
# What a step may carry
# --------------------------------------------------------------------------


def test_an_unknown_status_is_refused() -> None:
    """The browser styles by status. A status it has no rule for would
    render as an unmarked row — visually identical to a success."""
    with pytest.raises(ValueError):
        Step("pubmed", "query", "exploded")


def test_a_long_detail_is_truncated_visibly() -> None:
    step = Step("claude", "formulate", "ok", "x" * (MAX_DETAIL + 50))

    assert len(step.shown_detail) == MAX_DETAIL
    assert step.shown_detail.endswith("…"), "a silent cut reads as complete"
    # And a detail that fits is left exactly alone.
    assert Step("a", "b", "ok", "short").shown_detail == "short"


def test_the_server_ships_structured_source_values(tmp_path) -> None:
    # Given: the server adapter receives one source event
    registry = JobRegistry(tmp_path / "data-structured-values")
    job = Job(
        job_id="j", kind="research", engine="mock", model=None, started_ts=0.0,
    )

    # When: the event enters the real job status surface
    registry._source_event(job)("source_failed", "pubmed", "fetch_failed")

    # Then: the response is built from stable machine values
    assert job.as_status()["steps"] == [
        {
            "tool": "pubmed",
            "action": "query",
            "status": "failed",
            "detail": "fetch_failed",
        },
    ]
