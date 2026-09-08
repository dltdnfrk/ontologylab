"""Ordinary entity actions shared by HTTP and conversational adapters."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ontologylab.connectors.resources import ResourceError
from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.paths import kg_db_path


def search_entities(*, data_dir: Path, query: str, limit: int) -> dict[str, Any]:
    """Find names including proposals, preserving their review status.

    A malformed store query is an empty result for incremental search.
    Opening the store remains outside that boundary: storage failures must
    reach the caller rather than masquerading as a successful empty search.
    """
    store = KGStore.open(kg_db_path(data_dir))
    try:
        matches = store.name_search(query, limit=limit, include_proposed=True)
    except KGStoreError:
        matches = []
    finally:
        store.close()
    return {
        "results": [
            {
                "id": item["id"],
                "name": item["name"],
                "entity_type": item["entity_type"],
                "status": item["status"],
                "score": item.get("match_score"),
            }
            for item in matches
        ]
    }


def enrich_nodes(*, data_dir: Path, limit: int) -> dict[str, Any]:
    """Queue curated matches through the existing human-reviewed enrichment.

    Open failures propagate; resource/query failures within the action keep
    the typed, redacted refusal envelope used by the HTTP adapter.
    """
    from ontologylab.enrichment import enrich

    store = KGStore.open(kg_db_path(data_dir))
    try:
        report = enrich(store, limit=limit)
        return {"ok": True, **report.as_dict()}
    except (ResourceError, sqlite3.Error) as exc:
        return {
            "ok": False,
            "error_kind": "failed",
            "detail": f"enrichment failed: {type(exc).__name__}",
        }
    finally:
        store.close()
