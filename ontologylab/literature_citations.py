"""Bounded OpenAlex citation-neighborhood retrieval."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.paths import NetworkBlocked


async def expand_citation_neighborhood(
    seeds: list[RawDocument],
    *,
    data_dir: Any = None,
    backward_limit: int = 15,
    forward_limit: int = 15,
) -> list[RawDocument]:
    """Walk one OpenAlex citation step in both directions for DOI seeds."""
    from ontologylab.connectors import paper_api

    key = paper_api.resolve_source_key(paper_api.OPENALEX_SOURCE, data_dir)
    query_key = ("api_key", key) if key else None

    async def _get(url: str) -> str:
        if query_key is None:
            return await asyncio.to_thread(paper_api._http_get_text, url)
        return await asyncio.to_thread(
            paper_api._http_get_text,
            url,
            query_key=query_key,
        )

    async def _get_optional(url: str) -> str | None:
        try:
            return await _get(url)
        except NetworkBlocked:
            raise
        except (HTTPError, URLError, paper_api.ResponseTooLarge):
            return None

    def _object(payload: str) -> dict[str, Any] | None:
        try:
            value: Any = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def _openalex_documents(payload: str) -> list[RawDocument]:
        try:
            return paper_api.parse_openalex(payload)
        except (TypeError, ValueError):
            return []

    documents: list[RawDocument] = []
    seen_seeds: set[str] = set()
    for seed in seeds:
        doi = normalize_doi(seed.doi)
        if not doi or doi in seen_seeds:
            continue
        seen_seeds.add(doi)
        lookup = (
            f"{paper_api.OPENALEX_API_URL}/"
            f"{quote(f'https://doi.org/{doi}', safe='')}"
            "?select=id"
        )
        lookup_payload = await _get_optional(lookup)
        if lookup_payload is None:
            continue
        work = _object(lookup_payload)
        if work is None:
            continue
        work_id = str(work.get("id") or "").rsplit("/", 1)[-1]
        if not work_id:
            continue
        for axis, filter_name, limit in (
            ("citation_backward", "cited_by", backward_limit),
            ("citation_forward", "cites", forward_limit),
        ):
            if limit <= 0:
                continue
            params = {
                "filter": f"{filter_name}:{work_id}",
                "per-page": min(limit, 100),
                "select": (
                    "id,doi,display_name,abstract_inverted_index,type,"
                    "publication_year,cited_by_count,authorships,"
                    "primary_location"
                ),
            }
            payload = await _get_optional(
                f"{paper_api.OPENALEX_API_URL}?{urlencode(params)}"
            )
            if payload is None:
                continue
            parsed = _openalex_documents(payload)
            documents.extend(
                replace(
                    document,
                    search_axis=axis,
                    search_query=doi,
                )
                for document in parsed[:limit]
                if document.doi != doi
            )
    unique: dict[str, RawDocument] = {}
    for document in documents:
        unique.setdefault(document.dedupe_key, document)
    return list(unique.values())
