"""Wave 2A: provider credential-origin binding and /test rate limiting.

These tests pin the intended protection. Against the pre-hardening registry
they fail because an arbitrary env can be aimed at an attacker origin, the
public projection names the locator, an origin change keeps the old env,
and /test accepts a rapid repeat. That missing protection is the RED, not
an import or syntax error.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab.engines import ApiEngine, EngineError
from ontologylab.paths import providers_path
from ontologylab.providers import (
    Provider,
    ProviderError,
    add_provider,
    dedicated_api_key_env,
    get_provider,
    load_providers,
    validate_provider,
)
from ontologylab.server.app import create_app

CANARY = "wave2a-canary-do-not-exfiltrate"
CANARY_ENV = "WAVE2A_CANARY_SECRET"


class _SilentHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def _discard_body(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)


class _CaptureServer:
    def __init__(self, seen: list[dict[str, str]]) -> None:
        this = self

        class Handler(_SilentHandler):
            def do_POST(self) -> None:
                self._discard_body()
                recorded = {
                    key.lower(): value for key, value in self.headers.items()
                }
                recorded["path"] = self.path
                this.seen.append(recorded)
                body = (
                    b'{"choices":[{"message":{"role":"assistant",'
                    b'"content":"pong"}}]}'
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.seen = seen
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True
        )
        self.thread.start()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _reset_provider_test_limiter() -> Iterator[None]:
    from ontologylab.server.rate_limit import reset_provider_test_limiter

    reset_provider_test_limiter()
    yield
    reset_provider_test_limiter()


def _client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return TestClient(create_app(data_dir=data_dir))


def _official_anthropic(**overrides: object) -> Provider:
    base: dict[str, object] = {
        "id": "anth",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
        "models": ("claude-fable-5",),
    }
    base.update(overrides)
    return Provider(**base)  # type: ignore[arg-type]


def test_arbitrary_env_secret_cannot_be_rebound_to_attacker_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CANARY_ENV, CANARY)
    seen: list[dict[str, str]] = []
    server = _CaptureServer(seen)
    try:
        attacker = Provider(
            id="x",
            kind="openai",
            base_url=f"{server.origin}/v1",
            api_key_env=CANARY_ENV,
            models=("steal",),
        )
        registered: Provider | None
        try:
            add_provider(tmp_path, attacker)
            registered = get_provider(tmp_path, "x")
        except ProviderError:
            registered = None
        if registered is not None:
            try:
                asyncio.run(ApiEngine(registered).generate("ping"))
            except EngineError:
                pass
        leaked = [
            row
            for row in seen
            if CANARY in " ".join(row.values())
        ]
        assert leaked == [], f"canary leaked to attacker origin: {leaked}"
        assert registered is None
        with pytest.raises(ProviderError):
            validate_provider(attacker)
    finally:
        server.close()
        seen.clear()


def test_unsafe_existing_registry_row_is_not_loaded(tmp_path: Path) -> None:
    providers_path(tmp_path).write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "x",
                        "kind": "openai",
                        "base_url": "https://attacker.example/v1",
                        "api_key_env": CANARY_ENV,
                        "models": ["steal"],
                        "label": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_providers(tmp_path) == []


def test_public_projection_hides_env_locator(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post(
        "/api/providers",
        json={
            "id": "orouter",
            "kind": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "models": ["meta/llama"],
        },
    )
    assert created.status_code == 200, created.text
    created_provider = created.json()["provider"]
    assert "api_key_env" not in created_provider
    listed = client.get("/api/providers")
    assert listed.status_code == 200
    body = listed.json()["providers"]
    assert len(body) == 1
    assert "api_key_env" not in body[0]
    assert "OPENROUTER_API_KEY" not in listed.text
    assert "OPENROUTER_API_KEY" not in created.text


def test_same_id_origin_change_cannot_reuse_prior_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C3 replay: id `capture` on origin A, then same id on origin B.

    The first origin may see the canary. The second origin must not, the
    old env must be refused for the new origin, and the bound names must
    differ.
    """
    seen_a: list[dict[str, str]] = []
    seen_b: list[dict[str, str]] = []
    server_a = _CaptureServer(seen_a)
    server_b = _CaptureServer(seen_b)
    try:
        url_a = f"{server_a.origin}/v1"
        url_b = f"{server_b.origin}/v1"
        env_a = dedicated_api_key_env("capture", url_a)
        env_b = dedicated_api_key_env("capture", url_b)
        assert env_a != env_b
        assert env_a.startswith("ONTOLOGYLAB_PROVIDER_CAPTURE_")
        assert env_b.startswith("ONTOLOGYLAB_PROVIDER_CAPTURE_")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        first = Provider(
            id="capture",
            kind="openai",
            base_url=url_a,
            api_key_env=env_a,
            models=("m",),
        )
        add_provider(data_dir, first)
        monkeypatch.setenv(env_a, CANARY)
        asyncio.run(ApiEngine(first).generate("ping"))
        assert any(CANARY in " ".join(row.values()) for row in seen_a)

        stale = Provider(
            id="capture",
            kind="openai",
            base_url=url_b,
            api_key_env=env_a,
            models=("m",),
        )
        with pytest.raises(ProviderError):
            add_provider(data_dir, stale)
        with pytest.raises(ProviderError):
            validate_provider(stale)

        client = TestClient(create_app(data_dir=data_dir))
        upsert = client.post(
            "/api/providers",
            json={
                "id": "capture",
                "kind": "openai",
                "base_url": url_b,
                "api_key_env": env_a,
                "models": ["m"],
            },
        )
        assert upsert.status_code == 400, upsert.text
        assert "api_key_env" not in (upsert.json().get("provider") or {})
        rebound = client.post(
            "/api/providers",
            json={
                "id": "capture",
                "kind": "openai",
                "base_url": url_b,
                "models": ["m"],
            },
        )
        assert rebound.status_code == 200, rebound.text
        assert "api_key_env" not in rebound.json()["provider"]
        loaded = get_provider(data_dir, "capture")
        assert loaded is not None
        assert loaded.api_key_env == env_b
        assert loaded.api_key_env != env_a
        try:
            asyncio.run(ApiEngine(loaded).generate("ping"))
        except EngineError:
            pass
        leaked_b = [
            row for row in seen_b if CANARY in " ".join(row.values())
        ]
        assert leaked_b == [], f"canary reused on new origin: {leaked_b}"
    finally:
        server_a.close()
        server_b.close()


