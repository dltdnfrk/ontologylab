"""FastAPI API routes for the ontologylab local web layer.

Exposes /api/engines, /api/settings, /api/cost, /api/proposals
(list / approve / reject), and the M8 dashboard surface:
/api/documents, /api/collect, /api/extract, /api/jobs, /api/packs,
/api/mcp/status — everything needed to drive collect → extract →
review → build → serve from the browser, no CLI required.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ontologylab import paths
from ontologylab.connectors.allowlist import NotAllowlisted
from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.paper_api import PaperApiConnector
from ontologylab.connectors.web_crawl import WebCrawlConnector
from ontologylab.kgstore import EndpointNotVerified, KGStore, KGStoreError, UnknownItem
from ontologylab.packbuilder import PackBuildError, build_pack, list_packs
from ontologylab.paths import default_data_dir, default_packs_dir, kg_db_path
from ontologylab.provenance import Provenance
from ontologylab.server import settings as settings_mod
from ontologylab.server.schemas import (
    CollectRequest,
    CostSummary,
    EngineInfo,
    ExtractRequest,
    PackBuildRequest,
    ProposalAction,
    Settings,
)

router = APIRouter(prefix="/api")

# Bound once by app.create_app(); holds the data-dir Path for the working KG.
_data_dir: Path = default_data_dir()

# Bound once by app.create_app(); holds the packs output directory.
_packs_dir: Path = default_packs_dir()


def attach_data_dir(data_dir: Path) -> None:
    global _data_dir
    _data_dir = Path(data_dir)


def attach_packs_dir(packs_dir: Path) -> None:
    global _packs_dir
    _packs_dir = Path(packs_dir)


def _open_store() -> KGStore:
    # Creates an empty store on first open, so the review UI boots cleanly
    # even before any collect job has run.
    return KGStore.open(kg_db_path(_data_dir))


# ---------------------------------------------------------------------------
# Engines / settings / cost
# ---------------------------------------------------------------------------


@router.get("/engines", response_model=list[EngineInfo])
def get_engines() -> list[EngineInfo]:
    return settings_mod.engines()


@router.get("/settings", response_model=Settings)
def get_settings() -> Settings:
    return settings_mod.load_settings()


@router.put("/settings", response_model=Settings)
def put_settings(new_settings: Settings) -> Settings:
    return settings_mod.save_settings(new_settings)


@router.get("/cost", response_model=CostSummary)
def get_cost() -> CostSummary:
    return settings_mod.cost_summary()


# ---------------------------------------------------------------------------
# Proposals (HITL review)
# ---------------------------------------------------------------------------


@router.get("/proposals")
def list_proposals(
    kind: str | None = Query(None, description="node | edge"),
    type_name: str | None = Query(None),
    source_doc_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    store = _open_store()
    try:
        items = store.pending_review(
            kind=kind,
            type_name=type_name,
            source_doc_id=source_doc_id,
            limit=limit,
        )
        counts = store.counts()
        return {"items": items, "counts": counts, "count": len(items)}
    finally:
        store.close()


@router.post("/proposals/approve")
def approve_proposal(body: ProposalAction) -> dict[str, Any]:
    store = _open_store()
    try:
        result = store.approve(
            body.id, by=body.by, note=body.note, cascade=body.cascade
        )
        return {"ok": True, **result}
    except EndpointNotVerified as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.post("/proposals/reject")
def reject_proposal(body: ProposalAction) -> dict[str, Any]:
    store = _open_store()
    try:
        result = store.reject(body.id, by=body.by, note=body.note)
        return {"ok": True, **result}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()
