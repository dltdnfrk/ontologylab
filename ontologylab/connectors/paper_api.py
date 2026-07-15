"""Keyless paper-metadata API connectors (stdlib only).

Fetches public metadata + abstracts from paper APIs — arXiv (Atom XML) and
Crossref (REST JSON); both endpoints need no auth key. Every
(source, query) pair is checked against ``allowlist.PAPER_API_ALLOWED``
**before** any network I/O (deny-by-default), mirroring the web_crawl
connector's enforcement point. Only titles and abstracts are ingested;
full-text retrieval is out of scope.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from ontologylab.connectors.allowlist import check_paper_query
from ontologylab.connectors.base import (
    FETCH_TIMEOUT_S as _FETCH_TIMEOUT_S,
    USER_AGENT as _USER_AGENT,
    RawDocument,
)

_ATOM_NS = "{http://www.w3.org/2005/Atom}"

# The only external endpoints this system ever fetches (both keyless).
ARXIV_API_URL = "https://export.arxiv.org/api/query"
CROSSREF_API_URL = "https://api.crossref.org/works"
DEFAULT_LIMIT = 5
MAX_LIMIT = 25
_MAX_LIMIT = MAX_LIMIT  # back-compat alias

DEFAULT_PAPER_SOURCE = "arxiv"

IMPLEMENTED_SOURCES: frozenset[str] = frozenset({"arxiv", "crossref"})


class UnsupportedPaperSource(NotImplementedError):
    """Raised for a source that is allowlisted but not implemented yet."""


def check_source_implemented(source: str) -> str:
    """Raise UnsupportedPaperSource unless the source has a real fetcher."""
    if source not in IMPLEMENTED_SOURCES:
        raise UnsupportedPaperSource(
            f"paper source {source!r} is allowlisted but not implemented yet "
            f"(supported: {sorted(IMPLEMENTED_SOURCES)})"
        )
    return source


def _http_get_text(url: str) -> str:
    """Fetch one allowlist-checked API URL; separated for test monkeypatching.

    The single network boundary for BOTH paper sources (Atom or JSON).
    """
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=_FETCH_TIMEOUT_S) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _build_query_url(query: str, limit: int) -> str:
    return (
        f"{ARXIV_API_URL}"
        f"?search_query=all:{quote_plus(query)}"
        f"&start=0&max_results={limit}"
    )


def _build_crossref_url(query: str, limit: int) -> str:
    # `select` keeps the payload to exactly the fields we ingest.
    return (
        f"{CROSSREF_API_URL}"
        f"?query={quote_plus(query)}"
        f"&rows={limit}"
        f"&select=DOI,URL,title,abstract"
    )


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_atom(xml_text: str) -> list[RawDocument]:
    """Parse an arXiv Atom feed into RawDocuments (title + abstract only)."""
    # Input is fetched from a single allowlisted host over the stdlib parser;
    # ET.fromstring does no DTD/external-entity resolution beyond internal
    # entities, so no hardened parser is needed for this trusted feed.
    root = ET.fromstring(xml_text)
    documents: list[RawDocument] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        title = _normalize(entry.findtext(f"{_ATOM_NS}title"))
        abstract = _normalize(entry.findtext(f"{_ATOM_NS}summary"))
        if not title and not abstract:
            continue
        source_uri = _normalize(entry.findtext(f"{_ATOM_NS}id"))
        if not source_uri:
            # No <id> -> no usable source_uri -> no provenance trail;
            # such an entry must never become a document row.
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
            )
        )
    return documents


# JATS/XML markup inside Crossref abstracts ("<jats:p>...</jats:p>").
_MARKUP_TAG_RE = re.compile(r"<[^>]+>")


def parse_crossref(json_text: str) -> list[RawDocument]:
    """Parse a Crossref /works JSON response into RawDocuments.

    Same ingest contract as parse_atom: title + abstract only, and an item
    with no usable source URI (URL or DOI) never becomes a document row —
    no provenance trail, no ingestion. Abstracts arrive as JATS XML
    fragments; markup is stripped to plain text.
    """
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"crossref response is not valid JSON: {exc}") from exc
    items = ((payload.get("message") or {}).get("items")) or []
    documents: list[RawDocument] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        titles = item.get("title") or []
        title = _normalize(" ".join(titles) if isinstance(titles, list) else titles)
        abstract = _normalize(_MARKUP_TAG_RE.sub(" ", item.get("abstract") or ""))
        if not title and not abstract:
            continue
        doi = _normalize(item.get("DOI"))
        source_uri = _normalize(item.get("URL")) or (
            f"https://doi.org/{doi}" if doi else ""
        )
        if not source_uri:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
            )
        )
    return documents


class PaperApiConnector:
    """Queries a keyless paper-metadata API (arXiv Atom / Crossref JSON)."""

    def name(self) -> str:
        return "paper_api"

    async def fetch(self, source_spec: dict[str, Any]) -> list[RawDocument]:
        source: str = source_spec.get("source") or DEFAULT_PAPER_SOURCE
        # Strip ONCE here so the allowlist check and the URL are built from
        # the same canonicalized query text.
        query: str = (source_spec.get("query") or "").strip()
        raw_limit = source_spec.get("limit")
        limit = DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
        limit = max(1, min(limit, _MAX_LIMIT))
        # Allowlist BEFORE building a URL or touching the network.
        check_paper_query(source, query)
        check_source_implemented(source)
        if source == "crossref":
            body = _http_get_text(_build_crossref_url(query, limit))
            return parse_crossref(body)
        body = _http_get_text(_build_query_url(query, limit))
        return parse_atom(body)
