"""Typed ingestion evidence errors survive resource scopes and retain diagnostics."""

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess

import pytest

from ontologylab import release_mutation_evidence as mutation
from tests.wave21.ingest_perf import PerformanceScratchRootError


@contextmanager
def _resource_scope():
    yield


@pytest.mark.parametrize("kind", ["scratch", "mutation"])
def test_typed_evidence_error_survives_contextmanager_traceback(kind: str) -> None:
    error = (
        PerformanceScratchRootError(Path("/not-an-admitted-scratch"))
        if kind == "scratch"
        else mutation.MutationGenerationError("observation.json")
    )
    with pytest.raises(type(error)) as caught:
        with _resource_scope():
            raise error
    assert caught.value is error
    assert error.__traceback__ is not None


def test_observation_json_failure_retains_bounded_child_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 17, stdout="", stderr="x" * 6000 + "\nprivate-child-marker",
        )

    monkeypatch.setattr(mutation.subprocess, "run", failed)
    with pytest.raises(mutation.MutationGenerationError) as caught:
        mutation._run_observation(tmp_path, tmp_path / "work")
    error = caught.value
    assert error.member == "observation.json"
    assert error.exit_code == 17
    assert error.stderr.endswith("private-child-marker")
    assert len(error.stderr) <= 4096
    assert "private-child-marker" not in str(error)
    assert "private-child-marker" not in repr(error)


def test_valid_nonzero_mutant_observation_is_not_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "schema": "ontologylab.ingestion-mutation-observation.v1",
        "finalizations": 76,
        "p95_ms": 1.0,
        "outputs": {
            "create": {"entries": 38, "created": 38, "conflicts": 2, "failures": 0},
            "duplicate": {"entries": 38, "created": 0, "conflicts": 2, "failures": 0},
        },
    }

    def expected_mutant(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(mutation.subprocess, "run", expected_mutant)
    observed = mutation._run_observation(tmp_path, tmp_path / "work")
    assert observed.exit_code == 1
    assert observed.finalizations == 76
