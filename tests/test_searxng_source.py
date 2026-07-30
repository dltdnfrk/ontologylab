"""A metasearch source the user runs themselves.

Every other paper source in this repo is one fixed, constant endpoint —
that is what makes the exact-match host allowlist possible at all. SearXNG
is not: it is a service the user installs, so its address is configuration.
That exception is the whole reason this file exists, and most of what it
pins is the narrower rule that replaces the one being given up.

The rest was learned from a live instance rather than the docs, which is
why it is worth pinning: `categories=science` also returns protein
structure records with no abstract, and SearXNG answers a whole page of
every engine at once regardless of what you asked for.
"""

from __future__ import annotations

import json

import pytest

from ontologylab.connectors.allowlist import (
    NotAllowlisted,
    check_searxng_base_url,
)
from ontologylab.connectors.base import collapse_duplicates
from ontologylab.connectors.paper_api import (
    SEARXNG_ENGINES,
    SEARXNG_SOURCE,
    SEARXNG_URL_ENV,
    SOURCE_ORDER,
    IMPLEMENTED_SOURCES,
    _build_searxng_url,
    available_sources,
    parse_searxng,
)


# --------------------------------------------------------------------------
# The exception, and the rule that replaces it
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080",
        "http://127.0.0.1:8888",
        "https://192.168.1.10:8443",
        "http://10.0.0.4:8080",
        "http://searx.lan:8080",
    ],
)
def test_an_instance_on_this_machine_or_network_is_allowed(url: str) -> None:
    assert check_searxng_base_url(url)


@pytest.mark.parametrize(
    "url",
    ["https://searx.be", "http://8.8.8.8:8080", "https://example.com/searx"],
)
def test_a_public_instance_is_refused(url: str) -> None:
    """The property the host allowlist exists to guarantee.

    A public instance would be a keyless, user-supplied, arbitrary internet
    endpoint receiving every query this tool makes. Loopback and private
    addresses cannot carry a research question to a third party, which is
    why they are the replacement for "one fixed host".
    """
    with pytest.raises(NotAllowlisted, match="loopback or private"):
        check_searxng_base_url(url)


def test_credentials_in_the_url_are_refused() -> None:
    """Userinfo would reach the job log and the provenance record — the same
    reason publisher keys travel as headers and never as query parameters."""
    with pytest.raises(NotAllowlisted, match="credential"):
        check_searxng_base_url("http://user:secret@localhost:8080")


def test_a_non_http_scheme_is_refused() -> None:
    with pytest.raises(NotAllowlisted, match="scheme"):
        check_searxng_base_url("ftp://localhost:8080")


def test_the_path_is_discarded_so_only_an_origin_survives() -> None:
    """The base URL is interpolated into a request path. Keeping whatever
    the user typed after the host would let a stray path segment redirect
    the query somewhere else on that host."""
    assert check_searxng_base_url("http://localhost:8080/searx/?x=1") == (
        "http://localhost:8080"
    )


# --------------------------------------------------------------------------
# What gets asked for
# --------------------------------------------------------------------------


def test_the_query_goes_to_named_scholarly_engines(monkeypatch) -> None:
    """Not `categories=science`.

    Measured against a live instance, that category also returns `pdbe`
    (protein structure records) and `openairedatasets` — titles with no
    abstract, in a corpus whose claim is that a proposal traces back to
    something a paper says.
    """
    monkeypatch.setenv(SEARXNG_URL_ENV, "http://localhost:8080")

    url = _build_searxng_url("BRCA1 DNA repair", 5)

    assert url.startswith("http://localhost:8080/search?")
    assert "format=json" in url
    assert "categories=science" not in url
    assert "google+scholar" in url, "the engine with no API of its own"
    assert "engines=" in url


def test_an_unconfigured_instance_is_refused_with_a_usable_message(
    monkeypatch,
) -> None:
    monkeypatch.delenv(SEARXNG_URL_ENV, raising=False)

    with pytest.raises(NotAllowlisted, match=SEARXNG_URL_ENV):
        _build_searxng_url("anything", 5)


def test_an_unconfigured_install_does_not_collect_a_failure_per_run(
    monkeypatch,
) -> None:
    """Not running a SearXNG is a choice, not a fault — the same reason an
    unconnected publisher source stays out of the default fan-out."""
    monkeypatch.delenv(SEARXNG_URL_ENV, raising=False)
    assert SEARXNG_SOURCE not in available_sources()

    monkeypatch.setenv(SEARXNG_URL_ENV, "http://localhost:8080")
    assert SEARXNG_SOURCE in available_sources()


