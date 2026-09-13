"""BYOK: provider keys in the Keychain and the OpenRouter OAuth connect flow.

Two halves, both offline:

* ``providers.py`` — a provider can now carry a Keychain account; resolution
  prefers it over the env var, and the registry still never serializes a key.
* ``oauth_connect.py`` + ``oauth_routes.py`` — the OpenRouter PKCE flow. The
  callback deliberately sits outside ``/api/*`` (the samesite=strict cookie
  is not sent on the cross-site navigation back), so the tests prove the
  state parameter is the whole guard: no session, single-use, TTL-bound.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from ontologylab import keychain, oauth_connect
from ontologylab.keychain import keychain_available
from ontologylab.oauth_connect import (
    CALLBACK_PATH,
    OAuthError,
    begin_flow,
    clear_pending,
    exchange_code_for_key,
    generate_pkce,
    take_flow,
)
from ontologylab.providers import (
    Provider,
    api_key_present,
    canonical_keychain_account,
    dedicated_api_key_env,
    forget_api_key,
    get_provider,
    load_providers,
    resolve_api_key,
)
from ontologylab.server.app import create_app
from tests.conftest import drop_test_session

SECRET = "sk-or-v1-testsecret0123456789abcdef"

_HELPER_SRC = (
    Path(__file__).resolve().parents[1] / "launcher" / "keychain-helper.swift"
)

needs_keychain = pytest.mark.skipif(
    not keychain_available(), reason="no macOS `security` binary"
)


@pytest.fixture(scope="module")
def keychain_helper():
    """Compile the real Swift helper once, like test_sources_routes does."""
    work = tempfile.mkdtemp(prefix="ol-keychain-helper-oauth-")
    binary = os.path.join(work, "keychain-helper")
    import subprocess

    completed = subprocess.run(
        ["swiftc", "-O", str(_HELPER_SRC), "-o", binary],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"swiftc unavailable or failed: {completed.stderr.strip()}")
    return binary


@pytest.fixture
def _isolated_keychain(monkeypatch, tmp_path, keychain_helper):
    """Redirect the Keychain service names and helper into this test only."""
    test_service = f"ontologylab.test.{os.getpid()}.{id(tmp_path)}"
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", keychain_helper)
    monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE", test_service)
    monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE_LEGACY", f"{test_service}-legacy")
    yield


@pytest.fixture(autouse=True)
def _no_pending_flows():
    clear_pending()
    yield
    clear_pending()


def _provider(**overrides) -> Provider:
    base = {
        "id": "openrouter",
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    }
    base.update(overrides)
    return Provider(**base)


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path / "data"))


def _stub_exchange(monkeypatch, key: str = SECRET, status: int = 200):
    """Replace the hardened urlopen with a canned token-endpoint response."""
    calls: list[dict] = []

    class _Response:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _fake_urlopen(request, timeout=0):
        calls.append(
            {
                "url": request.full_url,
                "body": json.loads(request.data.decode()),
            }
        )
        if status != 200:
            from urllib.error import HTTPError

            from email.message import Message
            from urllib.error import HTTPError

            raise HTTPError(request.full_url, status, "err", Message(), None)
        return _Response(json.dumps({"key": key}).encode())

    monkeypatch.setattr(oauth_connect, "urlopen", _fake_urlopen)
    return calls


# --- providers.py: Keychain locator ----------------------------------------


def test_provider_roundtrip_keeps_keychain_account(tmp_path):
    provider = _provider(keychain_account="provider.openrouter")
    from ontologylab.providers import add_provider

    add_provider(tmp_path, provider)
    loaded = get_provider(tmp_path, "openrouter")
    assert loaded is not None
    assert loaded.keychain_account == "provider.openrouter"


def test_provider_registry_still_never_serializes_a_key(tmp_path):
    from ontologylab.providers import add_provider
    from ontologylab.paths import providers_path

    add_provider(tmp_path, _provider(keychain_account="provider.openrouter"))
    raw = providers_path(tmp_path).read_text(encoding="utf-8")
    assert SECRET not in raw
    stored = json.loads(raw)["providers"][0]
    assert "key" not in stored
    assert stored["keychain_account"] == "provider.openrouter"


def test_resolve_api_key_prefers_keychain_over_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    provider = _provider(keychain_account="provider.openrouter")
    monkeypatch.setattr(
        "ontologylab.providers.resolve_key",
        lambda account, env: "keychain-key" if account else None,
    )
    assert resolve_api_key(provider) == "keychain-key"


def test_api_key_present_is_passive(monkeypatch):
    # A configured account reports present without touching the Keychain.
    provider = _provider(keychain_account="provider.openrouter")
    assert api_key_present(provider) is True
    # Env path still reports by whether the variable is set.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert api_key_present(_provider()) is False
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert api_key_present(_provider()) is True


def test_forget_api_key_only_touches_keychain(monkeypatch):
    deleted: list[str] = []
    monkeypatch.setattr(
        "ontologylab.providers.delete_key", lambda a: deleted.append(a) or True
    )
    assert forget_api_key(_provider(keychain_account="provider.x")) is True
    assert deleted == ["provider.x"]
    assert forget_api_key(_provider()) is False


# --- oauth_connect.py: PKCE + flow state ------------------------------------


def test_pkce_verifier_challenges_to_s256():
    verifier, challenge = generate_pkce()
    import base64
    import hashlib

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert verifier != challenge


def test_begin_flow_url_carries_pkce_and_state():
    url = begin_flow("openrouter", "http://127.0.0.1:8765" + CALLBACK_PATH)
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://openrouter.ai/auth?")
    assert query["code_challenge_method"] == ["S256"]
    assert query["callback_url"] == ["http://127.0.0.1:8765" + CALLBACK_PATH]
    assert len(query["state"][0]) >= 16
    # The verifier itself never leaves the process via the URL.
    flow = take_flow(query["state"][0])
    assert flow.code_verifier not in url


def test_take_flow_is_single_use():
    url = begin_flow("openrouter", "http://127.0.0.1:8765" + CALLBACK_PATH)
    state = parse_qs(urlparse(url).query)["state"][0]
    take_flow(state)
    with pytest.raises(OAuthError):
        take_flow(state)


def test_take_flow_rejects_unknown_state():
    with pytest.raises(OAuthError):
        take_flow("never-registered")


def test_expired_flow_is_rejected(monkeypatch):
    url = begin_flow("openrouter", "http://127.0.0.1:8765" + CALLBACK_PATH)
    state = parse_qs(urlparse(url).query)["state"][0]
    # Push the flow's deadline into the past rather than sleeping.
    with oauth_connect._lock:
        flow = oauth_connect._pending[state]
        oauth_connect._pending[state] = type(flow)(
            state=flow.state,
            code_verifier=flow.code_verifier,
            provider_id=flow.provider_id,
            expires_at=0.0,
        )
    with pytest.raises(OAuthError):
        take_flow(state)


def test_exchange_posts_code_and_verifier(monkeypatch):
    calls = _stub_exchange(monkeypatch)
    url = begin_flow("openrouter", "http://127.0.0.1:8765" + CALLBACK_PATH)
    state = parse_qs(urlparse(url).query)["state"][0]
    flow = take_flow(state)
    key = exchange_code_for_key(flow, "the-code")
    assert key == SECRET
    assert calls[0]["url"] == "https://openrouter.ai/api/v1/auth/keys"
    assert calls[0]["body"]["code"] == "the-code"
    assert calls[0]["body"]["code_verifier"] == flow.code_verifier
    assert calls[0]["body"]["code_challenge_method"] == "S256"


def test_exchange_rejects_a_non_key_response(monkeypatch):
    _stub_exchange(monkeypatch, key="not-an-openrouter-key")
    url = begin_flow("openrouter", "http://127.0.0.1:8765" + CALLBACK_PATH)
    state = parse_qs(urlparse(url).query)["state"][0]
    flow = take_flow(state)
    with pytest.raises(OAuthError):
        exchange_code_for_key(flow, "the-code")


def test_exchange_error_never_quotes_the_code(monkeypatch):
    _stub_exchange(monkeypatch, status=403)
    url = begin_flow("openrouter", "http://127.0.0.1:8765" + CALLBACK_PATH)
    state = parse_qs(urlparse(url).query)["state"][0]
    flow = take_flow(state)
    with pytest.raises(OAuthError) as excinfo:
        exchange_code_for_key(flow, "the-secret-code")
    assert "the-secret-code" not in str(excinfo.value)


def test_exchange_is_blocked_in_offline_mode(monkeypatch):
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    url = begin_flow("openrouter", "http://127.0.0.1:8765" + CALLBACK_PATH)
    state = parse_qs(urlparse(url).query)["state"][0]
    flow = take_flow(state)
    from ontologylab.paths import NetworkBlocked

    with pytest.raises(NetworkBlocked):
        exchange_code_for_key(flow, "the-code")


# --- routes: connect + callback ---------------------------------------------


def test_connect_returns_auth_url(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ontologylab.server.oauth_routes.keychain_available", lambda: True
    )
    client = _client(tmp_path)
    response = client.post("/api/providers/openrouter/connect")
    assert response.status_code == 200
    auth_url = response.json()["auth_url"]
    assert auth_url.startswith("https://openrouter.ai/auth?")
    assert parse_qs(urlparse(auth_url).query)["state"]


def test_connect_without_keychain_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ontologylab.server.oauth_routes.keychain_available", lambda: False
    )
    client = _client(tmp_path)
    response = client.post("/api/providers/openrouter/connect")
    assert response.status_code == 400
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


def test_callback_needs_no_session_cookie(tmp_path, monkeypatch):
    """The whole point of the route: samesite=strict means no cookie arrives."""
    monkeypatch.setattr(
        "ontologylab.server.oauth_routes.keychain_available", lambda: True
    )
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "ontologylab.server.oauth_routes.write_key",
        lambda account, key: written.append((account, key)),
    )
    _stub_exchange(monkeypatch)

    client = _client(tmp_path)
    auth_url = client.post("/api/providers/openrouter/connect").json()["auth_url"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]

    bare = drop_test_session(TestClient(client.app))
    response = bare.get(
        f"{CALLBACK_PATH}?code=abc&state={state}", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/engines?connected=openrouter"
    assert written == [("provider.openrouter", SECRET)]
    provider = get_provider(tmp_path / "data", "openrouter")
    assert provider is not None
    assert provider.keychain_account == "provider.openrouter"
    # The key itself never appears in the redirect or the registry.
    assert SECRET not in response.headers["location"]


def test_callback_rejects_bad_state_without_session(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ontologylab.server.oauth_routes.keychain_available", lambda: True
    )
    client = _client(tmp_path)
    bare = drop_test_session(TestClient(client.app))
    response = bare.get(
        f"{CALLBACK_PATH}?code=abc&state=wrong", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/engines?connect_error=state"
    assert load_providers(tmp_path / "data") == []


def test_callback_rejects_replayed_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ontologylab.server.oauth_routes.keychain_available", lambda: True
    )
    monkeypatch.setattr(
        "ontologylab.server.oauth_routes.write_key", lambda account, key: None
    )
    _stub_exchange(monkeypatch)
    client = _client(tmp_path)
    auth_url = client.post("/api/providers/openrouter/connect").json()["auth_url"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    bare = drop_test_session(TestClient(client.app))
    first = bare.get(
        f"{CALLBACK_PATH}?code=abc&state={state}", follow_redirects=False
    )
    second = bare.get(
        f"{CALLBACK_PATH}?code=abc&state={state}", follow_redirects=False
    )
    assert first.headers["location"] == "/engines?connected=openrouter"
    assert second.headers["location"] == "/engines?connect_error=state"


def test_callback_error_param_redirects_denied(tmp_path):
    client = _client(tmp_path)
    bare = drop_test_session(TestClient(client.app))
    response = bare.get(
        f"{CALLBACK_PATH}?error=access_denied", follow_redirects=False
    )
    assert response.headers["location"] == "/engines?connect_error=denied"


def test_callback_exchange_failure_redirects_typed_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ontologylab.server.oauth_routes.keychain_available", lambda: True
    )
    _stub_exchange(monkeypatch, status=403)
    client = _client(tmp_path)
    auth_url = client.post("/api/providers/openrouter/connect").json()["auth_url"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    bare = drop_test_session(TestClient(client.app))
    response = bare.get(
        f"{CALLBACK_PATH}?code=abc&state={state}", follow_redirects=False
    )
    assert response.headers["location"] == "/engines?connect_error=exchange"


# --- routes: pasted key + forget --------------------------------------------


@needs_keychain
def test_create_provider_with_key_stores_in_real_keychain(
    tmp_path, monkeypatch, _isolated_keychain
):
    client = _client(tmp_path)
    response = client.post(
        "/api/providers",
        json={
            "id": "openrouter",
            "kind": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "key": SECRET,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"]["key_present"] is True
    assert body["provider"]["key_location"] == "keychain"
    assert SECRET not in response.text
    provider = get_provider(tmp_path / "data", "openrouter")
    assert provider is not None
    assert resolve_api_key(provider) == SECRET


def test_create_provider_key_never_echoed_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ontologylab.server.routes.keychain_available", lambda: True
    )

    def _refuse(account, key):
        raise keychain.KeychainError(f"the Keychain refused: {SECRET}")

    monkeypatch.setattr("ontologylab.server.routes.write_key", _refuse)
    client = _client(tmp_path)
    response = client.post(
        "/api/providers",
        json={
            "id": "openrouter",
            "kind": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "key": SECRET,
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert SECRET not in response.text


def test_create_provider_key_without_keychain_is_typed_error(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "ontologylab.server.routes.keychain_available", lambda: False
    )
    client = _client(tmp_path)
    response = client.post(
        "/api/providers",
        json={
            "id": "openrouter",
            "kind": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "key": SECRET,
        },
    )
    assert response.json()["error_kind"] == "unsupported"
    assert SECRET not in response.text


def test_forget_provider_key_clears_locator(tmp_path, monkeypatch):
    deleted: list[str] = []
    monkeypatch.setattr(
        "ontologylab.providers.delete_key", lambda a: deleted.append(a) or True
    )
    from ontologylab.providers import add_provider

    add_provider(
        tmp_path / "data",
        _provider(keychain_account="provider.openrouter"),
    )
    client = _client(tmp_path)
    response = client.delete("/api/providers/openrouter/key")
    assert response.json()["forgotten"] is True
    assert deleted == ["provider.openrouter"]
    provider = get_provider(tmp_path / "data", "openrouter")
    assert provider is not None
    assert provider.keychain_account == ""
    assert api_key_present(provider) is False


def test_delete_provider_reports_retained_key(tmp_path):
    from ontologylab.providers import add_provider

    add_provider(
        tmp_path / "data",
        _provider(keychain_account="provider.openrouter"),
    )
    client = _client(tmp_path)
    response = client.delete("/api/providers/openrouter")
    assert response.json()["key_retained"] is True
