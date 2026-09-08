from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab import research_run as research_run_module
from ontologylab.kgstore import KGStore
from ontologylab.literature import formulate_scholarly_queries
from ontologylab.server.app import create_app
from ontologylab.server.jobs import TERMINAL_STATUSES, Job
from ontologylab.server.schemas import ResearchRequest
from tests.research_contract_fixtures import (
    FixtureValidationError,
    JsonValue,
    build_inventory,
)
from tests.research_contract_fixtures import main as fixture_main
from tests.test_research_run import _fake_fetch, _paper

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "research"


def test_fixture_inventory_has_approved_contract_counts() -> None:
    # Given: the approved research contract fixture directory
    # When: its deterministic inventory is built
    inventory = build_inventory(_FIXTURE_DIR)

    # Then: every fixture has its approved exact cardinality
    assert inventory.counts == {
        "chat-direct-parity.jsonl": 40,
        "controlled-omission.jsonl": 24,
        "crash-replay.jsonl": 12,
        "interaction-policy.jsonl": 60,
        "source-eligibility.jsonl": 18,
    }


def test_fixture_inventory_hashes_current_bytes() -> None:
    # Given: the current fixture bytes
    inventory = build_inventory(_FIXTURE_DIR)

    # When: each reported hash is independently recomputed
    actual = {item.name: item.sha256 for item in inventory.files}
    expected = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _FIXTURE_DIR.glob("*.jsonl")
    }

    # Then: no stale or derived hash is reported
    assert actual == expected


def test_fixture_validator_reports_duplicate_id_and_illegal_expected_value(
    tmp_path: Path,
) -> None:
    # Given: a disposable fixture copy with two independent row defects
    copied = tmp_path / "research"
    shutil.copytree(_FIXTURE_DIR, copied)
    path = copied / "controlled-omission.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[1]["id"] = rows[0]["id"]
    rows[2]["expected_recommendation"] = "illegal"
    path.write_text(
        "".join(
            f"{json.dumps(row, sort_keys=True, separators=(',', ':'))}\n"
            for row in rows
        ),
        encoding="utf-8",
    )

    # When: the copied contract is validated
    with pytest.raises(FixtureValidationError) as raised:
        build_inventory(copied)

    # Then: diagnostics identify typed fields and exact rows
    locations = {
        (issue.path.name, issue.row, issue.field, issue.code)
        for issue in raised.value.issues
    }
    assert (path.name, 2, "id", "duplicate_id") in locations
    assert (
        path.name,
        3,
        "expected_recommendation",
        "invalid_enum",
    ) in locations


def test_fixture_validator_rejects_duplicate_id_across_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: an ID from controlled omissions copied into another fixture
    copied = tmp_path / "research"
    shutil.copytree(_FIXTURE_DIR, copied)
    path = copied / "source-eligibility.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["id"] = "omission-01"
    path.write_text(
        "".join(
            f"{json.dumps(row, sort_keys=True, separators=(',', ':'))}\n"
            for row in rows
        ),
        encoding="utf-8",
    )

    # When: the CLI boundary validates the copied inventory
    exit_code = fixture_main([str(copied)])
    output = capsys.readouterr()

    # Then: the second global occurrence is located and refused
    assert exit_code == 2
    assert output.out == ""
    assert f"{path}:1:id: duplicate_id" in output.err.splitlines()


def test_fixture_validator_rejects_unapproved_inventory_entry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: a copied inventory containing an unapproved JSONL file
    copied = tmp_path / "research"
    shutil.copytree(_FIXTURE_DIR, copied)
    path = copied / "unapproved.jsonl"
    path.write_text("{}\n", encoding="utf-8")

    # When: the CLI boundary validates the copied inventory
    exit_code = fixture_main([str(copied)])
    output = capsys.readouterr()

    # Then: exact membership rejects the unexpected file
    assert exit_code == 2
    assert output.out == ""
    assert f"{path}:0:$: unexpected_file" in output.err.splitlines()


