"""Consume-layer engine resolution: one default policy, no consumer override."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ontologylab.engines import (
    ApiEngine,
    ClaudeEngine,
    EngineError,
    MockEngine,
    resolve_engine,
)
from ontologylab.providers import Provider, add_provider


def test_none_and_blank_use_default_engine() -> None:
    # Given: no engine name, or an empty one
    # When: resolve_engine applies the single default policy
    # Then: both resolve to the Claude CLI adapter, never mock
    assert isinstance(resolve_engine(None), ClaudeEngine)
    assert isinstance(resolve_engine(""), ClaudeEngine)


def test_auto_is_typed_unavailable() -> None:
    # Given: the retired translate candidate token
    # When: it is requested as an engine name
    # Then: it is typed-unavailable, not walked as a fallback list
    with pytest.raises(EngineError, match="engine 'auto' is not a valid engine"):
        resolve_engine("auto")


def test_explicit_names_still_work() -> None:
    # Given: a real built-in name and a junk name
    # When: resolve_engine is asked for each
    # Then: mock constructs; unknown raises the factory error
    assert isinstance(resolve_engine("mock"), MockEngine)
    with pytest.raises(EngineError):
        resolve_engine("nope")


def test_resolve_engine_forwards_decode_params(tmp_path: Path) -> None:
    # Given: a registered API provider, same shape as test_api_engine
    add_provider(
        tmp_path,
        Provider(
            id="anth",
            kind="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key_env="ANTHROPIC_API_KEY",
            models=("claude-fable-5",),
        ),
    )

    # When: decode_params travel through resolve_engine
    engine = resolve_engine(
        "api:anth",
        data_dir=tmp_path,
        decode_params={"temperature": 0.3},
    )

    # Then: the API adapter received them; resolve_engine did not drop them
    assert isinstance(engine, ApiEngine)
    assert engine._decode_params["temperature"] == 0.3


_REPO = Path(__file__).resolve().parents[1]
_CONSUME_MODULES = (
    _REPO / "ontologylab" / "main.py",
    _REPO / "ontologylab" / "server" / "routes.py",
    _REPO / "ontologylab" / "server" / "jobs.py",
    _REPO / "ontologylab" / "mcp_server.py",
    _REPO / "ontologylab" / "competency.py",
)
_RESOLVE_REQUIRED = (
    _REPO / "ontologylab" / "main.py",
    _REPO / "ontologylab" / "server" / "routes.py",
    _REPO / "ontologylab" / "server" / "jobs.py",
    _REPO / "ontologylab" / "mcp_server.py",
)


def _call_func_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.append(func.id)
        elif isinstance(func, ast.Attribute):
            names.append(func.attr)
    return names


def test_consume_modules_call_resolve_engine_only() -> None:
    # Given: the consume-layer modules that used to pick engines themselves
    # When: their call graph is walked
    # Then: get_engine is gone; resolve_engine owns the default policy
    for path in _CONSUME_MODULES:
        names = _call_func_names(path)
        assert "get_engine" not in names, f"{path.name} still calls get_engine"
    for path in _RESOLVE_REQUIRED:
        names = _call_func_names(path)
        assert "resolve_engine" in names, f"{path.name} never calls resolve_engine"
