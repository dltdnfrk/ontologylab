"""Persisted job corruption is local; live job work remains available."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ontologylab import paths
from ontologylab.kgstore import KGStore
from ontologylab.server import jobs as jobs_module
from ontologylab.server.jobs import Job, JobRegistry


def test_malformed_research_pointer_does_not_block_registry_startup(
    tmp_path: Path,
) -> None:
    store = KGStore.open(paths.kg_db_path(tmp_path))
    store.run_upsert(
        {
            "id": "research-corrupt-pointer",
            "kind": "research",
            "status": "complete",
            "phase": "extract",
            "engine": "mock",
            "model": None,
            "started_ts": time.time(),
            "ask": json.dumps(
                {
                    "schema_version": "research-job-pointers-v1",
                    "ask": "recoverable topic",
                    "research_artifacts": {},
                }
            ),
        }
    )
    store.close()

    registry = JobRegistry(tmp_path)

    recovered = registry.get("research-corrupt-pointer")
    assert recovered is not None
    assert recovered.status == "complete"
    assert recovered.ask is None
    assert recovered.research_pointers is None


def test_best_effort_persist_contains_sqlite_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = JobRegistry(tmp_path)
    job = Job(
        job_id="research-live-after-sqlite-error",
        kind="research",
        engine="mock",
        model=None,
        started_ts=time.time(),
        _registry=registry,
    )

    def fail_open(_cls, _path):
        raise sqlite3.OperationalError("database is busy")

    monkeypatch.setattr(
        jobs_module.KGStore,
        "open",
        classmethod(fail_open),
    )

    registry.persist(job)

    assert job.status == "running"
    assert job.persisted is False