def test_direct_research_preserves_controls_and_accepted_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a direct request with every control distinct from its default
    app = create_app(data_dir=tmp_path / "data")
    captured: dict[str, JsonValue] = {}

    def accept(**parameters: JsonValue) -> Job:
        captured.update(parameters)
        return Job(
            job_id="research-contract",
            kind="research",
            engine="mock",
            model="contract-model",
            started_ts=0.0,
        )

    monkeypatch.delenv("ONTOLOGYLAB_OFFLINE", raising=False)
    monkeypatch.setattr(app.state.jobs, "create_research", accept)
    client = TestClient(app)
    request = {
        "topic": "contract topic",
        "sources": ["crossref"],
        "limit": 7,
        "max_queries": 2,
        "fulltext": False,
        "citation_expansion": False,
        "citation_seed_count": 1,
        "citation_limit": 9,
        "engine": "mock",
        "model": "contract-model",
        "max_engine_calls": 3,
        "time_budget": 45.0,
        "seed": 17,
    }

    # When: direct Research is accepted
    response = client.post("/api/research", json=request)

    # Then: the envelope and worker controls retain their legacy fields
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "job_id": "research-contract",
        "status": "running",
    }
    start_input = captured.pop("start_input")
    assert start_input.topic == request["topic"]
    assert start_input.controls.to_json_value() == {
        key: value for key, value in request.items() if key != "topic"
    }
    assert not captured


def test_direct_research_keeps_typed_refusal_envelope(
    tmp_path: Path,
) -> None:
    # Given: a direct request rejected by the source gate
    client = TestClient(create_app(data_dir=tmp_path / "data"))

    # When: the request crosses the route boundary
    response = client.post(
        "/api/research",
        json={"topic": "contract topic", "sources": ["not-a-source"]},
    )
    body = response.json()

    # Then: refusal stays synchronous and typed without a job envelope
    assert response.status_code == 200
    assert set(body) == {"ok", "error_kind", "detail"}
    assert body["ok"] is False
    assert body["error_kind"] == "rejected"


def test_research_status_and_phase_vocabularies_remain_separate() -> None:
    # Given: the legacy job state machine
    job = Job(
        job_id="research-contract",
        kind="research",
        engine="mock",
        model=None,
        started_ts=0.0,
    )

    # When: its machine-consumed status snapshot is read
    status = job.as_status()

    # Then: phase is not encoded as another terminal status
    assert TERMINAL_STATUSES == frozenset({"complete", "failed", "cancelled"})
    assert status["status"] == "running"
    assert status["phase"] == ""


def test_raw_topic_fallback_is_distinguishable_in_usage() -> None:
    # Given: no query-planning engine
    topic = "raw contract topic"

    # When: scholarly query formulation fails open
    queries, usage = anyio.run(formulate_scholarly_queries, topic, None)

    # Then: the raw axis and degraded usage remain machine-distinguishable
    assert [(query.query, query.axis) for query in queries] == [(topic, "topic")]
    assert isinstance(usage.get("error"), str)


def test_research_request_status_vocabulary_has_no_hidden_job_state() -> None:
    # Given: the direct boundary model's complete control set
    fields = set(ResearchRequest.model_fields)

    # When: compared with status-bearing concepts
    # Then: controls do not smuggle a second job/status field into Research
    assert "status" not in fields
    assert "phase" not in fields


def test_research_extraction_leaves_human_review_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one locally faked collected paper
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/authority")])]),
    )
    app = create_app(data_dir=data_dir)
    client = TestClient(app)

    # When: Research completes extraction through its real worker boundary
    started = client.post(
        "/api/research",
        json={
            "topic": "authority contract",
            "sources": ["crossref"],
            "engine": "mock",
            "fulltext": False,
            "citation_expansion": False,
        },
    ).json()
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)
    assert not job._thread.is_alive()

    # Then: extracted facts remain proposals for explicit human review
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        statuses = {
            str(row[0])
            for table in ("nodes", "edges")
            for row in store.conn.execute(f"SELECT status FROM {table}").fetchall()
        }
    finally:
        store.close()
    assert statuses == {"proposed"}
