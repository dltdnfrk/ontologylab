"""Method extraction obeys the same eligibility rule as graph extraction.

The second gate review of todo 15 drove an observed abstract-only document
through ``ontologylab method extract --document-id`` to a succeeded run with
one statement occurrence. The CLI now refuses before an engine is resolved,
and ``extract_occurrences`` refuses before any run row, chunk claim or engine
call on both the fresh and the resume path. Uploads and full text still work.
"""

from __future__ import annotations

import asyncio
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from ontologylab.authority_repo import insert_observation
from ontologylab.kgstore import KGStore
from ontologylab.main import main
from ontologylab.method_extract import extract_occurrences
from ontologylab.method_store import MethodStateError, MethodStore, MethodUnitOfWork
from tests.test_method_extract import SpyEngine, _hash, extraction_counts

TEXT = "Heat sample to 80 C. Hold for ten minutes."


def _seed(tmp_path: Path, *, kinds: tuple[str, ...] = ()) -> str:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        document, _ = store.insert_document(
            source_kind="paper_api" if kinds else "upload",
            source_uri="file:///method.txt", title="method",
            raw_text=TEXT, content_hash=_hash(TEXT),
            source="crossref" if kinds else "",
            evidence_grade="peer_reviewed" if kinds else "",
        )
        for index, kind in enumerate(kinds):
            insert_observation(
                store.conn, idempotency_key=f"method-{index}",
                representation_id=document.id, content_kind=kind,
            )
        store.conn.commit()
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            method.create_source_policy(
                "policy-1", origin_pattern="file://*", policy_version="1",
                allowed_quote=True, allowed_extract=True, allowed_pack=True,
                allowed_train=False, allowed_redistribute=False,
                sensitivity="internal", allowed_processors=("spy",),
                allowed_regions=("local",), decision_note="fixture",
                decided_by="reviewer",
            )
            method.create_document_policy_snapshot(
                "snapshot-1", document_id=document.id,
                document_content_hash=document.content_hash,
                source_policy_id="policy-1", resolution_status="resolved",
                resolved_by="reviewer",
            )
            method.create_workspace(
                "workspace-1", name="Heat", objective="Extract method",
                scope={}, created_by="reviewer",
            )
        return document.id
    finally:
        store.close()


def _counts(tmp_path: Path) -> tuple[int, int, int]:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        return extraction_counts(store)
    finally:
        store.close()


def _run_cli(tmp_path: Path, doc_id: str, engine: SpyEngine, *extra: str):
    argv = [
        "method", "extract", "--workspace-id", "workspace-1",
        "--document-id", doc_id, "--policy-snapshot-id", "snapshot-1",
        "--engine", "mock", "--processor", "spy", "--region", "local",
        "--owner-token", "owner", "--run-id", "run-1",
        "--data-dir", str(tmp_path), *extra,
    ]
    out, err = io.StringIO(), io.StringIO()
    with patch("ontologylab.main.resolve_engine", return_value=engine) as resolved, \
            redirect_stdout(out), redirect_stderr(err):
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
    return excinfo.value.code, out.getvalue(), err.getvalue(), resolved.call_count


def test_cli_refuses_abstract_only_before_resolving_an_engine(tmp_path: Path) -> None:
    doc_id = _seed(tmp_path, kinds=("abstract",))
    engine = SpyEngine()

    code, out, err, resolved = _run_cli(tmp_path, doc_id, engine)

    assert code == 1
    assert out == ""
    assert "extraction refused" in err and doc_id in err and "'abstract'" in err
    assert resolved == 0
    assert engine.calls == 0
    assert _counts(tmp_path) == (0, 0, 0)


def test_cli_resume_refuses_abstract_only(tmp_path: Path) -> None:
    doc_id = _seed(tmp_path, kinds=("abstract",))
    engine = SpyEngine()

    code, _out, err, resolved = _run_cli(tmp_path, doc_id, engine, "--resume")

    assert code == 1
    assert "extraction refused" in err and doc_id in err
    assert resolved == 0
    assert engine.calls == 0
    assert _counts(tmp_path) == (0, 0, 0)


@pytest.mark.parametrize("resume", [False, True])
def test_extract_occurrences_refuses_before_any_write(tmp_path: Path, resume: bool) -> None:
    doc_id = _seed(tmp_path, kinds=("abstract",))
    engine = SpyEngine()
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        with pytest.raises(MethodStateError, match="extraction refused"):
            asyncio.run(extract_occurrences(
                store, workspace_id="workspace-1", document_id=doc_id,
                policy_snapshot_id="snapshot-1", engine=engine, processor="spy",
                region="local", owner_token="owner", run_id="run-1", resume=resume,
            ))
        assert engine.calls == 0
        assert extraction_counts(store) == (0, 0, 0)
    finally:
        store.close()


@pytest.mark.parametrize(
    "kinds", [(), ("abstract", "fulltext")], ids=["upload", "fulltext"]
)
def test_cli_extracts_uploads_and_full_text(tmp_path: Path, kinds: tuple[str, ...]) -> None:
    doc_id = _seed(tmp_path, kinds=kinds)
    engine = SpyEngine()

    code, out, err, resolved = _run_cli(tmp_path, doc_id, engine)

    assert code == 0, err
    assert json.loads(out) == {"run_id": "run-1", "status": "complete"}
    assert resolved == 1
    assert engine.calls == 1
    assert _counts(tmp_path) == (1, 1, 1)
