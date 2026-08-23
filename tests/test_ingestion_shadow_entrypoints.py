"""Wave 2.1 Step 6D: production entrypoints share one shadow adapter."""

from __future__ import annotations

import io
import json
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from ontologylab.connectors.base import RawDocument
from ontologylab.ingestion import ingest_documents
from ontologylab.ingestion_shadow import (
    FULL_V2_AUTHORITY,
    MAX_SHADOW_BATCH,
    SAMPLE_OPERATION_KEY,
    SAMPLE_SOURCE_URI,
    SHADOW_MODE,
    ShadowBatchBoundError,
    load_shadow_queue,
    shadow_persist,
)
from ontologylab.kgstore import KGStore
from ontologylab.main import main
from ontologylab.paths import kg_db_path
from ontologylab.provenance import Provenance
from ontologylab.provenance_outbox import load_outbox_events
from ontologylab.server.routes import SAMPLE_DOC_TEXT, SAMPLE_DOC_TITLE


SECRET = "ELS-must-never-surface-9f3a"


def _open(data_dir: Path) -> KGStore:
    data_dir.mkdir(parents=True, exist_ok=True)
    return KGStore.open(kg_db_path(data_dir))


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _raw(
    *,
    uri: str,
    text: str,
    title: str = "Shadow",
    doi: str | None = None,
    source: str = "upload",
    source_kind: str = "upload",
) -> RawDocument:
    return RawDocument(
        source_kind=source_kind,
        source_uri=uri,
        title=title,
        raw_text=text,
        doi=doi,
        source=source,
        evidence_grade="C",
    )


def _provenance(tmp_path: Path, name: str = "collect-shadow") -> Provenance:
    return Provenance(str(tmp_path / "jobs" / name), seed=0)


def _cli_collect(data_dir: Path, fixture: Path) -> int:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            main(
                [
                    "collect",
                    "--file",
                    str(fixture),
                    "--data-dir",
                    str(data_dir),
                ]
            )
            return 0
        except SystemExit as exc:
            return 0 if exc.code is None else int(exc.code)


def _client(tmp_path: Path, data_dir: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    return TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))


def _function_source(path: Path, func_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    needle = f"def {func_name}("
    start = text.find(needle)
    assert start != -1, f"{func_name} missing from {path}"
    depth = 0
    end = len(text)
    for index, line in enumerate(text[start:].splitlines(keepends=True)):
        if index > 0 and line.startswith("def ") and depth == 0:
            break
        depth += line.count("(") - line.count(")")
        end = start + sum(
            len(chunk)
            for chunk in text[start:].splitlines(keepends=True)[: index + 1]
        )
    return text[start:end]


def test_adapter_is_legacy_compatible_shadow_not_full_v2() -> None:
    assert SHADOW_MODE == "legacy_compatible"
    assert FULL_V2_AUTHORITY is False
    assert MAX_SHADOW_BATCH == 100
    assert SAMPLE_SOURCE_URI == "sample://onboarding/order-system"
    assert SAMPLE_OPERATION_KEY == (
        "collect.sample:sample://onboarding/order-system"
    )


def test_cli_collect_traverses_adapter_and_mirrors_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ontologylab.ingestion_shadow as shadow

    calls: list[int] = []
    real = shadow.shadow_persist

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(shadow, "shadow_persist", wrapped)

    data_dir = tmp_path / "cli-data"
    data_dir.mkdir()
    fixture = tmp_path / "cli-notes.md"
    fixture.write_text(
        "The PaymentGateway validates cards through the FraudDetector.\n",
        encoding="utf-8",
    )
    assert _cli_collect(data_dir, fixture) == 0
    assert calls == [1]

    store = KGStore.open(kg_db_path(data_dir), read_only=True)
    try:
        docs = store.list_documents()
        assert len(docs) == 1
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "provenance_outbox") == 1
        assert _count(store.conn, "works") == 1
        assert store.document_raw_text(docs[0].id).startswith("The PaymentGateway")
    finally:
        store.close()


