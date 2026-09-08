from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ontologylab import intent as intent_module
from ontologylab import research_run as research_run_module
from ontologylab import research_spec
from ontologylab.intent import Intent
from ontologylab.research_plan import PlannerReading
from ontologylab.server import schemas
from ontologylab.server.app import create_app
from ontologylab.server.jobs import JobAlreadyRunning, JobRegistry
from tests.research_contract_fixtures import load_fixture
from tests.research_route_contract_helpers import (
    build_start_input,
    execution_controls,
)

_FIXTURE = Path(__file__).parent / "fixtures/research/interaction-policy.jsonl"
_INTERACTION_ROWS = load_fixture(_FIXTURE)


def _client(tmp_path: Path) -> TestClient:
    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    return TestClient(app)


def _jobs(client: TestClient) -> JobRegistry:
    app = client.app
    assert isinstance(app, FastAPI)
    jobs = app.state.jobs
    assert isinstance(jobs, JobRegistry)
    return jobs


class _ClassifierEngine:
    def __init__(self, ambiguity_kind: str) -> None:
        self.ambiguity_kind = ambiguity_kind

    async def generate(
        self, prompt: str, *, model: str | None = None
    ) -> tuple[str, dict[str, int]]:
        del prompt, model
        return (
            json.dumps(
                {
                    "action": "research",
                    "params": {"topic": "TP53"},
                    "reading": "research TP53",
                    "ambiguity_kind": self.ambiguity_kind,
                }
            ),
            {},
        )


@pytest.mark.parametrize(
    "row", _INTERACTION_ROWS, ids=[str(row["id"]) for row in _INTERACTION_ROWS]
)
def test_all_60_interaction_cases_cross_the_start_boundary(row) -> None:
    origin_value = row["origin"]
    ambiguity = row["ambiguity_kind"]
    expected_value = row["expected_decision"]
    expected_started = row["expected_job_started"]
    assert isinstance(origin_value, str)
    assert isinstance(ambiguity, str)
    assert isinstance(expected_value, str)
    assert isinstance(expected_started, bool)
    origin = research_spec.ResearchOrigin(origin_value)

    if origin is research_spec.ResearchOrigin.CHAT:
        classified = anyio.run(
            intent_module.classify, "research TP53", _ClassifierEngine(ambiguity)
        )
        decision = classified.interaction_decision
    else:
        decision = research_spec.decide_interaction(origin, ambiguity)

    start_input = build_start_input(topic="TP53", origin=origin, decision=decision)
    assert start_input.interaction_decision.value == expected_value
    starts = start_input.interaction_decision in {
        research_spec.InteractionDecision.EXECUTE,
        research_spec.InteractionDecision.DECOMPOSE,
    }
    assert starts is expected_started


@pytest.mark.parametrize(
    ("decision", "expected_detail"),
    [
        (research_spec.InteractionDecision.CLARIFY, "which topic"),
        (research_spec.InteractionDecision.ABSTAIN, "cannot start"),
    ],
)
def test_chat_clarify_and_abstain_make_zero_job_or_source_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision, expected_detail: str
) -> None:
    client = _client(tmp_path)
    calls = {"jobs": 0, "sources": 0}

    async def classify_once(message, engine, model=None):
        del message, engine, model
        return Intent(
            "research",
            params={"topic": "TP53"},
            reading="research TP53",
            interaction_decision=decision,
        )

    def create_research(**kwargs):
        del kwargs
        calls["jobs"] += 1
        return SimpleNamespace(job_id="should-not-start")

    async def fetch_sources(*args, **kwargs):
        del args, kwargs
        calls["sources"] += 1
        return [], []

    monkeypatch.setattr(intent_module, "classify", classify_once)
    monkeypatch.setattr(_jobs(client), "create_research", create_research)
    monkeypatch.setattr(research_run_module, "fetch_sources", fetch_sources)

    payload = {"message": "research TP53", "engine": "mock"}
    result = client.post("/api/chat", json=payload).json()["result"]

    assert result["kind"] == "blocked"
    assert result["error_kind"] == decision.value
    assert result["interaction_decision"] == decision.value
    assert expected_detail in result["detail"]
    assert calls == {"jobs": 0, "sources": 0}


