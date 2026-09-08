"""Shared paper-source identifiers and payload value conversions."""

from __future__ import annotations

import json
import re
from typing import Any

DOI_BASE_URL = "https://doi.org/"


MAX_LIMIT = 25


ARXIV_SOURCE = "arxiv"


CROSSREF_SOURCE = "crossref"


OPENALEX_SOURCE = "openalex"


SEMANTIC_SCHOLAR_SOURCE = "semanticscholar"


CLINICALTRIALS_SOURCE = "clinicaltrials"


BIORXIV_SOURCE = "biorxiv"


PUBMED_SOURCE = "pubmed"


EUROPEPMC_SOURCE = "europepmc"


ELSEVIER_SOURCE = "elsevier"


SPRINGER_SOURCE = "springer"


CORE_SOURCE = "core"


SEARXNG_SOURCE = "searxng"


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _year_from_parts(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts") or []
    if not parts or not isinstance(parts[0], list) or not parts[0]:
        return None
    return _integer(parts[0][0])


_MARKUP_TAG_RE = re.compile(r"<[^>]+>")


def _load_json(json_text: str, source: str) -> Any:
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{source} response is not valid JSON: {exc}"
        ) from exc