def test_http_collect_preserves_legacy_shape_and_mirrors_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ontologylab.ingestion_shadow as shadow

    calls: list[int] = []
    real = shadow.shadow_persist

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(shadow, "shadow_persist", wrapped)

    data_dir = tmp_path / "http-data"
    data_dir.mkdir()
    fixture = tmp_path / "http-notes.md"
    fixture.write_text("The RateLimiter implements the TokenBucketAlgorithm.\n")
    with _client(tmp_path, data_dir) as client:
        response = client.post("/api/collect", json={"files": [str(fixture)]})
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": True,
        "documents": 1,
        "created": 1,
        "duplicates": 0,
    }
    assert calls == [1]

    store = KGStore.open(kg_db_path(data_dir), read_only=True)
    try:
        assert _count(store.conn, "documents") == 1
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "provenance_outbox") == 1
    finally:
        store.close()


def test_research_worker_ingestion_uses_the_same_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs_src = Path("ontologylab/server/jobs.py").read_text(encoding="utf-8")
    assert "result = ingest_documents(store, raw_docs, provenance)" in jobs_src
    persist_region = jobs_src.split("if job._cancelled.is_set():", 2)[-1]
    assert "store.insert_document(" not in persist_region

    import ontologylab.ingestion_shadow as shadow

    calls: list[int] = []
    real = shadow.shadow_persist

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(shadow, "shadow_persist", wrapped)

    data_dir = tmp_path / "research-data"
    store = _open(data_dir)
    try:
        result = ingest_documents(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/research.one",
                    text="The RiskEngine reports to the FraudDetector.\n",
                    title="Research paper",
                    doi="10.1000/research.one",
                    source="crossref",
                    source_kind="paper_api",
                )
            ],
            _provenance(tmp_path, "research-1"),
        )
        assert result.created_count == 1
        assert calls == [1]
        docs = store.list_documents()
        assert docs[0].doi == "10.1000/research.one"
        assert _count(store.conn, "work_identifiers") == 1
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "provenance_outbox") == 1
        identifier = store.conn.execute(
            "SELECT scheme, normalized_value FROM work_identifiers"
        ).fetchone()
        assert tuple(identifier) == ("doi", "10.1000/research.one")
    finally:
        store.close()


def test_collect_sample_keeps_uri_and_mirrors_through_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ontologylab.ingestion_shadow as shadow

    calls: list[str] = []
    real = shadow.shadow_persist

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        operation = kwargs.get("operation_id")
        calls.append(str(operation))
        return real(*args, **kwargs)

    monkeypatch.setattr(shadow, "shadow_persist", wrapped)
    insert_calls: list[str] = []
    real_insert = KGStore.insert_document

    def insert_wrapped(self: KGStore, *args: Any, **kwargs: Any) -> Any:
        insert_calls.append("insert_document")
        return real_insert(self, *args, **kwargs)

    monkeypatch.setattr(KGStore, "insert_document", insert_wrapped)

    sample_src = _function_source(
        Path("ontologylab/server/routes.py"), "collect_sample"
    )
    assert "insert_document" not in sample_src
    assert "ingest_sample" in sample_src or "shadow_ingest_sample" in sample_src

    data_dir = tmp_path / "sample-data"
    data_dir.mkdir()
    with _client(tmp_path, data_dir) as client:
        first = client.post("/api/collect/sample")
        again = client.post("/api/collect/sample")
    assert first.status_code == 200
    body = first.json()
    assert body["ok"] is True
    assert body["created"] is True
    assert body["title"] == SAMPLE_DOC_TITLE
    assert again.json()["created"] is False
    assert again.json()["document_id"] == body["document_id"]
    assert insert_calls == []
    assert calls == [SAMPLE_OPERATION_KEY, SAMPLE_OPERATION_KEY]

    store = KGStore.open(kg_db_path(data_dir), read_only=True)
    try:
        docs = store.list_documents()
        assert len(docs) == 1
        assert docs[0].source_uri == SAMPLE_SOURCE_URI
        assert docs[0].id == body["document_id"]
        assert store.document_raw_text(docs[0].id) == SAMPLE_DOC_TEXT
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "provenance_outbox") == 1
        key = store.conn.execute(
            "SELECT idempotency_key FROM document_observations"
        ).fetchone()
        assert key is not None
        assert SAMPLE_OPERATION_KEY in str(key[0])
    finally:
        store.close()


