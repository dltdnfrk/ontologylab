"""Existing run-level Provenance JSONL logger (not the SQLite outbox)."""

from __future__ import annotations

import json
from pathlib import Path

from ontologylab.provenance import Provenance


def test_run_logger_appends_one_json_line(tmp_path: Path) -> None:
    provenance = Provenance(str(tmp_path / "run"), seed=7)
    provenance.log("collect.end", {"documents": 1})
    path = tmp_path / "run" / "provenance.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["step"] == "collect.end"
    assert record["seed"] == 7
    assert record["payload"]["documents"] == 1


def test_run_logger_rewrites_status_snapshot(tmp_path: Path) -> None:
    provenance = Provenance(str(tmp_path / "run"), seed=3)
    provenance.log("collect.doc", {"doc_id": "d1"})
    status = json.loads((tmp_path / "run" / "status.json").read_text(encoding="utf-8"))
    assert status["seed"] == 3
    assert status["log_entries"] == 1
    assert status["last_step"] == "collect.doc"


def test_resume_uses_log_instead_of_reset_status(tmp_path: Path) -> None:
    # Given a prior writer's real calls and the historical zero-count snapshot.
    run_dir = str(tmp_path / "run")
    original = Provenance(run_dir, seed=7)
    original.log("extract.start")
    original.track_engine_call("extract", 1.25)
    original.track_engine_call("critic", 0.5)
    Provenance(run_dir, seed=0).log("job.failed", {"type": "RuntimeError"})
    before = original.jsonl_path.read_bytes()

    # When a terminal writer resumes, it appends without replaying events.
    resumed = Provenance.resume(run_dir, seed=0)
    assert original.jsonl_path.read_bytes() == before
    resumed.log("job.failed", {"type": "OSError"})

    # Then all usage comes from the log, not the stale snapshot.
    assert original.jsonl_path.read_bytes().startswith(before)
    status = json.loads(original.status_path.read_text())
    assert status["engine_calls"] == 2
    assert status["engine_elapsed_s"] == 1.75
    assert status["seed"] == 7
    assert status["log_entries"] == 5
    assert status["per_step"]["extract"]["calls"] == 1
    assert status["per_step"]["critic"]["calls"] == 1
    assert status["per_step"]["job.failed"]["log_entries"] == 2


def test_resume_before_first_event_keeps_zero_usage(tmp_path: Path) -> None:
    resumed = Provenance.resume(str(tmp_path / "run"), seed=9)
    resumed.log("job.failed", {"type": "EngineError"})
    status = json.loads(resumed.status_path.read_text())
    assert status["engine_calls"] == 0
    assert status["seed"] == 9
    assert status["log_entries"] == 1
