"""Keyless paper-metadata API connectors (stdlib only).

Fetches public metadata + abstracts from paper APIs — arXiv (Atom XML),
Crossref, OpenAlex, Semantic Scholar, and Europe PMC (REST JSON); every
endpoint is keyless. Each (source, query) pair is checked against the
allowlist **before** any network I/O (deny-by-default), mirroring the
web_crawl connector's enforcement point. Only titles and abstracts are
ingested; full-text retrieval is out of scope.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from ontologylab.connectors.allowlist import check_paper_query
from ontologylab.paths import assert_network_allowed
from ontologylab.connectors.base import (
    FETCH_TIMEOUT_S as _FETCH_TIMEOUT_S,
    USER_AGENT as _USER_AGENT,
    RawDocument,
)

_ATOM_NS = "{http://www.w3.org/2005/Atom}"

# The only external endpoints this system ever fetches (all keyless).
ARXIV_API_URL = "https://export.arxiv.org/api/query"
CROSSREF_API_URL = "https://api.crossref.org/works"
OPENALEX_API_URL = "https://api.openalex.org/works"
SEMANTIC_SCHOLAR_API_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
)
EUROPEPMC_API_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
)
# DOI resolver base for items that carry a DOI but no URL field.
DOI_BASE_URL = "https://doi.org/"
DEFAULT_LIMIT = 5
MAX_LIMIT = 25
_MAX_LIMIT = MAX_LIMIT  # back-compat alias

# Canonical source names: the fetch dispatch, IMPLEMENTED_SOURCES, and the
# default all reference these — never re-type the strings.
ARXIV_SOURCE = "arxiv"
CROSSREF_SOURCE = "crossref"
OPENALEX_SOURCE = "openalex"
SEMANTIC_SCHOLAR_SOURCE = "semanticscholar"
EUROPEPMC_SOURCE = "europepmc"
DEFAULT_PAPER_SOURCE = ARXIV_SOURCE

IMPLEMENTED_SOURCES: frozenset[str] = frozenset({
    ARXIV_SOURCE,
    CROSSREF_SOURCE,
    OPENALEX_SOURCE,
    SEMANTIC_SCHOLAR_SOURCE,
    EUROPEPMC_SOURCE,
})

# Crossref fields we request AND the exact keys parse_crossref reads —
# dropping one here silently empties the corresponding parsed value, so the
# two stay coupled through this tuple.
_CROSSREF_SELECT_FIELDS = ("DOI", "URL", "title", "abstract")


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
    # Search terms leak research direction to third-party APIs; offline mode
    # refuses the whole channel.
    assert_network_allowed(f"paper API fetch ({url})")
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
        "&select=" + ",".join(_CROSSREF_SELECT_FIELDS)
    )


# OpenAlex routes requests carrying a contact `mailto` into a faster,
# more lenient "polite pool". The address is read from the environment at
# request time (never hard-coded / committed); absent -> the common pool.
OPENALEX_MAILTO_ENV = "OPENALEX_MAILTO"


def _openalex_mailto() -> str:
    return os.environ.get(OPENALEX_MAILTO_ENV, "").strip()


def _build_openalex_url(query: str, limit: int) -> str:
    url = (
        f"{OPENALEX_API_URL}"
        f"?search={quote_plus(query)}"
        f"&per-page={limit}"
        "&select=id,doi,display_name,abstract_inverted_index"
    )
    mailto = _openalex_mailto()
    if mailto:
        url += f"&mailto={quote_plus(mailto)}"
    return url


def _build_semanticscholar_url(query: str, limit: int) -> str:
    return (
        f"{SEMANTIC_SCHOLAR_API_URL}"
        f"?query={quote_plus(query)}"
        f"&limit={limit}"
        "&fields=title,abstract,url,externalIds"
    )


def _build_europepmc_url(query: str, limit: int) -> str:
    return (
        f"{EUROPEPMC_API_URL}"
        f"?query={quote_plus(query)}"
        f"&pageSize={limit}"
        "&format=json&resultType=core"
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
            f"{DOI_BASE_URL}{doi}" if doi else ""
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


def _load_json(json_text: str, source: str) -> Any:
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{source} response is not valid JSON: {exc}"
        ) from exc


def _restore_inverted_abstract(inverted: Any) -> str:
    """Rebuild plain text from OpenAlex's abstract_inverted_index.

    The index maps each word to the list of positions where it occurs;
    placing every word at its positions and joining restores the abstract.
    """
    if not isinstance(inverted, dict) or not inverted:
        return ""
    slots: dict[int, str] = {}
    for word, positions in inverted.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int) and pos >= 0:
                slots[pos] = str(word)
    return " ".join(slots[i] for i in sorted(slots))


def parse_openalex(json_text: str) -> list[RawDocument]:
    """Parse an OpenAlex /works JSON response into RawDocuments."""
    payload = _load_json(json_text, OPENALEX_SOURCE)
    documents: list[RawDocument] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("display_name"))
        abstract = _normalize(
            _restore_inverted_abstract(item.get("abstract_inverted_index"))
        )
        if not title and not abstract:
            continue
        # OpenAlex serves `doi` as a full https://doi.org/... URL and `id`
        # as a canonical openalex.org URL — either is a provenance trail.
        source_uri = _normalize(item.get("doi")) or _normalize(item.get("id"))
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


def parse_semanticscholar(json_text: str) -> list[RawDocument]:
    """Parse a Semantic Scholar /paper/search JSON response."""
    payload = _load_json(json_text, SEMANTIC_SCHOLAR_SOURCE)
    documents: list[RawDocument] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        abstract = _normalize(item.get("abstract"))
        if not title and not abstract:
            continue
        external = item.get("externalIds") or {}
        doi = _normalize(
            external.get("DOI") if isinstance(external, dict) else ""
        )
        source_uri = _normalize(item.get("url")) or (
            f"{DOI_BASE_URL}{doi}" if doi else ""
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


def parse_europepmc(json_text: str) -> list[RawDocument]:
    """Parse a Europe PMC /search JSON response (resultType=core)."""
    payload = _load_json(json_text, EUROPEPMC_SOURCE)
    results = ((payload.get("resultList") or {}).get("result")) or []
    documents: list[RawDocument] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        abstract = _normalize(
            _MARKUP_TAG_RE.sub(" ", item.get("abstractText") or "")
        )
        if not title and not abstract:
            continue
        doi = _normalize(item.get("doi"))
        src = _normalize(item.get("source"))
        ext_id = _normalize(item.get("id"))
        source_uri = (
            f"{DOI_BASE_URL}{doi}" if doi
            else (
                f"https://europepmc.org/abstract/{src}/{ext_id}"
                if src and ext_id else ""
            )
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


# source -> (url builder, response parser). Adding a source = one endpoint
# constant + one builder + one parser + one row here (+ the allowlist entry).
_SOURCE_DISPATCH = {
    ARXIV_SOURCE: (_build_query_url, parse_atom),
    CROSSREF_SOURCE: (_build_crossref_url, parse_crossref),
    OPENALEX_SOURCE: (_build_openalex_url, parse_openalex),
    SEMANTIC_SCHOLAR_SOURCE: (_build_semanticscholar_url, parse_semanticscholar),
    EUROPEPMC_SOURCE: (_build_europepmc_url, parse_europepmc),
}


class PaperApiConnector:
    """Queries a keyless paper-metadata API (arXiv/Crossref/OpenAlex/
    Semantic Scholar/Europe PMC)."""

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
        build_url, parse = _SOURCE_DISPATCH[source]
        body = _http_get_text(build_url(query, limit))
        return parse(body)
