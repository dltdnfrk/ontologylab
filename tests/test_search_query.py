"""The topic a person types is not a query a paper index can answer.

Measured before this existed, on ``G-11 사과대목의 하드닝 최적 생육 조건에
대해서`` (optimal hardening conditions for the G-11 apple rootstock), the
fan-out sent that sentence verbatim and Crossref returned:

    Theoretical Study on Optimal Conditions for Absorbent Regeneration in CO2
    원효 저작의 성립 순서에 대해서
    A Study on the Optimum Shot Peening Condition for Al7075-T6
    Physicochemical Properties of Non-Formaldehyde Resin Finished Cotton Fabric

Those are not near misses. The index ORs its tokens, so it matched the
Korean grammatical ending ``에 대해서`` ("about") and the word ``조건``
("condition"); arXiv matched only ``G-11``, which its tokenizer splits into
``g`` and ``11``, returning Muon g-2 papers. The run then stored all of it,
because nothing downstream judged relevance.

With the same topic formulated first — ``Geneva 11 apple rootstock
acclimatization hardening`` — Crossref returns the Geneva apple rootstock
breeding program and *Bio-hardening of in vitro raised plants of Geneva (G.)
series clonal rootstock*.

The failure mode these tests guard is not "bad query" but "silently bad
query": every fallback path must say it fell back, because the original
behaviour was invisible for exactly as long as it was silent.
"""

from __future__ import annotations

import asyncio

import pytest

from ontologylab.searchquery import (
    MAX_QUERY_LEN,
    MAX_TERMS,
    build_search_query_prompt,
    formulate_search_query,
    parse_search_query,
)

TOPIC = "G-11 사과대목의 하드닝 최적 생육 조건에 대해서"


def _fenced(payload: str) -> str:
    return f"```json\n{payload}\n```"


class _Engine:
    """Minimal stand-in for an engine: returns canned text, or raises."""

    def __init__(self, text: str | None = None, error: Exception | None = None):
        self._text = text
        self._error = error
        self.prompts: list[str] = []

    async def generate(self, prompt, model=None):
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        return self._text, {"engine_calls": 1}


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_a_well_formed_answer_yields_query_and_notes() -> None:
    raw = _fenced(
        '{"query": "Geneva 11 apple rootstock hardening",'
        ' "notes": "Expanded G-11 to Geneva 11."}'
    )

    query, notes = parse_search_query(raw, TOPIC)

    assert query == "Geneva 11 apple rootstock hardening"
    assert notes == "Expanded G-11 to Geneva 11."


@pytest.mark.parametrize(
    "raw",
    [
        "no fenced block here",
        "```json\nnot json at all\n```",
        '```json\n["an", "array", "not", "an", "object"]\n```',
        '```json\n{"notes": "forgot the query"}\n```',
        '```json\n{"query": 42}\n```',
        '```json\n{"query": "   "}\n```',
    ],
)
def test_unusable_output_is_reported_as_none(raw: str) -> None:
    """Failure is `None`, distinct from any legitimate query.

    Using the topic as the failure sentinel is what made a correct
    formulation indistinguishable from a broken one — see
    `test_a_query_equal_to_the_topic_is_a_success_not_a_failure`.
    """
    query, notes = parse_search_query(raw, TOPIC)

    assert query is None
    assert notes == ""


def test_an_over_long_answer_is_rejected_rather_than_truncated() -> None:
    raw = _fenced('{"query": "%s"}' % ("x" * (MAX_QUERY_LEN + 1)))

    assert parse_search_query(raw, TOPIC)[0] is None


def test_too_many_terms_are_cut_to_the_cap() -> None:
    """These indexes OR their tokens, so an ignored length rule widens the
    very net the rule exists to narrow."""
    raw = _fenced('{"query": "%s"}' % " ".join(f"t{i}" for i in range(MAX_TERMS + 4)))

    query, _ = parse_search_query(raw, TOPIC)

    assert len(query.split()) == MAX_TERMS


def test_the_prompt_carries_the_topic_and_the_rules_that_were_learned() -> None:
    prompt = build_search_query_prompt(TOPIC)

    assert TOPIC in prompt
    assert "ENGLISH" in prompt, "the indexes are English-language"
    assert "rootstock code" in prompt, "expand domain codes — the G-11 case"
    assert "OR" in prompt, "explain why brevity matters, not just that it does"


