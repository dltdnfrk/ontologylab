from __future__ import annotations

import asyncio
from pathlib import Path
from collections.abc import Iterator

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.method_ir import IRValidationError
from ontologylab.models import Document
from ontologylab.extractor import Chunk
from ontologylab.method_store import (
    MethodConflictError,
    MethodStateError,
    MethodStore,
    MethodUnitOfWork,
)
from ontologylab.safety import KillSwitch
from test_method_extract import SpyEngine, extraction_counts, seed_store


class _RuntimeFailureEngine(SpyEngine):
    async def generate(
        self, prompt: str, *, model: str | None,
    ) -> tuple[str, dict[str, object]]:
        if self.calls == 1:
            self.calls += 1
            self.models.append(model)
            raise RuntimeError("independent engine fault")
        return await super().generate(prompt, model=model)


class _ParserFailureEngine(SpyEngine):
    async def generate(
        self, prompt: str, *, model: str | None,
    ) -> tuple[str, dict[str, object]]:
        if self.calls == 1:
            self.calls += 1
            self.models.append(model)
            return "not fenced json", {"calls": 1}
        return await super().generate(prompt, model=model)


class _DuplicateIdentityEngine(SpyEngine):
    async def generate(
        self, prompt: str, *, model: str | None,
    ) -> tuple[str, dict[str, object]]:
        raw, stats = await super().generate(prompt, model=model)
        marker = '"id": "'
        start = raw.index(marker) + len(marker)
        end = raw.index('"', start)
        return raw[:start] + "occ-duplicate" + raw[end:], stats


class _ProcessKillSentinel(BaseException):
    pass


class _ProcessKillEngine(SpyEngine):
    async def generate(
        self, prompt: str, *, model: str | None,
    ) -> tuple[str, dict[str, object]]:
        self.calls += 1
        self.models.append(model)
        raise _ProcessKillSentinel("process terminated outside cleanup")


def _resume_observer(store: KGStore) -> bytes:
    with MethodUnitOfWork(store.conn) as uow:
        return MethodStore(store.conn, uow).read_snapshot(
            "workspace-1"
        ).canonical_json


def _extraction_rows(
    store: KGStore,
) -> tuple[
    tuple[object, ...],
    tuple[tuple[object, ...], ...],
    tuple[str, ...],
]:
    run = store.conn.execute(
        "SELECT status, owner_token, error_kind, error_identity "
        "FROM method_extraction_runs WHERE id='run-ordinary'"
    ).fetchone()
    assert run is not None
    chunks = store.conn.execute(
        "SELECT chunk_index, status, owner_token, attempts, "
        "error_kind, error_identity FROM method_extraction_chunks "
        "WHERE run_id='run-ordinary' ORDER BY chunk_index"
    ).fetchall()
    occurrences = store.conn.execute(
        "SELECT id FROM statement_occurrence ORDER BY id"
    ).fetchall()
    return (
        tuple(run),
        tuple(tuple(row) for row in chunks),
        tuple(row[0] for row in occurrences),
    )


@pytest.fixture
def interrupted_run(
    tmp_path: Path,
) -> Iterator[tuple[KGStore, Document]]:
    from ontologylab.method_extract import extract_occurrences

    store, document = seed_store(tmp_path)
    kill_path = tmp_path / "KILL"
    kill_path.write_text("", encoding="utf-8")
    with pytest.raises(MethodStateError, match="kill switch"):
        asyncio.run(extract_occurrences(
            store, workspace_id="workspace-1", document_id=document.id,
            policy_snapshot_id="snapshot-1", engine=SpyEngine(),
            processor="spy", region="local", owner_token="owner-initial",
            model="model-initial", decode_params={"temperature": 0},
            run_id="run-1", kill_switch=KillSwitch(str(tmp_path)),
        ))
    kill_path.unlink()
    yield store, document
    store.close()


def _assert_resume_refused(
    fixture: tuple[KGStore, Document], *, engine: SpyEngine | None = None,
    policy_snapshot_id: str = "snapshot-1", processor: str = "spy",
    region: str = "local", model: str = "model-initial", temperature: int = 0,
) -> None:
    from ontologylab.method_extract import extract_occurrences

    store, document = fixture
    engine = engine or SpyEngine()
    before = _resume_observer(store)
    with pytest.raises(MethodStateError):
        asyncio.run(extract_occurrences(
            store, workspace_id="workspace-1", document_id=document.id,
            policy_snapshot_id=policy_snapshot_id, engine=engine,
            processor=processor, region=region, owner_token="owner-resume",
            model=model, decode_params={"temperature": temperature},
            run_id="run-1", resume=True,
        ))
    assert (engine.calls, _resume_observer(store)) == (0, before)


