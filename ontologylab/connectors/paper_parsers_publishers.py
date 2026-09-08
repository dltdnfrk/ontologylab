"""Pure Elsevier, Springer, and CORE record parsers."""

from __future__ import annotations

import re
from ontologylab import evidence
from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.connectors.paper_common import (
    CORE_SOURCE,
    DOI_BASE_URL,
    ELSEVIER_SOURCE,
    SPRINGER_SOURCE,
    _MARKUP_TAG_RE,
    _integer,
    _load_json,
    _normalize,
)

def parse_elsevier(json_text: str) -> list[RawDocument]:
    """Parse a Scopus Search response (`search-results.entry`).

    Scopus keys are OpenSearch/PRISM-namespaced, so the field names carry
    their prefixes literally: `dc:title`, `dc:description`, `prism:doi`.
    """
    payload = _load_json(json_text, ELSEVIER_SOURCE)
    entries = ((payload.get("search-results") or {}).get("entry")) or []
    documents: list[RawDocument] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        # An error entry carries `error` instead of a record; skipping keeps
        # one bad row from emptying an otherwise good page.
        if item.get("error"):
            continue
        title = _normalize(item.get("dc:title"))
        abstract = _normalize(item.get("dc:description"))
        if not title and not abstract:
            continue
        doi = _normalize(item.get("prism:doi"))
        source_uri = f"{DOI_BASE_URL}{doi}" if doi else _normalize(item.get("prism:url"))
        if not source_uri:
            continue
        year_match = re.match(
            r"(\d{4})",
            _normalize(item.get("prism:coverDate")),
        )
        creator = _normalize(item.get("dc:creator"))
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                source=ELSEVIER_SOURCE,
                evidence_grade=evidence.grade_from_source(ELSEVIER_SOURCE),
                authors=(creator,) if creator else (),
                year=int(year_match.group()) if year_match else None,
                venue=_normalize(item.get("prism:publicationName")) or None,
                cited_by=_integer(item.get("citedby-count")),
                publication_type=(
                    _normalize(item.get("subtypeDescription")) or None
                ),
            )
        )
    return documents


def parse_springer(json_text: str) -> list[RawDocument]:
    """Parse a Springer Nature Meta v2 response (`records`)."""
    payload = _load_json(json_text, SPRINGER_SOURCE)
    records = payload.get("records") or []
    documents: list[RawDocument] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        # `abstract` is a string on most records but an object with `p` on
        # structured ones; neither shape is worth a crash.
        raw_abstract = item.get("abstract")
        if isinstance(raw_abstract, dict):
            raw_abstract = raw_abstract.get("p") or ""
        if isinstance(raw_abstract, list):
            raw_abstract = " ".join(str(part) for part in raw_abstract)
        abstract = _normalize(_MARKUP_TAG_RE.sub(" ", str(raw_abstract or "")))
        if not title and not abstract:
            continue
        doi = _normalize(item.get("doi"))
        source_uri = f"{DOI_BASE_URL}{doi}" if doi else _first_springer_url(item)
        if not source_uri:
            continue
        creators = item.get("creators") or []
        authors = tuple(
            _normalize(creator.get("creator"))
            for creator in creators
            if isinstance(creator, dict)
            and _normalize(creator.get("creator"))
        )
        year_match = re.match(
            r"(\d{4})",
            _normalize(item.get("publicationDate")),
        )
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                pdf_url=_first_springer_url(item, want_pdf=True) or None,
                source=SPRINGER_SOURCE,
                evidence_grade=evidence.grade_from_source(SPRINGER_SOURCE),
                authors=authors,
                year=int(year_match.group()) if year_match else None,
                venue=_normalize(item.get("publicationName")) or None,
                publication_type=_normalize(item.get("contentType")) or None,
            )
        )
    return documents


def _first_springer_url(item: dict, *, want_pdf: bool = False) -> str:
    """Springer's `url` is a list of {format, platform, value} objects."""
    urls = item.get("url")
    if not isinstance(urls, list):
        return ""
    for entry in urls:
        if not isinstance(entry, dict):
            continue
        fmt = str(entry.get("format") or "").lower()
        if want_pdf and fmt != "pdf":
            continue
        if not want_pdf and fmt == "pdf":
            continue
        value = _normalize(entry.get("value"))
        if value:
            return value
    return ""


def parse_core(json_text: str) -> list[RawDocument]:
    """Parse a CORE v3 `search/works` response (`results`)."""
    payload = _load_json(json_text, CORE_SOURCE)
    results = payload.get("results") or []
    documents: list[RawDocument] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        abstract = _normalize(item.get("abstract"))
        if not title and not abstract:
            continue
        doi = _normalize(item.get("doi"))
        source_uri = (
            f"{DOI_BASE_URL}{doi}" if doi
            else _normalize(item.get("fullTextIdentifier"))
        )
        if not source_uri:
            continue
        authors = tuple(
            _normalize(author.get("name"))
            for author in (item.get("authors") or [])
            if isinstance(author, dict) and _normalize(author.get("name"))
        )
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                pdf_url=_normalize(item.get("downloadUrl")) or None,
                source=CORE_SOURCE,
                evidence_grade=evidence.grade_from_source(CORE_SOURCE),
                authors=authors,
                year=_integer(item.get("yearPublished")),
                venue=_normalize(item.get("publisher")) or None,
                cited_by=_integer(item.get("citationCount")),
                publication_type=_normalize(item.get("documentType")) or None,
            )
        )
    return documents
