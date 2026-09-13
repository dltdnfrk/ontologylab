"""OAuth connect routes — the only endpoints outside ``/api/*``.

The session cookie is ``samesite=strict``, so the top-level navigation back
from the provider's consent page arrives WITHOUT it. The callback therefore
cannot sit under ``/api/*`` (the session guard would 401 it) and is guarded
by the single-use OAuth ``state`` parameter instead — minted by the
authenticated connect POST, consumed once by ``take_flow``.

Both endpoints answer with redirects, never JSON: the browser is mid-
navigation, and the React app reads the result from the query string on
/engines. Error details travel as a small typed code, not a message — a
message could carry text derived from an upstream response.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ontologylab.keychain import KeychainError, keychain_available, write_key
from ontologylab.oauth_connect import (
    CALLBACK_PATH,
    OPENROUTER_BASE_URL,
    OPENROUTER_PROVIDER_ID,
    OAuthError,
    begin_flow,
    exchange_code_for_key,
    take_flow,
)
from ontologylab.paths import NetworkBlocked
from ontologylab.providers import (
    Provider,
    add_provider,
    canonical_keychain_account,
    dedicated_api_key_env,
)
from ontologylab.server.dependencies import AppDependency

router = APIRouter()

_ENGINES = "/engines"


def _redirect_error(kind: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"{_ENGINES}?connect_error={kind}", status_code=303
    )


def _callback_url(request: Request) -> str:
    """Build the loopback callback URL from this request's own port.

    The server binds 127.0.0.1, so the callback host is pinned to it; only
    the port varies. The Host header is already pinned to loopback by the
    outer middleware, so its port is trustworthy here.
    """
    host = request.headers.get("host") or ""
    port = host.rsplit(":", 1)[1] if ":" in host else ""
    netloc = f"127.0.0.1:{port}" if port else "127.0.0.1"
    return f"http://{netloc}{CALLBACK_PATH}"


@router.post("/api/providers/openrouter/connect")
def connect_openrouter(deps: AppDependency, request: Request) -> dict:
    """Start the OpenRouter PKCE flow; the browser follows ``auth_url``."""
    if not keychain_available():
        raise HTTPException(
            status_code=400,
            detail=(
                "this machine has no macOS Keychain; set OPENROUTER_API_KEY "
                "as an environment variable instead"
            ),
        )
    try:
        auth_url = begin_flow(OPENROUTER_PROVIDER_ID, _callback_url(request))
    except OAuthError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"ok": True, "auth_url": auth_url}


@router.get(CALLBACK_PATH, include_in_schema=False)
def openrouter_callback(
    deps: AppDependency, code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    """Receive the OpenRouter redirect, exchange the code, store the key.

    Success lands on /engines with the provider registered; every failure
    lands there with a typed ``connect_error`` instead.
    """
    if error:
        return _redirect_error("denied")
    if not code or not state:
        return _redirect_error("malformed")
    try:
        flow = take_flow(state)
    except OAuthError:
        return _redirect_error("state")
    try:
        key = exchange_code_for_key(flow, code)
    except NetworkBlocked:
        return _redirect_error("offline")
    except OAuthError:
        return _redirect_error("exchange")

    account = canonical_keychain_account(flow.provider_id)
    try:
        write_key(account, key)
    except KeychainError:
        return _redirect_error("keychain")

    provider = Provider(
        id=flow.provider_id,
        kind="openai",
        base_url=OPENROUTER_BASE_URL,
        api_key_env=dedicated_api_key_env(flow.provider_id, OPENROUTER_BASE_URL),
        label="OpenRouter",
        keychain_account=account,
    )
    try:
        add_provider(deps.data_dir, provider)
    except Exception:
        return _redirect_error("register")
    return RedirectResponse(
        url=f"{_ENGINES}?connected={flow.provider_id}", status_code=303
    )
