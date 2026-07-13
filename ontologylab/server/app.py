"""FastAPI application factory for the ontologylab local web layer.

Wires API routes + a minimal vanilla frontend. Binds locally only
(127.0.0.1) — see ontologylab/serve.py for the run entrypoint.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
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

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(str(INDEX_HTML))

    return app
