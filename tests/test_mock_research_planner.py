"""Deterministic combined research-planner contract."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import replace
from typing import TypeVar

import anyio
from fastapi.testclient import TestClient

from ontologylab import research_plan
from ontologylab import research_run as research_run_module
from ontologylab.engine_requests import EngineRequest, EngineTask, generate_for_request
from ontologylab.engines import MockEngine
from ontologylab.literature import formulate_research_plan, parse_research_plan
from ontologylab.research_artifacts import ResearchArtifactStore
from ontologylab.research_planner_contract import prepare_research_plan_prompt
from ontologylab.searchquery import build_search_queries_prompt
from ontologylab.server import jobs as jobs_module
from ontologylab.server.app import create_app
from tests.test_literature_artifacts import _paper

_TOPIC = "G-11 사과대목의 하드닝 최적 생육 조건에 대해서"
_T = TypeVar("_T")


def _run(awaitable: Awaitable[_T]) -> _T:
    async def wait() -> _T:
        return await awaitable

    return anyio.run(wait)


def test_mock_engine_builds_a_non_degraded_combined_research_plan() -> None:
    # Given: the shipped deterministic offline engine
    engine = MockEngine()

    # When: combined planning runs without a monkeypatched planner
    reading, usage = _run(formulate_research_plan(
        _TOPIC, engine, sources=("openalex", "pubmed"), max_queries=2,
    ))

    # Then: Mock exercises the real spec-and-plan contract instead of the
    # query-expansion fallback shape
    assert reading.degraded_reason is None
    assert reading.goal == _TOPIC
    assert reading.evidence_needs
    assert reading.axes
    assert all(axis.need_ids for axis in reading.axes)
    assert "error" not in usage


def test_request_aware_mock_plan_needs_no_marker_and_counts_once() -> None:
    # Given: an explicit planning task whose prompt has no legacy marker
    engine = MockEngine()
    request = EngineRequest(EngineTask.RESEARCH_PLAN, _TOPIC, "planner-model")

    # When: the caller-owned dispatcher sends the request
    raw_text, usage = _run(generate_for_request(engine, request))
    reading = parse_research_plan(
        raw_text, _TOPIC, ("openalex",), max_queries=1,
    )

    # Then: task dispatch creates a strict plan with one billed call
    assert reading is not None
    assert engine._calls == 1
    assert usage["calls"] == 1
    assert usage["task"] == EngineTask.RESEARCH_PLAN.value


def test_legacy_mock_plan_marker_remains_compatible() -> None:
    # Given: the existing marker-based prompt contract
    engine = MockEngine()
    prompt = prepare_research_plan_prompt(
        build_search_queries_prompt(_TOPIC, 1),
        ("<query-expansion>", "</query-expansion>"),
    )

    # When: a legacy caller uses generate directly
    raw_text, usage = _run(engine.generate(prompt, model="planner-model"))
    reading = parse_research_plan(
        raw_text, _TOPIC, ("openalex",), max_queries=1,
    )

    # Then: marker dispatch still creates a strict plan and bills once
    assert reading is not None
    assert engine._calls == 1
    assert usage["calls"] == 1
    assert "task" not in usage


def test_mock_plan_is_persisted_before_collection(
    tmp_path,
    monkeypatch,
) -> None:
    engine = MockEngine()
    resolve_calls = 0
    observed_plan: list[research_plan.PlanSnapshot] = []
    data_dir = tmp_path / "data-mock-plan"

    def _resolve(*args, **kwargs):
        nonlocal resolve_calls
        del args, kwargs
        resolve_calls += 1
        return engine

    async def _fetch(*args, **kwargs):
        del args, kwargs
        [job_dir] = (data_dir / "jobs").glob("research-*")
        replay = ResearchArtifactStore(job_dir).load()
        observed_plan.append(replay.plans[0])
        paper = replace(
            _paper(),
            search_axis="topic",
            search_query="mock plan fixture",
            search_axes=("topic",),
            search_queries=("mock plan fixture",),
        )
        return [("crossref", [paper])], []

    monkeypatch.setattr(jobs_module, "resolve_engine", _resolve)
    monkeypatch.setattr(research_run_module, "fetch_sources", _fetch)
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    started = client.post(
        "/api/research",
        json={
            "topic": "mock plan fixture",
            "sources": ["crossref"],
            "engine": "mock",
            "fulltext": False,
            "citation_expansion": False,
            "max_queries": 1,
        },
    ).json()
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)

    assert job.status == "complete", job.error
    assert resolve_calls == 1
    assert len(observed_plan) == 1
    plan = observed_plan[0]
    assert plan.degraded_reason is None
    assert plan.axes[0].origin is research_plan.AxisOrigin.PLANNED
    assert plan.axes[0].query == "mock plan fixture"
    assert all("invalid_output" not in line for line in job.progress)
