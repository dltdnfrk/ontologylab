"""HTTP validation for entity discovery and curated enrichment actions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ontologylab.server import entity_actions
from ontologylab.server.dependencies import AppDependency

router = APIRouter(prefix="/api")


@router.get("/search")
def search_entities(
    deps: AppDependency,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(8, ge=1, le=25),
) -> dict[str, Any]:
    """Name search across verified nodes and proposals for the palette."""
    return entity_actions.search_entities(data_dir=deps.data_dir, query=q, limit=limit)


@router.post("/enrich")
def enrich_nodes(
    deps: AppDependency, limit: int = Query(50, ge=1, le=500)
) -> dict[str, Any]:
    """Synchronously queue curated-resource matches, capped by node count."""
    return entity_actions.enrich_nodes(data_dir=deps.data_dir, limit=limit)
