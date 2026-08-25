"""FastAPI application factory for the ontologylab local web layer.

Wires API routes + a minimal vanilla frontend. Binds locally only
(127.0.0.1) — see ontologylab/serve.py for the run entrypoint.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ontologylab.paths import ROOT, default_data_dir, default_packs_dir
from ontologylab.server.ingest_routes import router as ingest_router
from ontologylab.server.jobs import JobRegistry
from ontologylab.server.routes import router
from ontologylab.server.security import (
    HARDENING_HEADERS,
    host_header_is_local,
    host_header_is_trusted,
    is_cross_site_state_change,
    is_local_hostname,
    loopback_host_peer_mismatch,
)
from ontologylab.server.session import (
    COOKIE_NAME,
    HEADER_NAME,
    install_session,
    presented_session_token,
    tokens_match,
)

WEB_DIR = ROOT / "web"
INDEX_HTML = WEB_DIR / "index.html"

# The working DB has two writers: the per-job extraction thread
# (server/jobs.py) and whatever the dashboard is doing in a request handler.
# WAL plus sqlite's busy timeout serializes them, but a write that waits out
# the timeout surfaces as OperationalError("database is locked"). That is a
# transient contention signal, not a server fault — answer 503 + Retry-After
# so the dashboard can retry, instead of an unhandled 500.
_BUSY_MARKERS = ("database is locked", "database table is locked", "busy")
_RETRY_AFTER_S = "2"


def _hardened_response(response):
    for key, value in HARDENING_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


def create_app(
    data_dir: Path | None = None, packs_dir: Path | None = None
) -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(
        title="ontologylab",
        description="Local knowledge-graph pipeline dashboard",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    resolved = Path(data_dir) if data_dir is not None else default_data_dir()
    secret = install_session(resolved)
    app.state.data_dir = resolved
    app.state.session_token = secret.token
    app.state.session_token_path = secret.path

    if packs_dir is not None:
        resolved_packs = Path(packs_dir)
    elif data_dir is not None:
        resolved_packs = resolved.parent / "packs"
    else:
        resolved_packs = default_packs_dir()
    app.state.packs_dir = resolved_packs

    # Construction performs G002 startup recovery for this app's store.
    app.state.jobs = JobRegistry(resolved)

    app.include_router(router)
    app.include_router(ingest_router)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Report *what* was wrong with a request, never *what was sent*.

        FastAPI's default 422 body carries an `input` field holding the
        offending value, and `ctx` can hold values too. Measured on this
        version: submitting `{"key": "<secret>"}` without the required `id`
        answers with `input: {"key": "<secret>"}` — the whole body, echoed.
        A wrong type on the key field echoes the key. `SecretStr` does not
        help; the masking happens after validation, and this error is raised
        before.

        That was harmless while no endpoint received a secret. `POST
        /api/sources` receives a publisher API key, so it is not any more.
        Stripping here rather than reshaping one schema covers every future
        endpoint as well — the field names and messages are still returned,
        which is what a caller needs to fix the request.

        `ctx` goes too. On this pydantic it holds constraints (`min_length`)
        and an empty `error` object, so dropping it removes nothing a caller
        can act on — but it is the field a custom validator's exception would
        land in, and `msg` already carries that text in readable form.
        """
        safe = [
            {key: value for key, value in error.items()
             if key not in ("input", "ctx")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": safe})

    @app.exception_handler(sqlite3.OperationalError)
    async def _sqlite_operational_error(
        request: Request, exc: sqlite3.OperationalError
    ) -> JSONResponse:
        """Turn storage contention into a retryable 503; redact everything else.

        Only the busy/locked case is retryable. Any other OperationalError is
        a real fault, and its message can name tables/columns, so it is logged
        server-side and answered generically — the same redaction posture the
        rest of the app takes with database internals.
        """
        message = str(exc).lower()
        if any(marker in message for marker in _BUSY_MARKERS):
            return JSONResponse(
                status_code=503,
                headers={"Retry-After": _RETRY_AFTER_S},
                content={
                    "ok": False,
                    "error_kind": "busy",
                    "detail": (
                        "The knowledge base is busy — an extraction job is "
                        "writing to it. Try again in a moment."
                    ),
                },
            )
        print(f"[ontologylab.server] sqlite error on {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error_kind": "storage",
                "detail": "A storage error occurred. Check the server log.",
            },
        )

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(str(INDEX_HTML))

    # Local single-user app: the UI iterates often, and browsers apply
    # heuristic caching to /static (Last-Modified only) — which kept serving
    # a stale stylesheet after redesigns. no-cache forces revalidation
    # (304s keep it cheap); on localhost correctness beats caching.
    @app.middleware("http")
    async def _no_cache_ui(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    # Session sits inside the Host/peer + CSRF guard. /healthz and the
    # dashboard document stay reachable; every /api/* call needs the token.
    @app.middleware("http")
    async def _session_guard(request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path.startswith("/api/"):
            presented = presented_session_token(
                cookie=request.cookies.get(COOKIE_NAME),
                header=request.headers.get(HEADER_NAME),
            )
            if not tokens_match(presented, request.app.state.session_token):
                return JSONResponse(
                    status_code=401,
                    content={
                        "ok": False,
                        "error_kind": "unauthenticated",
                        "detail": "Missing or invalid session.",
                    },
                    headers={"Cache-Control": "no-store"},
                )
        response = await call_next(request)
        peer = request.client.host if request.client is not None else None
        if (
            request.method.upper() == "GET"
            and path == "/"
            and host_header_is_local(request.headers.get("host"))
            and is_local_hostname(peer)
        ):
            response.set_cookie(
                key=COOKIE_NAME,
                value=request.app.state.session_token,
                httponly=True,
                samesite="strict",
                path="/",
            )
            response.headers["Cache-Control"] = "no-store"
        return response

    # Registered last => outermost => runs first. Host/peer + CSRF reject
    # before the session middleware sees the request. Forwarded headers are
    # not consulted; the peer is the ASGI client address only.
    @app.middleware("http")
    async def _local_guard(request, call_next):  # type: ignore[no-untyped-def]
        host = request.headers.get("host")
        peer = request.client.host if request.client is not None else None
        if not host_header_is_trusted(host) or loopback_host_peer_mismatch(
            host, peer
        ):
            return _hardened_response(
                JSONResponse(
                    status_code=421,
                    content={
                        "ok": False,
                        "error_kind": "bad_host",
                        "detail": (
                            "This server only accepts loopback Host headers "
                            "(127.0.0.1 / localhost / [::1]) from a loopback "
                            "peer unless a hostname is allowlisted via "
                            "ONTOLOGYLAB_ALLOWED_HOSTS."
                        ),
                    },
                )
            )
        if is_cross_site_state_change(
            request.method,
            request.headers.get("sec-fetch-site"),
            request.headers.get("origin"),
        ):
            return _hardened_response(
                JSONResponse(
                    status_code=403,
                    content={
                        "ok": False,
                        "error_kind": "cross_site",
                        "detail": (
                            "Cross-site state-changing requests are refused. Use "
                            "the local dashboard or a non-browser client."
                        ),
                    },
                )
            )
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/") or path == "/healthz":
            response.headers["Cache-Control"] = "no-store"
        elif COOKIE_NAME in (response.headers.get("set-cookie") or ""):
            response.headers["Cache-Control"] = "no-store"
        return _hardened_response(response)

    return app