def test_rights_blocked_before_engine_and_all_writes(tmp_path: Path) -> None:
    from ontologylab.method_extract import extract_occurrences

    store, document = seed_store(tmp_path, "denied")
    engine = SpyEngine()
    try:
        with pytest.raises(MethodStateError, match="resolved"):
            asyncio.run(extract_occurrences(
                store, workspace_id="workspace-1", document_id=document.id,
                policy_snapshot_id="snapshot-1", engine=engine,
                processor="spy", region="local", owner_token="owner-1",
            ))
        assert engine.calls == 0
        assert extraction_counts(store) == (0, 0, 0)
    finally:
        store.close()


def test_injection_source_denied_without_calls_or_writes(tmp_path: Path) -> None:
    from ontologylab.method_extract import extract_occurrences

    store, document = seed_store(tmp_path, "discovery_only")
    engine = SpyEngine()
    try:
        with pytest.raises(MethodStateError):
            asyncio.run(extract_occurrences(
                store, workspace_id="workspace-1", document_id=document.id,
                policy_snapshot_id="snapshot-1", engine=engine,
                processor="spy", region="local", owner_token="owner-1",
            ))
        assert (engine.calls, extraction_counts(store)) == (0, (0, 0, 0))
    finally:
        store.close()


def test_malformed_output_is_stored_nowhere(tmp_path: Path) -> None:
    from ontologylab.method_extract import extract_occurrences

    store, document = seed_store(tmp_path)
    class MalformedEngine(SpyEngine):
        async def generate(
            self, prompt: str, *, model: str | None,
        ) -> tuple[str, dict[str, object]]:
            self.calls += 1
            return "not fenced json", {"calls": 1}

    engine = MalformedEngine()
    try:
        with pytest.raises(IRValidationError):
            asyncio.run(extract_occurrences(
                store, workspace_id="workspace-1", document_id=document.id,
                policy_snapshot_id="snapshot-1", engine=engine,
                processor="spy", region="local", owner_token="owner-1",
            ))
        assert extraction_counts(store)[2] == 0
    finally:
        store.close()


@pytest.mark.parametrize(
    ("engine_type", "error_type", "error_kind", "error_text", "error_identity"),
    [
        (
            _RuntimeFailureEngine,
            RuntimeError,
            "RuntimeError",
            "independent engine fault",
            "sha256:26c0d6fbf4bc6bc5aae36b7689394e8b"
            "b3b2351564aeb76c17fd5aa4d0bd99e4",
        ),
        (
            _ParserFailureEngine,
            IRValidationError,
            "IRValidationError",
            "method-occurrence-v1: output must be one exact fenced JSON block",
            "sha256:84c584d1219e0faaadc7e6e2fb633b52"
            "91dea79a741716d6867ea8a6263a5740",
        ),
        (
            _DuplicateIdentityEngine,
            MethodConflictError,
            "MethodConflictError",
            "occurrence identity already exists",
            "sha256:6c886f7a9be3eea4ad47a3db2214cea"
            "5b446e0fc4357c875361847b17803009c",
        ),
    ],
    ids=["engine", "parser", "persistence"],
)
def test_ordinary_failure_marks_retryable_state_and_exact_resume_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine_type: type[SpyEngine],
    error_type: type[Exception],
    error_kind: str,
    error_text: str,
    error_identity: str,
) -> None:
    from ontologylab import method_extract
    from ontologylab.method_extract import extract_occurrences

    store, document = seed_store(tmp_path)
    database = store.db_path
    text = store.document_raw_text(document.id)
    second = "Hold for ten minutes."
    monkeypatch.setattr(
        method_extract,
        "chunk_document",
        lambda _raw: [
            Chunk(0, 0, "Heat sample to 80 C."),
            Chunk(1, text.index(second), second),
        ],
    )
    failure_persistence_calls = 0
    fail_extraction = MethodStore.fail_extraction_chunk

    def count_failure_persistence(
        method: MethodStore,
        run_id: str,
        chunk_index: int,
        *,
        owner_token: str,
        error_kind: str,
        error_identity: str,
    ) -> None:
        nonlocal failure_persistence_calls
        failure_persistence_calls += 1
        fail_extraction(
            method,
            run_id,
            chunk_index,
            owner_token=owner_token,
            error_kind=error_kind,
            error_identity=error_identity,
        )

    monkeypatch.setattr(
        MethodStore, "fail_extraction_chunk", count_failure_persistence
    )
    engine = engine_type()
    try:
        with pytest.raises(error_type) as raised:
            asyncio.run(extract_occurrences(
                store, workspace_id="workspace-1", document_id=document.id,
                policy_snapshot_id="snapshot-1", engine=engine,
                processor="spy", region="local", owner_token="owner-failure",
                run_id="run-ordinary",
            ))
        assert type(raised.value) is error_type
        assert str(raised.value) == error_text
        before_reopen = _extraction_rows(store)
    finally:
        store.close()

    expected_chunks = (
        (0, "succeeded", None, 1, None, None),
        (1, "failed", None, 1, error_kind, error_identity),
    )
    assert engine.calls == 2
    assert failure_persistence_calls == 1
    assert before_reopen[0] == ("failed", None, error_kind, error_identity)
    assert before_reopen[1] == expected_chunks
    assert len(before_reopen[2]) == 1

    reopened = KGStore.open(database)
    try:
        assert _extraction_rows(reopened) == before_reopen
        resume_engine = SpyEngine()
        assert asyncio.run(extract_occurrences(
            reopened, workspace_id="workspace-1", document_id=document.id,
            policy_snapshot_id="snapshot-1", engine=resume_engine,
            processor="spy", region="local", owner_token="owner-resume",
            run_id="run-ordinary", resume=True,
        )) == "run-ordinary"
        final = _extraction_rows(reopened)
        assert resume_engine.calls == 1
        assert final[0] == ("succeeded", None, None, None)
        assert final[1] == (
            expected_chunks[0],
            (1, "succeeded", None, 2, None, None),
        )
        assert len(final[2]) == len(set(final[2])) == 2
        assert failure_persistence_calls == 1
    finally:
        reopened.close()


