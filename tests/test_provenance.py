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
