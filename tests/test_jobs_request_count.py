"""Terminal job accounting must agree with the append-only request log."""

from __future__ import annotations

import json

import pytest

from ontologylab import extractor
from ontologylab.engines import EngineError, MockEngine
from ontologylab.server import jobs
from tests.test_partial_chunk_failure import _insert_document, _join


@pytest.mark.parametrize(
    "failure, cap, expected_status, expected_calls",
    [
        (RuntimeError, 0, "failed", 2),
        (EngineError, 0, "failed", 2),
        (None, 1, "partial", 1),
        (None, 0, "complete", 2),
    ],
)
def test_terminal_job_request_count_matches_provenance(
    tmp_path, monkeypatch, failure, cap, expected_status, expected_calls,
):
    # Given a real worker and store, with only the external engine scripted.
    text = "The PaymentGateway uses the DatabaseService."
    data_dir = tmp_path / "data"
    doc_id = _insert_document(data_dir, text + text)
    monkeypatch.setattr(extractor, "chunk_document", lambda raw: [
        extractor.Chunk(0, 0, raw[:len(text)]),
        extractor.Chunk(1, len(text), raw[len(text):]),
    ])

    class ScriptedEngine:
        calls = 0

        async def generate(self, prompt, *, model=None):
            self.calls += 1
            if self.calls == 2 and failure is not None:
                raise failure("scripted second-request failure")
            return await MockEngine().generate(prompt, model=model)

    engine = ScriptedEngine()
    monkeypatch.setattr(jobs, "resolve_engine", lambda *args, **kwargs: engine)
    registry = jobs.JobRegistry(data_dir)

    # When the worker reaches its actual terminal transition.
    job = registry.create(
        engine="mock", model=None, doc_ids=[doc_id],
        max_engine_calls=cap, time_budget=0, seed=7,
    )
    _join(job)

    # Then status retains every attempted request, even the throwing call.
    job_dir = data_dir / "jobs" / job.job_id
    records = [
        json.loads(line)
        for line in (job_dir / "provenance.jsonl").read_text().splitlines()
    ]
    calls = [row for row in records if row["payload"].get("engine_call")]
    status = json.loads((job_dir / "status.json").read_text())
    assert job.as_status()["status"] == expected_status
    assert job.totals["nodes_new"] > 0
    assert status["engine_calls"] == len(calls) == engine.calls == expected_calls
    assert status["seed"] == 7
    assert status["log_entries"] == len(records)
    assert status["per_step"]["extract"]["calls"] == expected_calls
    assert status["engine_elapsed_s"] == pytest.approx(
        sum(row["payload"]["elapsed_s"] for row in calls)
    )
    if failure is RuntimeError:
        assert records[-1]["step"] == status["last_step"] == "job.failed"
        assert records[-1]["payload"]["type"] == "RuntimeError"
