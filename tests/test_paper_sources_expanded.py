"""2026-07 paper-source expansion: OpenAlex / Semantic Scholar / Europe PMC.

All offline (network monkeypatched). Pins the shared ingest contract for
every new source: title+abstract only, provenance URI required, degenerate
rows skipped, allowlist checked before any I/O, and the free-text query
policy end-to-end through the CLI.
"""

from __future__ import annotations

import asyncio

import pytest

from ontologylab import paths
from ontologylab.connectors.allowlist import NotAllowlisted
from ontologylab.connectors.paper_api import (
    PaperApiConnector,
    _build_europepmc_url,
    _build_openalex_url,
    _build_semanticscholar_url,
    _restore_inverted_abstract,
    parse_europepmc,
    parse_openalex,
    parse_semanticscholar,
)
from ontologylab.kgstore import KGStore
from ontologylab.main import main

OPENALEX_FIXTURE = """{
  "results": [
    {
      "id": "https://openalex.org/W2741809807",
      "doi": "https://doi.org/10.7717/peerj.4375",
      "display_name": "The state of OA journals",
      "abstract_inverted_index": {
        "Open": [0], "access": [1], "journals": [2, 5],
        "grow": [3], "as": [4], "mature.": [6]
      }
    },
    {
      "id": "https://openalex.org/W111",
      "display_name": "No abstract, id-only provenance",
      "abstract_inverted_index": null
    },
    {"id": "", "display_name": "", "abstract_inverted_index": null}
  ]
}"""


def test_restore_inverted_abstract_orders_by_position():
    text = _restore_inverted_abstract(
        {"world": [1], "hello": [0], "again": [2]}
    )
    assert text == "hello world again"
    assert _restore_inverted_abstract(None) == ""
    assert _restore_inverted_abstract({}) == ""


def test_parse_openalex_contract():
    docs = parse_openalex(OPENALEX_FIXTURE)
    assert len(docs) == 2  # empty row skipped
    first, second = docs
    assert first.source_kind == "paper_api"
    assert first.title == "The state of OA journals"
    assert "Open access journals grow as journals mature." in first.raw_text
    assert first.source_uri == "https://doi.org/10.7717/peerj.4375"
    # doi absent -> falls back to the canonical openalex id URL
    assert second.source_uri == "https://openalex.org/W111"


S2_FIXTURE = """{
  "total": 2,
  "data": [
    {
      "title": "Attention Is All You Need",
      "abstract": "We propose the Transformer, based solely on attention.",
      "url": "https://www.semanticscholar.org/paper/abc123",
      "externalIds": {"DOI": "10.48550/arXiv.1706.03762"}
    },
    {
      "title": "DOI-only paper",
      "abstract": "No url field on this row.",
      "externalIds": {"DOI": "10.1000/xyz"}
    },
    {"title": "", "abstract": ""}
  ]
}"""


def test_parse_semanticscholar_contract():
    docs = parse_semanticscholar(S2_FIXTURE)
    assert len(docs) == 2
    first, second = docs
    assert first.title == "Attention Is All You Need"
    assert first.source_uri == "https://www.semanticscholar.org/paper/abc123"
    assert second.source_uri == "https://doi.org/10.1000/xyz"


EUROPEPMC_FIXTURE = """{
  "resultList": {
    "result": [
      {
        "id": "34567",
        "source": "MED",
        "doi": "10.1093/nar/gkab1112",
        "title": "Europe PMC in 2022",
        "abstractText": "<h4>Background</h4>Europe PMC is an open repository."
      },
      {
        "id": "PPR999",
        "source": "PPR",
        "title": "Preprint without DOI",
        "abstractText": "Falls back to the europepmc abstract URL."
      },
      {"id": "x", "source": "MED"}
    ]
  }
}"""


def test_parse_europepmc_contract():
    docs = parse_europepmc(EUROPEPMC_FIXTURE)
    assert len(docs) == 2
    first, second = docs
    assert first.title == "Europe PMC in 2022"
    assert "<h4>" not in first.raw_text  # markup stripped
    assert first.source_uri == "https://doi.org/10.1093/nar/gkab1112"
    assert second.source_uri == "https://europepmc.org/abstract/PPR/PPR999"


@pytest.mark.parametrize(
    ("source", "fixture", "builder", "endpoint_fragment"),
    [
        ("openalex", OPENALEX_FIXTURE, _build_openalex_url,
         "api.openalex.org/works"),
        ("semanticscholar", S2_FIXTURE, _build_semanticscholar_url,
         "api.semanticscholar.org/graph/v1/paper/search"),
        ("europepmc", EUROPEPMC_FIXTURE, _build_europepmc_url,
         "ebi.ac.uk/europepmc/webservices/rest/search"),
    ],
)
def test_fetch_dispatch_hits_right_endpoint(
    monkeypatch, source, fixture, builder, endpoint_fragment
):
    import ontologylab.connectors.paper_api as pa

    seen: list[str] = []

    def fake_fetch(url):
        seen.append(url)
        return fixture

    monkeypatch.setattr(pa, "_http_get_text", fake_fetch)
    docs = asyncio.run(
        PaperApiConnector().fetch(
            {"source": source, "query": "open science", "limit": 3}
        )
    )
    assert len(docs) == 2
    (url,) = seen
    assert url == builder("open science", 3)
    assert endpoint_fragment in url
    assert url.startswith("https://")


def test_new_sources_still_gated_before_io(monkeypatch):
    import ontologylab.connectors.paper_api as pa

    def boom(url):  # pragma: no cover - must not be reached
        raise AssertionError("network I/O attempted for rejected query")

    monkeypatch.setattr(pa, "_http_get_text", boom)
    for source in ("openalex", "semanticscholar", "europepmc"):
        with pytest.raises(NotAllowlisted):
            asyncio.run(
                PaperApiConnector().fetch(
                    {"source": source, "query": "https://evil.example/x"}
                )
            )


def test_cli_free_query_through_openalex(tmp_path, monkeypatch):
    """Free-text query end-to-end: CLI -> allowlist -> fetch -> insert."""
    import ontologylab.connectors.paper_api as pa

    monkeypatch.setattr(pa, "_http_get_text", lambda url: OPENALEX_FIXTURE)
    data = str(tmp_path / "data")
    with pytest.raises(SystemExit) as exc:
        main([
            "collect", "--data-dir", data,
            "--paper-source", "openalex",
            "--paper-query", "open access publishing trends",
        ])
    assert exc.value.code == 0

    store = KGStore.open(paths.kg_db_path(tmp_path / "data"))
    try:
        docs = store.list_documents()
    finally:
        store.close()
    assert len(docs) == 2
    assert {d.source_kind for d in docs} == {"paper_api"}
