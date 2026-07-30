"""C2: a redirect must not carry a credential to another host.

The original plan said paper APIs have fixed hosts and therefore "no
redirects". That was an observation about how the endpoints behave, not a
property anything enforced — and it was wrong as a security claim.
`urllib`'s `HTTPRedirectHandler.redirect_request` strips exactly two headers,
`Content-Length` and `Content-Type`; everything else, an API key included,
goes to the next host unchanged. Dropping credentials across an origin
boundary is what `requests`/`urllib3` do, and this module uses neither.

No attacker is required. One 302 from an endpoint to a maintenance page or a
CDN puts a publisher key in that host's access log. Which is why this lands
*before* step 4 adds keys, not with it.

These tests run a real HTTP server on loopback and drive real redirects
through the real opener. A mocked `redirect_request` would only prove that a
function this file could also have written does what this file says.
"""

from __future__ import annotations

import http.server
import threading
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from ontologylab.connectors import paper_api
from ontologylab.connectors.allowlist import NotAllowlisted
from ontologylab.connectors.paper_api import (
    PAPER_API_HOSTS,
    SOURCE_ORDER,
    _REDIRECT_SAFE_HEADERS,
    check_paper_host,
)

SECRET = "ELS-key-must-never-cross-a-host-9f3a"


class _Recorder(http.server.BaseHTTPRequestHandler):
    """Redirects /start to wherever the test says, and records what arrives."""

    redirect_to = ""
    seen: list[dict[str, str]] = []

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
        type(self).seen.append(
            {k.lower(): v for k, v in self.headers.items()} | {"path": self.path}
        )
        if self.path.startswith("/start"):
            self.send_response(302)
            self.send_header("Location", type(self).redirect_to)
            self.end_headers()
            return
        body = b"redirected body"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep pytest output clean
        return


@pytest.fixture()
def server():
    _Recorder.seen = []
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _origin(httpd) -> str:
    return f"http://127.0.0.1:{httpd.server_address[1]}"


def _allow_loopback(monkeypatch, httpd) -> None:
    """Let the loopback test server stand in for a real endpoint.

    Only the *host list* is relaxed, and only for loopback names. The
    redirect handler, the opener, and the header logic under test all run
    unmodified — a real https endpoint cannot be stood up in a unit test
    without a CA, and mocking the handler instead would prove nothing.

    `127.0.0.1` and `localhost` are the same socket but different hosts to
    the comparison being tested, which is what makes them usable as the two
    sides of an origin boundary.
    """
    original = paper_api.check_paper_host

    def _checked(url: str) -> str:
        from urllib.parse import urlparse as _urlparse

        if (_urlparse(url).hostname or "") in ("127.0.0.1", "localhost", "::1"):
            return url
        return original(url)

    monkeypatch.setattr(paper_api, "check_paper_host", _checked)


def _fetch(url: str, headers: dict[str, str]):
    request = Request(url, headers=headers)
    with paper_api._opener.open(request, timeout=10) as response:
        return response.read()


# --------------------------------------------------------------------------
# The host allowlist
# --------------------------------------------------------------------------


def test_the_host_list_is_derived_from_the_endpoint_constants() -> None:
    """Re-typed hosts drift. Every source's endpoint must be represented."""
    assert PAPER_API_HOSTS == {
        # keyless
        "export.arxiv.org",
        "api.crossref.org",
        "api.openalex.org",
        "api.semanticscholar.org",
        "www.ebi.ac.uk",
        "clinicaltrials.gov",
        # publisher APIs — one fixed host each, which is what lets them sit
        # in an exact-match allowlist at all
        "api.elsevier.com",
        "api.springernature.com",
        "api.core.ac.uk",
    }
    # Every source contributes a host EXCEPT the one whose endpoint is the
    # user's own machine. That exception is named here rather than being a
    # count that quietly absorbs the next source someone adds without a
    # constant — which is the drift this test exists to catch.
    from ontologylab.connectors.paper_api import SEARXNG_SOURCE

    hostless = set(SOURCE_ORDER) - {
        "arxiv", "crossref", "openalex", "semanticscholar", "europepmc",
        "clinicaltrials", "elsevier", "springer", "core",
    }
    assert hostless == {SEARXNG_SOURCE}, (
        "a source with no endpoint constant cannot be host-checked; "
        "SearXNG is allowed only because check_searxng_base_url confines "
        "it to loopback/private addresses"
    )


