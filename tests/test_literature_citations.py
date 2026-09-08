"""Citation-neighborhood retrieval through the guarded OpenAlex seam."""

from __future__ import annotations

import asyncio
import json

import pytest

from ontologylab.connectors.base import RawDocument
from ontologylab.literature import expand_citation_neighborhood
from ontologylab.paths import NetworkBlocked


def test_openalex_expansion_walks_backward_and_forward_once(
    monkeypatch,
) -> None:
    from ontologylab.connectors import paper_api

    seen: list[str] = []

    def _response(url: str, headers=None, query_key=None) -> str:
        del headers, query_key
        seen.append(url)
        if "/works/https%3A%2F%2Fdoi.org%2F" in url:
            return json.dumps({"id": "https://openalex.org/W1"})
        if "cited_by%3AW1" in url:
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W2",
                            "doi": "https://doi.org/10.1000/backward",
                            "display_name": "Earlier work",
                        }
                    ]
                }
            )
        if "cites%3AW1" in url:
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W3",
                            "doi": "https://doi.org/10.1000/forward",
                            "display_name": "Later work",
                        }
                    ]
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(paper_api, "_http_get_text", _response)
    seed = RawDocument(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/parity",
        title="Parity paper",
        raw_text="seed",
        doi="10.1000/parity",
        source="crossref",
    )

    documents = asyncio.run(
        expand_citation_neighborhood(
            [seed],
            backward_limit=1,
            forward_limit=1,
        )
    )

    assert {document.doi for document in documents} == {
        "10.1000/backward",
        "10.1000/forward",
    }
    assert {document.search_axis for document in documents} == {
        "citation_backward",
        "citation_forward",
    }
    assert len(seen) == 3


def test_citation_expansion_preserves_network_kill_switch(
    monkeypatch,
) -> None:
    from ontologylab.connectors import paper_api

    monkeypatch.setattr(
        paper_api,
        "_http_get_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            NetworkBlocked("network disabled")
        ),
    )
    seed = RawDocument(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/network",
        title="Network seed",
        raw_text="seed",
        doi="10.1000/network",
        source="crossref",
    )

    with pytest.raises(NetworkBlocked):
        asyncio.run(expand_citation_neighborhood([seed]))
