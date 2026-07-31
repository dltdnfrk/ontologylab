"""ApiEngine + factory: offline tests (the urllib POST helper is monkeypatched).

No provider is ever contacted. Request-shape tests assert the exact url,
headers (incl. the key read from the env var), and body per kind; the
secret-safety tests assert the key never appears in a raised error.
"""

from __future__ import annotations

import asyncio
from urllib.error import HTTPError, URLError

import pytest

import ontologylab.engines as engines
from ontologylab.engines import (
    ApiEngine,
    EngineError,
    engine_name_arg,
    get_engine,
    is_valid_engine_name,
)
from ontologylab.providers import Provider, add_provider

_KEY = "sk-live-do-not-leak"


def _anthropic() -> Provider:
    return Provider(
        id="anth",
        kind="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTH_KEY",
        models=("claude-fable-5",),
    )


def _openai() -> Provider:
    return Provider(
        id="orouter",
        kind="openai",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OR_KEY",
        models=("meta/llama",),
    )


def _capture(monkeypatch, response):
    """Monkeypatch the POST helper; return a dict that records the call args."""
    seen: dict = {}

    def fake_post(url, headers, payload, timeout_s):
        seen["url"] = url
        seen["headers"] = headers
        seen["payload"] = payload
        return response

    monkeypatch.setattr(engines, "_http_post_json", fake_post)
    return seen


def test_name_is_api_prefixed():
    assert ApiEngine(_anthropic()).name() == "api:anth"


def test_anthropic_request_shape_and_parsing(monkeypatch):
    monkeypatch.setenv("ANTH_KEY", _KEY)
    seen = _capture(
        monkeypatch,
        {
            "content": [
                {"type": "text", "text": "po"},
                {"type": "thinking", "text": "IGNORED"},
                {"type": "text", "text": "ng"},
            ],
            "usage": {"input_tokens": 7, "output_tokens": 2},
        },
    )
    text, usage = asyncio.run(ApiEngine(_anthropic()).generate("hi"))

    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == _KEY
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["payload"]["model"] == "claude-fable-5"
    assert seen["payload"]["max_tokens"] == 4096
    assert seen["payload"]["messages"] == [{"role": "user", "content": "hi"}]
    # Only type=="text" blocks are concatenated.
    assert text == "pong"
    assert usage["engine"] == "api:anth"
    assert usage["model"] == "claude-fable-5"
    assert usage["calls"] == 1
    assert usage["prompt_tokens"] == 7
    assert usage["completion_tokens"] == 2


def test_openai_request_shape_and_parsing(monkeypatch):
    monkeypatch.setenv("OR_KEY", _KEY)
    seen = _capture(
        monkeypatch,
        {
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        },
    )
    text, usage = asyncio.run(ApiEngine(_openai()).generate("hi"))

    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["Authorization"] == f"Bearer {_KEY}"
    assert seen["payload"]["model"] == "meta/llama"
    assert seen["payload"]["messages"] == [{"role": "user", "content": "hi"}]
    assert text == "pong"
    assert usage["prompt_tokens"] == 5
    assert usage["completion_tokens"] == 1


def test_explicit_model_overrides_provider_default(monkeypatch):
    monkeypatch.setenv("ANTH_KEY", _KEY)
    seen = _capture(monkeypatch, {"content": [{"type": "text", "text": "x"}]})
    asyncio.run(ApiEngine(_anthropic()).generate("hi", model="claude-haiku"))
    assert seen["payload"]["model"] == "claude-haiku"


def test_missing_key_env_raises_engineerror(monkeypatch):
    monkeypatch.delenv("ANTH_KEY", raising=False)
    with pytest.raises(EngineError) as exc:
        asyncio.run(ApiEngine(_anthropic()).generate("hi"))
    assert "ANTH_KEY" in str(exc.value)  # the NAME, not a value
    assert "is not set" in str(exc.value)


def test_no_model_available_raises_engineerror(monkeypatch):
    monkeypatch.setenv("ANTH_KEY", _KEY)
    provider = Provider(
        id="anth", kind="anthropic",
        base_url="https://api.anthropic.com/v1", api_key_env="ANTH_KEY",
        models=(),  # no default model
    )
    with pytest.raises(EngineError):
        asyncio.run(ApiEngine(provider).generate("hi"))