def test_every_implemented_source_endpoint_passes_its_own_check() -> None:
    """A source whose endpoint its own guard rejects could never fetch."""
    for url in (
        paper_api.ARXIV_API_URL,
        paper_api.CROSSREF_API_URL,
        paper_api.OPENALEX_API_URL,
        paper_api.SEMANTIC_SCHOLAR_API_URL,
        paper_api.EUROPEPMC_API_URL,
        paper_api.ELSEVIER_API_URL,
        paper_api.SPRINGER_API_URL,
        paper_api.CORE_API_URL,
    ):
        assert check_paper_host(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/x",
        "https://api.crossref.org.evil.com/x",  # suffix trick
        "https://evil.com/?api.crossref.org",
        "https://cdn.crossref.org/x",  # subdomain, not exact
    ],
)
def test_a_foreign_host_is_refused(url) -> None:
    with pytest.raises(NotAllowlisted):
        check_paper_host(url)


def test_an_http_downgrade_on_an_allowlisted_host_is_refused() -> None:
    """The host is right and the request is still in the clear.

    A key travels in a header; a header travels over the wire. An endpoint
    that 302s to its own http:// URL would expose it to anything on the path.
    """
    with pytest.raises(NotAllowlisted):
        check_paper_host("http://api.crossref.org/works")


# --------------------------------------------------------------------------
# Real redirects, real headers
# --------------------------------------------------------------------------


def test_a_credential_does_not_survive_a_cross_host_redirect(
    server, monkeypatch
) -> None:
    """The reproduction. Two hosts, one key, and it must stop at the first."""
    port = server.server_address[1]
    # `localhost` and `127.0.0.1` resolve to the same socket but are different
    # hosts to the redirect logic — exactly the boundary being tested.
    _Recorder.redirect_to = f"http://localhost:{port}/landed"
    _allow_loopback(monkeypatch, server)

    _fetch(
        f"http://127.0.0.1:{port}/start",
        {"X-Els-Apikey": SECRET, "Authorization": f"Bearer {SECRET}"},
    )

    assert len(_Recorder.seen) == 2, "the redirect did not happen"
    first, second = _Recorder.seen
    assert first.get("x-els-apikey") == SECRET, "the key never reached hop 1"
    assert SECRET not in " ".join(second.values()), (
        f"a credential crossed a host boundary: {second}"
    )


def test_an_unrecognised_key_header_is_dropped_too(server, monkeypatch) -> None:
    """Why this is an allowlist.

    A denylist of known key headers protects only the publishers someone
    remembered. Springer, CORE and whoever comes next each name theirs
    differently, and the failure mode of forgetting one is silent.
    """
    port = server.server_address[1]
    _Recorder.redirect_to = f"http://localhost:{port}/landed"
    _allow_loopback(monkeypatch, server)

    _fetch(
        f"http://127.0.0.1:{port}/start",
        {"X-Some-Future-Publisher-Token": SECRET},
    )

    _first, second = _Recorder.seen
    assert SECRET not in " ".join(second.values())
    assert "x-some-future-publisher-token" not in second


def test_the_user_agent_does_survive_so_the_fetch_still_works(
    server, monkeypatch
) -> None:
    """Stripping everything would be safe and useless — APIs rate-limit
    anonymous clients, which is what the User-Agent exists to avoid."""
    port = server.server_address[1]
    _Recorder.redirect_to = f"http://localhost:{port}/landed"
    _allow_loopback(monkeypatch, server)

    _fetch(f"http://127.0.0.1:{port}/start", {"User-Agent": "ontologylab-test"})

    _first, second = _Recorder.seen
    assert second.get("user-agent") == "ontologylab-test"


def test_a_same_host_redirect_keeps_its_headers(server, monkeypatch) -> None:
    """Redirect within one host is not a boundary crossing.

    Endpoints redirect to themselves routinely (trailing slash, canonical
    path). Stripping there would break authenticated fetches for no gain.
    """
    port = server.server_address[1]
    _Recorder.redirect_to = f"http://127.0.0.1:{port}/landed"
    _allow_loopback(monkeypatch, server)

    _fetch(f"http://127.0.0.1:{port}/start", {"X-Els-Apikey": SECRET})

    _first, second = _Recorder.seen
    assert second.get("x-els-apikey") == SECRET


