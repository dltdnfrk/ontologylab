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
import json
from datetime import date, timedelta

import pytest

from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.paper_api import (
    BIORXIV_API_URL,
    BIORXIV_WINDOW_DAYS,
    PUBMED_EUTILS_URL,
    PUBMED_SOURCE,
    _build_biorxiv_url,
    _build_pubmed_url,
    parse_biorxiv,
    parse_pubmed,
    PaperApiConnector,
)
from ontologylab.evidence import PREPRINT, PEER_REVIEWED
from ontologylab.sources import Source, add_source

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


@pytest.mark.parametrize(
    ("abstract_xml", "expected"),
    [
        pytest.param("", "", id="missing-abstract"),
        pytest.param("<Abstract/>", "", id="empty-abstract"),
        pytest.param(
            "<Abstract><AbstractText/></Abstract>", "", id="empty-paragraph"
        ),
        pytest.param(
            "<Abstract><AbstractText> \n\t </AbstractText></Abstract>",
            "", id="whitespace-paragraph",
        ),
        pytest.param(
            "<Abstract><AbstractText><sup/></AbstractText></Abstract>",
            "", id="empty-inline-element",
        ),
        pytest.param(
            "<Abstract><AbstractText>Plain paragraph.</AbstractText></Abstract>",
            "Plain paragraph.", id="plain-paragraph",
        ),
        pytest.param(
            "<Abstract><AbstractText>Before<sup>1</sup> after.</AbstractText></Abstract>",
            "Before1 after.", id="inline-citation-and-tail",
        ),
        pytest.param(
            "<Abstract><AbstractText>Alpha <b>beta <i>gamma</i> delta</b> epsilon."
            "</AbstractText></Abstract>",
            "Alpha beta gamma delta epsilon.", id="nested-text-and-tails",
        ),
        pytest.param(
            "<Abstract><AbstractText><i>Only child</i> with tail."
            "</AbstractText></Abstract>",
            "Only child with tail.", id="child-first-paragraph",
        ),
        pytest.param(
            '<Abstract><AbstractText Label="BACKGROUND"> First <i>nested</i> tail. '
            '</AbstractText><AbstractText/><AbstractText Label="RESULTS">'
            "Second<sup>2</sup> tail.</AbstractText></Abstract>",
            "First nested tail. Second2 tail.", id="ordered-mixed-paragraphs",
        ),
    ],
)
def test_parse_pubmed_preserves_abstract_text_nodes(
    abstract_xml: str, expected: str
) -> None:
    start = PUBMED_XML.index("<Abstract>")
    end = PUBMED_XML.index("</Abstract>") + len("</Abstract>")
    first, second = parse_pubmed(PUBMED_XML[:start] + abstract_xml + PUBMED_XML[end:])
    assert first.raw_text == (
        "BRCA2 and PARP inhibitor resistance in ovarian cancer\n\n" + expected
    )
    assert first.source == PUBMED_SOURCE
    assert first.source_uri == "https://doi.org/10.1000/j.ovc.2026.001"
    assert second.raw_text == "Unrelated meteorology\n\n"


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


def test_pubmed_key_reaches_both_eutils_requests_without_entering_logged_urls(
    tmp_path, monkeypatch
) -> None:
    secret = "NCBI-key-must-stay-beside-the-url"
    monkeypatch.setenv("TEST_NCBI_API_KEY", secret)
    add_source(
        tmp_path,
        Source(
            id=PUBMED_SOURCE,
            role="literature",
            api_key_env="TEST_NCBI_API_KEY",
        ),
    )
    calls = []

    def fake_get_text(url, headers=None, query_key=None):
        calls.append((url, query_key))
        if "esearch" in url:
            return '{"esearchresult": {"idlist": ["38000001"]}}'
        return PUBMED_XML

    monkeypatch.setattr(
        "ontologylab.connectors.paper_api._http_get_text",
        fake_get_text,
    )

    docs = asyncio.run(
        _connector().fetch(
            {
                "source": PUBMED_SOURCE,
                "query": "BRCA2",
                "limit": 10,
                "data_dir": tmp_path,
            }
        )
    )

    assert docs
    assert len(calls) == 2
    assert all(query_key == ("api_key", secret) for _url, query_key in calls)
    assert all(secret not in url for url, _query_key in calls)


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
    assert docs[0].title is not None
    assert "BRCA2" in docs[0].title

    none = asyncio.run(
        _connector()._fetch_biorxiv(
            _build_biorxiv_url("quantum teleportation", 50), "quantum teleportation", 50, parse_biorxiv
        )
    )
    assert none == []


def test_biorxiv_harvest_advances_the_documented_cursor(monkeypatch) -> None:
    cursors: list[int] = []

    def fake_get_text(url, headers=None, query_key=None):
        del headers, query_key
        cursor = int(url.rstrip("/").split("/")[-1])
        cursors.append(cursor)
        count = 30 if cursor == 0 else 5
        return json.dumps(
            {
                "messages": [{"status": "ok", "total": 35}],
                "collection": [
                    {
                        "doi": f"10.1101/2026.08.26.{cursor + index:06d}",
                        "title": f"BRCA2 cursor record {cursor + index}",
                        "abstract": "BRCA2 repair evidence",
                        "date": "2026-08-26",
                    }
                    for index in range(count)
                ],
            }
        )

    monkeypatch.setattr(
        "ontologylab.connectors.paper_api._http_get_text",
        fake_get_text,
    )

    docs = asyncio.run(
        _connector().harvest(
            {
                "source": "biorxiv",
                "query": "BRCA2",
                "max_records": 35,
                "page_size": 30,
            }
        )
    )

    assert cursors == [0, 30]
    assert len(docs) == 35
