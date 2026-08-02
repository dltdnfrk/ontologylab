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
from ontologylab.server.jobs import JobRegistry
from ontologylab.server.routes import router
from ontologylab.server.security import (
    host_header_is_trusted,
    is_cross_site_state_change,
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


def create_app(
    data_dir: Path | None = None, packs_dir: Path | None = None
) -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(
        title="ontologylab",
        description="Local knowledge-graph pipeline dashboard",
    )

    resolved = Path(data_dir) if data_dir is not None else default_data_dir()
    resolved.mkdir(parents=True, exist_ok=True)
    app.state.data_dir = resolved

    resolved_packs = (
        Path(packs_dir) if packs_dir is not None else default_packs_dir()
    )
    app.state.packs_dir = resolved_packs

    # Construction performs G002 startup recovery for this app's store.
    app.state.jobs = JobRegistry(resolved)

    app.include_router(router)

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
            response.headers["Cache-Control"] = "no-cache"
        return response

    # Registered last => outermost => runs first. The server binds to loopback
    # with no auth, so a web page the user visits is the real adversary here.
    # Reject non-loopback Host headers (DNS rebinding) and cross-site
    # state-changing requests (CSRF) before any handler sees them. See
    # server/security.py for the rationale and the unit-tested predicates.
    @app.middleware("http")
    async def _local_guard(request, call_next):  # type: ignore[no-untyped-def]
        if not host_header_is_trusted(request.headers.get("host")):
            return JSONResponse(
                status_code=421,
                content={
                    "ok": False,
                    "error_kind": "bad_host",
                    "detail": (
                        "This server only accepts loopback Host headers "
                        "(127.0.0.1 / localhost / [::1]) unless a hostname is "
                        "allowlisted via ONTOLOGYLAB_ALLOWED_HOSTS."
                    ),
                },
            )
        if is_cross_site_state_change(
            request.method,
            request.headers.get("sec-fetch-site"),
            request.headers.get("origin"),
        ):
            return JSONResponse(
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
        return await call_next(request)

    return app