def test_non_2xx_raises_redacted_engineerror(monkeypatch):
    monkeypatch.setenv("ANTH_KEY", _KEY)

    def boom(url, headers, payload, timeout_s):
        raise HTTPError(url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(engines, "_http_post_json", boom)
    with pytest.raises(EngineError) as exc:
        asyncio.run(ApiEngine(_anthropic()).generate("hi"))
    message = str(exc.value)
    assert "401" in message
    assert _KEY not in message  # key must never appear in the error


def test_urlerror_raises_redacted_engineerror(monkeypatch):
    monkeypatch.setenv("ANTH_KEY", _KEY)

    def boom(url, headers, payload, timeout_s):
        raise URLError("connection refused")

    monkeypatch.setattr(engines, "_http_post_json", boom)
    with pytest.raises(EngineError) as exc:
        asyncio.run(ApiEngine(_anthropic()).generate("hi"))
    assert _KEY not in str(exc.value)


def test_unexpected_response_shape_raises_engineerror(monkeypatch):
    monkeypatch.setenv("OR_KEY", _KEY)
    _capture(monkeypatch, {"choices": []})  # no message
    # openai parser on an empty choices list -> IndexError -> EngineError
    with pytest.raises(EngineError):
        asyncio.run(ApiEngine(_openai()).generate("hi"))


# --- factory + engine-name validation -------------------------------------


def test_get_engine_api_returns_apiengine(tmp_path):
    add_provider(tmp_path, _anthropic())
    engine = get_engine("api:anth", data_dir=tmp_path)
    assert isinstance(engine, ApiEngine)
    assert engine.name() == "api:anth"


def test_get_engine_api_unknown_provider_raises(tmp_path):
    with pytest.raises(EngineError) as exc:
        get_engine("api:ghost", data_dir=tmp_path)
    assert "ghost" in str(exc.value)


def test_get_engine_mock_is_still_the_offline_default(tmp_path):
    engine = get_engine("mock", data_dir=tmp_path)
    assert engine.name() == "mock"


@pytest.mark.parametrize("name", ["mock", "claude", "codex", "gemini", "api:foo",
                                  "api:my-provider_1"])
def test_is_valid_engine_name_accepts(name):
    assert is_valid_engine_name(name) is True


@pytest.mark.parametrize("name", ["", "nope", "api:", "api:BAD!", "api:UP",
                                  "openai"])
def test_is_valid_engine_name_rejects(name):
    assert is_valid_engine_name(name) is False


def test_engine_name_arg_rejects_junk():
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        engine_name_arg("api:BAD!")
    assert engine_name_arg("api:good") == "api:good"


# --------------------------------------------------------------------------
# Finding the CLI at all
# --------------------------------------------------------------------------


def test_a_cli_engine_is_found_when_path_is_minimal(monkeypatch, tmp_path):
    """launchd gives the server `/usr/bin:/bin:/usr/sbin:/sbin`.

    That is how the launcher starts it, and an npm-installed `claude` lives
    in `~/.npm-global/bin`, which is not on that list. Every extraction and
    every critic batch failed with "engine executable not found" while the
    same call worked from a shell — which reads as an intermittent fault
    rather than a missing directory.
    """
    from ontologylab import engines

    fake_home = tmp_path / "home"
    binary = fake_home / ".npm-global/bin/claude"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(engines.pathlib.Path, "home", lambda: fake_home)

    assert engines.resolve_cli("claude") == str(binary)


def test_a_genuinely_missing_binary_keeps_its_familiar_error(monkeypatch, tmp_path):
    """Falling back to the bare name matters: the error a user sees for a
    tool they never installed should not change."""
    from ontologylab import engines

    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(engines.pathlib.Path, "home", lambda: tmp_path)

    assert engines.resolve_cli("not-installed-anywhere") == "not-installed-anywhere"


def test_every_cli_engine_resolves_rather_than_trusting_path():
    """Three engines shell out; all three had the same bug."""
    import inspect
    import re

    from ontologylab import engines

    source = inspect.getsource(engines)
    for tool in ("claude", "codex", "gemini"):
        assert f'cmd = ["{tool}"' not in source, (
            f"{tool} is invoked by bare name and depends on PATH"
        )
        assert re.search(rf'cmd = \[resolve_cli\("{tool}"\)', source), (
            f"{tool} does not go through resolve_cli"
        )


# --------------------------------------------------------------------------
# Availability must be decided by the lookup that does the running
# --------------------------------------------------------------------------


def test_engine_availability_uses_the_same_lookup_as_invocation(monkeypatch):
    """The load-bearing one.

    `resolve_cli` was added so the server could run a CLI that PATH does not
    mention; the availability probe kept calling `shutil.which` directly and
    so answered a question about a different process. Under launchd's PATH
    they disagree, and the disagreement is silent in the worst direction:
    /api/engines reports every CLI engine unavailable, the browser disables
    them in every picker and selects the first available one instead, and
    the chat composer ends up on mock — which finds nothing in a biomedical
    abstract and reports that as zero proposals, not as an error.
    """
    from ontologylab import engines as engines_mod
    from ontologylab.server import settings as settings_mod

    # Exactly the launchd condition: not on PATH, present where npm puts it.
    monkeypatch.setattr(engines_mod.shutil, "which", lambda _n: None)
    monkeypatch.setattr(engines_mod, "resolve_cli",
                        lambda name: f"/somewhere/else/{name}")

    infos = {e.name: e.available for e in settings_mod.engines()}

    assert infos["claude"] is True, "found by resolve_cli, reported missing"
    assert infos["codex"] is True and infos["gemini"] is True


def test_an_engine_that_is_genuinely_absent_still_reports_unavailable():
    """The guard on the fix: resolve_cli returns the bare name when it finds
    nothing, and a truthiness test on that string would call everything
    available — which is the same bug pointing the other way."""
    from ontologylab.engines import resolve_available

    assert resolve_available("definitely-not-a-real-cli-xyzzy") is False
