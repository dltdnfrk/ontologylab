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

from ontologylab.server.jobs import Job, _source_event_line
from ontologylab.trace import MAX_DETAIL, Step, source_step


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


def test_the_job_log_helper_has_no_strings_of_its_own() -> None:
    """`_source_event_line` must stay a thin call onto `Step.line`.

    These words used to be string literals in `jobs.py`, which was fine
    until the browser also needed the structure behind them. Re-spelling
    them there would recreate the two-writer bug in the exact place it was
    removed from.
    """
    import inspect

    body = inspect.getsource(_source_event_line)
    assert "source_step(" in body
    assert "querying" not in body.split('"""')[-1]


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


def test_a_failed_source_is_recorded_once() -> None:
    """`_traced` already announces every failure as it happens.

    The worker used to record them a second time from the `failures` list
    afterwards. Invisible in a log — the line scrolled past twice — and one
    duplicated row per failed source the moment a screen drew one row per
    step.
    """
    import inspect

    from ontologylab.server import jobs

    source = inspect.getsource(jobs.JobRegistry._research_async)
    failures_loop = source.split("for failure in failures:", 1)[1].split(
        "if not batches", 1
    )[0]

    assert "provenance.log" in failures_loop
    assert "job.record" not in failures_loop, (
        "the live source_failed event already recorded this one"
    )
    assert "job.log" not in failures_loop


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


def test_the_server_ships_values_not_display_text() -> None:
    """Korean lives in the browser, next to the other display strings.

    A server that sent "조회 중" would be a server that has to be redeployed
    to fix a typo on a screen, and a second place for the same words to live.
    """
    import re
    from pathlib import Path

    from ontologylab.server import jobs, routes

    hangul = re.compile(r"[가-힣]")
    for module in (jobs, routes):
        body = Path(module.__file__).read_text(encoding="utf-8")
        for call in re.findall(r"Step\(([^)]*)\)", body, re.S):
            assert not hangul.search(call), (
                f"display text in a Step in {Path(module.__file__).name}: "
                f"{call!r}"
            )