def test_four_entrypoints_share_one_adapter_symbol() -> None:
    main_src = Path("ontologylab/main.py").read_text(encoding="utf-8")
    routes_src = Path("ontologylab/server/routes.py").read_text(encoding="utf-8")
    jobs_src = Path("ontologylab/server/jobs.py").read_text(encoding="utf-8")
    ingest_src = Path("ontologylab/ingestion.py").read_text(encoding="utf-8")
    assert "ingest_documents(" in _function_source(
        Path("ontologylab/main.py"), "cmd_collect"
    )
    assert "ingest_documents(" in _function_source(
        Path("ontologylab/server/routes.py"), "collect"
    )
    assert "ingest_documents(" in jobs_src
    assert "shadow_persist" in ingest_src
    assert "insert_document" not in _function_source(
        Path("ontologylab/ingestion.py"), "ingest_documents"
    )
    assert "shadow_persist" in Path("ontologylab/ingestion_shadow.py").read_text(
        encoding="utf-8"
    )
    del main_src, routes_src


def test_installed_cli_collect_writes_legacy_row_and_observation(
    tmp_path: Path,
) -> None:
    from tests.wave21.surface import run_installed_cli

    data_dir = tmp_path / "installed-data"
    data_dir.mkdir()
    fixture = tmp_path / "installed-notes.md"
    fixture.write_text(
        "The OrderService writes to the OrderDatabase.\n", encoding="utf-8"
    )
    collected = run_installed_cli(
        "collect", "--file", str(fixture), "--data-dir", str(data_dir)
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    store = KGStore.open(kg_db_path(data_dir), read_only=True)
    try:
        assert len(store.list_documents()) == 1
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "provenance_outbox") == 1
    finally:
        store.close()


def test_representable_outcome_has_matching_observation_and_outbox(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path / "rep")
    try:
        result = shadow_persist(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/shadow.one",
                    text="abstract one",
                    doi="10.1000/shadow.one",
                    source="crossref",
                    source_kind="paper_api",
                )
            ],
            _provenance(tmp_path, "op-rep"),
            operation_id="op-rep",
        )
        assert result.created_count == 1
        doc = result.entries[0].document
        observation = store.conn.execute(
            "SELECT id, representation_id FROM document_observations"
        ).fetchone()
        assert observation is not None
        assert observation[1] == doc.id
        events = load_outbox_events(store.conn)
        assert len(events) == 1
        payload = json.loads(events[0].payload_json)
        assert payload["observation_id"] == observation[0]
        assert payload["representation_id"] == doc.id
        assert doc.doi == "10.1000/shadow.one"
        linked = store.conn.execute(
            "SELECT work_id FROM documents WHERE id = ?", (doc.id,)
        ).fetchone()
        assert linked is not None and linked[0]
    finally:
        store.close()


def test_richer_same_doi_new_bytes_is_queued_not_second_representation(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path / "richer")
    try:
        first = ingest_documents(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/richer",
                    text="short abstract",
                    doi="10.1000/richer",
                    source="crossref",
                    source_kind="paper_api",
                )
            ],
            _provenance(tmp_path, "richer-1"),
        )
        second = ingest_documents(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/richer",
                    text="short abstract plus full text that is richer",
                    doi="10.1000/richer",
                    source="crossref",
                    source_kind="paper_api",
                )
            ],
            _provenance(tmp_path, "richer-2"),
        )
        assert first.created_count == 1
        assert second.created_count == 0
        assert second.document_count == 1
        assert second.entries[0].document.id == first.entries[0].document.id
        assert len(store.list_documents()) == 1
        assert store.document_raw_text(first.entries[0].document.id) == (
            "short abstract"
        )
        queued = load_shadow_queue(store.conn)
        assert len(queued) == 1
        assert queued[0].reason == "richer"
        assert queued[0].status == "queued"
        assert "full text that is richer" in queued[0].payload_json
        assert _count(store.conn, "documents") == 1
        assert FULL_V2_AUTHORITY is False
    finally:
        store.close()


