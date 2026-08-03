from pathlib import Path

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
HISTORICAL_FIXTURE_COMMIT = "0baab72"


def test_pytest_matrix_checkouts_include_historical_fixture_commit() -> None:
    """Pytest archives a committed fixture, so its checkout needs repository history."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    relevant_jobs = []
    for job_name, job in workflow["jobs"].items():
        matrix = job.get("strategy", {}).get("matrix", {})
        steps = job.get("steps", [])
        if "python-version" in matrix and any(
            "pytest" in step.get("run", "") for step in steps
        ):
            relevant_jobs.append((job_name, steps))

    assert relevant_jobs, "expected a Python matrix job that runs pytest"
    for job_name, steps in relevant_jobs:
        checkouts = [
            step
            for step in steps
            if step.get("uses", "").startswith("actions/checkout@")
        ]
        assert checkouts, f"{job_name} must check out the repository"
        for checkout in checkouts:
            assert checkout.get("with", {}).get("fetch-depth") == 0, (
                f"{job_name} checkout must include history for immutable fixture "
                f"commit {HISTORICAL_FIXTURE_COMMIT}"
            )
