"""Regression tests for the local-only web hardening and offline kill switch.

Covers the adversarial-review findings:
* DNS-rebinding defense — non-loopback Host headers are refused (421).
* CSRF defense — cross-site state-changing requests are refused (403).
* Pack path traversal — pack name / pack_id are confined to a safe segment.
* Offline mode — ONTOLOGYLAB_OFFLINE blocks outbound network egress.
* Serve bind guard — non-loopback bind requires an explicit acknowledgement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ontologylab import paths
from ontologylab.server import security


# ---------------------------------------------------------------------------
# Pure predicates (no server)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header,expected",
    [
        ("127.0.0.1:8765", True),
        ("127.0.0.1", True),
        ("localhost", True),
        ("localhost:8765", True),
        ("[::1]:8765", True),
        ("[::1]", True),
        ("127.0.0.2", True),  # whole 127/8 is loopback
        ("evil.com", False),
        ("evil.com:8765", False),
        ("169.254.169.254", False),  # cloud metadata IP is not loopback
        ("", False),
        (None, False),
    ],
)
def test_host_header_is_local(header, expected):
    assert security.host_header_is_local(header) is expected


def test_extra_allowed_hosts_widen_trust(monkeypatch):
    monkeypatch.setenv("ONTOLOGYLAB_ALLOWED_HOSTS", "proxy.internal, testserver")
    assert security.host_header_is_trusted("proxy.internal") is True
    assert security.host_header_is_trusted("testserver:80") is True
    assert security.host_header_is_trusted("evil.com") is False


def test_extra_allowed_hosts_empty_by_default(monkeypatch):
    monkeypatch.delenv("ONTOLOGYLAB_ALLOWED_HOSTS", raising=False)
    assert security.host_header_is_trusted("127.0.0.1:8765") is True
    assert security.host_header_is_trusted("anything.example") is False


@pytest.mark.parametrize(
    "method,sec_fetch_site,origin,expected",
    [
        ("GET", "cross-site", "http://evil.com", False),  # safe method
        ("HEAD", "cross-site", None, False),
        ("POST", "same-origin", None, False),
        ("POST", "none", None, False),
        ("POST", "same-site", None, True),
        ("POST", "cross-site", None, True),
        ("POST", None, None, False),  # non-browser client (curl/CLI/MCP)
        ("POST", None, "http://127.0.0.1:8765", False),  # local origin
        ("POST", None, "http://evil.com", True),  # remote origin, no fetch hdr
        ("DELETE", "cross-site", None, True),
    ],
)
def test_is_cross_site_state_change(method, sec_fetch_site, origin, expected):
    assert (
        security.is_cross_site_state_change(method, sec_fetch_site, origin)
        is expected
    )


# ---------------------------------------------------------------------------
# Middleware integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    # The session fixture allowlists "testserver"; keep that so the default
    # TestClient host passes and we can probe the guards with explicit headers.
    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    with TestClient(app) as tc:
        yield tc


def test_non_loopback_host_is_refused(client):
    # A rebound attacker origin still carries its own Host header.
    resp = client.get("/api/engines", headers={"Host": "evil.com"})
    assert resp.status_code == 421
    assert resp.json()["error_kind"] == "bad_host"


def test_loopback_host_passes(client):
    resp = client.get("/api/engines", headers={"Host": "127.0.0.1:8765"})
    assert resp.status_code == 200


def test_cross_site_state_change_is_refused(client):
    resp = client.post(
        "/api/packs/build",
        json={"name": "demo"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_kind"] == "cross_site"


def test_same_origin_state_change_allowed(client):
    resp = client.post(
        "/api/packs/build",
        json={"name": "demo"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    # Passes the guard; the build itself succeeds (empty pack is buildable).
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_cross_site_read_is_allowed(client):
    # Safe methods are never blocked as CSRF.
    resp = client.get("/api/engines", headers={"Sec-Fetch-Site": "cross-site"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Pack path traversal
# ---------------------------------------------------------------------------


def test_pack_name_rejects_traversal():
    from ontologylab.packbuilder import PackBuildError, safe_pack_component

    for bad in ["../../etc", "a/b", "..", ".", "", "x\x00y", "na me"]:
        with pytest.raises(PackBuildError):
            safe_pack_component(bad)
    assert safe_pack_component("demo-2026.01") == "demo-2026.01"


def test_pack_build_request_rejects_bad_name():
    pytest.importorskip("pydantic")
    from pydantic import ValidationError

    from ontologylab.server.schemas import PackBuildRequest

    with pytest.raises(ValidationError):
        PackBuildRequest(name="../../evil")
    assert PackBuildRequest(name="good_pack").name == "good_pack"


def test_pack_sqlite_path_rejects_traversal(tmp_path):
    from ontologylab.packbuilder import PackBuildError, pack_sqlite_path

    with pytest.raises(PackBuildError):
        pack_sqlite_path(tmp_path, "../../../etc")


def test_build_pack_rejects_bad_name(tmp_path):
    from ontologylab.packbuilder import PackBuildError, build_pack

    # Even before the KG-exists check, an unsafe name is refused.
    with pytest.raises(PackBuildError):
        build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "../escape")


# ---------------------------------------------------------------------------
# Offline kill switch
# ---------------------------------------------------------------------------


def test_offline_mode_env_parsing(monkeypatch):
    for truthy in ["1", "true", "TRUE", "yes", "on"]:
        monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", truthy)
        assert paths.offline_mode() is True
    for falsy in ["0", "false", "no", "", "off"]:
        monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", falsy)
        assert paths.offline_mode() is False
    monkeypatch.delenv("ONTOLOGYLAB_OFFLINE", raising=False)
    assert paths.offline_mode() is False


def test_assert_network_allowed_blocks_when_offline(monkeypatch):
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    with pytest.raises(paths.NetworkBlocked):
        paths.assert_network_allowed("test egress")
    monkeypatch.delenv("ONTOLOGYLAB_OFFLINE", raising=False)
    paths.assert_network_allowed("test egress")  # no raise when online


def test_offline_blocks_cli_engine(monkeypatch):
    import asyncio

    from ontologylab.engines import ClaudeEngine

    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    with pytest.raises(paths.NetworkBlocked):
        asyncio.run(ClaudeEngine().generate("hello"))


def test_offline_blocks_paper_connector(monkeypatch):
    from ontologylab.connectors.paper_api import _http_get_text

    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    with pytest.raises(paths.NetworkBlocked):
        _http_get_text("https://export.arxiv.org/api/query?search_query=x")


def test_offline_blocks_web_crawl(monkeypatch):
    from ontologylab.connectors.web_crawl import _fetch_url

    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    with pytest.raises(paths.NetworkBlocked):
        _fetch_url("https://docs.python.org/3/")


def test_offline_allows_loopback_api_engine(monkeypatch):
    # A provider pointing at loopback keeps data on-device, so offline mode
    # must NOT block it. Verify the egress guard exempts loopback URLs.
    from ontologylab.engines import _url_is_loopback

    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    assert _url_is_loopback("http://localhost:11434/v1/chat/completions") is True
    assert _url_is_loopback("http://127.0.0.1:11434/api") is True
    assert _url_is_loopback("https://api.anthropic.com/v1/messages") is False


# ---------------------------------------------------------------------------
# Serve bind guard
# ---------------------------------------------------------------------------


def test_serve_refuses_non_loopback_without_flag(monkeypatch):
    from ontologylab import serve

    monkeypatch.setattr(sys, "argv", ["ontologylab.serve", "--host", "0.0.0.0"])
    with pytest.raises(SystemExit):
        serve.main()


def test_serve_is_local_hostname_predicate():
    assert security.is_local_hostname("127.0.0.1") is True
    assert security.is_local_hostname("localhost") is True
    assert security.is_local_hostname("0.0.0.0") is False
    assert security.is_local_hostname("192.168.1.5") is False
