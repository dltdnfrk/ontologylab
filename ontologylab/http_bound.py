"""Bounded stdlib HTTP for credentialed provider calls.

This is the only network opener ApiEngine may use. It disables environment
and system proxies, refuses every redirect before a second hop, checks the
original exact origin, and caps the decoded body at 8 MiB. Messages never
include a URL, header, or body.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class BoundHttpError(Exception):
    """Typed seam failure. The message must not include URL, headers, or body."""


class RedirectRefused(BoundHttpError):
    """A redirect would be a second hop; credentialed calls do not follow."""


class ResponseTooLarge(BoundHttpError):
    """Decoded body exceeded ``MAX_RESPONSE_BYTES``."""


class OriginMismatch(BoundHttpError):
    """Response origin did not match the original exact origin."""


def _exact_origin(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise OriginMismatch("origin mismatch")
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, host, port


class _RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedirectRefused("redirect refused")


def _build_opener() -> OpenerDirector:
    return build_opener(ProxyHandler({}), _RefuseRedirects())


_OPENER = _build_opener()


def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout_s: float,
) -> dict[str, object]:
    """POST ``payload`` as JSON and return the decoded object.

    The opener is built once with an empty proxy map so process environment
    and macOS system proxies cannot become a credentialed hop.
    """
    expected = _exact_origin(url)
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST")
    with _OPENER.open(request, timeout=timeout_s) as response:
        if _exact_origin(response.geturl()) != expected:
            raise OriginMismatch("origin mismatch")
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge("response exceeded 8 MiB")
    decoded = json.loads(body.decode(charset, errors="replace"))
    if not isinstance(decoded, dict):
        raise ValueError("response was not a JSON object")
    return decoded
