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

from collections.abc import Awaitable
from typing import TypeVar

import anyio
import pytest

import ontologylab.literature as searchquery_adapter
from ontologylab import research_plan, searchquery
from ontologylab.engine_requests import EngineRequest, EngineTask
from ontologylab.engines import EngineError
from ontologylab.research_plan import DegradedReason
from ontologylab.research_planner_contract import prepare_research_plan_prompt
from ontologylab.research_spec import JsonObject
from ontologylab.searchquery import (
    MAX_QUERY_LEN,
    MAX_TERMS,
    build_search_query_prompt,
    formulate_search_query,
    parse_search_query,
)

TOPIC = "G-11 사과대목의 하드닝 최적 생육 조건에 대해서"
T = TypeVar("T")


def _run(awaitable: Awaitable[T]) -> T:
    async def wait() -> T:
        return await awaitable

    return anyio.run(wait)


def _fenced(payload: str) -> str:
    return f"```json\n{payload}\n```"


class _Engine:
    """Minimal stand-in for an engine: returns canned text, or raises."""

    def __init__(self, text: str | None = None, error: Exception | None = None):
        self._text = text
        self._error = error
        self.prompts: list[str] = []

    def name(self) -> str:
        return "legacy-test"

    async def generate(
        self, prompt: str, *, model: str | None = None,
    ) -> tuple[str, JsonObject]:
        del model
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        assert self._text is not None
        return self._text, {"engine_calls": 1}


class _RequestAwarePlanner:
    """Planner whose legacy path is observable and intentionally unsuitable."""

    def __init__(
        self,
        text: str,
        *,
        error: EngineError | None = None,
        legacy_text: str | None = None,
    ) -> None:
        self._text = text
        self._error = error
        self._legacy_text = legacy_text
        self.requests: list[EngineRequest] = []
        self.legacy_calls: list[tuple[str, str | None]] = []

    def name(self) -> str:
        return "aware-test"

    async def generate_request(
        self, request: EngineRequest,
    ) -> tuple[str, JsonObject]:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return self._text, {"calls": 1, "task": "forged"}

    async def generate(
        self, prompt: str, *, model: str | None = None,
    ) -> tuple[str, JsonObject]:
        self.legacy_calls.append((prompt, model))
        if self._legacy_text is None:
            raise EngineError("legacy planner path was billed")
        return self._legacy_text, {"calls": 1, "path": "legacy"}


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
    query, notes = parse_search_query(raw, TOPIC)

    assert query is None
    assert notes == ""


def test_an_over_long_answer_is_rejected_rather_than_truncated() -> None:
    raw = _fenced('{"query": "%s"}' % ("x" * (MAX_QUERY_LEN + 1)))

    assert parse_search_query(raw, TOPIC)[0] is None


def test_too_many_terms_are_cut_to_the_cap() -> None:
    query_text = " ".join(f"t{i}" for i in range(MAX_TERMS + 4))
    raw = _fenced(f'{{"query": "{query_text}"}}')

    query, _ = parse_search_query(raw, TOPIC)

    assert query is not None
    assert len(query.split()) == MAX_TERMS


def test_complementary_queries_are_deduplicated_and_capped() -> None:
    raw = _fenced(
        '{"queries": ['
        '{"query": "Geneva 11 apple rootstock hardening", "axis": "process"},'
        '{"query": "geneva 11 apple rootstock hardening", "axis": "duplicate"},'
        '{"query": "apple rootstock acclimatization survival", "axis": "outcome"},'
        '{"query": "micropropagation apple rootstock protocol", "axis": "method"},'
        '{"query": "fire blight resistant rootstock physiology", "axis": "biology"}'
        '], "notes": "Covered process, outcome, method, and biology."}'
    )

    queries, notes = searchquery.parse_search_queries(
        raw, TOPIC, max_queries=3
    )

    assert queries == [
        "Geneva 11 apple rootstock hardening",
        "apple rootstock acclimatization survival",
        "micropropagation apple rootstock protocol",
    ]
    assert notes == "Covered process, outcome, method, and biology."