def test_direct_route_never_classifies_or_compiles_in_request_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    calls = {"classify": 0, "compile": 0}

    def classify_spy(*args, **kwargs):
        del args, kwargs
        calls["classify"] += 1
        raise AssertionError("direct Research classified")

    def compile_spy(*args, **kwargs):
        del args, kwargs
        calls["compile"] += 1
        raise AssertionError("ResearchSpec compiled in request thread")

    monkeypatch.setattr(intent_module, "classify", classify_spy)
    monkeypatch.setattr(schemas.ResearchStartInput, "compile", compile_spy)
    monkeypatch.setattr(
        _jobs(client), "create_research",
        lambda **kwargs: SimpleNamespace(job_id="research-direct")
    )

    response = client.post(
        "/api/research", json={"topic": "TP53", "sources": ["crossref"], "engine": "mock"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "job_id": "research-direct",
        "status": "running",
    }
    assert calls == {"classify": 0, "compile": 0}


def test_direct_route_preserves_all_12_nonfallback_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    expected = execution_controls({"engine": "api:nonfallback-contract"})
    captured: research_spec.JsonObject = {}

    def create_research(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(job_id="research-controls")

    monkeypatch.setattr(_jobs(client), "create_research", create_research)
    expected_payload = expected.to_json_value()
    fallback_payload = schemas.ResearchRequest.model_validate(
        {"topic": "fallback"}
    ).model_dump(exclude={"topic"})
    assert set(expected_payload) == set(fallback_payload)
    assert all(
        expected_payload[name] != fallback_payload[name]
        for name in expected_payload
    )
    response = client.post(
        "/api/research", json={"topic": "TP53", **expected_payload}
    )

    assert response.status_code == 200
    start_input = captured.pop("start_input")
    assert isinstance(start_input, schemas.ResearchStartInput)
    assert start_input.topic == "TP53"
    assert start_input.controls.to_json_value() == expected_payload
    assert not captured


def _stable_bytes(payload: research_spec.JsonObject) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def test_legacy_direct_envelopes_remain_byte_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    jobs = _jobs(client)
    monkeypatch.setattr(
        jobs, "create_research",
        lambda **kwargs: SimpleNamespace(job_id="research-fixed")
    )
    accepted = client.post(
        "/api/research", json={"topic": "TP53", "sources": ["crossref"], "engine": "mock"}
    ).json()

    def busy(**kwargs):
        del kwargs
        raise JobAlreadyRunning("research-busy")

    monkeypatch.setattr(jobs, "create_research", busy)
    busy_body = client.post(
        "/api/research", json={"topic": "TP53", "sources": ["crossref"], "engine": "mock"}
    ).json()
    rejected = client.post(
        "/api/research", json={"topic": "TP53", "sources": ["evilsource"], "engine": "mock"}
    ).json()
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    offline = client.post(
        "/api/research", json={"topic": "TP53", "sources": ["crossref"], "engine": "mock"}
    ).json()

    assert _stable_bytes(accepted) == (
        b'{"job_id":"research-fixed","ok":true,"status":"running"}'
    )
    assert _stable_bytes(busy_body) == (
        b'{"detail":"research run research-busy is still going; cancel it or wait '
        b'for it to finish","error_kind":"busy","job_id":"research-busy","ok":false}'
    )
    assert _stable_bytes(rejected) == (
        b"{\"detail\":\"paper source 'evilsource' is not on the allowlist "
        b"(allowed: ['arxiv', 'biorxiv', 'clinicaltrials', 'core', 'crossref', "
        b"'elsevier', 'europepmc', 'openalex', 'pubmed', 'searxng', "
        b"'semanticscholar', 'springer'])\",\"error_kind\":\"rejected\","
        b"\"ok\":false}"
    )
    assert _stable_bytes(offline) == (
        b'{"detail":"offline mode (ONTOLOGYLAB_OFFLINE) blocks network collection; '
        b'unset it to run a research topic","error_kind":"offline","ok":false}'
    )


def test_invalid_classifier_ambiguity_fails_closed() -> None:
    classified = anyio.run(
        intent_module.classify,
        "research TP53",
        _ClassifierEngine("invented"),
    )

    assert classified.action == "research"
    assert classified.interaction_decision is research_spec.InteractionDecision.ABSTAIN
    assert classified.error


def test_nonresearch_classifier_payload_is_unchanged() -> None:
    class StatusEngine:
        async def generate(self, prompt, *, model=None):
            del prompt, model
            return json.dumps(
                {
                    "action": "status",
                    "reading": "status",
                    "ambiguity_kind": "unsafe_request",
                }
            ), {}

    classified = anyio.run(
        intent_module.classify, "status", StatusEngine()
    )

    assert classified.as_dict() == {
        "action": "status",
        "params": {},
        "reading": "status",
        "needs_confirmation": False,
    }


def _planner_reading(goal: str) -> PlannerReading:
    need = research_spec.build_evidence_need(
        research_spec.EvidenceNeedDraft(
            research_spec.EvidenceNeedKind.GENERAL,
            goal,
            True,
            research_spec.ContentClass.ABSTRACT,
        )
    )
    return PlannerReading(goal, (need,), (), (), None)


def test_start_input_normalizes_topic_to_nfc_collapsed_whitespace() -> None:
    # Given: a topic with decomposed Unicode and mixed whitespace
    decomposed = "  Cafe\u0301\n yield  "

    # When: the server-owned start type parses the topic
    start_input = schemas.ResearchStartInput(
        topic=decomposed,
        origin=research_spec.ResearchOrigin.DIRECT_API,
        interaction_policy=research_spec.InteractionPolicy.NEVER,
        interaction_decision=research_spec.InteractionDecision.EXECUTE,
        controls=execution_controls(),
    )

    # Then: the stored topic is NFC and internally whitespace-collapsed
    assert start_input.topic == "Caf\u00e9 yield"
    assert start_input.topic != decomposed
    assert "Cafe\u0301" not in start_input.topic


@pytest.mark.parametrize(
    ("origin", "policy"),
    [
        (
            research_spec.ResearchOrigin.CHAT,
            research_spec.InteractionPolicy.NEVER,
        ),
        (
            research_spec.ResearchOrigin.DIRECT_API,
            research_spec.InteractionPolicy.CHAT_SELECTIVE,
        ),
    ],
)
def test_start_input_rejects_origin_policy_mismatch(origin, policy) -> None:
    # Given: an origin paired with a policy that origin forbids

    # When: the server-owned start type is constructed with that pair
    with pytest.raises(research_spec.ResearchSpecParseError) as raised:
        schemas.ResearchStartInput(
            topic="TP53",
            origin=origin,
            interaction_policy=policy,
            interaction_decision=research_spec.InteractionDecision.EXECUTE,
            controls=execution_controls(),
        )

    # Then: the typed parse error names the origin-policy mismatch
    assert raised.value.path == "$.interaction_policy"
    assert raised.value.code == "origin_policy_mismatch"


def test_build_research_start_input_preserves_every_execution_control() -> None:
    # Given: every execution control differs from the HTTP request fallback
    expected = execution_controls({"engine": "api:nonfallback-contract"})
    expected_payload = expected.to_json_value()
    fallback_payload = schemas.ResearchRequest.model_validate(
        {"topic": "fallback"}
    ).model_dump(exclude={"topic"})
    assert set(expected_payload) == set(fallback_payload)
    assert set(expected_payload) == set(
        research_spec.ResearchExecutionControls.field_names()
    )
    assert all(
        expected_payload[name] != fallback_payload[name]
        for name in expected_payload
    )

    # When: the server-owned builder materializes a start input
    start_input = schemas.build_research_start_input(
        topic="TP53",
        origin=research_spec.ResearchOrigin.DIRECT_API,
        interaction_decision=research_spec.InteractionDecision.EXECUTE,
        sources=expected.sources,
        limit=expected.limit,
        max_queries=expected.max_queries,
        fulltext=expected.fulltext,
        citation_expansion=expected.citation_expansion,
        citation_seed_count=expected.citation_seed_count,
        citation_limit=expected.citation_limit,
        engine=expected.engine,
        model=expected.model,
        max_engine_calls=expected.max_engine_calls,
        time_budget=expected.time_budget,
        seed=expected.seed,
    )

    # Then: every control field is preserved as supplied
    assert start_input.controls.to_json_value() == expected_payload


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (research_spec.InteractionDecision.EXECUTE, True),
        (research_spec.InteractionDecision.DECOMPOSE, True),
        (research_spec.InteractionDecision.CLARIFY, False),
        (research_spec.InteractionDecision.ABSTAIN, False),
    ],
)
def test_starts_job_follows_authorized_interaction_decisions(
    decision, expected: bool
) -> None:
    # Given: a start input for a chat origin with a specific decision

    # When: the server-owned type reports whether a job may start
    start_input = build_start_input(
        topic="TP53",
        origin=research_spec.ResearchOrigin.CHAT,
        decision=decision,
    )

    # Then: only execute/decompose authorize a job
    assert start_input.starts_job is expected