def test_the_body_still_arrives_after_a_stripped_redirect(
    server, monkeypatch
) -> None:
    """The guard must not turn a working fetch into a broken one."""
    port = server.server_address[1]
    _Recorder.redirect_to = f"http://localhost:{port}/landed"
    _allow_loopback(monkeypatch, server)

    body = _fetch(f"http://127.0.0.1:{port}/start", {"X-Els-Apikey": SECRET})

    assert body == b"redirected body"


def test_a_redirect_to_a_foreign_host_is_refused_outright(
    server, monkeypatch
) -> None:
    """Stripping is the second line. The hop itself should not happen."""
    port = server.server_address[1]
    _Recorder.redirect_to = "https://evil.example.com/collect"
    # No loopback relaxation: the real check runs on the redirect target.

    with pytest.raises(NotAllowlisted):
        _fetch(f"http://127.0.0.1:{port}/start", {"X-Els-Apikey": SECRET})

    assert len(_Recorder.seen) == 1, "the request reached a second host"


def test_the_refusal_names_the_host_not_the_url(server, monkeypatch) -> None:
    """H1 applies here: this message reaches provenance and the job log."""
    port = server.server_address[1]
    _Recorder.redirect_to = f"https://evil.example.com/collect?apiKey={SECRET}"

    with pytest.raises(NotAllowlisted) as excinfo:
        _fetch(f"http://127.0.0.1:{port}/start", {})

    assert SECRET not in str(excinfo.value)
    assert "evil.example.com" in str(excinfo.value)


# --------------------------------------------------------------------------
# The fetch path actually uses the guarded opener
# --------------------------------------------------------------------------


def test_the_module_seam_routes_through_the_guarded_opener() -> None:
    """`urlopen` is the name every test patches, including the conftest
    safety nets that make an accidental real network call explode. It has to
    stay that name *and* go through the opener."""
    assert paper_api.urlopen == paper_api._opener.open


def test_the_opener_has_the_redirect_guard_installed() -> None:
    assert any(
        isinstance(handler, paper_api._AllowlistedPaperRedirect)
        for handler in paper_api._opener.handlers
    )


def test_a_real_fetch_follows_a_redirect_through_the_guard(
    server, monkeypatch
) -> None:
    """End to end: `_http_get_text`, not the opener directly.

    The stripping assertion is the load-bearing one. Without it this test
    passes against a plain unguarded opener too — a redirect gets followed
    and a body comes back either way, which is exactly how a bypassed guard
    would look.
    """
    port = server.server_address[1]
    _Recorder.redirect_to = f"http://localhost:{port}/landed"
    _allow_loopback(monkeypatch, server)
    monkeypatch.setattr(paper_api, "assert_network_allowed", lambda _msg: None)
    monkeypatch.setattr(paper_api, "_USER_AGENT", "ontologylab-test")
    # A key would live here once step 4 lands; put one there now.
    monkeypatch.setattr(
        paper_api, "Request",
        lambda url, headers=None: Request(
            url, headers={**(headers or {}), "X-Els-Apikey": SECRET}
        ),
    )

    text = paper_api._http_get_text(f"http://127.0.0.1:{port}/start")

    assert text == "redirected body"
    assert len(_Recorder.seen) == 2
    first, second = _Recorder.seen
    assert first.get("x-els-apikey") == SECRET, "the key never reached hop 1"
    assert SECRET not in " ".join(second.values()), (
        "the real fetch path carried a credential across a host boundary"
    )


def test_safe_headers_are_a_closed_set() -> None:
    """Adding to this set is how a credential would be re-admitted."""
    assert _REDIRECT_SAFE_HEADERS == {"user-agent", "accept", "accept-encoding"}
    assert all(name.islower() for name in _REDIRECT_SAFE_HEADERS), (
        "comparison lowercases the header name; the set must match"
    )


def test_an_error_response_is_not_swallowed_by_the_guard(
    server, monkeypatch
) -> None:
    """A 404 must still be a 404 — the handler only touches 3xx."""
    _Recorder.redirect_to = ""
    port = server.server_address[1]

    class _NotFound(_Recorder):
        def do_GET(self):  # noqa: N802
            self.send_response(404)
            self.end_headers()

    server.RequestHandlerClass = _NotFound
    with pytest.raises(HTTPError):
        _fetch(f"http://127.0.0.1:{port}/start", {})
