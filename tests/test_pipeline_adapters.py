from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ontologylab import main as cli_module
from ontologylab.engines import MockEngine
from ontologylab.main import main
from ontologylab.server import routes
from ontologylab.server.app import create_app


def _function_source(path: Path, func_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    needle = f"def {func_name}("
    start = text.find(needle)
    assert start != -1, f"{func_name} missing from {path}"
    depth = 0
    end = len(text)
    for index, line in enumerate(text[start:].splitlines(keepends=True)):
        if index > 0 and line.startswith(("def ", "async def ")) and depth == 0:
            break
        depth += line.count("(") - line.count(")")
        end = start + sum(
            len(chunk)
            for chunk in text[start:].splitlines(keepends=True)[: index + 1]
        )
    return text[start:end]


def test_extract_wrappers_call_run_extract_job() -> None:
    cli_src = _function_source(Path("ontologylab/main.py"), "_extract_async")
    jobs_src = _function_source(
        Path("ontologylab/server/jobs.py"), "_extract_async"
    )
    assert "run_extract_job(" in cli_src
    assert "run_extract_job(" in jobs_src


def test_critic_and_merge_still_call_stage_functions() -> None:
    assert "critic_review(" in _function_source(
        Path("ontologylab/main.py"), "cmd_critic"
    )
    assert "critic_review(" in _function_source(
        Path("ontologylab/server/routes.py"), "critic_run"
    )
    assert "scan_merge_candidates(" in _function_source(
        Path("ontologylab/main.py"), "cmd_merge_scan"
    )
    assert "scan_merge_candidates(" in _function_source(
        Path("ontologylab/server/routes.py"), "merge_scan"
    )
    assert not Path("ontologylab/services").exists()


def test_pack_wrappers_call_build_pack_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both entry points execute the same owner and publish real manifests."""
    original = cli_module.build_pack_release
    assert routes.build_pack_release is original
    calls: list[str] = []

    def observe(*args: Any, **kwargs: Any):
        calls.append(args[2])
        return original(*args, **kwargs)

    monkeypatch.setattr(cli_module, "build_pack_release", observe)
    monkeypatch.setattr(routes, "build_pack_release", observe)
    cli_data, cli_packs = tmp_path / "cli-data", tmp_path / "cli-packs"
    with redirect_stdout(StringIO()), pytest.raises(SystemExit) as exited:
        main([
            "build-pack", "--name", "adapter-cli",
            "--data-dir", str(cli_data), "--packs-dir", str(cli_packs),
        ])
    assert exited.value.code in (0, None)
    cli_manifests = list(cli_packs.glob("*/manifest.json"))
    assert len(cli_manifests) == 1
    cli_manifest = json.loads(cli_manifests[0].read_text())
    assert cli_manifest["pack_id"] == cli_manifests[0].parent.name

    http_packs = tmp_path / "http-packs"
    with TestClient(create_app(tmp_path / "http-data", http_packs)) as client:
        response = client.post("/api/packs/build", json={"name": "adapter-http"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    http_manifest = http_packs / body["manifest"]["pack_id"] / "manifest.json"
    published = json.loads(http_manifest.read_text())
    assert "methodology" not in published
    assert body["manifest"]["methodology"] is None
    assert {**published, "methodology": None} == body["manifest"]
    assert calls == ["adapter-cli", "adapter-http"]


def test_cli_extract_records_resolved_engine_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = MockEngine(seed=0)
    captured: dict[str, Any] = {}

    def fake_resolve(*_args: Any, **_kwargs: Any) -> MockEngine:
        return engine

    async def fake_run_extract_job(*_args: Any, **kwargs: Any) -> str:
        captured["engine_name"] = kwargs["engine_name"]
        return ""

    monkeypatch.setattr("ontologylab.main.resolve_engine", fake_resolve)
    monkeypatch.setattr("ontologylab.main.run_extract_job", fake_run_extract_job)
    monkeypatch.setattr(
        "ontologylab.main.extraction_doc_ids", lambda _store: ["doc-seed"]
    )
    stdout = StringIO()
    stderr = StringIO()
    with (
        redirect_stdout(stdout),
        redirect_stderr(stderr),
        pytest.raises(SystemExit) as excinfo,
    ):
        main(["extract", "--data-dir", str(tmp_path)])
    assert excinfo.value.code in (0, None)
    engine_name = captured["engine_name"]
    assert isinstance(engine_name, str)
    assert engine_name != ""
    assert engine_name == engine.name()