def test_failure_persistence_error_keeps_original_exception_outermost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ontologylab import method_extract
    from ontologylab.method_extract import extract_occurrences

    store, document = seed_store(tmp_path)
    text = store.document_raw_text(document.id)
    second = "Hold for ten minutes."
    monkeypatch.setattr(
        method_extract,
        "chunk_document",
        lambda _raw: [
            Chunk(0, 0, "Heat sample to 80 C."),
            Chunk(1, text.index(second), second),
        ],
    )
    failure_persistence_calls = 0

    def fail_persistence(
        _method: MethodStore,
        _run_id: str,
        _chunk_index: int,
        *,
        owner_token: str,
        error_kind: str,
        error_identity: str,
    ) -> None:
        nonlocal failure_persistence_calls
        failure_persistence_calls += 1
        assert owner_token == "owner-failure"
        assert error_kind == "RuntimeError"
        assert error_identity.endswith("d0bd99e4")
        raise MethodStateError("failure persistence unavailable")

    monkeypatch.setattr(MethodStore, "fail_extraction_chunk", fail_persistence)
    try:
        with pytest.raises(RuntimeError) as raised:
            asyncio.run(extract_occurrences(
                store, workspace_id="workspace-1", document_id=document.id,
                policy_snapshot_id="snapshot-1",
                engine=_RuntimeFailureEngine(), processor="spy",
                region="local", owner_token="owner-failure",
                run_id="run-ordinary",
            ))
        assert str(raised.value) == "independent engine fault"
        assert type(raised.value.__cause__) is MethodStateError
        assert str(raised.value.__cause__) == "failure persistence unavailable"
        assert failure_persistence_calls == 1
        assert _extraction_rows(store)[:2] == (
            ("running", "owner-failure", None, None),
            (
                (0, "succeeded", None, 1, None, None),
                (1, "running", "owner-failure", 1, None, None),
            ),
        )
    finally:
        store.close()


def test_base_exception_escapes_without_python_cleanup(tmp_path: Path) -> None:
    from ontologylab.method_extract import extract_occurrences

    store, document = seed_store(tmp_path)
    database = store.db_path
    engine = _ProcessKillEngine()
    try:
        with pytest.raises(_ProcessKillSentinel) as raised:
            asyncio.run(extract_occurrences(
                store, workspace_id="workspace-1", document_id=document.id,
                policy_snapshot_id="snapshot-1", engine=engine,
                processor="spy", region="local", owner_token="owner-process",
                run_id="run-ordinary",
            ))
        assert str(raised.value) == "process terminated outside cleanup"
        before_reopen = _extraction_rows(store)
    finally:
        store.close()

    assert engine.calls == 1
    assert before_reopen == (
        ("running", "owner-process", None, None),
        ((0, "running", "owner-process", 1, None, None),),
        (),
    )
    reopened = KGStore.open(database)
    try:
        assert _extraction_rows(reopened) == before_reopen
    finally:
        reopened.close()


