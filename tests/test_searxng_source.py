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


# --------------------------------------------------------------------------
# Configuration, where a person can see it
# --------------------------------------------------------------------------


def test_the_saved_setting_reaches_the_connector(monkeypatch) -> None:
    """The address is a setting, not only a variable — but the connector
    never reads settings itself.

    `connectors` importing `server.settings` inverts the dependency and
    makes every source lookup read a machine-global file; saving the
    address once in the browser was enough to change what unrelated tests
    saw. `apply_to_environment` is the one explicit bridge.
    """
    from ontologylab.server import settings as settings_mod
    from ontologylab.server.schemas import Settings

    monkeypatch.delenv(SEARXNG_URL_ENV, raising=False)
    assert SEARXNG_SOURCE not in available_sources(), "not yet applied"

    # Through monkeypatch's own environ, so the export does not outlive the
    # test. `apply_to_environment` writes real process state — the bridge
    # working is exactly why it has to be undone here.
    monkeypatch.setattr(
        settings_mod.os, "environ", dict(settings_mod.os.environ),
        raising=True,
    )
    settings_mod.apply_to_environment(
        Settings(searxng_url="http://10.0.0.9:8080")
    )

    assert settings_mod.os.environ[SEARXNG_URL_ENV] == "http://10.0.0.9:8080"


def test_the_connector_does_not_read_settings_itself() -> None:
    """The layering this file had to be walked back to.

    server -> connectors is the direction everywhere else, and reversing it
    is what made an unrelated test's result depend on whether the developer
    happens to run a SearXNG.
    """
    import inspect

    from ontologylab.connectors import paper_api

    source = inspect.getsource(paper_api._searxng_base_url)

    assert "load_settings" not in source
    assert "os.environ" in source


def test_the_environment_variable_overrides_the_setting(monkeypatch) -> None:
    """One process departing from the durable default — the same shape as
    ONTOLOGYLAB_OFFLINE overriding everything else."""
    from ontologylab.server import settings as settings_mod
    from ontologylab.server.schemas import Settings

    monkeypatch.setattr(
        settings_mod, "load_settings",
        lambda *a, **k: Settings(searxng_url="http://10.0.0.9:8080"),
        raising=True,
    )
    monkeypatch.setenv(SEARXNG_URL_ENV, "http://localhost:8080")

    assert "localhost:8080" in _build_searxng_url("q", 5)


def test_unreadable_settings_do_not_stop_a_fetch(monkeypatch) -> None:
    """The CLI runs with no server, and a corrupt settings file already
    degrades to defaults everywhere else."""
    from ontologylab.server import settings as settings_mod

    def boom(*a, **k):
        raise OSError("settings.json is a directory")

    monkeypatch.setattr(settings_mod, "load_settings", boom, raising=True)
    monkeypatch.setenv(SEARXNG_URL_ENV, "http://localhost:8080")

    assert "localhost:8080" in _build_searxng_url("q", 5)


@pytest.fixture()
def settings_client(tmp_path, monkeypatch):
    """A client whose settings writes land in tmp_path.

    `put_settings` calls `save_settings(new_settings)` with no root, so it
    writes under `paths.ROOT` — the repository's own data directory, not
    the app's. A test that skipped this fixture would edit the developer's
    real settings.json, which is exactly what happened when this file first
    exercised the route.
    """
    import os

    from fastapi.testclient import TestClient

    from ontologylab.server import settings as settings_mod
    from ontologylab.server.app import create_app

    saved: dict = {}
    monkeypatch.setattr(
        settings_mod, "save_settings",
        lambda s, root=None: saved.setdefault("value", s) or s,
        raising=True,
    )
    # `put_settings` also exports the address so it takes effect without a
    # restart. That write outlives the test — it is process state, not a
    # file — and left in place it told every later test that this machine
    # has a SearXNG configured.
    monkeypatch.setattr(
        settings_mod, "apply_to_environment", lambda s: None, raising=True
    )
    os.environ.setdefault("ONTOLOGYLAB_ALLOWED_HOSTS", "testserver")
    return TestClient(create_app(data_dir=tmp_path / "data"))


def test_a_public_address_is_refused_when_it_is_typed(settings_client) -> None:
    """Not thirty seconds into a research run, as one refused source among
    six. The gate is the same; the message moves to where the value came
    from."""
    response = settings_client.put("/api/settings", json={
        "default_engine": "mock", "searxng_url": "https://searx.be",
    })

    assert response.status_code == 400
    assert "loopback or private" in response.json()["detail"]


def test_a_local_address_is_accepted(settings_client) -> None:
    saved = settings_client.put("/api/settings", json={
        "default_engine": "mock", "searxng_url": "http://localhost:8080",
    })

    assert saved.status_code == 200
    assert saved.json()["searxng_url"] == "http://localhost:8080"


# --------------------------------------------------------------------------
# The misconfiguration everyone hits first
# --------------------------------------------------------------------------


def test_json_disabled_is_its_own_failure_not_a_network_one() -> None:
    """Measured against a stock instance: `403` with an HTML body.

    Reported as `fetch_failed` it reads as "the network is down", and the
    network is fine — so the user goes looking for a problem they do not
    have instead of adding one line to settings.yml.
    """
    from urllib.error import HTTPError

    from ontologylab.connectors.paper_api import SearxngJsonDisabled, _classify

    assert _classify(SearxngJsonDisabled("x")) == "no_json"
    # And an ordinary HTTP failure is still an ordinary HTTP failure.
    assert _classify(HTTPError("u", 500, "m", {}, None)) == "fetch_failed"


def test_the_no_json_failure_says_what_to_change() -> None:
    """An error naming a cause the reader cannot act on is only slightly
    better than one naming no cause at all."""
    import asyncio
    from urllib.error import HTTPError

    from ontologylab.connectors import paper_api

    connector = paper_api.PaperApiConnector()

    def refuse(url, *a, **k):
        raise HTTPError(url, 403, "Forbidden", {}, None)

    original = paper_api._http_get_text
    paper_api._http_get_text = refuse
    try:
        with pytest.raises(paper_api.SearxngJsonDisabled) as caught:
            asyncio.run(connector._fetch_searxng("http://localhost:8080/s", 5,
                                                 parse_searxng))
    finally:
        paper_api._http_get_text = original

    message = str(caught.value)
    assert "search.formats" in message
    assert "json" in message


def test_the_browser_names_the_json_failure_too() -> None:
    """A kind the browser has no word for renders as the raw string."""
    from pathlib import Path

    source = Path("web/app.js").read_text(encoding="utf-8")
    fail_map = source.split("var FAIL_KO = {", 1)[1].split("};", 1)[0]

    assert "no_json" in fail_map


def test_every_source_has_a_name_the_trace_can_show() -> None:
    """A tool with no entry renders as its bare id.

    Caught on screen: the fan-out row read `searxng 조회 5` next to
    `Europe PMC 조회 5`, because the trace's label map had been written
    from the default fan-out and never revisited when sources were added.
    """
    from pathlib import Path

    from ontologylab.connectors.paper_api import SOURCE_ORDER

    source = Path("web/app.js").read_text(encoding="utf-8")
    tool_map = source.split("var TOOL_KO = {", 1)[1].split("};", 1)[0]

    missing = [name for name in SOURCE_ORDER if f"{name}:" not in tool_map]
    assert not missing, f"the trace would show raw ids for: {missing}"