# --------------------------------------------------------------------------
# Failing open, and saying so
# --------------------------------------------------------------------------


def test_no_engine_returns_the_topic_and_reports_why() -> None:
    query, usage = asyncio.run(formulate_search_query(TOPIC, None))

    assert query == TOPIC
    assert usage["error"]


def test_an_engine_failure_does_not_stop_the_search() -> None:
    """A degraded search beats a run that refuses to start."""
    engine = _Engine(error=RuntimeError("engine exploded"))

    query, usage = asyncio.run(formulate_search_query(TOPIC, engine))

    assert query == TOPIC
    assert "engine exploded" in usage["error"]


def test_an_unusable_answer_is_reported_as_an_error_not_a_success() -> None:
    """The caller decides what to tell the user, and it can only do that if
    "I searched the raw topic" is distinguishable from "I formulated it"."""
    engine = _Engine(text="```json\n{}\n```")

    query, usage = asyncio.run(formulate_search_query(TOPIC, engine))

    assert query == TOPIC
    assert usage["error"]


def test_a_good_answer_is_returned_without_an_error() -> None:
    engine = _Engine(
        text=_fenced(
            '{"query": "Geneva 11 apple rootstock acclimatization hardening",'
            ' "notes": "Translated from Korean; G-11 is Geneva 11."}'
        )
    )

    query, usage = asyncio.run(formulate_search_query(TOPIC, engine))

    assert query == "Geneva 11 apple rootstock acclimatization hardening"
    assert "error" not in usage
    assert "Geneva 11" in usage["notes"]


def test_the_engine_is_asked_about_the_topic_itself() -> None:
    engine = _Engine(text=_fenced('{"query": "apple rootstock"}'))

    asyncio.run(formulate_search_query(TOPIC, engine))

    assert TOPIC in engine.prompts[0]


# --------------------------------------------------------------------------
# Wired into the run
# --------------------------------------------------------------------------


def test_the_research_job_searches_the_formulated_query_not_the_topic() -> None:
    """The wiring is the point; a formulator nothing calls fixes nothing."""
    import inspect

    from ontologylab.server import jobs

    source = inspect.getsource(jobs.JobRegistry._research_async)

    assert "formulate_search_query" in source
    # The fetch must receive the formulated query. Asserting only that the
    # formulator is called would pass on a version that computes a query and
    # then searches `topic` anyway — which is the bug, not the fix.
    after_fetch = source.split("fetch_sources", 1)[1][:160]
    assert "search_query" in after_fetch
    assert "topic" not in after_fetch


def test_a_fallback_is_announced_on_the_job_log() -> None:
    """Silence is what let the old behaviour survive."""
    import inspect

    from ontologylab.server import jobs

    source = inspect.getsource(jobs.JobRegistry._research_async)

    assert "searching the topic as typed" in source
    assert "searching for:" in source


def test_each_source_reports_when_it_starts_and_how_it_ended() -> None:
    from ontologylab.server.jobs import _source_event_line

    assert "querying arxiv" in _source_event_line("source_start", "arxiv", None)
    assert "returned 5" in _source_event_line("source_ok", "arxiv", 5)
    assert "did not answer" in _source_event_line(
        "source_failed", "arxiv", "fetch_failed"
    )


def test_a_query_equal_to_the_topic_is_a_success_not_a_failure() -> None:
    """Found in review: a working engine was reported as a broken one.

    When the topic is already English keywords the right answer is to leave
    it alone, and the engine does. The old code used `query == topic` as its
    failure sentinel, so that correct answer raised `error` and the run
    logged "searching the topic as typed" about a search it had formulated —
    an operator reading the log would distrust a search that was fine.
    """
    already_good = "apple rootstock cold hardiness"
    engine = _Engine(
        text=_fenced('{"query": "%s", "notes": "already keywords"}' % already_good)
    )

    query, usage = asyncio.run(formulate_search_query(already_good, engine))

    assert query == already_good
    assert "error" not in usage, "a no-op formulation is not an error"