def test_conflicting_different_doi_same_bytes_is_queued_and_typed(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path / "conflict")
    try:
        shared = "Identical body shared by two distinct registered works."
        result = ingest_documents(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/seam.a",
                    text=shared,
                    doi="10.1000/seam.a",
                    source="crossref",
                    source_kind="paper_api",
                ),
                _raw(
                    uri="https://doi.org/10.1000/seam.b",
                    text=shared,
                    doi="10.1000/seam.b",
                    source="crossref",
                    source_kind="paper_api",
                ),
                _raw(
                    uri="https://doi.org/10.1000/seam.c",
                    text="A different body entirely.",
                    doi="10.1000/seam.c",
                    source="crossref",
                    source_kind="paper_api",
                ),
            ],
            _provenance(tmp_path, "conflict-batch"),
        )
        assert result.document_count == 2
        assert result.created_count == 2
        assert len(result.conflicts) == 1
        assert result.conflicts[0].incoming_doi == "10.1000/seam.b"
        assert result.conflicts[0].existing_doi == "10.1000/seam.a"
        assert len(store.list_documents()) == 2
        queued = load_shadow_queue(store.conn)
        assert any(item.reason == "conflict" for item in queued)
        schemes = {
            row[0]
            for row in store.conn.execute(
                "SELECT scheme FROM work_identifiers"
            )
        }
        assert "content_hash" not in schemes
        hashes = {
            row[0]
            for row in store.conn.execute(
                "SELECT normalized_value FROM work_identifiers"
            )
        }
        assert not any(value.startswith("sha256:") for value in hashes)
        assert _count(store.conn, "document_observations") == 2
    finally:
        store.close()


def test_doi_spellings_canonicalize_to_one_work(tmp_path: Path) -> None:
    store = _open(tmp_path / "canon")
    try:
        spellings = (
            "10.1000/Foo",
            "10.1000/foo",
            "https://doi.org/10.1000/foo",
            "10.1000/foo ",
            " 10.1000/foo",
        )
        last = None
        for index, spelling in enumerate(spellings):
            last = ingest_documents(
                store,
                [
                    _raw(
                        uri=f"https://example.invalid/{index}",
                        text=f"same paper body {index}",
                        doi=spelling,
                        source="crossref",
                        source_kind="paper_api",
                    )
                ],
                _provenance(tmp_path, f"canon-{index}"),
            )
        assert last is not None
        assert _count(store.conn, "works") == 1
        values = [
            row[0]
            for row in store.conn.execute(
                "SELECT normalized_value FROM work_identifiers "
                "WHERE scheme = 'doi'"
            )
        ]
        assert values == ["10.1000/foo"]
        dois = [
            row[0]
            for row in store.conn.execute("SELECT doi FROM documents")
        ]
        assert set(dois) == {"10.1000/foo"}
    finally:
        store.close()


def test_safe_errors_do_not_leak_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ontologylab.ingestion_shadow as shadow

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise sqlite3.OperationalError(
            f"disk I/O error in /secret/{SECRET}/kg.sqlite"
        )

    monkeypatch.setattr(shadow, "shadow_persist", boom)
    data_dir = tmp_path / "leak-data"
    data_dir.mkdir()
    fixture = tmp_path / "leak-notes.md"
    fixture.write_text("leak probe\n", encoding="utf-8")
    with _client(tmp_path, data_dir) as client:
        response = client.post("/api/collect", json={"files": [str(fixture)]})
    assert response.status_code == 200
    body = response.json()
    dumped = json.dumps(body)
    assert SECRET not in dumped
    assert "OperationalError" not in dumped
    assert "/secret/" not in dumped
    assert body["ok"] is False
    assert body["error_kind"] == "failed"
    assert body["detail"] == "internal_error"