def test_origin_change_rejects_stale_official_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARY)
    add_provider(tmp_path, _official_anthropic())
    seen: list[dict[str, str]] = []
    server = _CaptureServer(seen)
    try:
        rebound = _official_anthropic(
            base_url=f"{server.origin}/v1",
            kind="openai",
            api_key_env="ANTHROPIC_API_KEY",
        )
        with pytest.raises(ProviderError):
            add_provider(tmp_path, rebound)
        loaded = get_provider(tmp_path, "anth")
        assert loaded is not None
        assert loaded.base_url == "https://api.anthropic.com/v1"
        assert seen == []
    finally:
        server.close()


def test_provider_test_rate_limited_on_repeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ontologylab.engines as engines

    client = _client(tmp_path)
    add = client.post(
        "/api/providers",
        json={
            "id": "orouter",
            "kind": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "models": ["meta/llama"],
        },
    )
    assert add.status_code == 200, add.text
    monkeypatch.setenv("OPENROUTER_API_KEY", CANARY)

    def fake_post(url, headers, payload, timeout_s):
        return {"choices": [{"message": {"content": "pong"}}]}

    monkeypatch.setattr(engines, "_http_post_json", fake_post)
    first = client.post("/api/providers/orouter/test")
    assert first.status_code == 200, first.text
    assert first.json()["ok"] is True
    second = client.post("/api/providers/orouter/test")
    assert second.status_code == 429
    assert second.headers.get("retry-after")
    assert CANARY not in second.text
    assert "OPENROUTER_API_KEY" not in second.text
    detail = second.text.lower()
    assert "traceback" not in detail
    assert "authorization" not in detail


def test_official_anthropic_and_openai_accept_only_dedicated_env() -> None:
    assert (
        validate_provider(_official_anthropic()).api_key_env
        == "ANTHROPIC_API_KEY"
    )
    openai = Provider(
        id="oai",
        kind="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        models=("gpt-4o",),
    )
    assert validate_provider(openai).api_key_env == "OPENAI_API_KEY"
    openrouter = Provider(
        id="orouter",
        kind="openai",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        models=("meta/llama",),
    )
    assert validate_provider(openrouter).api_key_env == "OPENROUTER_API_KEY"
    with pytest.raises(ProviderError):
        validate_provider(
            _official_anthropic(api_key_env="ONTOLOGYLAB_PROVIDER_ANTH")
        )
    with pytest.raises(ProviderError):
        validate_provider(
            Provider(
                id="oai",
                kind="openai",
                base_url="https://api.openai.com/v1",
                api_key_env="ONTOLOGYLAB_PROVIDER_OAI",
                models=("gpt-4o",),
            )
        )


def test_custom_and_loopback_providers_use_origin_derived_env() -> None:
    custom_url = "https://models.example/v1"
    custom_env = dedicated_api_key_env("x", custom_url)
    custom = Provider(
        id="x",
        kind="openai",
        base_url=custom_url,
        api_key_env=custom_env,
        models=("m",),
    )
    assert validate_provider(custom).api_key_env == custom_env
    assert custom_env.startswith("ONTOLOGYLAB_PROVIDER_X_")
    loop_url = "http://127.0.0.1:11434/v1"
    loop_env = dedicated_api_key_env("ollama", loop_url)
    loopback = Provider(
        id="ollama",
        kind="openai",
        base_url=loop_url,
        api_key_env=loop_env,
        models=("llama",),
    )
    assert validate_provider(loopback).api_key_env == loop_env
    assert loop_env.startswith("ONTOLOGYLAB_PROVIDER_OLLAMA_")
    with pytest.raises(ProviderError):
        validate_provider(
            Provider(
                id="x",
                kind="openai",
                base_url="https://models.example/v1",
                api_key_env="ANTHROPIC_API_KEY",
                models=("m",),
            )
        )
    with pytest.raises(ProviderError):
        validate_provider(
            Provider(
                id="ollama",
                kind="openai",
                base_url="http://127.0.0.1:11434/v1",
                api_key_env="OLLAMA_KEY",
                models=("llama",),
            )
        )
