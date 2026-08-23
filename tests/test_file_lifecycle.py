"""Wave 2.1 Step 6B / F4: staged file lifecycle and deterministic recovery."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from ontologylab.file_lifecycle import (
    FileIntegrityError,
    FileNotReady,
    PathEscapeError,
    classify_representation,
    contain_source_path,
    content_hash_for,
    final_raw_text_path,
    finalize_representation,
    read_ready_text,
    reconcile_files,
    stage_bytes,
)
from ontologylab.ingestion_service import (
    IngestItem,
    RepresentationInput,
    ingest_item,
)
from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.work_view import work_snapshot


BODY = b"G008 staged representation body\n"
SENTINEL = "ELS-must-never-surface-9f3a"
_NO_TEXT = object()


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _open(tmp_path: Path) -> KGStore:
    return KGStore.open(tmp_path / "kg.sqlite")


def _item(
    *,
    operation: str = "op-1",
    doi: str = "10.1000/lifecycle.one",
    body: bytes = BODY,
    content_hash: str | None = None,
    raw_text_path: str = "",
    raw_text: bytes | str | object | None = _NO_TEXT,
) -> IngestItem:
    payload: bytes | str | None
    if raw_text is _NO_TEXT:
        payload = body
    elif isinstance(raw_text, (bytes, str)) or raw_text is None:
        payload = raw_text
    else:
        payload = None
    return IngestItem(
        idempotency_key=operation,
        scheme="doi",
        normalized_value=doi,
        source="crossref",
        evidence_grade="A",
        representation=RepresentationInput(
            source_kind="paper_api",
            source_uri=f"https://doi.org/{doi}",
            title="File lifecycle",
            content_hash=content_hash if content_hash is not None else _sha(body),
            raw_text_path=raw_text_path,
            raw_text=payload,
        ),
        stage="published",
        content_kind="fulltext",
    )


def _state(conn: sqlite3.Connection, representation_id: str) -> tuple[str, str]:
    row = conn.execute(
        "SELECT raw_text_path, representation_state FROM documents WHERE id = ?",
        (representation_id,),
    ).fetchone()
    assert row is not None
    return str(row[0]), str(row[1])


def _ingest_committed(store: KGStore, item: IngestItem):
    receipt = ingest_item(store.conn, item)
    assert receipt.status == "staged"
    assert receipt.representation_id is not None
    store.conn.commit()
    return receipt


def test_stage_bytes_is_operation_owned_and_fsyncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fsyncs: list[int] = []
    original = os.fsync

    def spy(fd: int) -> None:
        fsyncs.append(fd)
        original(fd)

    monkeypatch.setattr(os, "fsync", spy)
    staged = stage_bytes(tmp_path, "op-1", "rep-1", BODY)
    assert staged == tmp_path / "staging" / "op-1" / "rep-1.part"
    assert staged.read_bytes() == BODY
    assert staged.is_relative_to(tmp_path / "staging" / "op-1")
    assert not staged.is_relative_to(tmp_path / "documents")
    assert len(fsyncs) >= 2


def test_first_db_write_stores_immutable_final_relative_path(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(
            store.conn,
            _item(raw_text_path="caller-supplied.txt"),
        )
        assert receipt.status == "staged"
        assert receipt.representation_id is not None
        path, state = _state(store.conn, receipt.representation_id)
        assert path == final_raw_text_path(receipt.representation_id)
        assert path == f"documents/{receipt.representation_id}/raw.txt"
        assert path != "caller-supplied.txt"
        assert not Path(path).is_absolute()
        assert state == "staged"
        assert content_hash_for(BODY).startswith("sha256:")
    finally:
        store.close()


def test_finalize_atomically_renames_fsyncs_and_marks_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replaces: list[tuple[str, str]] = []
    original_replace = os.replace
    fsyncs: list[int] = []
    original_fsync = os.fsync

    def spy_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        replaces.append((str(src), str(dst)))
        original_replace(src, dst)

    def spy_fsync(fd: int) -> None:
        fsyncs.append(fd)
        original_fsync(fd)

    store = _open(tmp_path)
    try:
        receipt = _ingest_committed(store, _item())
        representation_id = receipt.representation_id
        assert representation_id is not None
        staged = tmp_path / "staging" / "op-1" / f"{representation_id}.part"
        assert staged.is_file()
        monkeypatch.setattr(os, "replace", spy_replace)
        monkeypatch.setattr(os, "fsync", spy_fsync)
        decision = finalize_representation(
            store.conn, tmp_path, representation_id
        )
        path, state = _state(store.conn, representation_id)
        final = tmp_path / path
        assert decision.classification == "valid-ready"
        assert state == "ready"
        assert path == f"documents/{representation_id}/raw.txt"
        assert final.read_bytes() == BODY
        assert not staged.exists()
        assert replaces
        assert Path(replaces[0][1]) == final
        assert len(fsyncs) >= 2
        assert read_ready_text(store.conn, tmp_path, representation_id) == (
            BODY.decode("utf-8")
        )
    finally:
        store.close()


def test_readers_consume_ready_only(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = _ingest_committed(store, _item())
        representation_id = receipt.representation_id
        assert representation_id is not None
        with pytest.raises(FileNotReady):
            read_ready_text(store.conn, tmp_path, representation_id)
        with pytest.raises(KGStoreError):
            store.document_raw_text(representation_id)
        snap = work_snapshot(store.conn, receipt.work_id or "")
        assert snap["preferred_representation_id"] is None
        for rep in snap["representations"]:
            assert rep["byte_length"] == 0
        finalize_representation(store.conn, tmp_path, representation_id)
        assert store.document_raw_text(representation_id) == BODY.decode("utf-8")
        ready_snap = work_snapshot(store.conn, receipt.work_id or "")
        assert ready_snap["preferred_representation_id"] == representation_id
        preferred = next(
            rep
            for rep in ready_snap["representations"]
            if rep["doc_id"] == representation_id
        )
        assert preferred["byte_length"] == len(BODY)
    finally:
        store.close()


def test_final_path_never_mutates(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = _ingest_committed(store, _item(raw_text_path="payload.txt"))
        representation_id = receipt.representation_id
        assert representation_id is not None
        before, _state_before = _state(store.conn, representation_id)
        finalize_representation(store.conn, tmp_path, representation_id)
        after, state = _state(store.conn, representation_id)
        reconcile_files(store.conn, tmp_path)
        again, _ = _state(store.conn, representation_id)
        assert before == after == again == final_raw_text_path(representation_id)
        assert state == "ready"
        assert before != "payload.txt"
    finally:
        store.close()


def test_absolute_parent_symlink_and_outside_staging_are_rejected(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        (tmp_path / "sources.json").write_text(SENTINEL, encoding="utf-8")
        outside = tmp_path.parent / "outside-secret"
        outside.write_text("SECRET", encoding="utf-8")
        staging = tmp_path / "staging" / "op-escape"
        staging.mkdir(parents=True)
        (staging / "escape.txt").symlink_to(outside)

        with pytest.raises(PathEscapeError):
            contain_source_path(tmp_path, "op-escape", "/etc/passwd")
        with pytest.raises(PathEscapeError):
            contain_source_path(tmp_path, "op-escape", "../sources.json")
        with pytest.raises(PathEscapeError):
            contain_source_path(tmp_path, "op-escape", "escape.txt")
        with pytest.raises(PathEscapeError):
            contain_source_path(tmp_path, "op-escape", "sources.json")

        cases = (
            ("op-abs", "/etc/passwd", "10.1000/escape.abs"),
            ("op-parent", "../sources.json", "10.1000/escape.parent"),
            ("op-escape", "escape.txt", "10.1000/escape.link"),
            ("op-secret", "sources.json", "10.1000/escape.sources"),
        )
        for operation, caller_path, doi in cases:
            receipt = ingest_item(
                store.conn,
                _item(
                    operation=operation,
                    doi=doi,
                    raw_text_path=caller_path,
                    raw_text=None,
                    content_hash=_sha(BODY),
                    body=BODY,
                ),
            )
            assert receipt.status == "failed", caller_path
            assert receipt.error is not None
            assert "PathEscapeError" in receipt.error
            planted = store.conn.execute(
                "SELECT id FROM documents WHERE raw_text_path = ?",
                (caller_path,),
            ).fetchone()
            assert planted is None
    finally:
        store.close()
        if outside.exists():
            outside.unlink()


def test_caller_path_is_never_persisted(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(
            store.conn,
            _item(raw_text_path="documents/forged/raw.txt"),
        )
        assert receipt.status == "staged"
        assert receipt.representation_id is not None
        path, _ = _state(store.conn, receipt.representation_id)
        assert path == final_raw_text_path(receipt.representation_id)
        assert "forged" not in path
    finally:
        store.close()


def test_f4_absent_finalizable_valid_ready_quarantine_truth_table(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        absent = classify_representation(store.conn, tmp_path, "rep-missing")
        assert absent.classification == "absent"

        store.conn.execute("SAVEPOINT caller")
        rolled = ingest_item(store.conn, _item(operation="op-absent", doi="10.1000/a"))
        assert rolled.status == "staged"
        assert rolled.representation_id is not None
        store.conn.execute("ROLLBACK TO SAVEPOINT caller")
        store.conn.execute("RELEASE SAVEPOINT caller")
        after_rollback = classify_representation(
            store.conn, tmp_path, rolled.representation_id
        )
        assert after_rollback.classification == "absent"
        cleaned = reconcile_files(store.conn, tmp_path)
        assert all(
            decision.classification == "absent"
            or decision.representation_id != rolled.representation_id
            for decision in cleaned
        )
        leftover = list((tmp_path / "staging").glob(f"*/{rolled.representation_id}.part"))
        assert leftover == []

        finalizable_receipt = _ingest_committed(
            store,
            _item(
                operation="op-finalizable",
                doi="10.1000/f",
                body=BODY + b"-finalizable",
            ),
        )
        finalizable_id = finalizable_receipt.representation_id
        assert finalizable_id is not None
        finalizable = classify_representation(store.conn, tmp_path, finalizable_id)
        assert finalizable.classification == "finalizable"
        assert _state(store.conn, finalizable_id)[1] == "staged"

        finalize_representation(store.conn, tmp_path, finalizable_id)
        valid = classify_representation(store.conn, tmp_path, finalizable_id)
        assert valid.classification == "valid-ready"
        assert _state(store.conn, finalizable_id)[1] == "ready"

        missing = _ingest_committed(
            store,
            _item(
                operation="op-missing",
                doi="10.1000/m",
                body=BODY + b"-missing",
            ),
        )
        missing_id = missing.representation_id
        assert missing_id is not None
        staged = tmp_path / "staging" / "op-missing" / f"{missing_id}.part"
        staged.unlink()
        missing_decision = classify_representation(store.conn, tmp_path, missing_id)
        assert missing_decision.classification == "quarantined"
        assert missing_decision.reason == "missing_bytes"

        mismatch = _ingest_committed(
            store,
            _item(
                operation="op-mismatch",
                doi="10.1000/h",
                body=BODY + b"-mismatch",
            ),
        )
        mismatch_id = mismatch.representation_id
        assert mismatch_id is not None
        bad = tmp_path / "staging" / "op-mismatch" / f"{mismatch_id}.part"
        bad.write_bytes(b"tampered-bytes")
        mismatch_decision = classify_representation(store.conn, tmp_path, mismatch_id)
        assert mismatch_decision.classification == "quarantined"
        assert mismatch_decision.reason == "hash_mismatch"

        reconciled = {item.representation_id: item for item in reconcile_files(store.conn, tmp_path)}
        assert reconciled[finalizable_id].classification == "valid-ready"
        assert reconciled[missing_id].classification == "quarantined"
        assert reconciled[mismatch_id].classification == "quarantined"
        assert _state(store.conn, missing_id)[1] == "quarantined"
        assert _state(store.conn, mismatch_id)[1] == "quarantined"
        still_valid = classify_representation(store.conn, tmp_path, finalizable_id)
        assert still_valid.classification == "valid-ready"
    finally:
        store.close()


def test_crash_before_rename_is_finalizable_only_with_matching_hash(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        receipt = _ingest_committed(store, _item(operation="op-crash", doi="10.1000/c"))
        representation_id = receipt.representation_id
        assert representation_id is not None
        assert _state(store.conn, representation_id)[1] == "staged"
        decision = classify_representation(store.conn, tmp_path, representation_id)
        assert decision.classification == "finalizable"
        finalize_representation(store.conn, tmp_path, representation_id)
        assert classify_representation(
            store.conn, tmp_path, representation_id
        ).classification == "valid-ready"
    finally:
        store.close()


def test_missing_file_cannot_finalize(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = _ingest_committed(store, _item(operation="op-gone", doi="10.1000/g"))
        representation_id = receipt.representation_id
        assert representation_id is not None
        staged = tmp_path / "staging" / "op-gone" / f"{representation_id}.part"
        staged.unlink()
        with pytest.raises(FileIntegrityError) as caught:
            finalize_representation(store.conn, tmp_path, representation_id)
        assert caught.value.reason == "missing_bytes"
        assert _state(store.conn, representation_id)[1] == "quarantined"
        with pytest.raises(FileNotReady):
            read_ready_text(store.conn, tmp_path, representation_id)
    finally:
        store.close()


def test_hash_mismatch_cannot_finalize_or_become_ready(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        receipt = ingest_item(
            store.conn,
            _item(
                operation="op-badhash",
                doi="10.1000/bh",
                content_hash="sha256:" + ("ab" * 32),
            ),
        )
        assert receipt.status == "failed"
        assert receipt.error is not None
        assert receipt.error.startswith("FileIntegrityError:")
        assert receipt.representation_id is None
        assert store.conn.execute(
            "SELECT COUNT(*) FROM documents"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_lifecycle_never_commits_or_rolls_back_caller_transaction(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        store.conn.execute("SAVEPOINT caller")
        sentinel = ingest_item(
            store.conn, _item(operation="op-sentinel", doi="10.1000/s")
        )
        assert sentinel.status == "staged"
        assert sentinel.representation_id is not None
        assert store.conn.in_transaction
        finalize_representation(
            store.conn, tmp_path, sentinel.representation_id
        )
        assert store.conn.in_transaction
        service_src = Path("ontologylab/ingestion_service.py").read_text(
            encoding="utf-8"
        )
        assert "conn.commit(" not in service_src
        assert "conn.rollback(" not in service_src
        store.conn.execute("ROLLBACK TO SAVEPOINT caller")
        store.conn.execute("RELEASE SAVEPOINT caller")
        assert store.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 0
    finally:
        store.close()


def test_h1_planted_store_paths_cannot_be_read(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        (tmp_path / "sources.json").write_text(SENTINEL, encoding="utf-8")
        planted = ingest_item(
            store.conn,
            _item(
                operation="op-plant",
                doi="10.1000/plant",
                raw_text_path="sources.json",
                raw_text=None,
            ),
        )
        assert planted.status == "failed"
        store.conn.execute(
            "INSERT INTO documents "
            "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
            "raw_text_path, work_id, representation_state) "
            "VALUES ('rep-plant', 'upload', 'file:sources.json', 'x', 0.0, "
            "'sha256:plant', 'sources.json', NULL, 'ready')"
        )
        with pytest.raises(KGStoreError):
            store.document_raw_text("rep-plant")
        store.conn.execute(
            "INSERT INTO documents "
            "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
            "raw_text_path, work_id, representation_state) "
            "VALUES ('rep-abs', 'upload', 'file:/etc/passwd', 'x', 0.0, "
            "'sha256:abs', '/etc/passwd', NULL, 'ready')"
        )
        with pytest.raises(KGStoreError):
            store.document_raw_text("rep-abs")
    finally:
        store.close()


def test_writable_open_reconciles_staged_representation(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    receipt = _ingest_committed(store, _item())
    representation_id = receipt.representation_id
    assert representation_id is not None
    store.close()

    reopened = _open(tmp_path)
    try:
        path, state = _state(reopened.conn, representation_id)
        assert path == final_raw_text_path(representation_id)
        assert state == "ready"
        assert reopened.document_raw_text(representation_id) == BODY.decode()
    finally:
        reopened.close()


def test_document_raw_text_rechecks_hash_for_ready_file(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        receipt = _ingest_committed(store, _item())
        representation_id = receipt.representation_id
        assert representation_id is not None
        finalize_representation(store.conn, tmp_path, representation_id)
        relative, state = _state(store.conn, representation_id)
        assert state == "ready"
        (tmp_path / relative).write_text("corrupted", encoding="utf-8")

        with pytest.raises(KGStoreError, match="hash"):
            store.document_raw_text(representation_id)
    finally:
        store.close()