def test_cancellation_after_claim_interrupts_and_resume_deduplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ontologylab import method_extract
    from ontologylab.method_extract import extract_occurrences

    store, document = seed_store(tmp_path)
    claimed = asyncio.Event()
    engine = SpyEngine(block=claimed, block_on_call=2)
    text = store.document_raw_text(document.id)
    second = "Hold for ten minutes."
    monkeypatch.setattr(
        method_extract, "chunk_document",
        lambda raw: [
            Chunk(0, 0, "Heat sample to 80 C."),
            Chunk(1, text.index(second), second),
        ],
    )

    async def scenario() -> str:
        task = asyncio.create_task(extract_occurrences(
            store, workspace_id="workspace-1", document_id=document.id,
            policy_snapshot_id="snapshot-1", engine=engine,
            processor="spy", region="local", owner_token="owner-1",
            run_id="run-1",
        ))
        await asyncio.wait_for(claimed.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = store.conn.execute(
            "SELECT status FROM method_extraction_runs WHERE id='run-1'"
        ).fetchone()
        assert row[0] == "interrupted"
        engine.block = None
        return await extract_occurrences(
            store, workspace_id="workspace-1", document_id=document.id,
            policy_snapshot_id="snapshot-1", engine=engine,
            processor="spy", region="local", owner_token="owner-2",
            run_id="run-1", resume=True,
        )

    try:
        assert asyncio.run(scenario()) == "run-1"
        assert engine.calls == 3
        assert extraction_counts(store)[2] == 2
    finally:
        store.close()


@pytest.mark.parametrize(
    ("processor", "region"),
    [("forbidden-processor", "local"), ("spy", "forbidden-region")],
)
def test_resume_rejects_processor_or_region_not_allowed_before_engine(
    interrupted_run: tuple[KGStore, Document],
    processor: str,
    region: str,
) -> None:
    _assert_resume_refused(interrupted_run, processor=processor, region=region)


@pytest.mark.parametrize(
    ("snapshot_id", "status"),
    [
        ("snapshot-denied", "denied"),
        ("snapshot-missing", None),
        ("snapshot-different", "resolved"),
    ],
)
def test_resume_rejects_policy_snapshot_mismatch_before_engine(
    interrupted_run: tuple[KGStore, Document],
    snapshot_id: str,
    status: str | None,
) -> None:
    store, document = interrupted_run
    if status:
        with MethodUnitOfWork(store.conn) as uow:
            MethodStore(store.conn, uow).create_document_policy_snapshot(
                snapshot_id, document_id=document.id,
                document_content_hash=document.content_hash,
                source_policy_id="policy-1", resolution_status=status,
                resolved_by="reviewer",
            )
    _assert_resume_refused(interrupted_run, policy_snapshot_id=snapshot_id)


@pytest.mark.parametrize("drift", ["engine", "model", "decode"])
def test_resume_rejects_engine_model_or_decode_drift_before_engine(
    interrupted_run: tuple[KGStore, Document],
    drift: str,
) -> None:
    _assert_resume_refused(
        interrupted_run,
        engine=SpyEngine(engine_name="other" if drift == "engine" else "spy"),
        model="model-resume" if drift == "model" else "model-initial",
        temperature=1 if drift == "decode" else 0,
    )


def test_resume_rejects_prompt_version_drift_before_engine(
    interrupted_run: tuple[KGStore, Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ontologylab import method_extract

    monkeypatch.setattr(method_extract, "PROMPT_VERSION", "method-occurrence-v2")
    _assert_resume_refused(interrupted_run)


@pytest.mark.parametrize(
    "drift", ["document", "offset", "text", "index", "count"],
)
def test_resume_rejects_chunk_plan_or_chunk_metadata_drift_before_engine(
    interrupted_run: tuple[KGStore, Document],
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    from ontologylab import method_extract

    store, document = interrupted_run
    if drift == "document":
        original = store.document_raw_text(document.id)
        monkeypatch.setattr(store, "document_raw_text",
                            lambda document_id: original + "!")
    else:
        plans = {
            "offset": lambda raw: [Chunk(0, 1, raw)],
            "text": lambda raw: [Chunk(0, 0, raw[1:])],
            "index": lambda raw: [Chunk(1, 0, raw)],
            "count": lambda raw: [Chunk(0, 0, raw),
                                  Chunk(1, len(raw), raw[:1])],
        }
        monkeypatch.setattr(method_extract, "chunk_document", plans[drift])
    _assert_resume_refused(interrupted_run)