def test_authorized_start_input_compiles_to_stable_spec_identity() -> None:
    # Given: an authorized start input and a planner reading
    origin = research_spec.ResearchOrigin.DIRECT_API
    start_input = build_start_input(
        topic="TP53",
        origin=origin,
        decision=research_spec.InteractionDecision.EXECUTE,
    )
    reading = _planner_reading("TP53 yield")
    expected = research_spec.build_research_spec(
        research_spec.ResearchSpecDraft(
            schema_version="research-spec-v1",
            parent_spec_id=None,
            origin=origin,
            goal=reading.goal,
            explicit_constraints=(),
            evidence_needs=reading.evidence_needs,
            assumptions=reading.assumptions,
            interaction_policy=research_spec.InteractionPolicy.for_origin(
                origin
            ),
            source_eligibility_policy=research_spec.SourceEligibilityPolicy(),
        )
    )

    # When: the server-owned type compiles the reading twice
    first = start_input.compile(reading)
    second = start_input.compile(reading)

    # Then: both compiles match the independent spec identity
    assert first == expected
    assert second == first
    assert first.spec_id == expected.spec_id


def test_http_and_domain_research_start_input_are_the_same_object() -> None:
    # Given: the domain module and the HTTP schema re-export
    import ontologylab.research_run_types as domain
    from ontologylab.server import schemas as http_schemas

    reading = _planner_reading("TP53 yield")
    start_input = build_start_input(
        topic="TP53",
        origin=research_spec.ResearchOrigin.DIRECT_API,
        decision=research_spec.InteractionDecision.EXECUTE,
    )

    # When: both import paths compile that start input
    domain_spec = domain.ResearchStartInput.compile(start_input, reading)
    http_spec = http_schemas.ResearchStartInput.compile(start_input, reading)

    # Then: HTTP and domain names are the same objects and compile identically
    assert domain.ResearchStartInput is http_schemas.ResearchStartInput
    assert domain.build_research_start_input is http_schemas.build_research_start_input
    assert domain.ResearchStartInput.__module__ == "ontologylab.research_run_types"
    assert domain_spec == http_spec
    assert domain_spec.spec_id == http_spec.spec_id
