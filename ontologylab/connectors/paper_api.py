"""Keyless paper-metadata API connector (stdlib only).

Fetches public metadata + abstracts from a paper API — arXiv first, because
its Atom endpoint needs no auth key and returns stable, well-formed XML.
Every (source, query) pair is checked against
``allowlist.PAPER_API_ALLOWED`` **before** any network I/O
(deny-by-default), mirroring the web_crawl connector's enforcement point.
Only titles and abstracts are ingested; full-text retrieval is out of scope.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from ontologylab.connectors.allowlist import check_paper_query
from ontologylab.connectors.base import RawDocument

_USER_AGENT = "ontologylab/0.1 (+local, single-user)"
_FETCH_TIMEOUT_S = 30.0

_ATOM_NS = "{http://www.w3.org/2005/Atom}"
DEFAULT_LIMIT = 5
_MAX_LIMIT = 25

IMPLEMENTED_SOURCES: frozenset[str] = frozenset({"arxiv"})


class UnsupportedPaperSource(NotImplementedError):
    """Raised for a source that is allowlisted but not implemented yet."""


def check_source_implemented(source: str) -> str:
    """Raise UnsupportedPaperSource unless the source has a real fetcher."""
    if source not in IMPLEMENTED_SOURCES:
        raise UnsupportedPaperSource(
            f"paper source {source!r} is allowlisted but not implemented yet "
            "(only 'arxiv' is supported)"
        )
    return source


def _fetch_atom(url: str) -> str:
    """Fetch one allowlist-checked API URL; separated for test monkeypatching."""
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=_FETCH_TIMEOUT_S) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _build_query_url(query: str, limit: int) -> str:
    return (
        "https://export.arxiv.org/api/query"
        f"?search_query=all:{quote_plus(query)}"
        f"&start=0&max_results={limit}"
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


class PaperApiConnector:
    """Queries a keyless paper-metadata API (arXiv Atom endpoint)."""

    def name(self) -> str:
        return "paper_api"

    async def fetch(self, source_spec: dict[str, Any]) -> list[RawDocument]:
        source: str = source_spec.get("source") or "arxiv"
        # Strip ONCE here so the allowlist check and the URL are built from
        # the same canonicalized query text.
        query: str = (source_spec.get("query") or "").strip()
        raw_limit = source_spec.get("limit")
        limit = DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
        limit = max(1, min(limit, _MAX_LIMIT))
        # Allowlist BEFORE building a URL or touching the network.
        check_paper_query(source, query)
        check_source_implemented(source)
        body = _fetch_atom(_build_query_url(query, limit))
        return parse_atom(body)
