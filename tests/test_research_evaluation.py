from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "research"


def test_complete_matrix_runs_every_approved_fixture_and_reports_dimensions() -> None:
    # Given: the complete approved fixture inventory
    from ontologylab.research_evaluation import evaluate_research_matrix

    # When: the product contracts are evaluated without network access
    report = evaluate_research_matrix(_FIXTURE_DIR)

    # Then: every case is run and each requested dimension remains separate
    assert report.inventory == {
        "controlled_omission": 24,
        "paired_parity": 40,
        "interaction": 60,
        "crash_replay": 12,
        "source_eligibility": 18,
    }
    assert set(report.dimensions) == {
        "false_stop",
        "false_continue",
        "precision_redundancy",
        "marginal_unique_eligible_evidence",
        "contradiction_visibility",
        "cost",
        "latency",
        "boundary_outcomes",
    }
    assert report.dimensions["boundary_outcomes"]["mismatch_case_ids"] == []


def test_matrix_receipt_is_deterministic_and_has_no_composite_claim() -> None:
    # Given: the same immutable fixtures evaluated twice
    from ontologylab.research_evaluation import evaluate_research_matrix

    first = evaluate_research_matrix(_FIXTURE_DIR).canonical_json()
    second = evaluate_research_matrix(_FIXTURE_DIR).canonical_json()

    # Then: receipt bytes are stable and make no threshold/population claim
    assert first == second
    value = json.loads(first)
    forbidden = {
        "composite_score",
        "pass_threshold",
        "representative_population",
    }
    assert forbidden.isdisjoint(value)
    assert all(forbidden.isdisjoint(item) for item in value["dimensions"].values())


def test_matrix_rejects_duplicate_fixture_ids(tmp_path: Path) -> None:
    from ontologylab.research_evaluation import evaluate_research_matrix
    from ontologylab.research_evaluation_fixtures import EvaluationError

    fixture_dir = tmp_path / "research"
    shutil.copytree(_FIXTURE_DIR, fixture_dir)
    path = fixture_dir / "controlled-omission.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    second = json.loads(rows[1])
    second["id"] = first["id"]
    rows[1] = json.dumps(second, sort_keys=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(EvaluationError, match="fixture_duplicate_id"):
        evaluate_research_matrix(fixture_dir)
