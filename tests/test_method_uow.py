"""One-connection Method unit-of-work, rollback, and lifecycle tests."""
from __future__ import annotations
import json
import multiprocessing
import sqlite3
from pathlib import Path
from typing import Any
import pytest
from tests.test_method_store import (
    _api,
    _bootstrap,
    _graph_image,
    _occurrence,
    _raw_path,
    _seed,
)


def _holder(db: str, pipe: Any) -> None:
    from ontologylab.method_store import MethodStore, MethodUnitOfWork
    conn = sqlite3.connect(db, timeout=0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with MethodUnitOfWork(conn) as uow:
            MethodStore(conn, uow).upsert_gap("lock-gap", workspace_id="workspace-1",
                gap_class="required_slot_missing", target_fragment_id=None,
                field_path=None, detector_id="lock", detector_version="1",
                input_snapshot_hash="sha256:" + "3" * 64, detail={"lock": True})
            pipe.send({"state": "write_lock_acquired"})
            if pipe.recv() != "release":
                raise RuntimeError("unexpected parent signal")
        pipe.send({"state": "first_writer_success"})
    except BaseException as exc:
        pipe.send({"state": "error", "kind": type(exc).__name__, "detail": str(exc)})
    finally:
        conn.close()
        pipe.close()


def _contender(db: str, pipe: Any) -> None:
    from ontologylab.method_store import MethodBusyError, MethodUnitOfWork
    conn = sqlite3.connect(db, timeout=0)
    conn.row_factory = sqlite3.Row
    try:
        try:
            with MethodUnitOfWork(conn):
                pipe.send({"state": "unexpected_lock"})
        except MethodBusyError:
            pipe.send({"state": "typed_busy"})
    finally:
        conn.close()
        pipe.close()


def _recv(pipe: Any, timeout: float = 10.0) -> Any:
    assert pipe.poll(timeout), "bounded child-process response timed out"
    return pipe.recv()


def test_failure_after_first_method_write_rolls_back_every_row(
    tmp_path: Path,
) -> None:
    _, _, _, MethodStore, MethodUnitOfWork, _ = _api()
    store, document, text, graph_before = _seed(tmp_path)
    db = store.db_path
    try:
        _bootstrap(store, document)
        with pytest.raises(RuntimeError, match="injected after occurrence"):
            with MethodUnitOfWork(store.conn) as uow:
                method = MethodStore(store.conn, uow)
                method.import_occurrence("workspace-1", _occurrence(document, text),
                    extractor_engine="offline", extractor_model=None,
                    prompt_version="v1", decode_params={})
                raise RuntimeError("injected after occurrence before review")
        observer = sqlite3.connect(db)
        try:
            receipt = {
                "occurrence_rows": observer.execute(
                    "SELECT COUNT(*) FROM statement_occurrence").fetchone()[0],
                "review_rows": observer.execute(
                    "SELECT COUNT(*) FROM method_review_event").fetchone()[0],
                "release_rows": observer.execute(
                    "SELECT COUNT(*) FROM method_release").fetchone()[0],
            }
        finally:
            observer.close()
        print(json.dumps(receipt, sort_keys=True))
        assert receipt == {"occurrence_rows": 0, "review_rows": 0,
                           "release_rows": 0}
        assert _graph_image(store.conn) == graph_before
    finally:
        store.close()


def test_uow_rejects_ambient_nested_and_inactive_ownership(tmp_path: Path) -> None:
    _, _, StateError, MethodStore, MethodUnitOfWork, _ = _api()
    store, document, _, graph_before = _seed(tmp_path)
    try:
        uow = MethodUnitOfWork(store.conn)
        with pytest.raises(StateError, match="active"):
            MethodStore(store.conn, uow)
        store.conn.execute("BEGIN")
        with pytest.raises(StateError, match="ambient"):
            with uow:
                pass
        store.conn.rollback()
        with MethodUnitOfWork(store.conn) as owner:
            MethodStore(store.conn, owner).create_workspace("workspace-1", name="x",
                objective="x", scope={}, created_by="human")
            with pytest.raises(StateError, match="ambient|nested"):
                with MethodUnitOfWork(store.conn):
                    pass
        with pytest.raises(StateError, match="active"):
            MethodStore(store.conn, owner)
        assert _graph_image(store.conn) == graph_before
    finally:
        store.close()


def test_two_process_writer_busy_then_retry_preserves_single_review_event(
    tmp_path: Path,
) -> None:
    _, _, _, MethodStore, MethodUnitOfWork, _ = _api()
    store, document, text, graph_before = _seed(tmp_path)
    db = store.db_path
    _bootstrap(store, document)
    with MethodUnitOfWork(store.conn) as uow:
        MethodStore(store.conn, uow).import_occurrence("workspace-1",
            _occurrence(document, text), extractor_engine="offline",
            extractor_model=None, prompt_version="v1", decode_params={})
    store.close()
    ctx = multiprocessing.get_context("spawn")
    holder_parent, holder_child = ctx.Pipe()
    contender_parent, contender_child = ctx.Pipe()
    holder = ctx.Process(target=_holder, args=(str(db), holder_child))
    contender = ctx.Process(target=_contender, args=(str(db), contender_child))
    holder.start()
    try:
        assert _recv(holder_parent) == {"state": "write_lock_acquired"}
        contender.start()
        assert _recv(contender_parent) == {"state": "typed_busy"}
        contender.join(10)
        assert contender.exitcode == 0
        holder_parent.send("release")
        assert _recv(holder_parent) == {"state": "first_writer_success"}
        holder.join(10)
        assert holder.exitcode == 0
    finally:
        if contender.is_alive():
            contender.terminate()
        if holder.is_alive():
            holder.terminate()
        contender.join(10) if contender.pid is not None else None
        holder.join(10) if holder.pid is not None else None
        holder_parent.close()
        contender_parent.close()
    retry = sqlite3.connect(db, timeout=2)
    retry.row_factory = sqlite3.Row
    retry.execute("PRAGMA foreign_keys=ON")
    try:
        with MethodUnitOfWork(retry) as uow:
            MethodStore(retry, uow).decide("occurrence", "occ-1", "accepted",
                reviewer="human-1", note="bounded external retry")
        review_events = retry.execute(
            "SELECT COUNT(*) FROM method_review_event").fetchone()[0]
        receipt = {"first_writer_successes": 1, "typed_busy_contenders": 1,
                   "bounded_retry_successes": 1, "review_events": review_events}
        print(json.dumps(receipt, sort_keys=True))
        assert receipt == {"first_writer_successes": 1,
            "typed_busy_contenders": 1, "bounded_retry_successes": 1,
            "review_events": 1}
        assert _graph_image(retry) == graph_before
    finally:
        retry.close()


def test_extraction_interrupt_resume_and_exact_failure_identity(tmp_path: Path) -> None:
    _, _, StateError, MethodStore, MethodUnitOfWork, _ = _api()
    store, document, _, graph_before = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        chunks = ((0, 0, "sha256:" + "4" * 64),
                  (1, 20, "sha256:" + "5" * 64))
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            method.create_extraction_run("run-1", workspace_id="workspace-1",
                document_id=document.id, document_content_hash=document.content_hash,
                policy_snapshot_id="snapshot-1", extractor_engine="offline",
                extractor_model=None, prompt_version="v1", decode_params={},
                chunk_plan_hash="sha256:" + "6" * 64, chunks=chunks)
            method.claim_extraction_run("run-1", owner_token="owner-1")
            assert method.claim_extraction_chunk("run-1", 0, owner_token="owner-1")
            method.succeed_extraction_chunk("run-1", 0, owner_token="owner-1",
                stats={"occurrences": 1})
            assert method.claim_extraction_chunk("run-1", 1, owner_token="owner-1")
            method.interrupt_extraction_run("run-1", owner_token="owner-1",
                reason="cancelled by operator")
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            assert method.resume_extraction_run("run-1", owner_token="owner-2") == (1,)
            method.claim_extraction_run("run-1", owner_token="owner-2")
            assert method.claim_extraction_chunk("run-1", 1, owner_token="owner-2")
            method.fail_extraction_chunk("run-1", 1, owner_token="owner-2",
                error_kind="schema_validation", error_identity="bad-field:/duration")
            with pytest.raises(StateError):
                method.fail_extraction_chunk("run-1", 1, owner_token="owner-2",
                    error_kind="other", error_identity="changed")
        row = store.conn.execute("SELECT status, attempts, error_kind, error_identity "
            "FROM method_extraction_chunks WHERE run_id='run-1' AND chunk_index=1").fetchone()
        assert tuple(row) == ("failed", 2, "schema_validation", "bad-field:/duration")
        assert _graph_image(store.conn) == graph_before
    finally:
        store.close()


@pytest.mark.parametrize(
    "case", ["stale_hash", "tampered_bytes", "negative_index", "negative_offset"]
)
def test_extraction_creation_validates_source_and_chunk_coordinates(
    tmp_path: Path, case: str
) -> None:
    _, _, _, MethodStore, MethodUnitOfWork, ValidationError = _api()
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        document_hash = document.content_hash
        chunk_index = 0
        char_offset = 0
        if case == "stale_hash":
            document_hash = "sha256:" + "f" * 64
        elif case == "tampered_bytes":
            _raw_path(store, document).write_text("tampered", encoding="utf-8")
        elif case == "negative_index":
            chunk_index = -1
        else:
            char_offset = -1
        with pytest.raises(ValidationError):
            with MethodUnitOfWork(store.conn) as uow:
                MethodStore(store.conn, uow).create_extraction_run(
                    "run-invalid",
                    workspace_id="workspace-1",
                    document_id=document.id,
                    document_content_hash=document_hash,
                    policy_snapshot_id="snapshot-1",
                    extractor_engine="offline",
                    extractor_model=None,
                    prompt_version="occurrence-v1",
                    decode_params={},
                    chunk_plan_hash="sha256:" + "1" * 64,
                    chunks=(
                        (
                            chunk_index,
                            char_offset,
                            "sha256:" + "2" * 64,
                        ),
                    ),
                )
        counts = tuple(
            store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("method_extraction_runs", "method_extraction_chunks")
        )
        assert counts == (0, 0)
    finally:
        store.close()


def _create_pending_run(store: Any, document: Any) -> None:
    _, _, _, MethodStore, MethodUnitOfWork, _ = _api()
    with MethodUnitOfWork(store.conn) as uow:
        MethodStore(store.conn, uow).create_extraction_run(
            "run-1",
            workspace_id="workspace-1",
            document_id=document.id,
            document_content_hash=document.content_hash,
            policy_snapshot_id="snapshot-1",
            extractor_engine="offline",
            extractor_model=None,
            prompt_version="occurrence-v1",
            decode_params={},
            chunk_plan_hash="sha256:" + "1" * 64,
            chunks=((0, 0, "sha256:" + "2" * 64),),
        )


def test_claim_rejects_failed_and_interrupted_states(tmp_path: Path) -> None:
    _, _, StateError, MethodStore, MethodUnitOfWork, _ = _api()
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        _create_pending_run(store, document)
        for status in ("failed", "interrupted"):
            store.conn.execute(
                "UPDATE method_extraction_runs SET status=?, "
                "error_kind='probe', error_identity='stale' WHERE id='run-1'",
                (status,),
            )
            store.conn.commit()
            with pytest.raises(StateError, match="cannot be claimed"):
                with MethodUnitOfWork(store.conn) as uow:
                    MethodStore(store.conn, uow).claim_extraction_run(
                        "run-1", owner_token="owner-1"
                    )
    finally:
        store.close()


def test_resume_then_claim_clears_stale_run_errors(tmp_path: Path) -> None:
    _, _, _, MethodStore, MethodUnitOfWork, _ = _api()
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        _create_pending_run(store, document)
        store.conn.execute(
            "UPDATE method_extraction_runs SET status='failed', "
            "error_kind='schema_validation', error_identity='bad-field' "
            "WHERE id='run-1'"
        )
        store.conn.commit()
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            assert method.resume_extraction_run(
                "run-1", owner_token="owner-1"
            ) == (0,)
            resumed = store.conn.execute(
                "SELECT status, owner_token, error_kind, error_identity "
                "FROM method_extraction_runs WHERE id='run-1'"
            ).fetchone()
            assert tuple(resumed) == (
                "resumed",
                None,
                "schema_validation",
                "bad-field",
            )
            method.claim_extraction_run("run-1", owner_token="owner-1")
            running = store.conn.execute(
                "SELECT status, owner_token, error_kind, error_identity "
                "FROM method_extraction_runs WHERE id='run-1'"
            ).fetchone()
            assert tuple(running) == ("running", "owner-1", None, None)
    finally:
        store.close()


def test_method_uow_is_permanently_spent_after_first_exit(tmp_path: Path) -> None:
    _, _, StateError, MethodStore, MethodUnitOfWork, _ = _api()
    store, _, _, _ = _seed(tmp_path)
    try:
        uow = MethodUnitOfWork(store.conn)
        with uow:
            MethodStore(store.conn, uow).create_workspace(
                "workspace-1",
                name="Heat method",
                objective="Heat safely",
                scope={"material": "sample"},
                created_by="reviewer-1",
            )
        with pytest.raises(StateError, match="spent"):
            with uow:
                pass
    finally:
        store.close()


def test_commit_failure_rolls_back_and_spends_owner(tmp_path: Path) -> None:
    from ontologylab.method_store import MethodStateError, MethodStore, MethodUnitOfWork

    store, _, _, graph_before = _seed(tmp_path)
    owner = MethodUnitOfWork(store.conn)
    denied = 0
    transactions: list[str | None] = []

    def authorize(
        action: int, first: str | None, second: str | None,
        database: str | None, trigger: str | None,
    ) -> int:
        nonlocal denied
        if action == sqlite3.SQLITE_TRANSACTION:
            transactions.append(first)
            if first == "COMMIT" and denied == 0:
                denied += 1
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    try:
        store.conn.set_authorizer(authorize)
        with pytest.raises(sqlite3.DatabaseError, match="not authorized") as caught:
            with owner:
                MethodStore(store.conn, owner).create_workspace(
                    "denied-workspace", name="Denied commit", objective="Rollback",
                    scope={}, created_by="human-1",
                )
        store.conn.set_authorizer(None)
        observed = {
            "in_transaction": store.conn.in_transaction,
            "workspace_rows": store.conn.execute(
                "SELECT COUNT(*) FROM method_workspace WHERE id='denied-workspace'"
            ).fetchone()[0],
            "active": owner.active,
            "owns_connection": owner.owns(store.conn),
            "denied_commits": denied,
        }
        print(json.dumps(observed, sort_keys=True))
        assert observed == {
            "in_transaction": False, "workspace_rows": 0,
            "active": False, "owns_connection": False, "denied_commits": 1,
        }, "failed COMMIT must be rolled back before external test cleanup"
        assert getattr(caught.value, "sqlite_errorcode", None) == sqlite3.SQLITE_AUTH
        assert caught.value.__cause__ is None
        assert transactions == ["BEGIN", "COMMIT", "ROLLBACK"]
        with pytest.raises(MethodStateError, match="spent"):
            with owner:
                pass
        with MethodUnitOfWork(store.conn) as fresh:
            MethodStore(store.conn, fresh).create_workspace(
                "fresh-workspace", name="Fresh owner", objective="Reuse",
                scope={}, created_by="human-1",
            )
        assert store.conn.in_transaction is False
        assert [row[0] for row in store.conn.execute(
            "SELECT id FROM method_workspace ORDER BY id"
        )] == ["fresh-workspace"]
        assert _graph_image(store.conn) == graph_before
    finally:
        store.conn.set_authorizer(None)
        store.conn.rollback()
        store.close()


@pytest.mark.parametrize("body_failure", [False, True])
def test_workspace_uow_preserves_success_and_body_error(
    tmp_path: Path, body_failure: bool,
) -> None:
    from ontologylab.method_store import MethodStore, MethodUnitOfWork

    store, _, _, graph_before = _seed(tmp_path)
    owner = MethodUnitOfWork(store.conn)
    failure = RuntimeError("controlled workspace body failure")
    try:
        try:
            with owner:
                MethodStore(store.conn, owner).create_workspace(
                    "workspace-control", name="Control", objective="Keep semantics",
                    scope={}, created_by="human-1",
                )
                if body_failure:
                    raise failure
        except RuntimeError as caught:
            assert body_failure and caught is failure
        else:
            assert not body_failure
        assert store.conn.in_transaction is False
        assert owner.active is False
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_workspace WHERE id='workspace-control'"
        ).fetchone()[0] == (0 if body_failure else 1)
        assert _graph_image(store.conn) == graph_before
    finally:
        store.conn.rollback()
        store.close()
