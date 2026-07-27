"""Trial registrations as a source, and the honest limits of adding more.

Asked to make the fan-out cover Claude Science's connector list (~70 hosts:
UniProt, Ensembl, KEGG, PDB, ChEMBL, gnomAD, ClinicalTrials, PubMed,
bioRxiv...). Most of that list cannot be a source here, and the reasons are
worth writing down next to the one that could:

* **Data resources** (UniProt, Ensembl, KEGG, PDB, ChEMBL, gnomAD, …) return
  structured records, not prose. This pipeline grounds every proposal in a
  span of source text a human can read and judge; a span pointing into a
  serialized JSON record is not evidence anyone can check. They belong to a
  different ingestion model, not to `_SOURCE_DISPATCH`.
* **bioRxiv** publishes no keyword-search endpoint — only details-by-DOI and
  date ranges (measured: `/details/biorxiv/{doi}` 500s, there is no search
  route). Its preprints already arrive through Europe PMC and Crossref.
* **PubMed** needs two requests (esearch → efetch) and the source contract
  here is one URL, one parser. Europe PMC already indexes PubMed, so the
  machinery would buy coverage this build largely has.

ClinicalTrials.gov is the one that fits and genuinely adds: one keyless
request, free-text query, and prose in the record. It is also a different
kind of evidence — what was attempted on people, including arms that never
became a paper.
"""

from __future__ import annotations

from ontologylab.connectors.allowlist import PAPER_API_SOURCES
from ontologylab.connectors.paper_api import (
    CLINICALTRIALS_SOURCE,
    IMPLEMENTED_SOURCES,
    PAPER_API_HOSTS,
    PAPER_SOURCE_LABELS,
    _build_clinicaltrials_url,
    parse_clinicaltrials,
)

# Trimmed to the fields the builder asks for, in the shape v2 returns.
RESPONSE = """
{"studies": [
  {"protocolSection": {
     "identificationModule": {"nctId": "NCT04208529",
        "briefTitle": "A Long-term Follow-up Study of CTX001"},
     "descriptionModule": {"briefSummary": "A rollover study of CTX001.",
        "detailedDescription": "Participants are followed for 15 years."}}},
  {"protocolSection": {
     "identificationModule": {"nctId": "NCT00000000",
        "briefTitle": "Title only, no prose"},
     "descriptionModule": {}}}
]}
"""


def test_the_source_is_registered_everywhere_it_has_to_be() -> None:
    """Four registries, and a source missing from any one of them fails
    somewhere else entirely — allowlist rejection, unsupported-source, or a
    picker option that 404s."""
    assert CLINICALTRIALS_SOURCE in PAPER_API_SOURCES
    assert CLINICALTRIALS_SOURCE in IMPLEMENTED_SOURCES
    assert CLINICALTRIALS_SOURCE in PAPER_SOURCE_LABELS
    assert "clinicaltrials.gov" in PAPER_API_HOSTS


def test_the_query_is_a_search_term_and_nothing_else() -> None:
    url = _build_clinicaltrials_url("CRISPR sickle cell", 3)

    assert url.startswith("https://clinicaltrials.gov/api/v2/studies?")
    assert "query.term=CRISPR+sickle+cell" in url
    assert "pageSize=3" in url
    assert "fields=" in url, "an unfielded study record is tens of kilobytes"


def test_a_trial_becomes_a_document_with_prose_to_cite() -> None:
    docs = parse_clinicaltrials(RESPONSE)

    assert len(docs) == 1, "the title-only record has nothing to ground a span in"
    doc = docs[0]
    assert doc.title == "A Long-term Follow-up Study of CTX001"
    assert doc.source_uri == "https://clinicaltrials.gov/study/NCT04208529"
    assert "rollover study" in doc.raw_text
    assert "15 years" in doc.raw_text, "detailed description is part of the body"


def test_a_trial_carries_no_doi() -> None:
    """Trials are identified by NCT number. Minting a DOI-shaped key would
    collide with the paper de-duplicator, which treats a shared DOI as
    'the same work'."""
    assert parse_clinicaltrials(RESPONSE)[0].doi is None


def test_a_malformed_payload_yields_nothing_rather_than_raising() -> None:
    """One source's bad day must not take the fan-out down with it."""
    assert parse_clinicaltrials('{"studies": [null, 7, {}]}') == []
