"""Claude Science literature-harvest parity, plus OntologyLab safeguards."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import pytest

from ontologylab.connectors.base import RawDocument, collapse_duplicates
from ontologylab.connectors.paper_api import (
    PaperApiConnector,
    check_paper_query,
    fetch_sources,
    parse_crossref,
)


class _Engine:
    async def generate(self, prompt: str, *, model: str | None = None):
        del prompt, model
        return (
            "```json\n"
            + json.dumps(
                {
                    "queries": [
                        {
                            "query": "apple rootstock micropropagation",
                            "axis": "protocol",
                            "terms": [
                                "apple rootstock",
                                "micropropagat",
                            ],
                        },
                        {
                            "query": "Geneva rootstock fire blight",
                            "axis": "resistance",
                            "terms": [
                                "Geneva rootstock",
                                "fire blight",
                            ],
                        },
                    ],
                    "notes": "protocol and resistance axes",
                }
            )
            + "\n```",
            {"calls": 1},
        )


def _document(source: str, text: str, **kwargs) -> RawDocument:
    return RawDocument(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/parity",
        title="Parity paper",
        raw_text=text,
        doi="10.1000/parity",
        source=source,
        **kwargs,
    )


def test_query_axes_keep_terms_and_translate_each_source_dialect() -> None:
    from ontologylab.literature import ScholarlyQuery

    query = ScholarlyQuery(
        query="apple rootstock micropropagation",
        axis="protocol",
        terms=("apple rootstock", "micropropagat"),
    )

    assert query.for_source("openalex") == (
        'title_and_abstract.search:"apple rootstock" "micropropagat"'
    )
    assert query.for_source("pubmed") == (
        '"apple rootstock"[Title/Abstract] '
        "AND micropropagat*[Title/Abstract]"
    )
    assert query.for_source("elsevier") == (
        'TITLE-ABS-KEY("apple rootstock") '
        "AND TITLE-ABS-KEY(micropropagat*)"
    )
    assert query.for_source("core") == (
        '"apple rootstock" AND "micropropagat"'
    )
    assert query.for_source("springer") == '"apple rootstock"'
    assert query.for_source("semanticscholar") == (
        "apple rootstock micropropagat"
    )


def test_translated_typed_queries_fit_provider_aware_gate() -> None:
    from ontologylab.literature import ScholarlyQuery

    query = ScholarlyQuery(
        query="bounded source query",
        axis="coverage",
        terms=tuple(f"{letter}{'x' * 59}" for letter in "abcd"),
    )

    for source in ("openalex", "pubmed", "elsevier"):
        translated = query.for_source(source)
        assert len(translated) > 200
        assert check_paper_query(source, translated) == (
            source,
            translated,
        )


def test_fetch_sources_propagates_task_cancellation(monkeypatch) -> None:
    async def cancelled(self, source_spec):
        del self, source_spec
        raise asyncio.CancelledError

    monkeypatch.setattr(PaperApiConnector, "harvest", cancelled)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(fetch_sources(["crossref"], "cancel me", 1))


def test_query_formulation_returns_typed_axes_not_lossy_strings() -> None:
    from ontologylab.literature import formulate_scholarly_queries

    queries, usage = asyncio.run(
        formulate_scholarly_queries(
            "사과 대목 전주기 생산",
            _Engine(),
            max_queries=2,
        )
    )

    assert [(item.axis, item.terms) for item in queries] == [
        ("protocol", ("apple rootstock", "micropropagat")),
        ("resistance", ("Geneva rootstock", "fire blight")),
    ]
    assert usage["notes"] == "protocol and resistance axes"


def test_crossref_harvest_pages_until_the_per_source_cap(
    monkeypatch,
) -> None:
    from ontologylab.connectors import paper_api

    offsets: list[int] = []

    def _page(url: str) -> str:
        params = parse_qs(urlparse(url).query)
        offset = int(params.get("offset", ["0"])[0])
        offsets.append(offset)
        count = min(25, max(0, 60 - offset))
        items = [
            {
                "DOI": f"10.1000/page-{offset + index}",
                "title": [f"Paper {offset + index}"],
                "abstract": "abstract",
            }
            for index in range(count)
        ]
        return json.dumps({"message": {"items": items}})

    monkeypatch.setattr(paper_api, "_http_get_text", _page)

    documents = asyncio.run(
        PaperApiConnector().harvest(
            {
                "source": "crossref",
                "query": "apple rootstock",
                "max_records": 60,
                "page_size": 25,
            }
        )
    )

    assert len(documents) == 60
    assert offsets == [0, 25, 50]
    assert len({document.dedupe_key for document in documents}) == 60


def test_loose_publisher_results_are_filtered_by_every_query_concept(
    monkeypatch,
) -> None:
    from ontologylab.connectors import paper_api

    fixture = {
        "results": [
            {
                "id": 1,
                "doi": "10.1000/relevant",
                "title": "Apple rootstock micropropagation protocol",
                "abstract": "A complete micropropagation method for apple rootstock.",
                "fullTextIdentifier": "https://core.ac.uk/works/1",
            },
            {
                "id": 2,
                "doi": "10.1000/noise",
                "title": "Unrelated glyphosate measurements",
                "abstract": "A loose boolean match with no rootstock protocol.",
                "fullTextIdentifier": "https://core.ac.uk/works/2",
            },
        ]
    }
    monkeypatch.setattr(
        paper_api,
        "resolve_source_key",
        lambda source, data_dir: "core-key",
    )
    monkeypatch.setattr(
        paper_api,
        "_http_get_text",
        lambda url, headers=None: json.dumps(fixture),
    )

    documents = asyncio.run(
        PaperApiConnector().harvest(
            {
                "source": "core",
                "query": '"apple rootstock" AND "micropropagat"',
                "query_terms": ("apple rootstock", "micropropagat"),
                "max_records": 5,
                "page_size": 5,
            }
        )
    )

    assert [document.doi for document in documents] == ["10.1000/relevant"]


def test_dedup_merges_corroboration_metadata_and_fulltext_route() -> None:
    crossref = _document(
        "crossref",
        "the longest abstract body",
        authors=("Kim", "Lee"),
        year=2025,
        search_axis="mechanism",
        search_query="probe mechanism",
    )
    europepmc = _document(
        "europepmc",
        "short",
        cited_by=12,
        fulltext_url="https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML",
        search_axis="method",
        search_query="probe assay",
    )

    [merged] = collapse_duplicates(
        [("crossref", [crossref]), ("europepmc", [europepmc])],
        ("crossref", "europepmc"),
    )

    assert merged.raw_text == "the longest abstract body"
    assert merged.all_sources == ("crossref", "europepmc")
    assert merged.source_count == 2
    assert merged.authors == ("Kim", "Lee")
    assert merged.year == 2025
    assert merged.cited_by == 12
    assert merged.search_axes == ("mechanism", "method")
    assert merged.fulltext_url == europepmc.fulltext_url


def test_dedup_primary_source_follows_the_richest_winner() -> None:
    crossref = RawDocument(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/parity",
        title="Parity paper",
        raw_text="short",
        doi="10.1000/parity",
        source="crossref",
        evidence_grade="crossref-grade",
    )
    openalex = RawDocument(
        source_kind="paper_api",
        source_uri="https://openalex.org/W1",
        title="Parity paper",
        raw_text="OpenAlex provides the substantially richer body",
        doi="10.1000/parity",
        source="openalex",
        evidence_grade="openalex-grade",
    )

    [merged] = collapse_duplicates(
        [("crossref", [crossref]), ("openalex", [openalex])],
        ("crossref", "openalex"),
    )

    assert merged.source == "openalex"
    assert merged.source_uri == openalex.source_uri
    assert merged.evidence_grade == "openalex-grade"
    assert merged.raw_text == openalex.raw_text
    assert merged.all_sources == ("crossref", "openalex")


def test_crossref_retraction_status_survives_parsing() -> None:
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1000/retracted",
                    "title": ["A surprising result"],
                    "update-to": [{"type": "retraction"}],
                }
            ]
        }
    }

    [document] = parse_crossref(json.dumps(payload))

    assert document.retracted is True


