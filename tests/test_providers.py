"""Provider registry: validation, atomic round-trip, and secret safety.

Everything is offline — no provider is ever contacted here. The load-bearing
assertion is that a resolved key never lands in the serialized registry.
"""

from __future__ import annotations

import json

import pytest

from ontologylab.paths import providers_path
from ontologylab.providers import (
    Provider,
    ProviderError,
    add_provider,
    get_provider,
    load_providers,
    remove_provider,
    resolve_api_key,
    save_providers,
    validate_provider,
)


def _anthropic(**overrides) -> Provider:
    base = {
        "id": "my-anthropic",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "MY_ANTH_KEY",
        "models": ("claude-fable-5",),
        "label": "primary",
    }
    base.update(overrides)
    return Provider(**base)


# --- validation -----------------------------------------------------------


def test_validate_accepts_good_anthropic_and_openai():
    assert validate_provider(_anthropic()) is not None
    openai = _anthropic(
        id="openrouter",
        kind="openai",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
    )
    assert validate_provider(openai).id == "openrouter"


def test_validate_allows_http_only_for_localhost():
    local = _anthropic(
        id="ollama",
        kind="openai",
        base_url="http://localhost:11434/v1",
        api_key_env="OLLAMA_KEY",
    )
    assert validate_provider(local).id == "ollama"


@pytest.mark.parametrize("bad_id", ["BAD", "has space", "-leads", "x" * 33, ""])
def test_validate_rejects_bad_id(bad_id):
    with pytest.raises(ProviderError):
        validate_provider(_anthropic(id=bad_id))


def test_validate_rejects_unknown_kind():
    with pytest.raises(ProviderError):
        validate_provider(_anthropic(kind="google"))


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://evil.example.com/v1",  # http only allowed for localhost
        "ftp://api.anthropic.com/v1",  # unsupported scheme
        "not-a-url",  # no scheme/host
    ],
)
def test_validate_rejects_bad_base_url(bad_url):
    with pytest.raises(ProviderError):
        validate_provider(_anthropic(base_url=bad_url))


@pytest.mark.parametrize("bad_env", ["lowercase", "1LEADING", "has-dash", ""])
def test_validate_rejects_bad_api_key_env(bad_env):
    with pytest.raises(ProviderError):
        validate_provider(_anthropic(api_key_env=bad_env))


# --- round-trip / upsert / remove -----------------------------------------


def test_save_load_roundtrip(tmp_path):
    providers = [_anthropic(), _anthropic(id="second", api_key_env="SECOND_KEY")]
    save_providers(tmp_path, providers)
    loaded = load_providers(tmp_path)
    assert [p.id for p in loaded] == ["my-anthropic", "second"]
    assert loaded[0].models == ("claude-fable-5",)


def test_add_provider_upserts_by_id(tmp_path):
    add_provider(tmp_path, _anthropic())
    add_provider(tmp_path, _anthropic(label="updated", models=("claude-haiku",)))
    loaded = load_providers(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].label == "updated"
    assert loaded[0].models == ("claude-haiku",)


def test_add_provider_rejects_invalid_before_write(tmp_path):
    with pytest.raises(ProviderError):
        add_provider(tmp_path, _anthropic(id="BAD ID"))
    # Nothing was written — the registry file must not exist.
    assert not providers_path(tmp_path).exists()


def test_get_provider(tmp_path):
    add_provider(tmp_path, _anthropic())
    assert get_provider(tmp_path, "my-anthropic").kind == "anthropic"
    assert get_provider(tmp_path, "missing") is None


def test_remove_provider(tmp_path):
    add_provider(tmp_path, _anthropic())
    assert remove_provider(tmp_path, "my-anthropic") is True
    assert remove_provider(tmp_path, "my-anthropic") is False
    assert load_providers(tmp_path) == []


def test_load_missing_returns_empty(tmp_path):
    assert load_providers(tmp_path) == []


def test_load_corrupt_returns_empty(tmp_path):
    providers_path(tmp_path).write_text("{ not valid json", encoding="utf-8")
    assert load_providers(tmp_path) == []


def test_load_skips_malformed_entry_keeps_good_one(tmp_path):
    providers_path(tmp_path).write_text(
        json.dumps(
            {"providers": [{"id": "ok", "kind": "openai",
                            "base_url": "https://x/v1", "api_key_env": "K"},
                           {"garbage": True}]}
        ),
        encoding="utf-8",
    )
    loaded = load_providers(tmp_path)
    assert [p.id for p in loaded] == ["ok"]


# --- secret posture -------------------------------------------------------


def test_resolve_api_key_from_env(monkeypatch):
    provider = _anthropic()
    assert resolve_api_key(provider) is None  # unset
    monkeypatch.setenv("MY_ANTH_KEY", "  sk-secret-123  ")
    assert resolve_api_key(provider) == "sk-secret-123"  # stripped
    monkeypatch.setenv("MY_ANTH_KEY", "   ")
    assert resolve_api_key(provider) is None  # empty/whitespace -> None


def test_saved_registry_never_contains_key_value(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_ANTH_KEY", "sk-super-secret-value")
    add_provider(tmp_path, _anthropic())
    raw = providers_path(tmp_path).read_text(encoding="utf-8")
    assert "sk-super-secret-value" not in raw
    assert "MY_ANTH_KEY" in raw  # only the env-var NAME is stored
    # And the parsed shape carries no key-like field.
    stored = json.loads(raw)["providers"][0]
    assert set(stored) == {"id", "kind", "base_url", "api_key_env", "models", "label"}
