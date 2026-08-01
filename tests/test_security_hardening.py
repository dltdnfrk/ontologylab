"""Security-hardening regression tests (2026-08-01 red-team audit).

Each test names the attack it blocks. Written RED against the audited
code, GREEN after the minimal defense landed. See .omo/evidence/sec-*.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from ontologylab import engines
from ontologylab.engines import EngineError
from ontologylab.extractor import Chunk, parse_and_validate_extraction
from ontologylab.packbuilder import PackBuildError

_CHUNK = Chunk(index=0, char_offset=0, text="Alpha is mentioned here.")


# ---------------------------------------------------------------------------
# F1 — web_crawl must bound the response body like paper_api does.
# An allowlisted host serving an unbounded body exhausted memory; the read
# must stop at a cap and refuse, not slurp.
# ---------------------------------------------------------------------------


class _HugeResponse:
    def __init__(self, n: int) -> None:
        self._remaining = n
        self.headers = self

    def get_content_charset(self):
        return "utf-8"

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self._remaining
        chunk = min(n, self._remaining)
        self._remaining -= chunk
        return b"x" * chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_web_crawl_refuses_an_overlarge_page(monkeypatch, tmp_path) -> None:
    import ontologylab.connectors.web_crawl as wc

    monkeypatch.setattr(wc, "assert_network_allowed", lambda *a, **k: None)
    huge = _HugeResponse(wc.MAX_RESPONSE_BYTES + 10)
    monkeypatch.setattr(
        wc, "_opener", type("O", (), {"open": lambda self, req, timeout: huge})()
    )
    with pytest.raises(ValueError, match="exceeded"):
        wc._fetch_url("https://docs.python.org/3/")


# ---------------------------------------------------------------------------
# F2 — extractor must reject non-container aliases/properties with
# EngineError, not crash the whole job with TypeError/AttributeError.
# ---------------------------------------------------------------------------

_SCHEMA = {
    "entity_types": [
        {"name": "Concept", "description": "c", "attributes": {}},
    ],
    "relation_types": [],
}


def _fenced(payload: dict) -> str:
    return "Here you go:\n```json\n" + json.dumps(payload) + "\n```"


def test_extraction_rejects_scalar_aliases() -> None:
    raw = _fenced(
        {"entities": [{"type": "Concept", "entity_type": "Concept", "name": "Alpha", "aliases": 1}]}
    )
    with pytest.raises(EngineError):
        parse_and_validate_extraction(raw, _SCHEMA, _CHUNK)


def test_extraction_rejects_list_properties() -> None:
    raw = _fenced(
        {
            "entities": [
                {"type": "Concept", "entity_type": "Concept", "name": "Alpha", "properties": ["not-a-dict"]}
            ]
        }
    )
    with pytest.raises(EngineError):
        parse_and_validate_extraction(raw, _SCHEMA, _CHUNK)


# ---------------------------------------------------------------------------
# F3 — providers.json on disk is not trusted: entries that registration
# would refuse (http:// remote host, suspicious env name) must not load.
# ---------------------------------------------------------------------------


def test_load_providers_drops_entries_registration_would_refuse(tmp_path) -> None:
    from ontologylab.providers import load_providers

    (tmp_path / "providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "evil",
                        "kind": "openai",
                        "base_url": "http://attacker.example.com/v1",
                        "api_key_env": "AWS_SECRET_ACCESS_KEY",
                        "models": ["x"],
                        "label": "evil",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_providers(tmp_path) == []


# ---------------------------------------------------------------------------
# F4 — pack_id reaches paths in mcpb/packdiff without safe_pack_component.
# ---------------------------------------------------------------------------


def test_build_mcpb_rejects_traversal_pack_id(tmp_path) -> None:
    from ontologylab.mcpb import build_mcpb

    with pytest.raises(PackBuildError, match="invalid pack id"):
        build_mcpb(tmp_path, "../escape")


def test_packdiff_rejects_traversal_pack_id(tmp_path) -> None:
    from ontologylab.packdiff import diff_packs

    with pytest.raises(PackBuildError, match="invalid pack id"):
        diff_packs(tmp_path, "../a", "b")


# ---------------------------------------------------------------------------
# F6 — agentic CLIs must be invoked with their tool-use disabled or
# sandboxed, so a poisoned document cannot drive local tool execution.
# ---------------------------------------------------------------------------


def _captured_cmd(monkeypatch, engine_cls_path: str) -> list[str]:
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, timeout_s):
        captured["cmd"] = list(cmd)
        return "ok", 0.1

    monkeypatch.setattr(engines, "_run_subprocess", fake_run)
    monkeypatch.setattr(engines, "assert_network_allowed", lambda *a, **k: None)
    return captured


def test_claude_engine_disables_tool_use(monkeypatch) -> None:
    import asyncio

    captured = _captured_cmd(monkeypatch, "claude")
    engine = engines.ClaudeEngine()
    asyncio.run(engine.generate("prompt", model=None))
    cmd = captured["cmd"]
    assert "--disallowedTools" in cmd or "--permission-mode" in cmd


def test_codex_engine_runs_sandboxed(monkeypatch) -> None:
    import asyncio

    captured = _captured_cmd(monkeypatch, "codex")
    engine = engines.CodexEngine()
    asyncio.run(engine.generate("prompt", model=None))
    cmd = captured["cmd"]
    assert "--sandbox" in cmd
    assert "read-only" in cmd


def test_gemini_engine_runs_without_auto_approval(monkeypatch) -> None:
    import asyncio

    captured = _captured_cmd(monkeypatch, "gemini")
    engine = engines.GeminiEngine()
    asyncio.run(engine.generate("prompt", model=None))
    cmd = captured["cmd"]
    assert "--approval-mode" in cmd


# ---------------------------------------------------------------------------
# F7 — private stores must not be world-readable on a multi-user host.
# ---------------------------------------------------------------------------


def test_kg_sqlite_is_owner_only(tmp_path) -> None:
    from ontologylab.kgstore import KGStore

    db = tmp_path / "kg.sqlite"
    KGStore.open(db).close()
    mode = stat.S_IMODE(os.stat(db).st_mode)
    assert mode & 0o077 == 0, f"kg.sqlite mode {oct(mode)} is group/world accessible"


def test_chat_sqlite_is_owner_only(tmp_path) -> None:
    from ontologylab.chatstore import ChatStore

    db = tmp_path / "chat.sqlite"
    ChatStore.open(db).close()
    mode = stat.S_IMODE(os.stat(db).st_mode)
    assert mode & 0o077 == 0, f"chat.sqlite mode {oct(mode)} is group/world accessible"


def test_settings_json_is_owner_only(tmp_path) -> None:
    from ontologylab.server.settings import default_settings, save_settings

    path = save_settings(default_settings(), tmp_path)
    settings_file = tmp_path / "settings.json"
    assert settings_file.is_file()
    mode = stat.S_IMODE(os.stat(settings_file).st_mode)
    assert mode & 0o077 == 0, f"settings.json mode {oct(mode)} is group/world accessible"
