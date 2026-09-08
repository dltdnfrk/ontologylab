"""Pure arXiv Atom and PubMed XML record parsers."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from ontologylab import evidence
from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.connectors.paper_common import (
    ARXIV_SOURCE,
    DOI_BASE_URL,
    PUBMED_SOURCE,
    _normalize,
)

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def parse_atom(xml_text: str) -> list[RawDocument]:
    """Parse an arXiv Atom feed into RawDocuments (title + abstract only)."""
    # Why the stdlib parser is enough here — stated accurately, because the
    # earlier justification was not. `ET.fromstring` DOES expand internal
    # entities, so "no external entities" was never the protection. What
    # actually bounds a billion-laughs payload is libexpat's amplification
    # limit (100x, 8 MiB threshold, expat >= 2.4), measured: a seven-stage
    # bomb is refused with `ParseError: limit on input amplification factor
    # breached`. A four-stage one stays under the threshold and parses, which
    # is why `_http_get_text` caps the input that expansion multiplies.
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
                # arXiv Atom entries carry no DOI. Leaving it None makes the
                # entry de-duplicate on its `<id>` URL instead of colliding
                # with every other DOI-less document under a shared key.
                doi=None,
                        source=ARXIV_SOURCE,
            evidence_grade=evidence.grade_from_source(ARXIV_SOURCE),
)
        )
    return documents


def parse_pubmed(xml_text: str) -> list[RawDocument]:
    """Parse an efetch PubmedArticleSet into documents.

    Same ingest contract: title + abstract only; an article without a DOI
    or PMID gets no source_uri and is skipped — no provenance trail, no
    ingestion.
    """
    root = ET.fromstring(xml_text)
    documents: list[RawDocument] = []
    for article in root.findall("PubmedArticle"):
        title = _normalize(article.findtext("MedlineCitation/Article/ArticleTitle"))
        abstract_parts = [
            _normalize("".join(node.itertext()))
            for node in article.findall(
                "MedlineCitation/Article/Abstract/AbstractText"
            )
        ]
        abstract = " ".join(p for p in abstract_parts if p)
        if not title and not abstract:
            continue
        doi = _normalize(
            article.findtext("PubmedData/ArticleIdList/ArticleId[@IdType='doi']")
        )
        pmid = _normalize(
            article.findtext("PubmedData/ArticleIdList/ArticleId[@IdType='pubmed']")
        )
        if doi:
            source_uri = f"{DOI_BASE_URL}{doi}"
        elif pmid:
            source_uri = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        else:
            continue
        author_nodes = article.findall(
            "MedlineCitation/Article/AuthorList/Author"
        )
        authors = tuple(
            name
            for node in author_nodes
            if (
                name := _normalize(
                    " ".join(
                        part
                        for part in (
                            node.findtext("ForeName") or "",
                            node.findtext("LastName") or "",
                        )
                        if part
                    )
                )
            )
        )
        year_text = (
            article.findtext(
                "MedlineCitation/Article/Journal/JournalIssue/PubDate/Year"
            )
            or article.findtext(
                "MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate"
            )
            or ""
        )
        year_match = re.search(r"\b(19|20)\d{2}\b", year_text)
        publication_types = [
            _normalize(node.text)
            for node in article.findall(
                "MedlineCitation/Article/PublicationTypeList/PublicationType"
            )
            if _normalize(node.text)
        ]
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                source=PUBMED_SOURCE,
                evidence_grade=evidence.grade_from_source(PUBMED_SOURCE),
                authors=authors,
                year=int(year_match.group()) if year_match else None,
                venue=_normalize(
                    article.findtext("MedlineCitation/Article/Journal/Title")
                ) or None,
                publication_type=";".join(publication_types) or None,
            )
        )
    return documents
