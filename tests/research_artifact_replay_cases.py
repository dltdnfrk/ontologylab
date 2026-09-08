from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontologylab import research_plan as research_plan_module
from ontologylab.provenance import Provenance
from ontologylab.research_artifacts import (
    ResearchArtifactError,
    ResearchArtifactStore,
)
from ontologylab.research_plan import PlanSnapshot
from tests.research_artifact_fixtures import (
    broadened_plan,
    initial_plan,
    research_spec,
)


def test_replay_uses_canonical_parsers_and_minimal_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    provenance = Provenance(str(job_dir), seed=9)
    store = ResearchArtifactStore(job_dir, provenance)
    spec = research_spec()
    root = initial_plan(spec)
    successor = broadened_plan(root, spec.evidence_needs[0].need_id)
    store.write_spec(spec)
    store.write_plan(root)
    store.write_plan(successor)
    store.write_acquisition(successor, {"recommendation": "extract"})
    calls = 0
    real_parser = research_plan_module.parse_canonical_plan

    def counting_parser(raw: str | bytes) -> PlanSnapshot:
        nonlocal calls
        calls += 1
        return real_parser(raw)

    monkeypatch.setattr(
        research_plan_module,
        "parse_canonical_plan",
        counting_parser,
    )
    replay = store.load()
    records = [
        json.loads(line)
        for line in (job_dir / "provenance.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert calls == 2
    assert replay.spec == spec
    assert replay.plans == (root, successor)
    assert replay.root_hash.startswith("sha256:")
    assert all("payload" not in record["payload"] for record in records)
    assert all(
        set(record["payload"])
        <= {
            "artifact_kind",
            "artifact_id",
            "content_hash",
            "filename",
            "plan_id",
            "plan_version",
            "spec_id",
        }
        for record in records
    )


def test_replay_rejects_bound_assessment_hash_mismatch(
    tmp_path: Path,
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    store = ResearchArtifactStore(job_dir)
    spec = research_spec()
    plan = initial_plan(spec)
    store.write_spec(spec)
    store.write_plan(plan)
    pointer = store.write_acquisition(plan, {"recommendation": "extract"})
    value = json.loads(pointer.path.read_bytes())
    value["artifact_id"] = "sha256:" + "0" * 64
    pointer.path.write_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    pointer.path.chmod(0o600)

    with pytest.raises(ResearchArtifactError) as caught:
        store.load()

    assert caught.value.code == "invalid_hash"
