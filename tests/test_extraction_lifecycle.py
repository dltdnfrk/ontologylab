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
from pathlib import Path
from types import SimpleNamespace

from ontologylab import paths
from ontologylab.engines import MockEngine
from ontologylab.extraction_state import ExtractionState
from ontologylab.extractor import chunk_document, run_extraction
from ontologylab.kgstore import KGStore
from ontologylab.server.jobs import JobRegistry
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
    store.close()  # process dies while the chunk is running

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
        store.close()
