"""Job status stays honest when only part of an extraction fails."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ontologylab import paths
from ontologylab.engines import EngineError, MockEngine
from ontologylab.extractor import chunk_document, run_extraction
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps
from ontologylab.server import jobs as jobs_module
from ontologylab.server.jobs import JobRegistry

from types import SimpleNamespace


_LONG_TEXT = "The PaymentGateway uses the DatabaseService. " * 800


class _FailSecondChunkOnce:
    def __init__(self) -> None:
        self.inner = MockEngine(seed=0)
        self.calls = 0
        self.failed = False

    async def generate(self, prompt: str, *, model: str | None = None):
        self.calls += 1
        if self.calls == 2 and not self.failed:
            self.failed = True
            raise EngineError("synthetic chunk failure")
        return await self.inner.generate(prompt, model=model)


class _CountingMock:
    def __init__(self) -> None:
        self.inner = MockEngine(seed=0)
        self.calls = 0

    async def generate(self, prompt: str, *, model: str | None = None):
        self.calls += 1
        return await self.inner.generate(prompt, model=model)


def _insert_document(data_dir: Path, text: str = _LONG_TEXT) -> str:
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        doc, _ = store.insert_document(
            source_kind="upload",
            source_uri="file:///partial.txt",
            title="partial",
            raw_text=text,
            content_hash="sha256:partial-chunk-failure",
        )
        return doc.id
    finally:
        store.close()


def _join(job) -> None:
    assert job._thread is not None
    job._thread.join(timeout=30)
    assert not job._thread.is_alive(), "extraction worker did not terminate"


def _create(registry: JobRegistry, doc_id: str):
    return registry.create(
        engine="mock",
        model=None,
        doc_ids=[doc_id],
        max_engine_calls=20,
        time_budget=60.0,
        seed=0,
    )


def test_fully_successful_extraction_job_ends_complete(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    doc_id = _insert_document(
        data_dir, "The PaymentGateway uses the DatabaseService."
    )
    monkeypatch.setattr(jobs_module, "get_engine", lambda *args, **kwargs: MockEngine(0))
    registry = JobRegistry(data_dir)

    job = _create(registry, doc_id)
    _join(job)

    assert job.status == "complete"
    assert job.error is None


def test_engine_factory_failure_is_redacted_and_failed(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    doc_id = _insert_document(data_dir)

    def fail_factory(*args, **kwargs):
        raise EngineError("factory detail must not escape")

    monkeypatch.setattr(jobs_module, "get_engine", fail_factory)
    registry = JobRegistry(data_dir)

    job = _create(registry, doc_id)
    _join(job)

    assert job.status == "failed"
    assert job.error == "extraction engine failed"


def test_partial_chunk_failure_job_status_matches_durable_run(
    tmp_path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    doc_id = _insert_document(data_dir)
    assert len(chunk_document(_LONG_TEXT)) == 4
    engine = _FailSecondChunkOnce()
    monkeypatch.setattr(jobs_module, "get_engine", lambda *args, **kwargs: engine)
    registry = JobRegistry(data_dir)

    job = _create(registry, doc_id)
    _join(job)

    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        run_status = store.conn.execute(
            "SELECT status FROM extraction_runs"
        ).fetchone()["status"]
        chunks = store.conn.execute(
            "SELECT chunk_index, status, error_kind FROM extraction_chunks "
            "ORDER BY chunk_index"
        ).fetchall()
    finally:
        store.close()

    assert job.status != "complete"
    assert job.status == run_status == "failed"
    assert tuple(chunks[1]) == (1, "failed", "engine_error")


def test_off_schema_chunk_output_marks_job_and_run_failed(
    tmp_path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    doc_id = _insert_document(
        data_dir, "The PaymentGateway uses the DatabaseService."
    )

    class _MalformedEngine:
        async def generate(self, prompt: str, *, model: str | None = None):
            return "```json\nnot-json\n```", {"elapsed": 0.0}

    monkeypatch.setattr(
        jobs_module, "get_engine", lambda *args, **kwargs: _MalformedEngine()
    )
    registry = JobRegistry(data_dir)

    job = _create(registry, doc_id)
    _join(job)

    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        durable = store.conn.execute(
            "SELECT status FROM extraction_runs"
        ).fetchone()["status"]
        error_kind = store.conn.execute(
            "SELECT error_kind FROM extraction_chunks"
        ).fetchone()["error_kind"]
    finally:
        store.close()
    assert job.status == durable == "failed"
    assert job.error == "extraction engine failed"
    assert error_kind == "parse_rejected"


def test_retry_only_reinvokes_failed_chunk_without_duplicates(tmp_path) -> None:
    data_dir = tmp_path / "data"
    doc_id = _insert_document(data_dir)
    store = KGStore.open(paths.kg_db_path(data_dir))
    caps = Caps(SimpleNamespace(
        iterations=0, time_budget_s=60.0, max_engine_calls=20
    ))

    async def drive(engine, job_dir: Path) -> None:
        try:
            await run_extraction(
                store,
                engine,
                Provenance(str(job_dir), seed=0),
                caps,
                [doc_id],
                extractor_engine="mock",
                extractor_model=None,
                on_progress=lambda _line: None,
                on_stats=lambda _stats: None,
            )
        except EngineError:
            # The status contract may surface an aggregate chunk failure to
            # the caller; checkpoint behavior is what this test characterizes.
            pass

    first = _FailSecondChunkOnce()
    asyncio.run(drive(first, tmp_path / "first"))
    assert first.calls == 4
    proposals_before = tuple(
        store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("nodes", "edges")
    )

    second = _CountingMock()
    asyncio.run(drive(second, tmp_path / "retry"))

    attempts = [
        row["attempts"]
        for row in store.conn.execute(
            "SELECT attempts FROM extraction_chunks ORDER BY chunk_index"
        )
    ]
    proposals_after = tuple(
        store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("nodes", "edges")
    )
    duplicate_citations = store.conn.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM citations GROUP BY kind, item_id, "
        "source_doc_id, source_span HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    store.close()

    assert second.calls == 1
    assert attempts == [1, 2, 1, 1]
    assert proposals_after == proposals_before
    assert duplicate_citations == 0
