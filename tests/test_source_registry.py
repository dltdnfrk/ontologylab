"""The paper-source list has one home, and every builder encodes its query.

`_SOURCE_DISPATCH` is the registry: a source exists exactly when it has a URL
builder and a parser. Everything else — `IMPLEMENTED_SOURCES`, the network
allowlist, the browser's picker — must follow it or be caught here.

The encoding tests iterate the registry rather than naming sources, so a
sixth source is covered the moment it is added. That is the point: the five
shipped builders were audited by hand once, and the risk is the next one.
"""

from __future__ import annotations

import pytest

from ontologylab.connectors.allowlist import PAPER_API_SOURCES
from ontologylab.connectors.paper_api import (
    _SOURCE_DISPATCH,
    DEFAULT_PAPER_SOURCE,
    IMPLEMENTED_SOURCES,
    PAPER_SOURCE_LABELS,
    SOURCE_ORDER,
)

# --------------------------------------------------------------------------
# One registry, and everything that has to agree with it
# --------------------------------------------------------------------------


def test_implemented_sources_is_exactly_the_dispatch_table() -> None:
    """A source that cannot be fetched must not claim to be implemented."""
    assert IMPLEMENTED_SOURCES == frozenset(_SOURCE_DISPATCH)


def test_the_network_allowlist_and_the_registry_agree() -> None:
    """`allowlist` cannot import `paper_api` (that direction is taken), so
    the two lists are separate objects. This is what catches their drift:
    a source that is fetchable but not allowlisted is dead code, and one
    that is allowlisted but not fetchable is a 500 waiting to happen.
    """
    assert set(IMPLEMENTED_SOURCES) == set(PAPER_API_SOURCES)


def test_every_source_has_a_display_label() -> None:
    assert set(PAPER_SOURCE_LABELS) == set(IMPLEMENTED_SOURCES)


def test_source_order_is_the_declaration_order_without_gaps() -> None:
    assert SOURCE_ORDER == tuple(_SOURCE_DISPATCH)
    assert set(SOURCE_ORDER) == set(IMPLEMENTED_SOURCES)
    assert len(SOURCE_ORDER) == len(set(SOURCE_ORDER))


def test_the_default_source_is_one_this_build_can_fetch() -> None:
    assert DEFAULT_PAPER_SOURCE in IMPLEMENTED_SOURCES


def test_every_source_has_both_a_builder_and_a_parser() -> None:
    for source, pair in _SOURCE_DISPATCH.items():
        build, parse = pair
        assert callable(build), f"{source} has no URL builder"
        assert callable(parse), f"{source} has no parser"


# --------------------------------------------------------------------------
# M3: query encoding, as a contract over the registry
# --------------------------------------------------------------------------

# Each fragment would change the request if it survived unencoded: a second
# parameter, a fragment that truncates the query string, a path escape, or a
# separator that splits one value into two.
INJECTIONS = (
    "x&injected=1",
    "x#fragment",
    "x/../../etc/passwd",
    "x?rows=9999",
    "x=y",
    "a b",
)


@pytest.mark.parametrize("source", sorted(_SOURCE_DISPATCH))
@pytest.mark.parametrize("payload", INJECTIONS)
def test_every_builder_encodes_the_query(source: str, payload: str) -> None:
    build, _ = _SOURCE_DISPATCH[source]

    url = build(payload, 5)

    query_part = url.split("?", 1)[1] if "?" in url else url
    assert "&injected=1" not in query_part
    assert "#fragment" not in url
    assert "../" not in url
    assert "?rows=9999" not in query_part.replace("?", "", 1)
    # A raw space would make the URL unusable rather than dangerous, but it
    # is the same failure to encode.
    assert " " not in url


@pytest.mark.parametrize("source", sorted(_SOURCE_DISPATCH))
def test_every_builder_keeps_the_query_inside_one_parameter(source: str) -> None:
    """The query must never become part of the host, scheme or path."""
    from urllib.parse import urlparse

    build, _ = _SOURCE_DISPATCH[source]

    parsed = urlparse(build("evil.example/path", 5))

    assert parsed.scheme == "https"
    assert "evil.example" not in (parsed.hostname or "")
    assert "evil.example" not in parsed.path


@pytest.mark.parametrize("source", sorted(_SOURCE_DISPATCH))
def test_every_builder_produces_an_https_url(source: str) -> None:
    from urllib.parse import urlparse

    build, _ = _SOURCE_DISPATCH[source]

    assert urlparse(build("cell adhesion", 5)).scheme == "https"


# --------------------------------------------------------------------------
# The browser renders from the API, so the endpoint is part of the contract
# --------------------------------------------------------------------------


def test_the_endpoint_offers_exactly_the_implemented_sources(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    client = TestClient(create_app(data_dir=tmp_path / "data"))

    body = client.get("/api/paper-sources").json()

    assert [item["id"] for item in body["sources"]] == list(SOURCE_ORDER)
    assert body["default"] == DEFAULT_PAPER_SOURCE
    assert all(item["label"] for item in body["sources"])


def test_a_publisher_source_is_listed_but_marked_unavailable(tmp_path) -> None:
    """It is implemented, so hiding it would hide that connecting a key
    unlocks it — but offering it as an ordinary choice hands the user a
    guaranteed failure. So: listed, flagged, and disabled in the picker.
    """
    from fastapi.testclient import TestClient

    from ontologylab.connectors.paper_api import KEYED_SOURCES
    from ontologylab.server.app import create_app

    client = TestClient(create_app(data_dir=tmp_path / "data"))

    body = client.get("/api/paper-sources").json()

    by_id = {item["id"]: item for item in body["sources"]}
    for name in KEYED_SOURCES:
        assert by_id[name]["keyed"] is True
        assert by_id[name]["available"] is False, "no key is connected here"
    for name in set(SOURCE_ORDER) - KEYED_SOURCES:
        assert by_id[name]["keyed"] is False
        assert by_id[name]["available"] is True


def test_a_connected_publisher_becomes_available(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app
    from ontologylab.sources import Source, add_source

    data_dir = tmp_path / "data"
    monkeypatch.setenv("TEST_PUB_KEY", "a-key")
    for name in ("elsevier", "springer", "core"):
        add_source(data_dir, Source(id=name, role="literature",
                                    api_key_env="TEST_PUB_KEY"))
    client = TestClient(create_app(data_dir=data_dir))

    body = client.get("/api/paper-sources").json()

    assert all(item["available"] for item in body["sources"])
