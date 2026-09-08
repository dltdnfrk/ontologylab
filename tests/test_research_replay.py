from __future__ import annotations

import hashlib
import json
import os
import time
import unicodedata
from pathlib import Path

import pytest

from ontologylab import research_run as research_run_module
from ontologylab.research_artifacts import (
    ResearchArtifactError,
    ResearchArtifactStore,
)
from ontologylab.research_plan import (
    canonical_plan_json,
    retry_plan,
)
from ontologylab.server.jobs import Job, JobRegistry
from tests import research_job_replay_cases as job_replay_cases
from tests.research_artifact_fixtures import (
    broadened_plan,
    initial_plan,
    research_spec,
)
from tests.research_contract_fixtures import JsonObject, JsonValue, load_fixture

test_job_pointer_payload_has_no_authoritative_artifact_body = (
    job_replay_cases.test_job_pointer_payload_has_no_authoritative_artifact_body
)
test_worker_broaden_appends_without_mutating_v1_and_persists_lineage_pointer = (
    job_replay_cases.test_worker_broaden_appends_without_mutating_v1_and_persists_lineage_pointer
)

CASES = load_fixture(Path("tests/fixtures/research/crash-replay.jsonl"))


def _canonical(value: JsonObject) -> bytes:
    return unicodedata.normalize(
        "NFC",
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")),
    ).encode()


def _reseal(raw: bytes, identity_field: str, **changes: JsonValue) -> bytes:
    value = json.loads(raw)
    value.update(changes)
    identity = dict(value)
    identity.pop(identity_field)
    value[identity_field] = "sha256:" + hashlib.sha256(_canonical(identity)).hexdigest()
    return _canonical(value)


def _private_write(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    path.chmod(0o600)


def _interrupted_reload(
    data_dir: Path,
    store: ResearchArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    replay = store.load()
    registry = JobRegistry(data_dir)
    job = Job(
        job_id=store.job_dir.name,
        kind="research",
        engine="mock",
        model=None,
        started_ts=time.time(),
        research_pointers=replay.pointers(),
        _registry=registry,
    )
    registry.persist(job)
    network_calls = 0

    async def forbidden_fetch(*args, **kwargs):
        nonlocal network_calls
        del args, kwargs
        network_calls += 1
        raise AssertionError("restart must not resume network work")

    monkeypatch.setattr(research_run_module, "fetch_sources", forbidden_fetch)
    restarted = JobRegistry(data_dir)
    restored = restarted.get(job.job_id)
    assert restored is not None
    assert restored.status == "failed"
    assert restored.error == "interrupted by server restart"
    assert restored._thread is None
    assert restored.research_pointers == replay.pointers()
    assert network_calls == 0
    assert store.load().root_hash == replay.root_hash
    return "interrupted"


def _fixture_text(case: JsonObject, field: str) -> str:
    value = case[field]
    assert isinstance(value, str)
    return value


def _run_case(
    case: JsonObject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    scenario = _fixture_text(case, "scenario")
    data_dir = tmp_path / _fixture_text(case, "id")
    job_dir = data_dir / "jobs" / "research-fixture"
    job_dir.mkdir(parents=True)
    store = ResearchArtifactStore(job_dir)
    spec = research_spec()
    root = initial_plan(spec)
    successor = broadened_plan(root, spec.evidence_needs[0].need_id)
    store.write_spec(spec)
    store.write_plan(root)
    if scenario == "valid_root_reload":
        return "canonical_reload" if store.load().plans == (root,) else "wrong"
    if scenario == "valid_broaden_reload":
        store.write_plan(successor)
    elif scenario == "interrupted_running_job":
        return _interrupted_reload(data_dir, store, monkeypatch)
    elif scenario == "partial_temp_file":
        temp = job_dir / ".research-plan-0002.json.research-artifact-crash.tmp"
        temp.write_bytes(b"{")
        result = "canonical_reload" if store.load().plans == (root,) else "wrong"
        assert not temp.exists()
        return result
    elif scenario == "missing_parent":
        raw = _reseal(
            canonical_plan_json(successor).encode(),
            "plan_id",
            plan_version=2,
            parent_plan_id="sha256:" + "0" * 64,
        )
        _private_write(job_dir / "research-plan-0002.json", raw)
    elif scenario == "version_gap":
        raw = _reseal(
            canonical_plan_json(successor).encode(),
            "plan_id",
            plan_version=3,
            parent_plan_id=root.plan_id,
        )
        _private_write(job_dir / "research-plan-0003.json", raw)
    elif scenario == "stale_spec_hash":
        raw = _reseal(
            (job_dir / "research-plan-0001.json").read_bytes(),
            "plan_id",
            spec_hash="sha256:" + "f" * 64,
        )
        _private_write(job_dir / "research-plan-0001.json", raw)
    elif scenario == "same_id_different_bytes":
        path = job_dir / "research-plan-0001.json"
        _private_write(path, path.read_bytes() + b"\n")
    elif scenario == "duplicate_semantic_execution":
        retry = retry_plan(root)
        raw = _reseal(
            canonical_plan_json(retry).encode(),
            "plan_id",
            retry_of_plan_id=None,
        )
        _private_write(job_dir / "research-plan-0002.json", raw)
    elif scenario == "orphan_successor":
        retry = retry_plan(root)
        os.unlink(job_dir / "research-plan-0001.json")
        _private_write(job_dir / "research-plan-0002.json", canonical_plan_json(retry).encode())
    elif scenario == "stale_assessment":
        store.write_plan(successor)
        pointer = store.write_acquisition(root, {"recommendation": "broaden"})
        raw = _reseal(pointer.path.read_bytes(), "artifact_id", plan_version=2)
        os.unlink(pointer.path)
        _private_write(job_dir / "research-acquisition-0002.json", raw)
    elif scenario == "valid_retry_reload":
        successor = retry_plan(root)
        store.write_plan(successor)
    else:
        raise AssertionError(f"unhandled fixture scenario: {scenario}")
    store.load()
    return "canonical_reload"


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=tuple(_fixture_text(case, "id") for case in CASES),
)
def test_approved_crash_replay_fixture(
    case: JsonObject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_result = case["expected_result"]
    expected_code = case["expected_error_code"]

    if expected_result == "refused":
        with pytest.raises(ResearchArtifactError) as caught:
            _run_case(case, tmp_path, monkeypatch)
        assert caught.value.code == expected_code
    else:
        assert _run_case(case, tmp_path, monkeypatch) == expected_result
