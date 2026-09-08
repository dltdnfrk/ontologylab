from __future__ import annotations

import os
import stat
import threading
from pathlib import Path

import pytest

from ontologylab import research_spec as research_spec_module
from ontologylab.provenance import Provenance
from ontologylab.research_artifacts import (
    ResearchArtifactError,
    ResearchArtifactStore,
)
from ontologylab.research_spec import (
    ResearchSpec,
    ResearchSpecDraft,
    build_research_spec,
)
from tests import research_artifact_replay_cases as replay_cases
from tests.research_artifact_fixtures import initial_plan, research_spec

test_replay_rejects_bound_assessment_hash_mismatch = (
    replay_cases.test_replay_rejects_bound_assessment_hash_mismatch
)
test_replay_uses_canonical_parsers_and_minimal_provenance = (
    replay_cases.test_replay_uses_canonical_parsers_and_minimal_provenance
)


def test_first_creation_is_atomic_owner_only_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    provenance = Provenance(str(job_dir), seed=7)
    store = ResearchArtifactStore(job_dir, provenance)
    spec = research_spec()
    plan = initial_plan(spec)
    events: list[str] = []
    real_fsync, real_link = os.fsync, os.link

    def recording_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        events.append("directory-fsync" if stat.S_ISDIR(mode) else "file-fsync")
        real_fsync(descriptor)

    def recording_link(source: Path, target: Path) -> None:
        events.append("link")
        real_link(source, target)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "link", recording_link)

    store.write_spec(spec)
    store.write_plan(plan)
    store.write_acquisition(plan, {"recommendation": "extract"})
    store.write_post_extraction(plan, {"support_state": "receipt_linked"})
    names = (
        "research-spec.json",
        "research-plan-0001.json",
        "research-acquisition-0001.json",
        "post-extraction-assessment.json",
    )
    before = {name: (job_dir / name).read_bytes() for name in names}
    store.write_spec(spec)

    assert before == {name: (job_dir / name).read_bytes() for name in names}
    assert all(stat.S_IMODE((job_dir / name).stat().st_mode) == 0o600 for name in before)
    assert events.index("file-fsync") < events.index("link") < events.index("directory-fsync")
    assert not tuple(job_dir.glob(".*.research-artifact-*.tmp"))


def test_existing_same_id_with_different_bytes_fails_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    store = ResearchArtifactStore(job_dir)
    spec = research_spec()
    path = store.write_spec(spec).path
    original = path.read_bytes()
    monkeypatch.setattr(
        research_spec_module,
        "canonical_research_spec",
        lambda _spec: original + b"\n",
    )

    with pytest.raises(ResearchArtifactError) as caught:
        store.write_spec(spec)

    assert caught.value.code == "conflicting_bytes"
    assert path.read_bytes() == original
    assert not tuple(job_dir.glob(".*.research-artifact-*.tmp"))


def test_concurrent_conflicting_first_publish_is_no_clobber(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    first = research_spec()
    second = build_research_spec(
        ResearchSpecDraft(
            first.schema_version,
            first.parent_spec_id,
            first.origin,
            first.goal + " alternate",
            first.explicit_constraints,
            first.evidence_needs,
            first.assumptions,
            first.interaction_policy,
            first.source_eligibility_policy,
        )
    )
    publish_barrier = threading.Barrier(2)
    real_replace = os.replace

    def racing_replace(source: Path, target: Path) -> None:
        publish_barrier.wait(timeout=2)
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", racing_replace)
    successes: list[ResearchSpec] = []
    errors: list[ResearchArtifactError] = []

    def publish(spec: ResearchSpec) -> None:
        try:
            ResearchArtifactStore(job_dir).write_spec(spec)
            successes.append(spec)
        except ResearchArtifactError as error:
            errors.append(error)

    workers = [
        threading.Thread(target=publish, args=(spec,))
        for spec in (first, second)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)

    assert all(not worker.is_alive() for worker in workers)
    assert len(successes) == 1
    assert [error.code for error in errors] == ["conflicting_bytes"]
    assert (job_dir / "research-spec.json").read_bytes() == (
        research_spec_module.canonical_research_spec(successes[0])
    )


def test_cleanup_removes_only_owned_temps(tmp_path: Path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    store = ResearchArtifactStore(job_dir)
    owned = job_dir / ".research-plan-0001.json.research-artifact-deadbeef.tmp"
    unrelated = job_dir / "notes.tmp"
    owned.write_text("partial", encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")

    assert store.cleanup_owned_temps() == 1
    assert not owned.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