def test_query_set_failure_falls_back_to_one_raw_topic() -> None:
    engine = _Engine(text="```json\n{}\n```")

    queries, usage = _run(
        searchquery.formulate_search_queries(TOPIC, engine, max_queries=4)
    )

    assert queries == [TOPIC]
    assert usage["error"]


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
    query, usage = _run(formulate_search_query(TOPIC, None))

    assert query == TOPIC
    assert usage["error"]


def test_an_engine_failure_does_not_stop_the_search() -> None:
    """A degraded search beats a run that refuses to start."""
    engine = _Engine(error=RuntimeError("engine exploded"))

    query, usage = _run(formulate_search_query(TOPIC, engine))

    assert query == TOPIC
    assert "engine exploded" in usage["error"]


def test_an_unusable_answer_is_reported_as_an_error_not_a_success() -> None:
    """The caller decides what to tell the user, and it can only do that if
    "I searched the raw topic" is distinguishable from "I formulated it"."""
    engine = _Engine(text="```json\n{}\n```")

    query, usage = _run(formulate_search_query(TOPIC, engine))

    assert query == TOPIC
    assert usage["error"]


def test_a_good_answer_is_returned_without_an_error() -> None:
    engine = _Engine(
        text=_fenced(
            '{"query": "Geneva 11 apple rootstock acclimatization hardening",'
            ' "notes": "Translated from Korean; G-11 is Geneva 11."}'
        )
    )

    query, usage = _run(formulate_search_query(TOPIC, engine))

    assert query == "Geneva 11 apple rootstock acclimatization hardening"
    assert "error" not in usage
    assert "Geneva 11" in usage["notes"]


def test_the_engine_is_asked_about_the_topic_itself() -> None:
    engine = _Engine(text=_fenced('{"query": "apple rootstock"}'))

    _run(formulate_search_query(TOPIC, engine))

    assert TOPIC in engine.prompts[0]


# --------------------------------------------------------------------------
# Wired into the run
# --------------------------------------------------------------------------


def test_the_research_job_searches_the_formulated_query_not_the_topic(
    tmp_path, monkeypatch,
) -> None:
    """The acquired query must be the planner output, not the raw topic."""
    from fastapi.testclient import TestClient

    from ontologylab import research_run as research_run_module
    from ontologylab.server import jobs as jobs_module
    from ontologylab.server.app import create_app

    formulated = "Geneva 11 apple rootstock hardening"
    engine = _Engine(text=_fenced(
        '{"goal":"Compare hardening","evidence_needs":['
        '{"need_id":"hardening","kind":"general",'
        '"description":"Hardening evidence","required":true,'
        '"minimum_content_class":"abstract"}],"assumptions":[],'
        f'"queries":[{{"query":"{formulated}","axis":"process",'
        '"terms":["Geneva 11","hardening"],'
        '"need_ids":["hardening"],"dependencies":[]}]}'
    ))
    observed: list[tuple[str, dict[str, str] | None]] = []

    async def fetch(*args, **kwargs):
        observed.append((args[1], kwargs.get("source_queries")))
        return [], []

    monkeypatch.setattr(jobs_module, "resolve_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(research_run_module, "fetch_sources", fetch)
    app = create_app(data_dir=tmp_path / "formulated-query")
    client = TestClient(app)

    started = client.post(
        "/api/research",
        json={"topic": TOPIC, "sources": ["crossref"], "engine": "mock",
              "fulltext": False, "citation_expansion": False, "max_queries": 1},
    ).json()
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)

    assert observed == [(formulated, {"crossref": formulated})]
    assert observed[0][0] != TOPIC


