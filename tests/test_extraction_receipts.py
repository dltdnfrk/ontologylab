"""Characterization and contract tests for extraction run/chunk receipts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ontologylab.authority_repo import create_work
from ontologylab.extraction_state import (
    ExtractionState,
    RunPlan,
    ensure_schema,
    recover_running_once,
)
from ontologylab.file_lifecycle import content_hash_for
from ontologylab.kgstore import KGStore


_TEXT = "The PaymentGateway uses the DatabaseService."
_HASH = content_hash_for(_TEXT.encode("utf-8"))


def _chunks(text: str = _TEXT) -> list[SimpleNamespace]:
    return [SimpleNamespace(index=0, char_offset=0, text=text)]


def _open_legacy_doc(tmp_path: Path) -> tuple[KGStore, str]:
    store = KGStore.open(tmp_path / "kg.sqlite")
    document, _created = store.insert_document(
        source_kind="upload",
        source_uri="file:///receipt-baseline.txt",
        title="baseline",
        raw_text=_TEXT,
        content_hash=_HASH,
    )
    return store, document.id


def _plan_legacy(state: ExtractionState, document_id: str) -> RunPlan:
    return state.plan(
        document_id,
        _chunks(),
        schema_version_id=1,
        engine="mock",
        model=None,
        prompt_version="extract-v1",
        decode_params=None,
    )


def test_legacy_claim_succeeds_and_finish_is_complete_when_chunk_succeeds(
    tmp_path: Path,
) -> None:
    store, document_id = _open_legacy_doc(tmp_path)
    state = ExtractionState(store.conn)
    try:
        plan = _plan_legacy(state, document_id)
        assert state.claim(plan.run_id, 0)
        state.succeeded(plan.run_id, 0, {"entities": 1})
        assert state.finish(plan.run_id) == "complete"
        run = store.conn.execute(
            "SELECT status FROM extraction_runs WHERE id = ?",
            (plan.run_id,),
        ).fetchone()
        chunk = store.conn.execute(
            "SELECT status, attempts FROM extraction_chunks "
            "WHERE run_id = ? AND chunk_index = 0",
            (plan.run_id,),
        ).fetchone()
        assert run["status"] == "complete"
        assert tuple(chunk) == ("succeeded", 1)
    finally:
        state.close()
        store.close()


def test_legacy_claim_failed_and_finish_is_failed_when_chunk_fails(
    tmp_path: Path,
) -> None:
    store, document_id = _open_legacy_doc(tmp_path)
    state = ExtractionState(store.conn)
    try:
        plan = _plan_legacy(state, document_id)
        assert state.claim(plan.run_id, 0)
        state.failed(plan.run_id, 0, "engine_error")
        assert state.finish(plan.run_id) == "failed"
        run = store.conn.execute(
            "SELECT status FROM extraction_runs WHERE id = ?",
            (plan.run_id,),
        ).fetchone()
        chunk = store.conn.execute(
            "SELECT status, error_kind FROM extraction_chunks "
            "WHERE run_id = ? AND chunk_index = 0",
            (plan.run_id,),
        ).fetchone()
        assert run["status"] == "failed"
        assert tuple(chunk) == ("failed", "engine_error")
    finally:
        state.close()
        store.close()


def test_legacy_interrupt_then_retry_resumes_same_run(tmp_path: Path) -> None:
    store, document_id = _open_legacy_doc(tmp_path)
    state = ExtractionState(store.conn)
    try:
        first = _plan_legacy(state, document_id)
        assert state.claim(first.run_id, 0)
        state.close()
        assert recover_running_once(store.conn) >= 1
        interrupted = store.conn.execute(
            "SELECT status FROM extraction_chunks WHERE run_id = ?",
            (first.run_id,),
        ).fetchone()
        assert interrupted["status"] == "interrupted"
        resumed = ExtractionState(store.conn)
        try:
            second = _plan_legacy(resumed, document_id)
            assert second.run_id == first.run_id
            assert 0 in second.retryable
            assert resumed.claim(second.run_id, 0)
        finally:
            resumed.close()
    finally:
        store.close()


def test_legacy_ensure_schema_commits_caller_transaction(tmp_path: Path) -> None:
    store, _document_id = _open_legacy_doc(tmp_path)
    try:
        store.conn.execute("BEGIN IMMEDIATE")
        store.conn.execute("CREATE TABLE caller_marker (n INTEGER)")
        store.conn.execute("INSERT INTO caller_marker VALUES (1)")
        state = ExtractionState(store.conn)
        state.close()
        store.conn.rollback()
        marker = store.conn.execute(
            "SELECT n FROM caller_marker"
        ).fetchone()
        assert marker is not None
        assert marker[0] == 1
    finally:
        store.close()


def test_legacy_plan_commits_so_caller_rollback_cannot_undo_run(
    tmp_path: Path,
) -> None:
    store, document_id = _open_legacy_doc(tmp_path)
    state = ExtractionState(store.conn)
    try:
        store.conn.execute("BEGIN IMMEDIATE")
        plan = _plan_legacy(state, document_id)
        store.conn.rollback()
        row = store.conn.execute(
            "SELECT id FROM extraction_runs WHERE id = ?",
            (plan.run_id,),
        ).fetchone()
        assert row is not None
    finally:
        state.close()
        store.close()


def test_legacy_failed_rolls_back_caller_transaction(tmp_path: Path) -> None:
    store, document_id = _open_legacy_doc(tmp_path)
    state = ExtractionState(store.conn)
    try:
        plan = _plan_legacy(state, document_id)
        assert state.claim(plan.run_id, 0)
        store.conn.execute("BEGIN IMMEDIATE")
        store.conn.execute("CREATE TABLE caller_marker (n INTEGER)")
        store.conn.execute("INSERT INTO caller_marker VALUES (1)")
        state.failed(plan.run_id, 0, "engine_error")
        marker = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'caller_marker'"
        ).fetchone()
        assert marker is None
    finally:
        state.close()
        store.close()


def _disposable_v2_layout(db: Path) -> KGStore:
    store = KGStore.open(db)
    conn = store.conn
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """CREATE TABLE documents_v2 (
            id            TEXT PRIMARY KEY,
            source_kind   TEXT NOT NULL,
            source_uri    TEXT NOT NULL,
            title         TEXT,
            fetched_ts    REAL NOT NULL,
            content_hash  TEXT NOT NULL,
            raw_text_path TEXT NOT NULL,
            doi           TEXT,
            source        TEXT NOT NULL DEFAULT '',
            evidence_grade TEXT NOT NULL DEFAULT '',
            work_id       TEXT REFERENCES works(id),
            representation_state TEXT NOT NULL DEFAULT 'ready'
        )"""
    )
    conn.execute(
        "INSERT INTO documents_v2 SELECT id, source_kind, source_uri, title, "
        "fetched_ts, content_hash, raw_text_path, doi, source, "
        "evidence_grade, work_id, representation_state FROM documents"
    )
    conn.execute("DROP TABLE documents")
    conn.execute("ALTER TABLE documents_v2 RENAME TO documents")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_representation "
        "ON documents (work_id, content_hash) WHERE work_id IS NOT NULL"
    )
    conn.execute("PRAGMA foreign_keys = ON")
    return store


def _insert_ready_representation(
    store: KGStore,
    *,
    representation_id: str,
    work_id: str,
    body: str = _TEXT,
    content_hash: str = _HASH,
    state: str = "ready",
) -> None:
    root = Path(store.db_path).parent / "documents" / representation_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw.txt").write_text(body, encoding="utf-8")
    store.conn.execute(
        "INSERT INTO documents (id, source_kind, source_uri, title, "
        "fetched_ts, content_hash, raw_text_path, source, evidence_grade, "
        "work_id, representation_state) "
        "VALUES (?, 'paper_api', ?, 'paper', 0.0, ?, ?, '', '', ?, ?)",
        (
            representation_id,
            f"https://doi.org/10.5555/{representation_id}",
            content_hash,
            f"documents/{representation_id}/raw.txt",
            work_id,
            state,
        ),
    )


def _two_ready_same_bytes(tmp_path: Path) -> tuple[KGStore, str, str]:
    store = _disposable_v2_layout(tmp_path / "kg.sqlite")
    create_work(store.conn, "work-a")
    create_work(store.conn, "work-b")
    _insert_ready_representation(
        store, representation_id="rep-a", work_id="work-a",
    )
    _insert_ready_representation(
        store, representation_id="rep-b", work_id="work-b",
    )
    store.conn.commit()
    return store, "rep-a", "rep-b"


def _one_ready(tmp_path: Path, *, state: str = "ready") -> tuple[KGStore, str]:
    store = _disposable_v2_layout(tmp_path / "kg.sqlite")
    create_work(store.conn, "work-a")
    _insert_ready_representation(
        store, representation_id="rep-a", work_id="work-a", state=state,
    )
    store.conn.commit()
    return store, "rep-a"


def _span(
    text: str = _TEXT,
    *,
    start: int = 0,
    end: int | None = None,
    index: int = 0,
    text_hash: str | None = None,
    profile: str = "document-utf8-v1",
):
    from ontologylab.extraction_state import ChunkSpan

    if end is None:
        end = len(text)
    slice_text = text[start:end]
    return ChunkSpan(
        index=index,
        start_offset=start,
        end_offset=end,
        text=slice_text,
        text_hash=text_hash or content_hash_for(slice_text.encode("utf-8")),
        coordinate_profile=profile,
    )


def _binding(
    representation_id: str,
    *,
    policy_identity: str = "policy-v1",
    config_identity: str = "config-v1",
):
    from ontologylab.extraction_state import ExtractionRunBinding

    return ExtractionRunBinding(
        representation_id=representation_id,
        policy_identity=policy_identity,
        config_identity=config_identity,
        schema_version_id=1,
        extractor_engine="mock",
        extractor_model="",
        prompt_version="extract-v1",
        decode_params_json="{}",
    )


def _put(conn, representation_id: str, chunks=None, **binding_kwargs):
    from ontologylab.extraction_state import put_extraction_receipts

    return put_extraction_receipts(
        conn,
        _binding(representation_id, **binding_kwargs),
        tuple(chunks or [_span()]),
    )


def _receipt_counts(conn) -> tuple[int, int]:
    runs = conn.execute(
        "SELECT COUNT(*) FROM extraction_run_receipts"
    ).fetchone()[0]
    chunks = conn.execute(
        "SELECT COUNT(*) FROM extraction_chunk_receipts"
    ).fetchone()[0]
    return int(runs), int(chunks)


def test_receipt_schema_binds_representation_policy_config_and_chunk_fields(
    tmp_path: Path,
) -> None:
    store, _document_id = _open_legacy_doc(tmp_path)
    try:
        ensure_schema(store.conn)
        run_columns = {
            row["name"]
            for row in store.conn.execute(
                "PRAGMA table_info(extraction_run_receipts)"
            )
        }
        chunk_columns = {
            row["name"]
            for row in store.conn.execute(
                "PRAGMA table_info(extraction_chunk_receipts)"
            )
        }
        assert {
            "receipt_id",
            "representation_id",
            "document_content_hash",
            "policy_identity",
            "config_identity",
            "chunk_plan_receipt_id",
        } <= run_columns
        assert {
            "receipt_id",
            "run_receipt_id",
            "chunk_index",
            "start_offset",
            "end_offset",
            "coordinate_profile",
            "chunk_text_hash",
            "plan_receipt_id",
        } <= chunk_columns
    finally:
        store.close()


def test_same_hash_two_representations_mint_distinct_run_receipts(
    tmp_path: Path,
) -> None:
    store, rep_a, rep_b = _two_ready_same_bytes(tmp_path)
    try:
        first = _put(store.conn, rep_a)
        second = _put(store.conn, rep_b)
        assert first.run.representation_id == rep_a
        assert second.run.representation_id == rep_b
        assert first.run.document_content_hash == _HASH
        assert second.run.document_content_hash == _HASH
        assert first.run.receipt_id != second.run.receipt_id
        assert first.chunks[0].receipt_id != second.chunks[0].receipt_id
        assert _receipt_counts(store.conn) == (2, 2)
    finally:
        store.close()


def test_run_receipt_binds_representation_policy_config_and_content_hash(
    tmp_path: Path,
) -> None:
    store, representation_id = _one_ready(tmp_path)
    try:
        receipt = _put(
            store.conn,
            representation_id,
            policy_identity="policy-explicit",
            config_identity="config-explicit",
        )
        assert receipt.run.representation_id == representation_id
        assert receipt.run.policy_identity == "policy-explicit"
        assert receipt.run.config_identity == "config-explicit"
        assert receipt.run.document_content_hash == _HASH
        row = store.conn.execute(
            "SELECT representation_id, policy_identity, config_identity, "
            "document_content_hash FROM extraction_run_receipts "
            "WHERE receipt_id = ?",
            (receipt.run.receipt_id,),
        ).fetchone()
        assert tuple(row) == (
            representation_id,
            "policy-explicit",
            "config-explicit",
            _HASH,
        )
    finally:
        store.close()


def test_chunk_receipt_binds_end_profile_text_hash_and_plan(
    tmp_path: Path,
) -> None:
    store, representation_id = _one_ready(tmp_path)
    try:
        mid = len(_TEXT) // 2
        chunks = (
            _span(start=0, end=mid, index=0),
            _span(start=mid, end=len(_TEXT), index=1),
        )
        receipt = _put(store.conn, representation_id, chunks)
        assert len(receipt.chunks) == 2
        for index, chunk in enumerate(receipt.chunks):
            assert chunk.end_offset > chunk.start_offset
            assert chunk.coordinate_profile == "document-utf8-v1"
            assert chunk.chunk_text_hash == chunks[index].text_hash
            assert chunk.plan_receipt_id == receipt.run.chunk_plan_receipt_id
            assert chunk.run_receipt_id == receipt.run.receipt_id
        row = store.conn.execute(
            "SELECT start_offset, end_offset, coordinate_profile, "
            "chunk_text_hash, plan_receipt_id FROM extraction_chunk_receipts "
            "WHERE run_receipt_id = ? ORDER BY chunk_index",
            (receipt.run.receipt_id,),
        ).fetchall()
        assert [tuple(item) for item in row] == [
            (
                chunk.start_offset,
                chunk.end_offset,
                chunk.coordinate_profile,
                chunk.chunk_text_hash,
                chunk.plan_receipt_id,
            )
            for chunk in receipt.chunks
        ]
    finally:
        store.close()


def test_retry_same_binding_converges_to_same_receipts(
    tmp_path: Path,
) -> None:
    store, representation_id = _one_ready(tmp_path)
    try:
        first = _put(store.conn, representation_id)
        second = _put(store.conn, representation_id)
        assert first.run.receipt_id == second.run.receipt_id
        assert first.chunks[0].receipt_id == second.chunks[0].receipt_id
        assert first.run.created is True
        assert second.run.created is False
        assert _receipt_counts(store.conn) == (1, 1)
    finally:
        store.close()


def test_conflicting_retry_refuses_and_writes_zero_rows(
    tmp_path: Path,
) -> None:
    from ontologylab.extraction_state import (
        ExtractionReceiptRefusalCode,
        ExtractionReceiptRefused,
    )

    store, representation_id = _one_ready(tmp_path)
    try:
        first = _put(store.conn, representation_id)
        with pytest.raises(ExtractionReceiptRefused) as refused:
            _put(
                store.conn,
                representation_id,
                [_span(start=0, end=len(_TEXT) - 1)],
            )
        assert refused.value.code is ExtractionReceiptRefusalCode.CONFLICT
        assert _receipt_counts(store.conn) == (1, 1)
        row = store.conn.execute(
            "SELECT receipt_id, chunk_plan_receipt_id FROM "
            "extraction_run_receipts"
        ).fetchone()
        assert tuple(row) == (
            first.run.receipt_id,
            first.run.chunk_plan_receipt_id,
        )
    finally:
        store.close()


def test_missing_representation_or_policy_or_config_is_refused(
    tmp_path: Path,
) -> None:
    from ontologylab.extraction_state import (
        ExtractionReceiptRefusalCode,
        ExtractionReceiptRefused,
    )

    store, representation_id = _one_ready(tmp_path)
    try:
        ensure_schema(store.conn)
        for kwargs in (
            {"representation_id": ""},
            {"policy_identity": ""},
            {"config_identity": ""},
        ):
            binding_kwargs = {
                "policy_identity": "policy-v1",
                "config_identity": "config-v1",
            }
            target = representation_id
            if "representation_id" in kwargs:
                target = kwargs["representation_id"]
            else:
                binding_kwargs.update(kwargs)
            with pytest.raises(ExtractionReceiptRefused) as refused:
                _put(store.conn, target, **binding_kwargs)
            assert (
                refused.value.code is ExtractionReceiptRefusalCode.MISSING_BINDING
            )
        assert _receipt_counts(store.conn) == (0, 0)
    finally:
        store.close()


def test_invalid_range_hash_or_profile_refuses_with_zero_rows(
    tmp_path: Path,
) -> None:
    from ontologylab.extraction_state import (
        ExtractionReceiptRefusalCode,
        ExtractionReceiptRefused,
    )

    store, representation_id = _one_ready(tmp_path)
    try:
        ensure_schema(store.conn)
        cases = (
            (
                [_span(start=8, end=3)],
                ExtractionReceiptRefusalCode.INVALID_RANGE,
            ),
            (
                [_span(text_hash="sha256:" + ("0" * 64))],
                ExtractionReceiptRefusalCode.INVALID_HASH,
            ),
            (
                [_span(profile="guessed-offsets-v0")],
                ExtractionReceiptRefusalCode.INVALID_PROFILE,
            ),
        )
        for chunks, code in cases:
            with pytest.raises(ExtractionReceiptRefused) as refused:
                _put(store.conn, representation_id, chunks)
            assert refused.value.code is code
        assert _receipt_counts(store.conn) == (0, 0)
    finally:
        store.close()


def test_put_leaves_caller_transaction_uncommitted(tmp_path: Path) -> None:
    store, representation_id = _one_ready(tmp_path)
    try:
        ensure_schema(store.conn)
        store.conn.execute("BEGIN IMMEDIATE")
        receipt = _put(store.conn, representation_id)
        assert receipt.run.created is True
        assert _receipt_counts(store.conn) == (1, 1)
        store.conn.rollback()
        assert _receipt_counts(store.conn) == (0, 0)
    finally:
        store.close()


def test_legacy_plan_rows_remain_readable_after_receipt_writes(
    tmp_path: Path,
) -> None:
    store, document_id = _open_legacy_doc(tmp_path)
    state = ExtractionState(store.conn)
    try:
        plan = _plan_legacy(state, document_id)
        create_work(store.conn, "work-receipt")
        store.conn.execute(
            "UPDATE documents SET work_id = ? WHERE id = ?",
            ("work-receipt", document_id),
        )
        store.conn.commit()
        receipt = _put(store.conn, document_id, config_identity="config-new")
        legacy = store.conn.execute(
            "SELECT id, document_content_hash, status FROM extraction_runs "
            "WHERE id = ?",
            (plan.run_id,),
        ).fetchone()
        assert tuple(legacy) == (plan.run_id, _HASH, "running")
        assert receipt.run.receipt_id != plan.run_id
        chunk = store.conn.execute(
            "SELECT char_offset, content_hash FROM extraction_chunks "
            "WHERE run_id = ?",
            (plan.run_id,),
        ).fetchone()
        assert chunk["char_offset"] == 0
        assert chunk["content_hash"] == _HASH
    finally:
        state.close()
        store.close()


