"""OAuth connect flows for model providers (stdlib only, secret-safe).

Currently one provider supports a real OAuth flow: OpenRouter's PKCE
"connect" (https://openrouter.ai/docs/guides/overview/auth/oauth). The user
authorizes in the browser; OpenRouter redirects back to this app's loopback
callback with a single-use code; we exchange it for a durable ``sk-or-...``
key and store that key in the macOS Keychain — the same posture publisher
source keys already take. No client_id registration is required.

Design notes that are load-bearing:

* The callback is a top-level navigation from openrouter.ai, so the
  ``samesite=strict`` session cookie is NOT sent. The callback therefore
  lives outside ``/api/*`` and is guarded by the OAuth ``state`` parameter
  instead of the session — the state is minted by an authenticated
  ``POST /api/providers/openrouter/connect`` and is single-use.
* Pending flows are process-local state with a TTL. A restart mid-flow just
  means starting over; nothing is persisted.
* The token exchange goes through ``connectors.paper_api.urlopen``, the
  hardened opener that refuses cross-origin redirects — an auth-code POST
  must never be redirected to a different host.
* The returned key is written to the Keychain and never appears in a
  response body, log line, or redirect target.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request

from ontologylab.connectors.paper_api import urlopen
from ontologylab.paths import NetworkBlocked, assert_network_allowed

OPENROUTER_AUTH_URL = "https://openrouter.ai/auth"
OPENROUTER_TOKEN_URL = "https://openrouter.ai/api/v1/auth/keys"
OPENROUTER_PROVIDER_ID = "openrouter"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CALLBACK_PATH = "/oauth/openrouter/callback"

# Authorization codes expire 10 minutes after issuance; pending state gets
# the same lifetime so a stale callback can never complete a dead flow.
FLOW_TTL_S = 600.0
_EXCHANGE_TIMEOUT_S = 30.0
# One browser round-trip at a time is enough for a single-user local app;
# the bound also keeps a request loop from accumulating pending state.
_MAX_PENDING_FLOWS = 8


class OAuthError(RuntimeError):
    """A connect flow failed. Messages never carry codes, verifiers, or keys."""


@dataclass(frozen=True, slots=True)
class PendingFlow:
    """One in-flight PKCE exchange, keyed by its ``state`` parameter."""

    state: str
    code_verifier: str
    provider_id: str
    expires_at: float


_lock = threading.Lock()
_pending: dict[str, PendingFlow] = {}


def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for the S256 method."""
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def _sweep_expired(now: float) -> None:
    for state, flow in list(_pending.items()):
        if flow.expires_at <= now:
            del _pending[state]


def begin_flow(provider_id: str, callback_url: str) -> str:
    """Register a pending flow and return the OpenRouter authorization URL.

    ``callback_url`` must already point at this app's loopback callback; the
    route layer builds it from the request's own host/port.
    """
    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    now = time.monotonic()
    with _lock:
        _sweep_expired(now)
        if len(_pending) >= _MAX_PENDING_FLOWS:
            raise OAuthError("too many connect flows in progress")
        _pending[state] = PendingFlow(
            state=state,
            code_verifier=code_verifier,
            provider_id=provider_id,
            expires_at=now + FLOW_TTL_S,
        )
    params = {
        "callback_url": callback_url,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "key_label": "ontologylab",
    }
    return f"{OPENROUTER_AUTH_URL}?{urlencode(params)}"


def take_flow(state: str) -> PendingFlow:
    """Consume the pending flow for ``state`` — single-use, TTL-enforced.

    Raises OAuthError for an unknown, expired, or replayed state. The pop
    happens under the lock so two simultaneous callbacks with the same state
    cannot both succeed.
    """
    with _lock:
        _sweep_expired(time.monotonic())
        flow = _pending.pop(state, None)
    if flow is None:
        raise OAuthError("unknown or expired connect state")
    return flow


def exchange_code_for_key(flow: PendingFlow, code: str) -> str:
    """Exchange the authorization code for a durable ``sk-or-...`` key.

    Raises OAuthError on any failure. Error text carries the HTTP status
    only — never the response body, which could quote the submitted code.
    """
    assert_network_allowed("OpenRouter OAuth key exchange")
    request = Request(
        OPENROUTER_TOKEN_URL,
        data=json.dumps(
            {
                "code": code,
                "code_verifier": flow.code_verifier,
                "code_challenge_method": "S256",
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=_EXCHANGE_TIMEOUT_S) as response:
            body = response.read()
    except NetworkBlocked:
        raise
    except Exception as exc:
        status = getattr(exc, "code", None)
        detail = f"HTTP {status}" if isinstance(status, int) else "no response"
        raise OAuthError(f"OpenRouter key exchange failed: {detail}") from None
    try:
        data = json.loads(body)
    except ValueError:
        raise OAuthError("OpenRouter key exchange returned malformed JSON") from None
    key = data.get("key") if isinstance(data, dict) else None
    if not isinstance(key, str) or not key.startswith("sk-or-"):
        raise OAuthError("OpenRouter key exchange returned no usable key")
    return key


def clear_pending() -> None:
    """Drop every pending flow. Test isolation hook."""
    with _lock:
        _pending.clear()


__all__ = [
    "CALLBACK_PATH",
    "FLOW_TTL_S",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_PROVIDER_ID",
    "OAuthError",
    "PendingFlow",
    "begin_flow",
    "clear_pending",
    "exchange_code_for_key",
    "generate_pkce",
    "take_flow",
]
