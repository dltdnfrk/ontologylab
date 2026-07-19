"""FastAPI application factory for the ontologylab local web layer.

Wires API routes + a minimal vanilla frontend. Binds locally only
(127.0.0.1) — see ontologylab/serve.py for the run entrypoint.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ontologylab.paths import ROOT, default_data_dir, default_packs_dir
from ontologylab.server.jobs import JobRegistry
from ontologylab.server.routes import (
    attach_data_dir,
    attach_jobs_registry,
    attach_packs_dir,
    router,
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
    attach_data_dir(resolved)
    app.state.data_dir = resolved

    resolved_packs = (
        Path(packs_dir) if packs_dir is not None else default_packs_dir()
    )
    attach_packs_dir(resolved_packs)
    app.state.packs_dir = resolved_packs

    jobs = JobRegistry(resolved)
    attach_jobs_registry(jobs)
    app.state.jobs = jobs

    app.include_router(router)

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

    return app
