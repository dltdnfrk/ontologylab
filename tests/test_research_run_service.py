"""Behavioral contract for the canonical Research service and job adapter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import anyio
import pytest
from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab import research_run as research_run_module
from ontologylab.engines import MockEngine
from ontologylab.extractor import ExtractionOutcome
from ontologylab.kgstore import KGStore
from ontologylab.research_artifact_codec import decode_job_pointer_snapshot
from ontologylab.research_artifact_types import ResearchArtifactPointers
from ontologylab.research_artifacts import ResearchArtifactStore
from ontologylab.research_run_types import (
    EngineFactory,
    ResearchRunCallbacks,
    ResearchRunInput,
    ResearchRunResult,
    ResearchStartInput,
    SourceEventDetail,
    build_research_start_input,
)
from ontologylab.research_spec import InteractionDecision, ResearchOrigin
from ontologylab.server import jobs as jobs_module
from ontologylab.server.app import create_app
from ontologylab.server.jobs import (
    NO_SOURCES_SUMMARY,
    Job,
    JobRegistry,
)
from tests.test_research_run import TOPIC, _fake_fetch, _paper


def _start_input() -> ResearchStartInput:
    return build_research_start_input(
        topic=TOPIC,
        origin=ResearchOrigin.DIRECT_API,
        interaction_decision=InteractionDecision.EXECUTE,
        sources=("crossref",),
        limit=10,
        max_queries=1,
        fulltext=False,
        citation_expansion=False,
        citation_seed_count=0,
        citation_limit=0,
        engine="mock",
        model=None,
        max_engine_calls=10,
        time_budget=30.0,
        seed=0,
    )


def _adapter_context(tmp_path: Path) -> tuple[JobRegistry, Job, Path]:
    registry = JobRegistry(tmp_path / "adapter-data")
    job_dir = tmp_path / "adapter-job"
    job_dir.mkdir()
    job = Job(
        job_id=job_dir.name,
        kind="research",
        engine="mock",
        model=None,
        started_ts=0.0,
        ask=TOPIC,
        _registry=registry,
    )
    return registry, job, job_dir


def _run_adapter(registry: JobRegistry, job: Job, job_dir: Path) -> str:
    async def invoke() -> str:
        return await registry._research_async(
            job, job_dir, start_input=_start_input(),
        )

    return anyio.run(invoke)


def test_adapter_maps_service_events_and_returns_one_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one service result and every typed callback event
    registry, job, job_dir = _adapter_context(tmp_path)
    engine = MockEngine()
    resolver = Mock(return_value=engine)
    plan_id = "sha256:" + "c" * 64
    pointers = ResearchArtifactPointers(
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
        (plan_id,),
        ("sha256:" + "d" * 64,),
        None,
        plan_id,
        1,
    )
    expected = ExtractionOutcome("")

    async def fake_run(
        inputs: ResearchRunInput,
        *,
        engine_factory: EngineFactory,
        callbacks: ResearchRunCallbacks,
    ) -> ResearchRunResult:
        assert inputs.job_dir == job_dir
        assert engine_factory() is engine
        callbacks.on_phase("extract")
        callbacks.on_progress("adapter-progress")
        callbacks.on_source_event("source_ok", "crossref", 2)
        callbacks.on_model_resolved("resolved-model")
        callbacks.on_stats({"nodes_new": 2, "edges_new": 3, "unknown": 99})
        callbacks.on_artifacts_changed(pointers)
        return ResearchRunResult(expected)

    monkeypatch.setattr(jobs_module, "run_research", fake_run)
    monkeypatch.setattr(jobs_module, "resolve_engine", resolver)

    # When: the lifecycle adapter awaits the service
    outcome = _run_adapter(registry, job, job_dir)

    # Then: each event is visible once and unknown totals never enter the job
    assert outcome is expected
    assert resolver.call_count == 1
    assert job.phase == "extract"
    assert "adapter-progress" in job.progress
    assert job.model == "resolved-model"
    assert job.totals == {
        "nodes_new": 2,
        "nodes_merged": 0,
        "edges_new": 3,
        "edges_merged": 0,
    }
    assert job.sources == {"crossref": {"status": "ok", "detail": "2"}}
    assert job.research_pointers == pointers
    store = KGStore.open(paths.kg_db_path(registry.data_dir))
    try:
        [row] = store.list_runs()
        _ask, persisted_pointers = decode_job_pointer_snapshot(row["ask"])
    finally:
        store.close()
    assert persisted_pointers == pointers


def test_create_research_persists_topic_with_pointer_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a Research service that completes without adding artifacts
    async def fake_run(
        inputs: ResearchRunInput,
        *,
        engine_factory: EngineFactory,
        callbacks: ResearchRunCallbacks,
    ) -> ResearchRunResult:
        del inputs, engine_factory, callbacks
        return ResearchRunResult(ExtractionOutcome(""))

    monkeypatch.setattr(jobs_module, "run_research", fake_run)
    registry = JobRegistry(tmp_path / "topic-data")
    start_input = _start_input()

    # When: the registry creates and persists the Research job
    job = registry.create_research(start_input=start_input)
    assert job._thread is not None
    job._thread.join(timeout=30)
    assert not job._thread.is_alive()

    # Then: both the live job and durable pointer envelope retain the topic
    assert job.ask == start_input.topic
    store = KGStore.open(paths.kg_db_path(registry.data_dir))
    try:
        [row] = store.list_runs()
        persisted_ask, persisted_pointers = decode_job_pointer_snapshot(row["ask"])
    finally:
        store.close()
    assert persisted_ask == start_input.topic
    assert persisted_pointers is None


def test_initial_cancellation_constructs_no_engine(
    tmp_path: Path,
) -> None:
    # Given: cancellation is already visible before the collect phase starts
    data_dir = tmp_path / "cancelled-data"
    job_dir = tmp_path / "cancelled-job"
    job_dir.mkdir()
    phases: list[str] = []
    factory_calls = 0

    def engine_factory() -> MockEngine:
        nonlocal factory_calls
        factory_calls += 1
        return MockEngine()

    callbacks = ResearchRunCallbacks(
        on_phase=phases.append,
        on_progress=lambda _line: None,
        on_source_event=lambda _kind, _source, _detail: None,
        on_model_resolved=lambda _model: None,
        on_stats=lambda _stats: None,
        on_artifacts_changed=lambda _pointers: None,
        abort_reason=lambda: "cancelled by request",
    )

    async def invoke() -> ResearchRunResult:
        return await research_run_module.run_research(
            ResearchRunInput(_start_input(), data_dir, job_dir),
            engine_factory=engine_factory,
            callbacks=callbacks,
        )

    # When: the real service evaluates its initial cancellation boundary
    result = anyio.run(invoke)

    # Then: it exits from collect without constructing or billing an engine
    assert result.extraction_outcome == "cancelled by request"
    assert phases == ["collect"]
    assert factory_calls == 0


def test_adapter_passes_a_live_abort_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a service that reads cancellation on both sides of a state change
    registry, job, job_dir = _adapter_context(tmp_path)
    observed: list[str] = []

    async def fake_run(
        inputs: ResearchRunInput,
        *,
        engine_factory: EngineFactory,
        callbacks: ResearchRunCallbacks,
    ) -> ResearchRunResult:
        del inputs, engine_factory
        observed.append(callbacks.abort_reason())
        job._cancelled.set()
        observed.append(callbacks.abort_reason())
        return ResearchRunResult(ExtractionOutcome(observed[-1]))

    monkeypatch.setattr(jobs_module, "run_research", fake_run)

    # When: the adapter supplies the callback
    outcome = _run_adapter(registry, job, job_dir)

    # Then: it reflects the live event rather than one captured value
    assert observed == ["", "cancelled by request"]
    assert outcome == "cancelled by request"


def test_no_usable_source_maps_to_the_existing_failed_job_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the service's typed expected no-source result
    registry, job, job_dir = _adapter_context(tmp_path)

    async def no_source(
        inputs: ResearchRunInput,
        *,
        engine_factory: EngineFactory,
        callbacks: ResearchRunCallbacks,
    ) -> ResearchRunResult:
        del inputs, engine_factory, callbacks
        return ResearchRunResult(None)

    monkeypatch.setattr(jobs_module, "run_research", no_source)

    # When: the unchanged lifecycle boundary translates the adapter outcome
    registry._run(
        job, job_dir, registry._research_async, start_input=_start_input(),
    )

    # Then: no-source remains the existing failed terminal contract
    assert job.status == "failed"
    assert job.error == NO_SOURCES_SUMMARY


def test_duplicate_only_run_keeps_the_existing_normal_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two Research runs collect the same canonical document
    data_dir = tmp_path / "duplicate-data"
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _fake_fetch((("crossref", [_paper("crossref", "10.1/duplicate")]),)),
    )
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    payload = {"topic": TOPIC, "sources": ["crossref"], "engine": "mock",
               "fulltext": False, "citation_expansion": False, "max_queries": 1}

    # When: the second run ingests only the already-known document
    first_id = client.post("/api/research", json=payload).json()["job_id"]
    first = app.state.jobs.get(first_id)
    assert first is not None and first._thread is not None
    first._thread.join(timeout=30)
    second_id = client.post("/api/research", json=payload).json()["job_id"]
    second = app.state.jobs.get(second_id)
    assert second is not None and second._thread is not None
    second._thread.join(timeout=30)

    # Then: duplicate-only remains a normal outcome and stores no second document
    assert second.status == "complete", second.error
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        assert len(store.list_documents()) == 1
    finally:
        store.close()


def test_initial_lineage_and_pointer_publish_precede_first_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the first source event observes the already-published job pointer
    data_dir = tmp_path / "pointer-data"
    app = create_app(data_dir=data_dir)
    observed: list[ResearchArtifactPointers] = []
    source_event = JobRegistry._source_event

    def checking_source_event(
        registry: JobRegistry, job: Job,
    ) -> Callable[[str, str, SourceEventDetail], None]:
        report = source_event(registry, job)

        def report_with_pointer(
            kind: str, source: str, detail: SourceEventDetail,
        ) -> None:
            assert job.research_pointers is not None
            [artifact_dir] = (data_dir / "jobs").glob("research-*")
            canonical = ResearchArtifactStore(artifact_dir).load().pointers()
            assert job.research_pointers == canonical
            observed.append(canonical)
            report(kind, source, detail)

        return report_with_pointer

    monkeypatch.setattr(JobRegistry, "_source_event", checking_source_event)
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _fake_fetch((("crossref", [_paper("crossref", "10.1/pointer")]),)),
    )
    client = TestClient(app)

    # When: the real service reaches its first fetch
    started = client.post(
        "/api/research",
        json={
            "topic": TOPIC,
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

    # Then: fetch emitted events only after canonical pointer publication
    assert observed
    assert all(pointer == observed[0] for pointer in observed)
    assert job.status == "complete", job.error
