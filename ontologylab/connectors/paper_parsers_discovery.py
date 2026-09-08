"""Pure JSON parsers for scholarly discovery services."""

from __future__ import annotations

import json
from ontologylab import evidence
from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.connectors.paper_common import (
    CROSSREF_SOURCE,
    DOI_BASE_URL,
    MAX_LIMIT,
    OPENALEX_SOURCE,
    SEARXNG_SOURCE,
    SEMANTIC_SCHOLAR_SOURCE,
    _MARKUP_TAG_RE,
    _integer,
    _load_json,
    _normalize,
    _year_from_parts,
)
from typing import Any

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
        authors = tuple(
            _normalize(author.get("family") or author.get("name"))
            for author in (item.get("author") or [])
            if isinstance(author, dict)
            and _normalize(author.get("family") or author.get("name"))
        )
        updates = item.get("update-to") or []
        retracted = any(
            "retract" in str(update.get("type") or "").casefold()
            for update in updates
            if isinstance(update, dict)
        )
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                source=CROSSREF_SOURCE,
                evidence_grade=evidence.grade_from_record(
                    CROSSREF_SOURCE, item
                ),
                authors=authors,
                year=_year_from_parts(item.get("published")),
                venue=_normalize(
                    (item.get("container-title") or [""])[0]
                ) or None,
                cited_by=_integer(item.get("is-referenced-by-count")),
                publication_type=_normalize(item.get("type")) or None,
                retracted=retracted,
            )
        )
    return documents


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
        # The URL form is why `normalize_doi` strips resolver prefixes: this
        # is the one source whose DOI does not arrive bare.
        source_uri = _normalize(item.get("doi")) or _normalize(item.get("id"))
        if not source_uri:
            continue
        authors = tuple(
            _normalize((authorship.get("author") or {}).get("display_name"))
            for authorship in (item.get("authorships") or [])
            if isinstance(authorship, dict)
            and isinstance(authorship.get("author"), dict)
            and _normalize(
                (authorship.get("author") or {}).get("display_name")
            )
        )
        location = item.get("primary_location") or {}
        venue = (
            (location.get("source") or {}).get("display_name")
            if isinstance(location, dict)
            else None
        )
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(item.get("doi")),
                source=OPENALEX_SOURCE,
                evidence_grade=evidence.grade_from_record(
                    OPENALEX_SOURCE, item
                ),
                authors=authors,
                year=_integer(item.get("publication_year")),
                venue=_normalize(venue) or None,
                cited_by=_integer(item.get("cited_by_count")),
                publication_type=_normalize(item.get("type")) or None,
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
        authors = tuple(
            _normalize(author.get("name"))
            for author in (item.get("authors") or [])
            if isinstance(author, dict) and _normalize(author.get("name"))
        )
        publication_types = item.get("publicationTypes") or []
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                source=SEMANTIC_SCHOLAR_SOURCE,
                evidence_grade=evidence.grade_from_record(
                    SEMANTIC_SCHOLAR_SOURCE, item
                ),
                authors=authors,
                year=_integer(item.get("year")),
                venue=_normalize(item.get("venue")) or None,
                cited_by=_integer(item.get("citationCount")),
                publication_type=";".join(
                    str(value) for value in publication_types
                ) or None,
            )
        )
    return documents


def parse_searxng(
    json_text: str, limit: int = MAX_LIMIT
) -> list[RawDocument]:
    """Parse a SearXNG `format=json` response (`results`).

    SearXNG's science engines populate `content` with the paper's abstract —
    arXiv passes the Atom summary through untouched, and OpenAlex
    reconstructs `abstract_inverted_index` the same way this module does. So
    a result carries the same title+abstract this pipeline extracts spans
    from, and routing through it does not shorten the provenance chain.

    A result whose `content` is only a snippet still enters as a document;
    what it produces is proposals with spans into that snippet, which the
    document panel shows for what it is.

    `limit` is applied here rather than in the URL because SearXNG takes no
    result count — it answers one page of every engine at once.
    """
    payload = _load_json(json_text, SEARXNG_SOURCE)
    results = payload.get("results") or []
    documents: list[RawDocument] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        abstract = _normalize(item.get("content"))
        # An abstract is required here, unlike the sibling parsers. They
        # talk to one API that returns papers; this one aggregates engines
        # whose records are sometimes a bare title (a structure entry, a
        # dataset listing). A title-only document yields proposals whose
        # only evidence is the title itself, which is exactly what the
        # document panel has to flag as ungrounded.
        if not abstract:
            continue
        doi = _normalize(item.get("doi"))
        source_uri = (
            f"{DOI_BASE_URL}{doi}" if doi else _normalize(item.get("url"))
        )
        if not source_uri:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                pdf_url=_normalize(item.get("pdf_url")) or None,
                        source=SEARXNG_SOURCE,
            evidence_grade=evidence.grade_from_source(SEARXNG_SOURCE),
)
        )
        if len(documents) >= limit:
            break
    return documents
