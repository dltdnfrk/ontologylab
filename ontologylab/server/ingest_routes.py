"""Internal HTTP authority-write routes over the shared ingestion seam."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ontologylab.file_lifecycle import reconcile_files
from ontologylab.ingestion_surfaces import collect_sample, run_ingest
from ontologylab.provenance_outbox import project_outbox
from ontologylab.kgstore import KGStore
from ontologylab.paths import kg_db_path
from ontologylab.server.dependencies import AppDependencies, AppDependency

router = APIRouter(prefix="/api")


def _open_store(deps: AppDependencies) -> KGStore:
    return KGStore.open(kg_db_path(deps.data_dir))


@router.post("/ingest")
def ingest_authority(deps: AppDependency, body: dict[str, Any]) -> JSONResponse:
    items = body.get("items", [])
    mode = body.get("mode") or "write"
    if mode not in ("write", "queue") or not isinstance(items, list):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "receipts": [],
                "error_class": "InvalidIngestItem",
                "error_classes": ["InvalidIngestItem"],
            },
        )
    store = _open_store(deps)
    try:
        batch = run_ingest(store.conn, items, mode=mode)
        if mode != "queue":
            store.conn.commit()
            reconcile_files(store.conn)
            project_outbox(store.conn)
            store.conn.commit()
        return JSONResponse(status_code=batch.http_status, content=batch.to_dict())
    finally:
        store.close()


@router.post("/ingest/sample")
def ingest_sample(deps: AppDependency, body: dict[str, Any]) -> JSONResponse:
    items = body.get("items", [])
    if not isinstance(items, list):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "receipts": [],
                "error_class": "InvalidIngestItem",
                "error_classes": ["InvalidIngestItem"],
            },
        )
    store = _open_store(deps)
    try:
        batch = collect_sample(store.conn, items)
        store.conn.commit()
        reconcile_files(store.conn)
        project_outbox(store.conn)
        store.conn.commit()
        return JSONResponse(status_code=batch.http_status, content=batch.to_dict())
    finally:
        store.close()
