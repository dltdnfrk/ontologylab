from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from ontologylab.collect import CollectInputs, collect_documents
from ontologylab.ingestion import IdentityConflict, persist_raw_document
from ontologylab.main import main
from ontologylab.provenance import Provenance


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


def _cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            main(argv)
        except SystemExit as exc:
            code = 0 if exc.code is None else int(exc.code)
        else:
            code = 0
    return code, stdout.getvalue(), stderr.getvalue()


def test_cli_collect_does_not_import_or_call_routes_collect() -> None:
    cmd_src = _function_source(Path("ontologylab/main.py"), "cmd_collect")
    main_src = Path("ontologylab/main.py").read_text(encoding="utf-8")
    assert "routes.collect" not in cmd_src
    assert "from ontologylab.server" not in main_src
    assert "import ontologylab.server" not in main_src


def test_cmd_collect_and_routes_call_collect_documents() -> None:
    cmd_src = _function_source(Path("ontologylab/main.py"), "cmd_collect")
    route_src = _function_source(Path("ontologylab/server/routes.py"), "collect")
    assert "collect_documents(" in cmd_src
    assert "collect_documents(" in route_src
    assert "check_url(" not in cmd_src
    assert "check_url(" not in route_src
    assert "check_collect_file(" not in cmd_src
    assert "check_collect_file(" not in route_src


def test_cli_collect_url_refuses_when_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    monkeypatch.setattr(
        "ontologylab.connectors.allowlist.WEB_CRAWL_ALLOWED_HOSTS",
        {"example.com"},
    )
    fetched: list[str] = []

    async def _must_not_fetch(self: object, source_spec: dict[str, object]) -> list[object]:
        fetched.append("called")
        raise AssertionError("offline collect must not fetch")

    monkeypatch.setattr(
        "ontologylab.connectors.web_crawl.WebCrawlConnector.fetch",
        _must_not_fetch,
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    code, stdout, stderr = _cli(
        [
            "collect",
            "--url",
            "https://example.com/",
            "--data-dir",
            str(data_dir),
        ]
    )
    output = stdout + stderr
    assert code == 2
    assert "offline" in output.lower()
    assert "Traceback" not in output
    assert fetched == []


def test_cli_unreadable_file_is_exit_2(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    missing = tmp_path / "no-such-notes.md"
    code, stdout, stderr = _cli(
        ["collect", "--file", str(missing), "--data-dir", str(data_dir)]
    )
    output = stdout + stderr
    assert code == 2
    assert "Traceback" not in output
    assert "FETCH FAILED" in stderr or "could not read" in output


def test_cli_and_http_collect_same_file_same_document(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    fixture = tmp_path / "notes.md"
    fixture.write_text(
        "The RateLimiter implements the TokenBucketAlgorithm.\n",
        encoding="utf-8",
    )

    code, _stdout, stderr = _cli(
        ["collect", "--file", str(fixture), "--data-dir", str(data_dir)]
    )
    assert code == 0, stderr

    client = TestClient(
        create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    )
    response = client.post("/api/collect", json={"files": [str(fixture)]})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["created"] == 0
    assert body["duplicates"] == 1


def _collect_files(tmp_path: Path, *names: str) -> tuple[Path, tuple[str, ...]]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    files: list[str] = []
    for name in names:
        path = tmp_path / name
        path.write_text(f"body of {name}\n", encoding="utf-8")
        files.append(str(path))
    return data_dir, tuple(files)


def test_collect_all_items_failed_is_not_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("disk I/O error in /secret/nope/kg.sqlite")

    monkeypatch.setattr(
        "ontologylab.ingestion.persist_raw_document", boom
    )
    data_dir, files = _collect_files(tmp_path, "only.md")
    outcome = collect_documents(
        CollectInputs(
            urls=(),
            files=files,
            paper_queries=(),
            paper_source="arxiv",
            limit=5,
            data_dir=data_dir,
        ),
        provenance=Provenance(str(tmp_path / "jobs" / "collect"), seed=0),
    )
    assert outcome.ok is False
    assert outcome.error_kind == "failed"
    assert outcome.detail == "internal_error"
    assert len(outcome.failures) == 1
    assert outcome.failures[0].error_class == "RuntimeError"


def test_collect_conflict_does_not_kill_the_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = persist_raw_document

    def maybe_conflict(*args: Any, **kwargs: Any) -> Any:
        raw = args[1]
        if raw.title == "clash":
            return IdentityConflict(
                source_uri=raw.source_uri,
                incoming_doi="10.1000/incoming",
                existing_doc_id="doc-existing",
                existing_doi="10.1000/existing",
                content_hash=raw.content_hash,
            )
        return real(*args, **kwargs)

    monkeypatch.setattr(
        "ontologylab.ingestion.persist_raw_document", maybe_conflict
    )
    data_dir, files = _collect_files(tmp_path, "good.md", "clash.md")
    outcome = collect_documents(
        CollectInputs(
            urls=(),
            files=files,
            paper_queries=(),
            paper_source="arxiv",
            limit=5,
            data_dir=data_dir,
        ),
        provenance=Provenance(str(tmp_path / "jobs" / "collect"), seed=0),
    )
    assert outcome.ok is True
    assert outcome.created >= 1
    assert len(outcome.conflicts) == 1
