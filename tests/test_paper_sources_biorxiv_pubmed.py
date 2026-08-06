"""bioRxiv and PubMed connectors (science-skills integration, slice 1).

bioRxiv's official API is a date-browse, not a keyword search, so the
connector follows the documented pattern: the builder fixes a recent
28-day window and the fetch path filters the single most recent page
locally by query terms. PubMed goes through NCBI E-utilities: esearch
for PMIDs, then efetch for the XML abstracts.

These tests pin the parsers, the builder contract (host fixed, https,
query handling as documented), and both special fetch paths.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.paper_api import (
    BIORXIV_API_URL,
    BIORXIV_WINDOW_DAYS,
    PUBMED_EUTILS_URL,
    _build_biorxiv_url,
    _build_pubmed_url,
    parse_biorxiv,
    parse_pubmed,
    PaperApiConnector,
)
from ontologylab.evidence import PREPRINT, PEER_REVIEWED

BIORXIV_PAGE = """{
  "messages": [{"status": "ok"}],
  "collection": [
    {
      "doi": "10.1101/2026.01.01.500001",
      "title": "BRCA2 loss drives PARP inhibitor resistance",
      "abstract": "We study homologous recombination repair in ovarian cancer.",
      "category": "cancer biology",
      "date": "2026-07-28"
    },
    {
      "doi": "10.1101/2026.01.01.500002",
      "title": "A survey of fluorescent probes",
      "abstract": "Spectral overlap of visible-wavelength dyes.",
      "category": "biophysics",
      "date": "2026-07-27"
    }
  ]
}"""

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>BRCA2 and PARP inhibitor resistance in ovarian cancer</ArticleTitle>
        <Abstract>
          <AbstractText>Homologous recombination repair deficiency</AbstractText>
          <AbstractText>predicts platinum sensitivity.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">38000001</ArticleId>
        <ArticleId IdType="doi">10.1000/j.ovc.2026.001</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Unrelated meteorology</ArticleTitle>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">38000002</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_parse_biorxiv_extracts_title_abstract_and_doi() -> None:
    docs = parse_biorxiv(BIORXIV_PAGE)
    assert len(docs) == 2
    first = docs[0]
    assert first.source == "biorxiv"
    assert first.title == "BRCA2 loss drives PARP inhibitor resistance"
    assert "homologous recombination repair" in first.raw_text.lower()
    assert first.source_uri == "https://doi.org/10.1101/2026.01.01.500001"
    assert first.doi == "10.1101/2026.01.01.500001"
    assert first.evidence_grade == PREPRINT


def test_parse_biorxiv_skips_items_without_doi() -> None:
    page = BIORXIV_PAGE.replace('"doi": "10.1101/2026.01.01.500001",\n      ', "")
    docs = parse_biorxiv(page)
    assert len(docs) == 1
    assert docs[0].title == "A survey of fluorescent probes"


def test_biorxiv_builder_fixes_a_recent_window_and_never_leaks_query() -> None:
    url = _build_biorxiv_url("BRCA2 PARP inhibitor", 50)
    assert url.startswith(f"{BIORXIV_API_URL}/")
    window = url.split("/")[-3:]
    start, end, _ = window
    assert date.fromisoformat(end) == date.today()
    assert date.fromisoformat(start) == date.today() - timedelta(days=BIORXIV_WINDOW_DAYS)
    assert "BRCA2" not in url and "PARP" not in url


def test_parse_pubmed_joins_abstract_paragraphs_and_uses_doi() -> None:
    docs = parse_pubmed(PUBMED_XML)
    assert len(docs) == 2
    first = docs[0]
    assert first.source == "pubmed"
    assert "Homologous recombination repair deficiency predicts platinum sensitivity." in first.raw_text
    assert first.source_uri == "https://doi.org/10.1000/j.ovc.2026.001"
    assert first.evidence_grade == PEER_REVIEWED
    # no DOI -> PubMed landing page, not a dropped row
    assert docs[1].source_uri == "https://pubmed.ncbi.nlm.nih.gov/38000002/"


def test_pubmed_builder_encodes_query_for_esearch() -> None:
    url = _build_pubmed_url("BRCA2 PARP inhibitor", 25)
    assert url.startswith(f"{PUBMED_EUTILS_URL}/esearch.fcgi")
    assert "term=BRCA2+PARP+inhibitor" in url
    assert "retmode=json" in url and "retmax=25" in url


def _connector():
    return PaperApiConnector()


def test_fetch_pubmed_runs_esearch_then_efetch(monkeypatch) -> None:
    calls = []

    def fake_get_text(url, headers=None, query_key=None):
        calls.append(url)
        if "esearch" in url:
            return '{"esearchresult": {"idlist": ["38000001", "38000002"]}}'
        return PUBMED_XML

    monkeypatch.setattr("ontologylab.connectors.paper_api._http_get_text", fake_get_text)
    docs = asyncio.run(_connector()._fetch_pubmed(_build_pubmed_url("BRCA2", 10), parse_pubmed))
    assert len(calls) == 2
    assert "esearch.fcgi" in calls[0] and "efetch.fcgi" in calls[1]
    assert "id=38000001,38000002" in calls[1]
    assert len(docs) == 2


def test_fetch_pubmed_empty_idlist_is_a_clean_no_answer(monkeypatch) -> None:
    def fake_get_text(url, headers=None, query_key=None):
        return '{"esearchresult": {"idlist": []}}'

    monkeypatch.setattr("ontologylab.connectors.paper_api._http_get_text", fake_get_text)
    docs = asyncio.run(_connector()._fetch_pubmed(_build_pubmed_url("nothing", 10), parse_pubmed))
    assert docs == []


def test_fetch_biorxiv_filters_the_page_by_query_terms(monkeypatch) -> None:
    def fake_get_text(url, headers=None, query_key=None):
        return BIORXIV_PAGE

    monkeypatch.setattr("ontologylab.connectors.paper_api._http_get_text", fake_get_text)
    docs = asyncio.run(
        _connector()._fetch_biorxiv(
            _build_biorxiv_url("BRCA2 PARP resistance", 50), "BRCA2 PARP resistance", 50, parse_biorxiv
        )
    )
    assert len(docs) == 1
    assert "BRCA2" in docs[0].title

    none = asyncio.run(
        _connector()._fetch_biorxiv(
            _build_biorxiv_url("quantum teleportation", 50), "quantum teleportation", 50, parse_biorxiv
        )
    )
    assert none == []
