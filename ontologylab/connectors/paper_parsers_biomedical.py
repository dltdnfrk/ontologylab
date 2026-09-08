"""Pure Europe PMC, bioRxiv, and trial-registration parsers."""

from __future__ import annotations

from ontologylab import evidence
from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.connectors.paper_common import (
    BIORXIV_SOURCE,
    CLINICALTRIALS_SOURCE,
    DOI_BASE_URL,
    EUROPEPMC_SOURCE,
    _MARKUP_TAG_RE,
    _integer,
    _load_json,
    _normalize,
)
from ontologylab.connectors.paper_urls import europepmc_fulltext_url

def parse_clinicaltrials(json_text: str) -> list[RawDocument]:
    """Parse a ClinicalTrials.gov v2 /studies response.

    A trial is not a paper and the difference is the point: this is what was
    attempted on people, including the arms that never produced a
    publication. The registry's prose fields — brief summary and detailed
    description — are what the extractor can ground spans in, so a record
    with neither is skipped rather than stored as a bare title.

    No DOI: trials are identified by NCT number, and inventing a DOI-shaped
    key would collide with the paper de-duplicator.
    """
    payload = _load_json(json_text, CLINICALTRIALS_SOURCE)
    studies = payload.get("studies") or []
    documents: list[RawDocument] = []
    for study in studies:
        if not isinstance(study, dict):
            continue
        protocol = study.get("protocolSection") or {}
        ident = protocol.get("identificationModule") or {}
        desc = protocol.get("descriptionModule") or {}

        nct_id = _normalize(ident.get("nctId"))
        if not nct_id:
            continue
        title = _normalize(
            ident.get("briefTitle") or ident.get("officialTitle")
        )
        summary = _normalize(desc.get("briefSummary"))
        detail = _normalize(desc.get("detailedDescription"))
        body = "\n\n".join(part for part in (summary, detail) if part)
        if not body:
            # Title-only records give the extractor nothing to cite.
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=f"https://clinicaltrials.gov/study/{nct_id}",
                title=title or nct_id,
                raw_text=body,
                        source=CLINICALTRIALS_SOURCE,
            evidence_grade=evidence.grade_from_source(CLINICALTRIALS_SOURCE),
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
        # `resultType=core` already carries the open-access flags; the
        # earlier parser read the response and threw them away, so every
        # collect stopped at the abstract even for articles whose full text
        # was one request further on. `inEPMC` is the one that matters:
        # isOpenAccess can be Y while the text lives somewhere Europe PMC
        # does not serve, and only the EPMC-hosted subset is reachable
        # without leaving the allowlisted host.
        fulltext_url = ""
        if _normalize(item.get("inEPMC")).upper() == "Y":
            fulltext_url = europepmc_fulltext_url(_normalize(item.get("pmcid")))
        oa_pdf = ""
        for entry in (item.get("fullTextUrlList") or {}).get("fullTextUrl", []):
            if not isinstance(entry, dict):
                continue
            if (
                _normalize(entry.get("documentStyle")).lower() == "pdf"
                and _normalize(entry.get("availability")).lower() == "open access"
            ):
                oa_pdf = _normalize(entry.get("url"))
                break
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
                doi=normalize_doi(doi),
                pdf_url=oa_pdf or None,
                fulltext_url=fulltext_url or None,
                year=_integer(item.get("pubYear")),
                        source=EUROPEPMC_SOURCE,
            evidence_grade=evidence.grade_from_record(EUROPEPMC_SOURCE, item),
)
        )
    return documents


def parse_biorxiv(json_text: str) -> list[RawDocument]:
    """Parse one page of the bioRxiv details API into documents.

    Same ingest contract as the other parsers: title + abstract only, and
    an item with no DOI or title never becomes a document row. Every row is
    a preprint by definition, so the evidence grade is constant.
    """
    payload = _load_json(json_text, BIORXIV_SOURCE)
    collection = payload.get("collection") or []
    documents: list[RawDocument] = []
    for item in collection:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        abstract = _normalize(item.get("abstract"))
        if not title and not abstract:
            continue
        doi = _normalize(item.get("doi"))
        if not doi:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=f"{DOI_BASE_URL}{doi}",
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                        source=BIORXIV_SOURCE,
            evidence_grade=evidence.grade_from_source(BIORXIV_SOURCE),
)
        )
    return documents
