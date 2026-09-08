from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ontologylab import research_run as research_run_module
from ontologylab.collect import SAMPLE_DOC_TEXT, SAMPLE_DOC_TITLE
from ontologylab.connectors.base import RawDocument
from ontologylab.ingestion import (
    MAX_INGEST_BATCH,
    SAMPLE_SOURCE_URI,
    IngestBatchBoundError,
    IngestionResult,
    ingest_raw_documents,
    ingest_raw_documents_and_finalize,
)
from ontologylab.kgstore import KGStore
from ontologylab.main import main
from ontologylab.paths import kg_db_path
from ontologylab.provenance import Provenance
from ontologylab.provenance_outbox import load_outbox_events

SECRET = "ELS-must-never-surface-9f3a"
SAMPLE_OPERATION_KEY = "collect.sample:sample://onboarding/order-system"


def _open(data_dir: Path) -> KGStore:
    data_dir.mkdir(parents=True, exist_ok=True)
    return KGStore.open(kg_db_path(data_dir))


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _raw(
    *,
    uri: str,
    text: str,
    title: str = "Collect",
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


def _provenance(tmp_path: Path, name: str = "collect") -> Provenance:
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


def _product_py_files() -> list[Path]:
    return [
        path
        for path in Path("ontologylab").rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def test_cli_collect_writes_document_observation_and_outbox(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "cli-data"
    data_dir.mkdir()
    fixture = tmp_path / "cli-notes.md"
    fixture.write_text(
        "The PaymentGateway validates cards through the FraudDetector.\n",
        encoding="utf-8",
    )
    assert _cli_collect(data_dir, fixture) == 0

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


def test_http_collect_returns_counts_and_writes_v2_rows(tmp_path: Path) -> None:
    data_dir = tmp_path / "http-data"
    data_dir.mkdir()
    fixture = tmp_path / "http-notes.md"
    fixture.write_text("The RateLimiter implements the TokenBucketAlgorithm.\n")
    with _client(tmp_path, data_dir) as client:
        response = client.post("/api/collect", json={"files": [str(fixture)]})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["documents"] == 1
    assert body["created"] == 1
    assert body["duplicates"] == 0
    assert body["failures"] == []
    assert body["conflicts"] == []

    store = KGStore.open(kg_db_path(data_dir), read_only=True)
    try:
        assert _count(store.conn, "documents") == 1
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "provenance_outbox") == 1
    finally:
        store.close()


def test_research_worker_persists_doi_and_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.extractor import ExtractionOutcome
    from ontologylab.server import jobs as jobs_module
    from ontologylab.server.app import create_app

    data_dir = tmp_path / "research-data"
    paper = _raw(
        uri="https://doi.org/10.1000/research.one",
        text="The RiskEngine reports to the FraudDetector.\n",
        title="Research paper",
        doi="10.1000/research.one",
        source="crossref",
        source_kind="paper_api",
    )

    async def fake_fetch(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return [("crossref", [paper])], []

    async def fake_extract(*args: Any, **kwargs: Any) -> ExtractionOutcome:
        del args, kwargs
        return ExtractionOutcome("")

    monkeypatch.setattr(research_run_module, "fetch_sources", fake_fetch)
    monkeypatch.setattr(
        research_run_module,
        "extract_research_documents",
        fake_extract,
    )
    app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    with TestClient(app) as client:
        client.get("/")
        started = client.post(
            "/api/research",
            json={
                "topic": "research adapter",
                "sources": ["crossref"],
                "engine": "mock",
                "fulltext": False,
                "citation_expansion": False,
            },
        ).json()
        assert started["ok"] is True
        job = app.state.jobs.get(started["job_id"])
        assert job is not None and job._thread is not None
        job._thread.join(timeout=30)
        assert job.status == "failed"
        assert job.error == jobs_module.NO_SOURCES_SUMMARY

    store = KGStore.open(
        kg_db_path(data_dir), read_only=True, immutable=False
    )
    try:
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


def test_collect_sample_keeps_uri_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_four_entrypoints_call_ingest_raw_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.extractor import ExtractionOutcome
    from ontologylab.server.app import create_app

    paper = _raw(
        uri="https://doi.org/10.1000/research.entrypoint",
        text="The ResearchGateway records the EvidenceDocument.\n",
        title="Research entrypoint",
        doi="10.1000/research.entrypoint",
        source="crossref",
        source_kind="paper_api",
    )
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        AsyncMock(return_value=([("crossref", [paper])], [])),
    )
    monkeypatch.setattr(
        research_run_module,
        "extract_research_documents",
        AsyncMock(return_value=ExtractionOutcome("")),
    )
    real_ingest = research_run_module.ingest_raw_documents_batched
    observed_document_ids: list[tuple[str, ...]] = []

    def observe_ingest(
        store: KGStore,
        documents: Sequence[RawDocument],
        provenance: Provenance,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> IngestionResult:
        result = real_ingest(
            store,
            documents,
            provenance,
            should_cancel=should_cancel,
        )
        observed_document_ids.append(result.document_ids)
        return result

    monkeypatch.setattr(
        research_run_module,
        "ingest_raw_documents_batched",
        observe_ingest,
    )
    data_dir = tmp_path / "research-entrypoint-data"
    app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    with TestClient(app) as client:
        started = client.post(
            "/api/research",
            json={
                "topic": "research ingestion entrypoint",
                "sources": ["crossref"],
                "engine": "mock",
                "fulltext": False,
                "citation_expansion": False,
            },
        ).json()
        job = app.state.jobs.get(started["job_id"])
        assert job is not None and job._thread is not None
        job._thread.join(timeout=30)
        assert not job._thread.is_alive()

    assert len(observed_document_ids) == 1
    [document_ids] = observed_document_ids
    store = KGStore.open(
        kg_db_path(data_dir), read_only=True, immutable=False
    )
    try:
        stored_ids = tuple(document.id for document in store.list_documents())
        assert stored_ids == document_ids
    finally:
        store.close()

    assert "ingest_raw_documents_and_finalize(" in _function_source(
        Path("ontologylab/collect.py"), "collect_documents"
    )
    assert "collect_documents(" in _function_source(
        Path("ontologylab/main.py"), "cmd_collect"
    )
    assert "collect_documents(" in _function_source(
        Path("ontologylab/server/routes.py"), "collect"
    )
    assert "collect_onboarding_sample(" in _function_source(
        Path("ontologylab/server/routes.py"), "collect_sample"
    )
    assert "ingest_onboarding_sample(" in _function_source(
        Path("ontologylab/collect.py"), "collect_onboarding_sample"
    )
    for path in _product_py_files():
        assert "ingestion_shadow" not in path.read_text(encoding="utf-8"), path


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
        result = ingest_raw_documents(
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


def test_richer_same_doi_new_bytes_create_second_representation(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path / "richer")
    try:
        first = ingest_raw_documents_and_finalize(
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
        second = ingest_raw_documents_and_finalize(
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
        assert second.created_count == 1
        assert second.document_count == 1
        assert second.entries[0].document.id != first.entries[0].document.id
        assert len(store.list_documents()) == 2
        assert store.document_raw_text(first.entries[0].document.id) == (
            "short abstract"
        )
        assert store.document_raw_text(second.entries[0].document.id) == (
            "short abstract plus full text that is richer"
        )
        work_ids = {
            str(row[0])
            for row in store.conn.execute(
                "SELECT work_id FROM documents ORDER BY id"
            )
        }
        assert len(work_ids) == 1
        assert _count(store.conn, "documents") == 2
    finally:
        store.close()


def test_conflicting_different_doi_same_bytes_is_typed(tmp_path: Path) -> None:
    store = _open(tmp_path / "conflict")
    try:
        shared = "Identical body shared by two distinct registered works."
        result = ingest_raw_documents(
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
            last = ingest_raw_documents(
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
        assert dois.count("10.1000/foo") == 1
        assert dois.count(None) == len(spellings) - 1
        assert _count(store.conn, "documents") == len(spellings)
    finally:
        store.close()


def test_collect_http_failure_does_not_leak_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ontologylab import ingestion

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(
            f"disk I/O error in /secret/{SECRET}/kg.sqlite"
        )

    monkeypatch.setattr(ingestion, "persist_raw_document", boom)
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
    assert SECRET not in response.text
    assert "/secret/" not in dumped
    assert body["failures"][0]["error_class"] == "RuntimeError"


def test_collect_http_batch_failure_returns_typed_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(
            f"disk I/O error in /secret/{SECRET}/kg.sqlite"
        )

    monkeypatch.setattr(
        "ontologylab.collect.ingest_raw_documents_and_finalize",
        boom,
    )
    data_dir = tmp_path / "batch-leak-data"
    data_dir.mkdir()
    fixture = tmp_path / "batch-leak-notes.md"
    fixture.write_text("batch leak probe\n", encoding="utf-8")
    with _client(tmp_path, data_dir) as client:
        response = client.post("/api/collect", json={"files": [str(fixture)]})
    assert response.status_code == 200
    body = response.json()
    dumped = json.dumps(body)
    assert body["ok"] is False
    assert body["error_kind"] == "failed"
    assert body["detail"] == "internal_error"
    assert SECRET not in dumped
    assert "/secret/" not in dumped
    assert "OperationalError" not in dumped
    assert "RuntimeError" not in dumped
    assert "Traceback" not in dumped


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
            for index in range(MAX_INGEST_BATCH + 1)
        ]
        with pytest.raises(IngestBatchBoundError):
            ingest_raw_documents(store, docs, _provenance(tmp_path, "bound"))
        assert _count(store.conn, "documents") == 0
        assert _count(store.conn, "document_observations") == 0
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
        result = ingest_raw_documents(
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
    finally:
        store.close()


def test_writer_never_commits_or_rolls_back_caller_transaction(
    tmp_path: Path,
) -> None:
    service_src = Path("ontologylab/ingestion_service.py").read_text(encoding="utf-8")
    assert "conn.commit(" not in service_src
    store = _open(tmp_path / "tx")
    try:
        store.conn.execute("SAVEPOINT caller")
        result = ingest_raw_documents(
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
            _provenance(tmp_path, "op-tx"),
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
    finally:
        store.close()


def test_content_hash_is_not_work_authority(tmp_path: Path) -> None:
    store = _open(tmp_path / "hash")
    try:
        result = ingest_raw_documents(
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


def test_sample_uri_and_batch_bound_are_stable() -> None:
    assert SAMPLE_SOURCE_URI == "sample://onboarding/order-system"
    assert MAX_INGEST_BATCH == 100


def test_authority_ingest_route_still_uses_run_ingest() -> None:
    src = Path("ontologylab/server/ingest_routes.py").read_text(encoding="utf-8")
    assert "run_ingest(" in src
    assert "ingestion_shadow" not in src


def test_shadow_modules_are_gone() -> None:
    assert importlib.util.find_spec("ontologylab.ingestion_shadow") is None
    leftover = [
        path
        for path in Path("ontologylab").rglob("*")
        if "__pycache__" not in path.parts
        and "ingestion_shadow" in path.name
    ]
    assert leftover == []
    for path in _product_py_files():
        assert "ingestion_shadow" not in path.read_text(encoding="utf-8"), path
    assert "shadow" not in Path("ontologylab/ingestion.py").read_text(
        encoding="utf-8"
    )
    assert "conn.commit(" not in Path(
        "ontologylab/ingestion_service.py"
    ).read_text(encoding="utf-8")
