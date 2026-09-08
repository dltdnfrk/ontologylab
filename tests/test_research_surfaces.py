from __future__ import annotations

import json
import stat
from pathlib import Path

from tests import research_corpus_surface_case as corpus_surface_case
from tests.research_surface_fixtures import _research_surface

test_corpus_summary_keeps_full_acquisition_detail = (
    corpus_surface_case.test_corpus_summary_keeps_full_acquisition_detail
)


def test_job_list_detail_and_reopen_expose_only_compact_research_summary(
    tmp_path: Path,
) -> None:
    # Given: owner-only canonical research artifacts and a reopened registry
    client, job_id, _acquisition, job_dir = _research_surface(
        tmp_path, degraded=False, partial=True
    )

    # When: list and detail serialize the persisted job
    listed = client.get("/api/jobs").json()["jobs"][0]
    detail = client.get(f"/api/jobs/{job_id}").json()

    # Then: compact machine fields survive reopen without exposing full records
    assert listed["research_summary"] == detail["research_summary"]
    summary = detail["research_summary"]
    assert set(summary) == {
        "spec_id",
        "current_plan_id",
        "acquisition_assessment_id",
        "post_extraction_assessment_id",
        "goal",
        "evidence_needs",
        "assumptions",
        "current_plan_version",
        "parent_plan_id",
        "degraded_reason",
        "need_occupancy",
        "recommendation",
        "stop_reason",
        "post_extraction_counts",
    }
    assert summary["goal"].startswith("surface")
    assert summary["degraded_reason"] is None
    assert summary["recommendation"] == "extract"
    assert summary["stop_reason"] == "budget_exhausted"
    assert any(
        item["mandatory"] and not item["occupied"]
        for item in summary["need_occupancy"]
    )
    assert summary["post_extraction_counts"] == {
        "support": {
            "not_assessed": 0,
            "receipt_linked": 1,
            "receipt_missing": 0,
        },
        "contradiction": {
            "not_assessed": 0,
            "not_observed": 0,
            "potential_conflict": 1,
        },
    }
    encoded = json.dumps(detail, sort_keys=True)
    assert all(
        field not in encoded
        for field in ("direct_overrides", "source_failures", "records", "axes")
    )
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in job_dir.glob("research-*.json")
    )


def test_degraded_reason_and_partial_stop_are_visible_without_status_drift(
    tmp_path: Path,
) -> None:
    # Given: a raw-topic fallback with usable but incomplete evidence
    client, job_id, _acquisition, _job_dir = _research_surface(
        tmp_path, degraded=True, partial=True
    )

    # When: the job detail is read
    detail = client.get(f"/api/jobs/{job_id}").json()

    # Then: reasoning is additive and the legacy status vocabulary is unchanged
    assert detail["status"] == "complete"
    assert detail["phase"] == "extract"
    assert detail["research_summary"]["degraded_reason"] == "invalid_output"
    assert detail["research_summary"]["stop_reason"] == "budget_exhausted"


def test_corrupt_artifact_is_visible_without_status_vocabulary_drift(
    tmp_path: Path,
) -> None:
    client, job_id, _acquisition, job_dir = _research_surface(
        tmp_path, degraded=False, partial=True
    )
    path = job_dir / "research-acquisition-0001.json"
    path.write_bytes(b"{")
    path.chmod(0o600)

    detail = client.get(f"/api/jobs/{job_id}").json()

    assert detail["status"] == "complete"
    assert detail["research_summary"] is None
    assert detail["research_summary_error"] == "artifact_unavailable"