def test_a_fallback_is_announced_on_the_job_log(
    tmp_path, monkeypatch,
) -> None:
    """Fallback is durable machine state and drives raw-topic acquisition."""
    from fastapi.testclient import TestClient

    from ontologylab import research_run as research_run_module
    from ontologylab.research_artifacts import ResearchArtifactStore
    from ontologylab.server import jobs as jobs_module
    from ontologylab.server.app import create_app

    engine = _Engine(text="```json\nnot json\n```")
    observed_queries: list[str] = []

    async def fetch(*args, **kwargs):
        del kwargs
        observed_queries.append(args[1])
        return [], []

    monkeypatch.setattr(jobs_module, "resolve_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(research_run_module, "fetch_sources", fetch)
    data_dir = tmp_path / "degraded-query"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)

    started = client.post(
        "/api/research",
        json={"topic": TOPIC, "sources": ["crossref"], "engine": "mock",
              "fulltext": False, "citation_expansion": False, "max_queries": 1},
    ).json()
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)
    [job_dir] = (data_dir / "jobs").glob("research-*")
    [plan] = ResearchArtifactStore(job_dir).load().plans

    assert plan.degraded_reason is research_plan.DegradedReason.INVALID_OUTPUT
    assert plan.axes[0].origin is research_plan.AxisOrigin.RAW_TOPIC_FALLBACK
    assert plan.axes[0].query == TOPIC
    assert observed_queries == [TOPIC]


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
        text=_fenced(
            f'{{"query": "{already_good}", "notes": "already keywords"}}'
        )
    )

    query, usage = _run(formulate_search_query(already_good, engine))

    assert query == already_good
    assert "error" not in usage, "a no-op formulation is not an error"


# --------------------------------------------------------------------------
# Combined immutable research planning adapter
# --------------------------------------------------------------------------


def test_scholarly_query_formulation_keeps_the_legacy_engine_path() -> None:
    # Given: an aware-capable engine with a usable legacy query response
    engine = _RequestAwarePlanner(
        "unused",
        legacy_text=_fenced('{"queries":[{"query":"legacy query"}]}'),
    )

    # When: the separate scholarly-query adapter runs
    queries, usage = _run(searchquery_adapter.formulate_scholarly_queries(
        TOPIC, engine, max_queries=1,
    ))

    # Then: that non-planner call site remains on legacy generate
    assert engine.requests == []
    assert len(engine.legacy_calls) == 1
    assert queries[0].query == "legacy query"
    assert usage["path"] == "legacy"
    assert "task" not in usage


def test_combined_planner_normalizes_semantics_and_need_linked_axes() -> None:
    # Given: one valid response carrying semantic and executable fields
    engine = _Engine(text=_fenced(
        '{"goal":"Compare hardening survival",'
        '"evidence_needs":[{"need_id":"survival","kind":"result",'
        '"description":"Report survival outcomes","required":true,'
        '"minimum_content_class":"fulltext"}],'
        '"assumptions":["Geneva 11 is G-11"],'
        '"queries":[{"query":"Geneva 11 hardening survival",'
        '"axis":"outcome","terms":["Geneva 11","hardening survival"],'
        '"need_ids":["survival"],"dependencies":[]}]}'))

    # When: the existing engine is called once for combined planning
    reading, usage = _run(searchquery_adapter.formulate_research_plan(
        TOPIC, engine, sources=("openalex", "pubmed"), max_queries=2,
    ))

    # Then: semantic normalization and source projections share that answer
    assert len(engine.prompts) == 1
    assert reading.goal == "Compare hardening survival"
    need_id = reading.evidence_needs[0].need_id
    assert need_id.startswith("sha256:")
    assert reading.axes[0].need_ids == (need_id,)
    assert dict(reading.axes[0].source_queries)["pubmed"].endswith("[Title/Abstract]")
    assert reading.degraded_reason is None
    assert "error" not in usage


def test_combined_planner_sends_one_exact_request_without_legacy_billing() -> None:
    # Given: an aware planner whose legacy method cannot produce a plan
    response = _fenced(
        '{"goal":"goal","evidence_needs":[{"need_id":"n",'
        '"kind":"general","description":"need","required":true,'
        '"minimum_content_class":"fulltext"}],"assumptions":[],'
        '"queries":[{"query":"query","axis":"topic","terms":["query"],'
        '"need_ids":["n"],"dependencies":[]}]}'
    )
    engine = _RequestAwarePlanner(response)
    model = "planner-model"

    # When: combined planning is formulated
    reading, usage = _run(searchquery_adapter.formulate_research_plan(
        TOPIC, engine, sources=("openalex",), model=model, max_queries=1,
    ))

    # Then: one immutable task request owns the billed call
    expected_prompt = prepare_research_plan_prompt(
        searchquery.build_search_queries_prompt(TOPIC, 1),
        ("<query-expansion>", "</query-expansion>"),
    )
    assert engine.requests == [EngineRequest(
        EngineTask.RESEARCH_PLAN, expected_prompt, model,
    )]
    assert engine.legacy_calls == []
    assert reading.degraded_reason is None
    assert usage["calls"] == 1
    assert usage["task"] == EngineTask.RESEARCH_PLAN.value