def test_a_misconfigured_url_is_reported_rather_than_silently_dropped(
    monkeypatch,
) -> None:
    """A typo that merely disabled the source would leave the run looking
    complete while quietly querying one source fewer."""
    monkeypatch.setenv(SEARXNG_URL_ENV, "https://searx.be")

    with pytest.raises(NotAllowlisted):
        available_sources()


# --------------------------------------------------------------------------
# What comes back
# --------------------------------------------------------------------------


def _response(*results: dict) -> str:
    return json.dumps({"query": "q", "results": list(results)})


def test_an_abstract_becomes_the_document_text() -> None:
    body = _response({
        "title": "BRCA1 and DNA repair",
        "content": "BRCA1 is essential for homologous recombination.",
        "url": "https://arxiv.org/abs/1234.5678",
        "doi": "10.1000/xyz",
    })

    documents = parse_searxng(body)

    assert len(documents) == 1
    assert documents[0].raw_text == (
        "BRCA1 and DNA repair\n\n"
        "BRCA1 is essential for homologous recombination."
    )
    assert documents[0].doi == "10.1000/xyz"


def test_a_record_with_no_abstract_is_dropped() -> None:
    """Unlike the sibling parsers, which keep a title-only record.

    They each talk to one API that returns papers. This one aggregates
    engines whose records are sometimes a bare title — a structure entry, a
    dataset listing — and a title-only document yields proposals whose only
    evidence is the title, which the document panel has to flag as
    ungrounded anyway.
    """
    body = _response(
        {"title": "Solution NMR Structure of BRCA1-PALB2", "content": "",
         "url": "https://www.ebi.ac.uk/pdbe/entry/pdb/1abc"},
        {"title": "A real paper", "content": "With a real abstract.",
         "url": "https://arxiv.org/abs/1"},
    )

    documents = parse_searxng(body)

    assert [d.title for d in documents] == ["A real paper"]


def test_the_page_is_capped_because_the_request_cannot_be() -> None:
    """SearXNG takes no result count; it answers a page of every engine at
    once. One ordinary query measured 55 results, which would let this one
    source outweigh the other six combined."""
    body = _response(*[
        {"title": f"Paper {n}", "content": f"Abstract {n}.",
         "url": f"https://arxiv.org/abs/{n}"}
        for n in range(50)
    ])

    assert len(parse_searxng(body, limit=5)) == 5


def test_a_result_with_no_locator_is_dropped() -> None:
    body = _response(
        {"title": "No URL", "content": "Has an abstract but nowhere to point."}
    )

    assert parse_searxng(body) == []


def test_the_same_paper_from_two_sources_collapses() -> None:
    """SearXNG queries arXiv too, so the fan-out sees the same paper twice.

    Neither copy carries a DOI — arXiv preprints often have none — so the
    identity falls back to the URL, and both engines report the same abs
    page. Verified against a live instance: one duplicate collapsed out of
    a three-source fan-out.
    """
    shared_url = "http://arxiv.org/abs/q-bio/0703003v1"
    native = parse_searxng(_response({
        "title": "Effect of Internal Viscosity",
        "content": "A longer abstract from the native connector, verbatim.",
        "url": shared_url,
    }))
    metasearch = parse_searxng(_response({
        "title": "Effect of Internal Viscosity",
        "content": "A shorter snippet.",
        "url": shared_url,
    }))

    merged = collapse_duplicates(
        [("arxiv", native), (SEARXNG_SOURCE, metasearch)], SOURCE_ORDER
    )

    assert len(merged) == 1
    # Longest text wins, which is the rule that keeps a re-run stable.
    assert "verbatim" in merged[0].raw_text


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def test_the_source_is_registered_everywhere_a_source_must_be() -> None:
    """A half-added source answers one table and is refused by another."""
    from ontologylab.connectors.allowlist import PAPER_API_SOURCES
    from ontologylab.connectors.paper_api import PAPER_SOURCE_LABELS

    assert SEARXNG_SOURCE in IMPLEMENTED_SOURCES
    assert SEARXNG_SOURCE in PAPER_API_SOURCES
    assert SEARXNG_SOURCE in PAPER_SOURCE_LABELS, "it would render unnamed"


def test_it_sorts_last_so_a_native_connector_wins_a_tie() -> None:
    """`collapse_duplicates` breaks ties on declaration order. The API that
    speaks to one source directly should outrank the aggregator."""
    assert SOURCE_ORDER[-1] == SEARXNG_SOURCE


def test_the_engine_list_names_google_scholar() -> None:
    """The reason this source earns its place: Scholar has no API, so it is
    unreachable any other way."""
    assert "google scholar" in SEARXNG_ENGINES
