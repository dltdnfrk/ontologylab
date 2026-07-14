"""Tier-2 search: fail-open LLM query expansion over FTS5 lexical search.

Everything runs offline (MockEngine / stub engines) — the real CLIs are
never spawned. Covers: the parse/validate contract, fail-open behavior,
MockEngine determinism (and its extraction regression guard), the canonical
"rate limiter" -> "RateLimiter" retrieval bridge, PackSession tier labeling,
the CLI `search` subcommand, and the MCP tool surface.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from ontologylab.engines import EngineError, MockEngine, extract_fenced_block
from ontologylab.expansion import (
    EXPANSION_PROMPT_VERSION,
    build_expansion_prompt,
    expand_query,
    parse_expansion,
)
from ontologylab.main import main
from ontologylab.mcp_server import PackSession

from tests.conftest import SAMPLE_TEXT, default_schema_dict, insert, make_entity


def run_cli(*argv) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return exc.value.code


def fenced(payload) -> str:
    return "```json\n" + json.dumps(payload) + "\n```"


# ---------------------------------------------------------------------------
# prompt contract
# ---------------------------------------------------------------------------


def test_prompt_contract():
    assert EXPANSION_PROMPT_VERSION == "expand-v1"
    prompt = build_expansion_prompt("rate limiter")
    assert "<query-expansion>\nrate limiter\n</query-expansion>" in prompt
    assert "EXACTLY ONE fenced ```json block" in prompt
    assert "NEVER invent product names" in prompt


# ---------------------------------------------------------------------------
# parse_expansion
# ---------------------------------------------------------------------------


def test_parse_expansion_valid_array_capped_at_8():
    items = [f"variant{i}" for i in range(12)]
    out = parse_expansion(fenced(items), "query")
    assert out == items[:8]


def test_parse_expansion_strips_dedupes_and_filters():
    raw = fenced(
        [
            "  Rate Limiter  ",   # stripped, kept
            "rate limiter",       # casefold-duplicate of the previous -> dropped
            "",                   # empty -> dropped
            "   ",                # whitespace-only -> dropped
            "x" * 51,             # too long -> dropped
            "throttle",           # kept
        ]
    )
    assert parse_expansion(raw, "throttling") == ["Rate Limiter", "throttle"]


def test_parse_expansion_drops_casefold_duplicate_of_original():
    raw = fenced(["Rate Limiter", "ratelimiter"])
    assert parse_expansion(raw, "rate limiter") == ["ratelimiter"]


@pytest.mark.parametrize(
    "raw",
    [
        "no fenced block at all",
        "```json\nnot valid json\n```",
        fenced({"variants": ["a"]}),  # object, not array
        fenced(["ok", 42]),           # non-string item
    ],
)
def test_parse_expansion_unparseable_raises(raw):
    with pytest.raises(EngineError):
        parse_expansion(raw, "query")


# ---------------------------------------------------------------------------
# expand_query fails OPEN, never raises
# ---------------------------------------------------------------------------


class RaisingEngine:
    async def generate(self, prompt, *, model=None):
        raise EngineError("engine exploded")


class GarbageEngine:
    async def generate(self, prompt, *, model=None):
        return "no fenced block here", {"calls": 1, "engine": "garbage"}


def test_expand_query_fails_open_when_engine_raises():
    variants, usage = asyncio.run(expand_query("rate limiter", RaisingEngine()))
    assert variants == []
    assert "engine exploded" in usage["error"]


def test_expand_query_fails_open_on_unparseable_output():
    variants, usage = asyncio.run(expand_query("rate limiter", GarbageEngine()))
    assert variants == []
    assert "error" in usage
    assert usage["calls"] == 1  # engine usage is preserved alongside the error


def test_expand_query_happy_path_has_no_error_key():
    variants, usage = asyncio.run(expand_query("rate limiter", MockEngine()))
    assert variants == ["ratelimiter"]
    assert "error" not in usage


# ---------------------------------------------------------------------------
# MockEngine: deterministic expansion + extraction regression guard
# ---------------------------------------------------------------------------


def test_mock_engine_expansion_is_deterministic():
    prompt = build_expansion_prompt("RateLimiter")
    engine = MockEngine()
    text1, _ = asyncio.run(engine.generate(prompt))
    text2, _ = asyncio.run(engine.generate(prompt))
    assert text1 == text2
    variants = parse_expansion(text1, "RateLimiter")
    assert variants == ["rate limiter"]  # camel split; joined form == original


def test_mock_engine_extraction_prompts_unaffected():
    from ontologylab.extractor import build_extraction_prompt

    prompt = build_extraction_prompt(default_schema_dict(), SAMPLE_TEXT)
    text, _ = asyncio.run(MockEngine().generate(prompt))
    payload = json.loads(extract_fenced_block(text))
    names = {e["name"] for e in payload["entities"]}
    assert {"ApiGateway", "RateLimiter"} <= names
    assert payload["relations"]  # still emits extraction shape, not an array


# ---------------------------------------------------------------------------
# canonical retrieval case: "rate limiter" must reach the RateLimiter node
# ---------------------------------------------------------------------------


def test_expansion_bridges_fts5_camelcase_tokenization(store, doc):
    insert(store, doc, [make_entity("RateLimiter")])
    node_id = store.pending_review(kind="node")[0]["id"]
    store.approve(node_id)
    store.rebuild_fts()

    # plain lexical query misses: FTS5 keeps "RateLimiter" as one token
    assert store.semantic_search("rate limiter") == []

    variants, usage = asyncio.run(expand_query("rate limiter", MockEngine()))
    assert "ratelimiter" in variants
    hits = store.semantic_search(" ".join(["rate limiter", *variants]))
    assert [h["name"] for h in hits] == ["RateLimiter"]


# ---------------------------------------------------------------------------
# PackSession + CLI + MCP surfaces
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path):
    """Tiny verified pack: collect (file) -> extract (mock) -> approve -> pack."""
    notes = tmp_path / "notes.md"
    notes.write_text(SAMPLE_TEXT, encoding="utf-8")
    data = str(tmp_path / "data")
    packs = tmp_path / "packs"
    assert run_cli("collect", "--data-dir", data, "--file", str(notes)) == 0
    assert run_cli("extract", "--data-dir", data, "--engine", "mock") == 0
    assert run_cli("approve", "--data-dir", data, "--filter", "min_confidence=0.5") == 0
    assert (
        run_cli(
            "build-pack", "--data-dir", data, "--name", "demo",
            "--packs-dir", str(packs),
        )
        == 0
    )
    return {"data": data, "packs": packs}


def test_pack_session_expanded_search_tier_labels(workspace):
    session = PackSession(workspace["packs"])
    try:
        assert session.try_autoload() is not None

        expanded = asyncio.run(
            session.semantic_search_expanded("rate limiter", engine_name="mock")
        )
        assert expanded["search_tier"] == "fts5+llm-expansion"
        assert expanded["expansion_terms"] == ["ratelimiter"]
        assert expanded["expansion_error"] is None
        assert "RateLimiter" in [r["name"] for r in expanded["results"]]

        plain = asyncio.run(session.semantic_search_expanded("rate limiter"))
        assert plain["search_tier"] == "fts5"  # no engine -> honest plain label
        assert plain["expansion_terms"] == []
        assert plain["count"] == 0
    finally:
        session.close()


def test_pack_session_plain_semantic_search_shape_unchanged(workspace):
    session = PackSession(workspace["packs"])
    try:
        session.try_autoload()
        result = session.semantic_search("ratelimiter")
        # uniform envelope: expansion fields always present (empty when unused)
        assert set(result) == {
            "query", "search_tier", "expansion_terms", "expansion_error",
            "results", "count", "pack",
        }
        assert result["search_tier"] == "fts5"
        assert result["expansion_terms"] == []
        assert result["pack"]["pack_id"] == session.pack_id
    finally:
        session.close()


def test_cli_search_with_expansion(workspace, capsys):
    code = run_cli(
        "search", "--data-dir", workspace["data"], "rate limiter",
        "--expand", "--engine", "mock",
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "tier: fts5+llm-expansion" in out
    assert "ratelimiter" in out  # expansion terms are printed
    assert "RateLimiter" in out


def test_cli_search_zero_hits_is_informative_exit_0(workspace, capsys):
    code = run_cli("search", "--data-dir", workspace["data"], "zzyzxquux")
    assert code == 0
    out = capsys.readouterr().out
    assert "tier: fts5" in out
    assert "0 results" in out


def test_mcp_semantic_search_tool_exposes_expand(tmp_path):
    pytest.importorskip("mcp")
    from ontologylab.mcp_server import build_mcp_app

    session = PackSession(tmp_path)
    try:
        app = build_mcp_app(session)
        tools = asyncio.run(app.list_tools())
        (tool,) = [t for t in tools if t.name == "semantic_search"]
        assert "expand" in tool.inputSchema["properties"]
        assert "NOT vector" in tool.description  # honest tier labeling
    finally:
        session.close()
