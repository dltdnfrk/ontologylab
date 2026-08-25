"""Wave 1A: credentialed provider HTTP must not follow, proxy, or slurp.

These tests drive real loopback sockets through ApiEngine's monkeypatchable
``_http_post_json`` helper. A mocked redirect hook would only prove that a
function this file could also have written does what this file says.

The load-bearing cases:

* a 302 from server A to server B must never deliver the canary
  ``Authorization`` header to hop 2 (no second hop at all);
* a decoded body of 8 MiB + 1 must be refused, not parsed;
* an environment proxy must not see the request.
"""

from __future__ import annotations

import http.server
import threading
from typing import Callable

import pytest

from ontologylab.engines import EngineError, _http_post_json

CANARY = "Bearer wave1a-canary-do-not-forward"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_TIMEOUT_S = 5.0


class _SilentHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def _discard_body(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)


class _BoundServer:
    def __init__(self, handler: type[http.server.BaseHTTPRequestHandler]) -> None:
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _headers_of(handler: http.server.BaseHTTPRequestHandler) -> dict[str, str]:
    recorded = {key.lower(): value for key, value in handler.headers.items()}
    recorded["path"] = handler.path
    recorded["command"] = handler.command
    return recorded


def _start_pair(
    hop1_factory: Callable[[str], type[http.server.BaseHTTPRequestHandler]],
    hop2_cls: type[http.server.BaseHTTPRequestHandler],
) -> tuple[_BoundServer, _BoundServer]:
    hop2 = _BoundServer(hop2_cls)
    hop1 = _BoundServer(hop1_factory(f"{hop2.origin}/landed"))
    return hop1, hop2


def test_authorization_never_reaches_a_redirect_hop() -> None:
    """Two isolated ports: hop 1 returns 302, hop 2 must stay dark."""
    hop2_seen: list[dict[str, str]] = []

    class Hop2(_SilentHandler):
        def do_GET(self) -> None:
            hop2_seen.append(_headers_of(self))
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            self.do_GET()

    def hop1_cls(location: str) -> type[http.server.BaseHTTPRequestHandler]:
        class Hop1(_SilentHandler):
            def do_POST(self) -> None:
                self._discard_body()
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:
                self.do_POST()

        return Hop1

    hop1: _BoundServer | None = None
    hop2: _BoundServer | None = None
    try:
        hop1, hop2 = _start_pair(hop1_cls, Hop2)
        raised: EngineError | None = None
        try:
            _http_post_json(
                f"{hop1.origin}/start",
                {
                    "Authorization": CANARY,
                    "content-type": "application/json",
                },
                {"ping": True},
                _TIMEOUT_S,
            )
        except EngineError as exc:
            raised = exc
        leaked = [row for row in hop2_seen if CANARY in " ".join(row.values())]
        assert hop2_seen == [], f"second hop was contacted: {hop2_seen}"
        assert leaked == [], f"canary Authorization reached hop 2: {leaked}"
        assert raised is not None, "redirect must surface EngineError"
        assert CANARY not in str(raised)
    finally:
        if hop1 is not None:
            hop1.close()
        if hop2 is not None:
            hop2.close()


def test_an_oversized_json_body_is_refused() -> None:
    """8 MiB + 1 must refuse; a silent slurp would json-decode this payload."""
    pad = _MAX_RESPONSE_BYTES + 1 - 8
    body = b'{"p":"' + (b"x" * pad) + b'"}'
    assert len(body) == _MAX_RESPONSE_BYTES + 1

    class Huge(_SilentHandler):
        def do_POST(self) -> None:
            self._discard_body()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = _BoundServer(Huge)
    try:
        with pytest.raises(EngineError) as excinfo:
            _http_post_json(
                f"{server.origin}/big",
                {"content-type": "application/json", "Authorization": CANARY},
                {"ping": True},
                30.0,
            )
        message = str(excinfo.value)
        assert CANARY not in message
        assert "8 MiB" in message or "8388608" in message
    finally:
        server.close()


def test_a_configured_proxy_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment HTTP_PROXY must not become a credentialed hop."""
    import urllib.request

    target_seen: list[str] = []
    proxy_seen: list[str] = []

    class Target(_SilentHandler):
        def do_POST(self) -> None:
            self._discard_body()
            target_seen.append(self.path)
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class Proxy(_SilentHandler):
        def do_GET(self) -> None:
            proxy_seen.append(f"{self.command} {self.path}")
            self.send_response(502)
            self.end_headers()

        def do_POST(self) -> None:
            self.do_GET()

        def do_CONNECT(self) -> None:
            proxy_seen.append(f"{self.command} {self.path}")
            self.send_response(502)
            self.end_headers()

    target = _BoundServer(Target)
    proxy = _BoundServer(Proxy)
    previous_opener = getattr(urllib.request, "_opener", None)
    try:
        proxy_url = proxy.origin
        monkeypatch.setenv("HTTP_PROXY", proxy_url)
        monkeypatch.setenv("http_proxy", proxy_url)
        monkeypatch.setenv("HTTPS_PROXY", proxy_url)
        monkeypatch.setenv("https_proxy", proxy_url)
        monkeypatch.setenv("ALL_PROXY", proxy_url)
        monkeypatch.setenv("all_proxy", proxy_url)
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.setattr("urllib.request.proxy_bypass", lambda *_a, **_k: False)
        # Rebuild the process-global opener after the env is set so this
        # asserts OUR seam ignores proxies, not that a stale opener was
        # built before HTTP_PROXY existed.
        urllib.request.install_opener(urllib.request.build_opener())

        result = _http_post_json(
            f"{target.origin}/direct",
            {"content-type": "application/json", "Authorization": CANARY},
            {"ping": True},
            _TIMEOUT_S,
        )
        assert result == {"ok": True}
        assert target_seen == ["/direct"]
        assert proxy_seen == [], f"proxy saw credentialed traffic: {proxy_seen}"
    finally:
        setattr(urllib.request, "_opener", previous_opener)
        target.close()
        proxy.close()


def test_api_engine_generate_surfaces_redacted_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from ontologylab.engines import ApiEngine
    from ontologylab.providers import Provider

    hop2_seen: list[dict[str, str]] = []

    class Hop2(_SilentHandler):
        def do_GET(self) -> None:
            hop2_seen.append(_headers_of(self))
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            self.do_GET()

    def hop1_cls(location: str) -> type[http.server.BaseHTTPRequestHandler]:
        class Hop1(_SilentHandler):
            def do_POST(self) -> None:
                self._discard_body()
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

        return Hop1

    hop1: _BoundServer | None = None
    hop2: _BoundServer | None = None
    try:
        hop1, hop2 = _start_pair(hop1_cls, Hop2)
        monkeypatch.setenv("OL_WAVE1A_KEY", "sk-live-do-not-leak")
        provider = Provider(
            id="local",
            kind="openai",
            base_url=f"{hop1.origin}/v1",
            api_key_env="OL_WAVE1A_KEY",
            models=("m",),
        )
        with pytest.raises(EngineError) as excinfo:
            asyncio.run(ApiEngine(provider).generate("hi"))
        message = str(excinfo.value)
        assert "sk-live-do-not-leak" not in message
        assert hop2_seen == []
    finally:
        if hop1 is not None:
            hop1.close()
        if hop2 is not None:
            hop2.close()


def test_http_post_json_signature_stays_monkeypatchable() -> None:
    import inspect

    parameters = list(inspect.signature(_http_post_json).parameters)
    assert parameters == ["url", "headers", "payload", "timeout_s"]
