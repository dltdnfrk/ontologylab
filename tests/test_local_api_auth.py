"""Local API session auth and fail-closed network boundary."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab.server.app import create_app
from tests.conftest import drop_test_session

_SESSION_HEADER = "X-OntologyLab-Session"
_SESSION_COOKIE = "ontologylab_session"
_PROVIDER = {
    "id": "orouter",
    "kind": "openai",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "SRV_OR_KEY",
    "models": ["meta/llama"],
}


def _app(tmp_path: Path):
    return create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")


def _bare_client(app, **kwargs) -> TestClient:
    return drop_test_session(TestClient(app, **kwargs))


def test_unauthenticated_api_is_rejected(tmp_path: Path) -> None:
    client = _bare_client(_app(tmp_path))

    settings = client.get("/api/settings")
    assert settings.status_code == 401, settings.text
    assert "default_engine" not in settings.text

    mutation = client.post("/api/providers", json=_PROVIDER)
    assert mutation.status_code == 401, mutation.text
    assert mutation.json().get("ok") is False


def test_malformed_token_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    client = _bare_client(app)
    token = getattr(app.state, "session_token", "a" * 64)

    for presented in ("", "nope", "0" * 64, token[:-1], token + "x"):
        resp = client.get("/api/settings", headers={_SESSION_HEADER: presented})
        assert resp.status_code == 401, (presented, resp.text)
        assert "default_engine" not in resp.text


def test_docs_and_openapi_are_disabled(tmp_path: Path) -> None:
    client = _bare_client(_app(tmp_path))
    for path in ("/docs", "/redoc", "/openapi.json"):
        resp = client.get(path)
        assert resp.status_code == 404, (path, resp.status_code, resp.text)


def test_security_headers_are_present(tmp_path: Path) -> None:
    client = _bare_client(_app(tmp_path))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "frame-ancestors 'none'" in resp.headers.get("content-security-policy", "")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("referrer-policy") == "no-referrer"
    assert resp.headers.get("permissions-policy")


def test_spoofed_loopback_host_from_non_loopback_peer_is_rejected(
    tmp_path: Path,
) -> None:
    client = _bare_client(
        _app(tmp_path),
        base_url="http://127.0.0.1",
        client=("8.8.8.8", 54321),
        headers={
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
            "X-Forwarded-Host": "127.0.0.1",
        },
    )
    resp = client.get("/")
    assert resp.status_code == 421, resp.text
    assert resp.json().get("error_kind") == "bad_host"


def test_loopback_root_cookie_bootstrap(tmp_path: Path) -> None:
    app = _app(tmp_path)
    client = _bare_client(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 54321),
    )
    root = client.get("/")
    assert root.status_code == 200
    assert "ontologylab" in root.text.lower()
    set_cookie = root.headers.get("set-cookie", "")
    assert _SESSION_COOKIE in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert root.headers.get("cache-control") == "no-store"

    settings = client.get("/api/settings")
    assert settings.status_code == 200, settings.text
    assert "default_engine" in settings.json()
    assert settings.headers.get("cache-control") == "no-store"


def test_healthz_is_the_only_unauthenticated_exemption(tmp_path: Path) -> None:
    client = _bare_client(_app(tmp_path))
    health = client.get("/healthz")
    assert health.status_code == 200, health.text
    body = health.json()
    assert body.get("ok") is True
    assert "default_engine" not in health.text
    assert "providers" not in health.text

    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/engines").status_code == 401


def test_stale_token_after_new_app_is_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    first = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    stale = getattr(first.state, "session_token", "stale-placeholder")
    second = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    fresh = getattr(second.state, "session_token", None)
    client = _bare_client(second)

    rejected = client.get("/api/settings", headers={_SESSION_HEADER: stale})
    assert rejected.status_code == 401, rejected.text
    assert stale != fresh
    assert fresh
    accepted = client.get("/api/settings", headers={_SESSION_HEADER: fresh})
    assert accepted.status_code == 200, accepted.text


def test_non_loopback_serve_refused_even_with_allow_remote(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    import uvicorn

    from ontologylab import serve

    called: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: called.append((a, k)))
    monkeypatch.setattr(
        "sys.argv",
        [
            "ontologylab-serve",
            "--host",
            "0.0.0.0",
            "--allow-remote",
            "--port",
            "8892",
            "--data-dir",
            str(tmp_path / "data"),
            "--packs-dir",
            str(tmp_path / "packs"),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        serve.main()

    assert exit_info.value.code != 0
    assert called == []
    stderr = capsys.readouterr().err
    assert "0.0.0.0" in stderr
    assert "allow-remote" in stderr


def test_session_token_file_is_owner_only(tmp_path: Path) -> None:
    create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    data_dir = tmp_path / "data"
    token_path = data_dir / "session.token"
    assert token_path.is_file()
    assert stat.S_IMODE(os.stat(token_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(data_dir).st_mode) == 0o700
    token = token_path.read_text(encoding="utf-8").strip()
    assert len(token) == 64
    int(token, 16)