def test_request_aware_planner_error_degrades_without_legacy_fallback() -> None:
    # Given: the aware call fails and a legacy fallback would be a second bill
    error = EngineError("aware planner failed")
    engine = _RequestAwarePlanner(
        "unused", error=error, legacy_text=_fenced(
            '{"goal":"fallback","evidence_needs":[{"need_id":"n",'
            '"kind":"general","description":"need","required":true,'
            '"minimum_content_class":"fulltext"}],"assumptions":[],'
            '"queries":[{"query":"fallback","axis":"topic",'
            '"terms":["fallback"],"need_ids":["n"],"dependencies":[]}]}'
        ),
    )

    # When: planning handles the engine failure
    reading, usage = _run(searchquery_adapter.formulate_research_plan(
        TOPIC, engine, sources=("openalex",), model="planner-model", max_queries=1,
    ))

    # Then: the aware failure is visible and legacy is never billed
    assert len(engine.requests) == 1
    assert engine.requests[0].task is EngineTask.RESEARCH_PLAN
    assert engine.legacy_calls == []
    assert reading.degraded_reason is DegradedReason.ENGINE_ERROR
    assert usage == {"error": str(error)}


def test_request_aware_invalid_plan_degrades_after_one_task_call() -> None:
    # Given: an aware planner returns text that fails the strict plan parser
    engine = _RequestAwarePlanner("```json\nnot json\n```")

    # When: planning parses the aware response
    reading, usage = _run(searchquery_adapter.formulate_research_plan(
        TOPIC, engine, sources=("openalex",), max_queries=1,
    ))

    # Then: parsing is not bypassed and no legacy call is billed
    assert len(engine.requests) == 1
    assert engine.legacy_calls == []
    assert reading.degraded_reason is DegradedReason.INVALID_OUTPUT
    assert usage["calls"] == 1
    assert usage["task"] == EngineTask.RESEARCH_PLAN.value
    assert usage["error"]


@pytest.mark.parametrize(
    "axis_fields",
    ['"need_ids":7,"dependencies":[]', '"need_ids":["n"],"dependencies":7',
     '"need_ids":["n"],"dependencies":[],"source_queries":7'],
)
def test_malformed_nested_planner_shape_degrades_visibly(axis_fields: str) -> None:
    payload = (
        '{"goal":"goal","evidence_needs":[{"need_id":"n","kind":"general",'
        '"description":"need","required":true,"minimum_content_class":"fulltext"}],'
        f'"assumptions":[],"queries":[{{"query":"query","axis":"topic",'
        f'"terms":["query"],{axis_fields}}}]}}'
    )
    engine = _Engine(text=_fenced(payload))

    reading, usage = _run(searchquery_adapter.formulate_research_plan(
        TOPIC, engine, sources=("openalex",), max_queries=1,
    ))

    assert len(engine.prompts) == 1
    assert reading.degraded_reason is not None
    assert usage["error"]


def test_invalid_combined_planner_has_visible_raw_topic_baseline() -> None:
    # Given: invalid fenced planner JSON
    engine = _Engine(text="```json\nnot json\n```")

    # When: planning fails open
    reading, usage = _run(searchquery_adapter.formulate_research_plan(
        TOPIC, engine, sources=("openalex",), max_queries=2,
    ))

    # Then: baseline semantics and degradation are machine-visible
    assert reading.goal == TOPIC
    need = reading.evidence_needs[0]
    assert need.kind.value == "general"
    assert need.minimum_content.value == "abstract"
    assert reading.axes[0].need_ids == (need.need_id,)
    assert reading.axes[0].query == TOPIC
    assert reading.degraded_reason is not None
    assert reading.assumptions[0].startswith("planner_degraded:")
    assert usage["error"]