def test_batch_above_100_is_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path / "bound")
    try:
        docs = [
            _raw(
                uri=f"https://example.invalid/{index}",
                text=f"body {index}",
                doi=f"10.1000/bound.{index}",
                source="crossref",
                source_kind="paper_api",
            )
            for index in range(MAX_SHADOW_BATCH + 1)
        ]
        with pytest.raises(ShadowBatchBoundError):
            ingest_documents(store, docs, _provenance(tmp_path, "bound"))
        assert _count(store.conn, "documents") == 0
        assert _count(store.conn, "document_observations") == 0
        assert load_shadow_queue(store.conn) == ()
    finally:
        store.close()

    from ontologylab.ingestion_surfaces import run_ingest

    store = _open(tmp_path / "bound-surface")
    try:
        items = [
            {
                "idempotency_key": f"op-{index}",
                "scheme": "doi",
                "normalized_value": f"10.1000/surface.{index}",
            }
            for index in range(101)
        ]
        batch = run_ingest(store.conn, items)
        assert batch.ok is False
        assert batch.http_status == 400
        assert "InvalidIngestItem" in batch.error_classes
        assert _count(store.conn, "works") == 0
    finally:
        store.close()


def test_partial_batch_remains_honest(tmp_path: Path) -> None:
    store = _open(tmp_path / "partial")
    try:
        shared = "shared-bytes-for-partial-honesty"
        result = ingest_documents(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/partial.good",
                    text="unique good body",
                    doi="10.1000/partial.good",
                    source="crossref",
                    source_kind="paper_api",
                ),
                _raw(
                    uri="https://doi.org/10.1000/partial.a",
                    text=shared,
                    doi="10.1000/partial.a",
                    source="crossref",
                    source_kind="paper_api",
                ),
                _raw(
                    uri="https://doi.org/10.1000/partial.b",
                    text=shared,
                    doi="10.1000/partial.b",
                    source="crossref",
                    source_kind="paper_api",
                ),
            ],
            _provenance(tmp_path, "partial"),
        )
        assert result.created_count == 2
        assert result.document_count == 2
        assert len(result.conflicts) == 1
        assert result.conflicts[0].incoming_doi == "10.1000/partial.b"
        assert _count(store.conn, "documents") == 2
        assert _count(store.conn, "document_observations") == 2
        assert any(item.reason == "conflict" for item in load_shadow_queue(store.conn))
    finally:
        store.close()


def test_adapter_never_commits_or_rolls_back_caller_transaction(
    tmp_path: Path,
) -> None:
    adapter_src = Path("ontologylab/ingestion_shadow.py").read_text(encoding="utf-8")
    assert "conn.commit(" not in adapter_src
    assert "conn.rollback(" not in adapter_src
    store = _open(tmp_path / "tx")
    try:
        store.conn.execute("SAVEPOINT caller")
        result = shadow_persist(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/tx",
                    text="transactional body",
                    doi="10.1000/tx",
                    source="crossref",
                    source_kind="paper_api",
                )
            ],
            None,
            operation_id="op-tx",
        )
        assert result.created_count == 1
        assert store.conn.in_transaction
        store.conn.execute("ROLLBACK TO SAVEPOINT caller")
        store.conn.execute("RELEASE SAVEPOINT caller")
        assert _count(store.conn, "documents") == 0
        assert _count(store.conn, "works") == 0
        assert _count(store.conn, "document_observations") == 0
        assert _count(store.conn, "provenance_outbox") == 0
        assert load_shadow_queue(store.conn) == ()
    finally:
        store.close()


def test_content_hash_is_not_work_authority(tmp_path: Path) -> None:
    store = _open(tmp_path / "hash")
    try:
        result = ingest_documents(
            store,
            [
                _raw(
                    uri="https://doi.org/10.1000/hash.a",
                    text="same-bytes",
                    doi="10.1000/hash.a",
                    source="crossref",
                    source_kind="paper_api",
                ),
                _raw(
                    uri="https://doi.org/10.1000/hash.b",
                    text="same-bytes",
                    doi="10.1000/hash.b",
                    source="crossref",
                    source_kind="paper_api",
                ),
            ],
            _provenance(tmp_path, "hash"),
        )
        assert len(result.conflicts) == 1
        assert _count(store.conn, "works") == 1
        owned = store.conn.execute(
            "SELECT normalized_value FROM work_identifiers WHERE scheme = 'doi'"
        ).fetchall()
        assert [row[0] for row in owned] == ["10.1000/hash.a"]
        assert store.conn.execute(
            "SELECT COUNT(*) FROM work_identifiers WHERE scheme = 'content_hash'"
        ).fetchone()[0] == 0
    finally:
        store.close()
