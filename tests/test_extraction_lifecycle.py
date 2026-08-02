"""Durable extraction checkpoints prevent partial retries duplicating work.

The defect had three plausible causes: the document-level ``unprocessed``
query hides a document as soon as chunk zero writes one node; no per-chunk
checkpoint tells an explicit retry which chunks succeeded; and proposal
writes commit independently of any checkpoint, leaving a crash window where
the write survives but the success marker does not.  This regression crosses
all three seams through the shared extraction loop and a reopened database.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest
from types import SimpleNamespace

from ontologylab import paths
from ontologylab.engines import MockEngine
from ontologylab.extraction_state import ExtractionState, recover_running_once
from ontologylab.extractor import chunk_document, run_extraction
from ontologylab.kgstore import KGStore
from ontologylab.server import jobs as jobs_module
from ontologylab.server.jobs import Job, JobRegistry
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps


class _CountingMock:
    def __init__(self) -> None:
        self.inner = MockEngine(seed=0)
        self.calls = 0

    async def generate(self, prompt: str, *, model: str | None = None):
        self.calls += 1
        return await self.inner.generate(prompt, model=model)


def _caps(max_calls: int = 0) -> Caps:
    return Caps(SimpleNamespace(
        iterations=0, time_budget_s=0.0, max_engine_calls=max_calls,
    ))


def _drive(
    store: KGStore, engine, doc_id: str, job: Path, max_calls: int = 0, **kwargs,
):
    return asyncio.run(run_extraction(
        store,
        engine,
        Provenance(str(job), seed=0),
        _caps(max_calls),
        [doc_id],
        extractor_engine="mock",
        extractor_model=None,
        on_progress=lambda _line: None,
        on_stats=lambda _stats: None,
        **kwargs,
    ))


def test_restart_retries_only_unfinished_chunks_without_duplicate_citations(
    tmp_path,
) -> None:
    text = "The PaymentGateway uses the DatabaseService. " * 900
    db = tmp_path / "kg.sqlite"
    store = KGStore.open(db)
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///long.txt",
        title="long",
        raw_text=text,
        content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
    )
    chunk_count = len(chunk_document(text))
    assert chunk_count > 1

    first = _CountingMock()
    assert "engine call cap reached" in _drive(
        store, first, doc.id, tmp_path / "job-1", max_calls=1,
    )
    assert first.calls == 1
    citation_count = store.conn.execute(
        "SELECT COUNT(*) FROM citations"
    ).fetchone()[0]
    successful_citations = [
        tuple(row) for row in store.conn.execute(
            "SELECT kind, item_id, source_span, COUNT(*) FROM citations "
            "GROUP BY kind, item_id, source_span ORDER BY kind, item_id, source_span"
        )
    ]
    store.close()

    # A new process/app gets a new store and provenance object.  Chunk zero's
    # successful write must remain complete and must not call the engine or
    # append its citations again.
    store = KGStore.open(db)
    second = _CountingMock()
    try:
        assert _drive(store, second, doc.id, tmp_path / "job-2") == ""
        assert second.calls == chunk_count - 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM citations"
        ).fetchone()[0] > citation_count
        resumed_citations = [
            tuple(row) for row in store.conn.execute(
                "SELECT kind, item_id, source_span, COUNT(*) FROM citations "
                "GROUP BY kind, item_id, source_span ORDER BY kind, item_id, source_span"
            )
        ]
        for citation in successful_citations:
            assert citation in resumed_citations

        run = store.conn.execute(
            "SELECT status FROM extraction_runs"
        ).fetchone()
        chunks = store.conn.execute(
            "SELECT status, attempts FROM extraction_chunks ORDER BY chunk_index"
        ).fetchall()
        assert run["status"] == "complete"
        assert [row["status"] for row in chunks] == ["succeeded"] * chunk_count
        assert [row["attempts"] for row in chunks] == [1] * chunk_count
    finally:
        store.close()


def test_effective_provider_default_is_run_identity_and_provenance(
    tmp_path, monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    store = KGStore.open(paths.kg_db_path(data_dir))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///default.txt", title="default",
        raw_text="The PaymentGateway uses the DatabaseService.",
        content_hash="sha256:default-model",
    )
    store.close()

    engine = _CountingMock()
    engine._model = "provider-default-v2"
    monkeypatch.setattr(jobs_module, "get_engine", lambda *args, **kwargs: engine)
    registry = JobRegistry(data_dir)
    job_dir = tmp_path / "job-default-model"
    job = Job(
        job_id=job_dir.name, kind="extract", engine="api:local", model=None,
        started_ts=0.0,
    )

    assert asyncio.run(registry._extract_async(
        job, job_dir, doc_ids=[doc.id], max_engine_calls=10,
        time_budget=60.0, seed=0,
    )) == ""

    engine._model = "provider-default-v3"
    second_job_dir = tmp_path / "job-new-default-model"
    second_job = Job(
        job_id=second_job_dir.name, kind="extract", engine="api:local",
        model=None, started_ts=0.0,
    )
    assert asyncio.run(registry._extract_async(
        second_job, second_job_dir, doc_ids=[doc.id], max_engine_calls=10,
        time_budget=60.0, seed=0,
    )) == ""

    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        assert {
            row["extractor_model"] for row in store.conn.execute(
                "SELECT extractor_model FROM extraction_runs"
            )
        } == {"provider-default-v2", "provider-default-v3"}
        assert "" not in {
            row["extractor_model"] or "" for row in store.conn.execute(
                "SELECT extractor_model FROM nodes"
            )
        }
    finally:
        store.close()
    provenance = (job_dir / "provenance.jsonl").read_text(encoding="utf-8")
    assert '"model": "provider-default-v2"' in provenance
    second_provenance = (
        second_job_dir / "provenance.jsonl"
    ).read_text(encoding="utf-8")
    assert '"model": "provider-default-v3"' in second_provenance


def test_competing_lifecycle_cannot_steal_or_finish_live_run(tmp_path) -> None:
    store = KGStore.open(tmp_path / "ownership.sqlite")
    text = "The PaymentGateway uses the DatabaseService. " * 900
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///owned.txt", title="owned",
        raw_text=text, content_hash="sha256:owned",
    )
    chunks = chunk_document(text)
    assert len(chunks) > 1
    owner = ExtractionState(store.conn)
    competitor = ExtractionState(store.conn)
    owner_plan = owner.plan(
        doc.id, chunks, schema_version_id=1, engine="mock", model=None,
        prompt_version="extract-v1", decode_params=None,
    )
    assert owner.claim(owner_plan.run_id, chunks[0].index)

    competing_plan = competitor.plan(
        doc.id, chunks, schema_version_id=1, engine="mock", model=None,
        prompt_version="extract-v1", decode_params=None,
    )
    assert competing_plan.run_id == owner_plan.run_id
    assert competing_plan.retryable == frozenset()
    assert competitor.claim(owner_plan.run_id, chunks[1].index) is False
    with pytest.raises(RuntimeError, match="ownership was lost"):
        competitor.succeeded(owner_plan.run_id, chunks[0].index, {})
    assert competitor.finish(owner_plan.run_id) == "running"

    rows = store.conn.execute(
        "SELECT chunk_index, status FROM extraction_chunks WHERE run_id = ? "
        "ORDER BY chunk_index", (owner_plan.run_id,),
    ).fetchall()
    assert tuple(rows[0]) == (chunks[0].index, "running")
    assert {row["status"] for row in rows[1:]} == {"pending"}
    competitor.close()
    owner.close()
    store.close()


def test_live_subprocess_owner_survives_competitor_then_dead_owner_is_reclaimed(
    tmp_path,
) -> None:
    data_dir = tmp_path / "cross-process-data"
    db = paths.kg_db_path(data_dir)
    store = KGStore.open(db)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///cross-process.txt",
        title="cross-process",
        raw_text="The PaymentGateway uses the DatabaseService.",
        content_hash="sha256:cross-process",
    )
    store.close()

    owner_code = textwrap.dedent("""
        import json
        import sys
        from ontologylab.extraction_state import ExtractionState
        from ontologylab.extractor import chunk_document
        from ontologylab.kgstore import KGStore

        store = KGStore.open(sys.argv[1])
        state = ExtractionState(store.conn)
        chunks = chunk_document(store.document_raw_text(sys.argv[2]))
        plan = state.plan(
            sys.argv[2], chunks, schema_version_id=1, engine="mock", model=None,
            prompt_version="extract-v1", decode_params=None,
        )
        assert state.claim(plan.run_id, 0)
        print(json.dumps({"run_id": plan.run_id, "owner": state.owner_token}),
              flush=True)
        sys.stdin.buffer.read(1)
    """)
    competitor_code = textwrap.dedent("""
        import json
        import sys
        from ontologylab import paths
        from ontologylab.extraction_state import ExtractionState
        from ontologylab.extractor import chunk_document
        from ontologylab.kgstore import KGStore
        from ontologylab.server.jobs import JobRegistry

        data_dir, db, doc_id, run_id = sys.argv[1:]
        JobRegistry(data_dir)
        store = KGStore.open(db)
        state = ExtractionState(store.conn)
        chunks = chunk_document(store.document_raw_text(doc_id))
        plan = state.plan(
            doc_id, chunks, schema_version_id=1, engine="mock", model=None,
            prompt_version="extract-v1", decode_params=None,
        )
        claimed = state.claim(run_id, 0)
        state.failed(run_id, 0, "competitor")
        finished = state.finish(run_id)
        row = store.conn.execute(
            "SELECT status, owner_token, attempts FROM extraction_chunks "
            "WHERE run_id = ? AND chunk_index = 0", (run_id,),
        ).fetchone()
        print(json.dumps({
            "retryable": sorted(plan.retryable), "claimed": claimed,
            "finished": finished, "row": list(row),
        }), flush=True)
        state.close()
        store.close()
    """)
    recovery_code = textwrap.dedent("""
        import json
        import sys
        from ontologylab.extraction_state import ExtractionState
        from ontologylab.extractor import chunk_document
        from ontologylab.kgstore import KGStore
        from ontologylab.server.jobs import JobRegistry

        data_dir, db, doc_id, run_id = sys.argv[1:]
        JobRegistry(data_dir)
        store = KGStore.open(db)
        state = ExtractionState(store.conn)
        chunks = chunk_document(store.document_raw_text(doc_id))
        plan = state.plan(
            doc_id, chunks, schema_version_id=1, engine="mock", model=None,
            prompt_version="extract-v1", decode_params=None,
        )
        claimed = state.claim(run_id, 0)
        row = store.conn.execute(
            "SELECT status, owner_token, attempts FROM extraction_chunks "
            "WHERE run_id = ? AND chunk_index = 0", (run_id,),
        ).fetchone()
        print(json.dumps({
            "retryable": sorted(plan.retryable), "claimed": claimed,
            "row": list(row),
        }), flush=True)
        state.finish(run_id, cancelled=True)
        state.close()
        store.close()
    """)
    args = [str(data_dir), str(db), doc.id]
    owner = subprocess.Popen(
        [sys.executable, "-c", owner_code, str(db), doc.id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert owner.stdout is not None
        ready_line = owner.stdout.readline()
        assert ready_line, owner.stderr.read() if owner.stderr else "owner exited"
        ready = json.loads(ready_line)

        competitor = subprocess.run(
            [sys.executable, "-c", competitor_code, *args, ready["run_id"]],
            check=True, capture_output=True, text=True, timeout=10,
        )
        live = json.loads(competitor.stdout)
        print("LIVE " + json.dumps(live, sort_keys=True))
        assert live == {
            "retryable": [], "claimed": False, "finished": "running",
            "row": ["running", ready["owner"], 1],
        }

        owner.terminate()
        owner.wait(timeout=10)
        recovered = subprocess.run(
            [sys.executable, "-c", recovery_code, *args, ready["run_id"]],
            check=True, capture_output=True, text=True, timeout=10,
        )
        dead = json.loads(recovered.stdout)
        print("DEAD " + json.dumps(dead, sort_keys=True))
        assert dead["retryable"] == [0]
        assert dead["claimed"] is True
        assert dead["row"][0] == "running"
        assert dead["row"][1] not in {None, ready["owner"]}
        assert dead["row"][2] == 2
    finally:
        if owner.poll() is None:
            owner.terminate()
            owner.wait(timeout=10)
        if owner.stdin is not None:
            owner.stdin.close()
        if owner.stdout is not None:
            owner.stdout.close()
        if owner.stderr is not None:
            owner.stderr.close()


def _owner_lock_files(db: Path) -> list[Path]:
    lock_dir = db.with_name(db.name + ".extraction-owners")
    return list(lock_dir.glob("*.lock")) if lock_dir.exists() else []


def test_retained_exception_task_releases_owner_lock_and_finishes_run(
    tmp_path,
) -> None:
    db = tmp_path / "exception.sqlite"
    store = KGStore.open(db)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///exception.txt",
        title="exception",
        raw_text="The PaymentGateway uses the DatabaseService.",
        content_hash="sha256:exception-cleanup",
    )

    async def exercise() -> asyncio.Task:
        callback_entered = asyncio.Event()

        def fail_after_commit(_line: str) -> None:
            callback_entered.set()
            raise RuntimeError("hostile progress callback")

        task = asyncio.create_task(run_extraction(
            store,
            MockEngine(seed=0),
            Provenance(str(tmp_path / "exception-job"), seed=0),
            _caps(),
            [doc.id],
            extractor_engine="mock",
            extractor_model=None,
            on_progress=fail_after_commit,
            on_stats=lambda _stats: None,
        ))
        await asyncio.wait_for(callback_entered.wait(), timeout=10)
        with pytest.raises(RuntimeError, match="hostile progress callback"):
            await task
        return task

    retained_task = asyncio.run(exercise())
    assert retained_task.exception() is not None
    assert _owner_lock_files(db) == []
    run = store.conn.execute(
        "SELECT status, owner_token FROM extraction_runs"
    ).fetchone()
    assert tuple(run) == ("complete", None)

    competitor = KGStore.open(db)
    try:
        assert recover_running_once(competitor.conn) == 0
    finally:
        competitor.close()
    store.close()


def test_retained_cancelled_task_releases_owner_lock_and_is_resumable(
    tmp_path,
) -> None:
    db = tmp_path / "cancelled-task.sqlite"
    store = KGStore.open(db)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///cancelled-task.txt",
        title="cancelled-task",
        raw_text="The PaymentGateway uses the DatabaseService.",
        content_hash="sha256:cancelled-task-cleanup",
    )

    class _BlockedEngine:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def generate(self, prompt: str, *, model: str | None = None):
            self.entered.set()
            await self.release.wait()
            return await MockEngine(seed=0).generate(prompt, model=model)

    async def exercise() -> asyncio.Task:
        engine = _BlockedEngine()
        task = asyncio.create_task(run_extraction(
            store,
            engine,
            Provenance(str(tmp_path / "cancelled-task-job"), seed=0),
            _caps(),
            [doc.id],
            extractor_engine="mock",
            extractor_model=None,
            on_progress=lambda _line: None,
            on_stats=lambda _stats: None,
        ))
        await asyncio.wait_for(engine.entered.wait(), timeout=10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return task

    retained_task = asyncio.run(exercise())
    assert retained_task.cancelled()
    assert _owner_lock_files(db) == []
    run = store.conn.execute(
        "SELECT status, owner_token FROM extraction_runs"
    ).fetchone()
    chunk = store.conn.execute(
        "SELECT status, owner_token, attempts FROM extraction_chunks"
    ).fetchone()
    assert tuple(run) == ("interrupted", None)
    assert tuple(chunk) == ("interrupted", None, 1)

    competitor = KGStore.open(db)
    try:
        assert recover_running_once(competitor.conn) == 0
        engine = _CountingMock()
        assert _drive(
            competitor, engine, doc.id, tmp_path / "cancelled-task-resume"
        ) == ""
        assert engine.calls == 1
        resumed = competitor.conn.execute(
            "SELECT status, attempts FROM extraction_chunks"
        ).fetchone()
        assert tuple(resumed) == ("succeeded", 2)
    finally:
        competitor.close()
    store.close()


def test_app_restart_marks_a_claim_interrupted_and_resumes_it(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = KGStore.open(paths.kg_db_path(data_dir))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///one.txt", title="one",
        raw_text="The PaymentGateway uses the DatabaseService.",
        content_hash="sha256:restart",
    )
    chunks = chunk_document(store.document_raw_text(doc.id))
    state = ExtractionState(store.conn)
    plan = state.plan(
        doc.id, chunks, schema_version_id=1, engine="mock", model=None,
        prompt_version="extract-v1", decode_params=None,
    )
    assert state.claim(plan.run_id, 0)
    # Releasing the process-lifetime owner lock models kernel cleanup after
    # process death; closing SQLite alone is only an ordinary store close.
    state.close()
    store.close()

    JobRegistry(data_dir)  # real app startup recovery boundary
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        row = store.conn.execute(
            "SELECT status FROM extraction_chunks WHERE run_id = ?",
            (plan.run_id,),
        ).fetchone()
        assert row["status"] == "interrupted"
        engine = _CountingMock()
        assert _drive(store, engine, doc.id, tmp_path / "resumed") == ""
        assert engine.calls == 1
        row = store.conn.execute(
            "SELECT status, attempts FROM extraction_chunks WHERE run_id = ?",
            (plan.run_id,),
        ).fetchone()
        assert tuple(row) == ("succeeded", 2)
    finally:
        store.close()


def test_unrelated_store_open_does_not_interrupt_a_live_claim(tmp_path) -> None:
    db = tmp_path / "live.sqlite"
    store = KGStore.open(db)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///live.txt", title="live",
        raw_text="The PaymentGateway uses the DatabaseService.",
        content_hash="sha256:live",
    )
    chunks = chunk_document(store.document_raw_text(doc.id))
    state = ExtractionState(store.conn)
    plan = state.plan(
        doc.id, chunks, schema_version_id=1, engine="mock", model=None,
        prompt_version="extract-v1", decode_params=None,
    )
    assert state.claim(plan.run_id, 0)

    unrelated = KGStore.open(db)  # the normal route/request boundary
    unrelated.close()
    try:
        row = store.conn.execute(
            "SELECT status FROM extraction_chunks WHERE run_id = ?",
            (plan.run_id,),
        ).fetchone()
        assert row["status"] == "running"
    finally:
        state.close()
        store.close()


def test_cancelled_run_and_unfinished_chunks_are_explicit(tmp_path) -> None:
    store = KGStore.open(tmp_path / "cancel.sqlite")
    text = "The PaymentGateway uses the DatabaseService. " * 900
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///cancel.txt", title="cancel",
        raw_text=text, content_hash="sha256:cancel",
    )
    engine = _CountingMock()
    try:
        stopped = _drive(
            store, engine, doc.id, tmp_path / "cancel-job",
            should_abort=lambda: "cancelled by request" if engine.calls else "",
        )
        assert stopped == "cancelled by request"
        run = store.conn.execute(
            "SELECT status FROM extraction_runs"
        ).fetchone()["status"]
        statuses = [row["status"] for row in store.conn.execute(
            "SELECT status FROM extraction_chunks ORDER BY chunk_index"
        )]
        assert run == "cancelled"
        assert statuses[0] == "succeeded"
        assert set(statuses[1:]) == {"cancelled"}
    finally:
        store.close()


def test_revision_and_stream_identity_create_fresh_runs(tmp_path) -> None:
    store = KGStore.open(tmp_path / "identity.sqlite")
    first, _ = store.insert_document(
        source_kind="upload", source_uri="file:///revision.txt", title="r1",
        raw_text="The PaymentGateway uses the DatabaseService.",
        content_hash="sha256:revision-1",
    )
    revised, _ = store.insert_document(
        source_kind="upload", source_uri="file:///revision.txt", title="r2",
        raw_text="The PaymentGateway uses the CacheService.",
        content_hash="sha256:revision-2",
    )
    store.conn.execute(
        "INSERT INTO schema_version (label, description, created_ts, is_active) "
        "VALUES ('identity-v2', '', 0, 0)"
    )
    store.conn.commit()
    state = ExtractionState(store.conn)

    def plan(doc_id, **changes):
        values = {
            "schema_version_id": 1, "engine": "mock", "model": None,
            "prompt_version": "extract-v1", "decode_params": None,
        }
        values.update(changes)
        chunks = chunk_document(store.document_raw_text(doc_id))
        return state.plan(doc_id, chunks, **values).run_id

    baseline = plan(first.id)
    assert plan(first.id) == baseline
    assert plan(first.id, decode_params={"top_p": 0.9, "temperature": 0.2}) == plan(
        first.id, decode_params={"temperature": 0.2, "top_p": 0.9},
    )
    identities = {
        baseline,
        plan(first.id, engine="claude"),
        plan(first.id, model="model-b"),
        plan(first.id, prompt_version="extract-v2"),
        plan(first.id, decode_params={"temperature": 0.7}),
        plan(first.id, schema_version_id=2),
        plan(revised.id),
    }
    try:
        assert len(identities) == 7
        assert store.conn.execute(
            "SELECT COUNT(*) FROM extraction_runs"
        ).fetchone()[0] == 8  # seven above plus the canonical-order stream
    finally:
        state.close()
        store.close()
