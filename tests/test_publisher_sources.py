"""The three keyed publisher sources: Elsevier, Springer Nature, CORE.

Fixtures are built from the published schemas, not from memory:

* Scopus Search answers `search-results.entry[]` with OpenSearch/PRISM
  prefixed keys (`dc:title`, `dc:description`, `prism:doi`), authenticates
  with `X-ELS-APIKey`, and — importantly — omits `dc:description` from its
  STANDARD view unless the fields are requested by name.
  <https://dev.elsevier.com/documentation/ScopusSearchAPI.wadl>
* Springer Nature Meta v2 answers `records[]` with plain keys and a `url`
  list of `{format, platform, value}`; it authenticates with `X-API-Key`.
  <https://dev.springernature.com/docs/quick-start/authentication/>
* CORE v3 `search/works` answers `results[]` with `title`/`abstract`/`doi`/
  `downloadUrl`/`fullTextIdentifier` and a `Bearer` token.
  <https://api.core.ac.uk/docs/v3>

What is NOT claimed here: that a live endpoint returns exactly these bytes.
Without a key that cannot be verified, so every test states the shape it
assumes rather than pretending to have seen a real response.

The security properties, by contrast, are fully testable and are the point:
a key travels in a header and never in a URL, an unconnected source is
refused before a request is built, and nothing quotes the key.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from ontologylab.connectors import paper_api
from ontologylab.connectors.paper_api import (
    CORE_SOURCE,
    ELSEVIER_SOURCE,
    KEYED_SOURCES,
    SOURCE_ORDER,
    SPRINGER_SOURCE,
    MissingSourceKey,
    PaperApiConnector,
    available_sources,
    parse_core,
    parse_elsevier,
    parse_springer,
)
from ontologylab.sources import Source, add_source

KEY = "ELS-key-9f3a-must-stay-in-a-header"

ELSEVIER_FIXTURE = json.dumps({
    "search-results": {
        "opensearch:totalResults": "2",
        "entry": [
            {
                "dc:identifier": "SCOPUS_ID:84940434926",
                "dc:title": "Optical constants of single layer MoS2",
                "dc:description": "We report the optical constants and "
                                  "dynamic conductivities of monolayers.",
                "dc:creator": "Morozov Y.",
                "prism:publicationName": "Applied Physics Letters",
                "prism:doi": "10.1063/1.4929700",
                "prism:url": "https://api.elsevier.com/content/abstract/scopus_id/84940434926",
            },
            {
                "dc:title": "A record with no abstract at all",
                "prism:doi": "10.1000/no-abstract",
            },
        ],
    }
})

SPRINGER_FIXTURE = json.dumps({
    "apiMessage": "This JSON was provided by Springer Nature",
    "records": [
        {
            "identifier": "doi:10.1007/s12345-67890",
            "title": "A study on renewable energy storage",
            "abstract": "This paper explores grid-scale storage options.",
            "publicationName": "Nature Energy",
            "doi": "10.1007/s12345-67890",
            "url": [
                {"format": "", "platform": "web",
                 "value": "https://link.springer.com/article/10.1007/s12345-67890"},
                {"format": "pdf", "platform": "web",
                 "value": "https://link.springer.com/content/pdf/10.1007/s12345-67890.pdf"},
            ],
        }
    ],
})

CORE_FIXTURE = json.dumps({
    "totalHits": 1,
    "limit": 5,
    "results": [
        {
            "title": "Open access aggregation at scale",
            "abstract": "We describe the CORE aggregation pipeline.",
            "doi": "10.1000/core-example",
            "downloadUrl": "https://core.ac.uk/download/pdf/12345.pdf",
            "fullTextIdentifier": "https://core.ac.uk/works/12345",
        }
    ],
})


# --------------------------------------------------------------------------
# Parsers — shape assumed from the published schema
# --------------------------------------------------------------------------


def test_elsevier_reads_the_prism_namespaced_keys() -> None:
    [first, second] = parse_elsevier(ELSEVIER_FIXTURE)

    assert first.title == "Optical constants of single layer MoS2"
    assert "dynamic conductivities" in first.raw_text
    assert first.doi == "10.1063/1.4929700"
    assert first.source_uri == "https://doi.org/10.1063/1.4929700"
    assert second.doi == "10.1000/no-abstract", "title-only records still count"


def test_the_elsevier_url_requests_the_abstract_field_by_name() -> None:
    """Scopus STANDARD view omits `dc:description`.

    Without the explicit field list the parser would work perfectly and
    return nothing but titles — a silent, plausible-looking degradation.
    """
    url = paper_api._build_elsevier_url("knowledge graphs", 5)

    assert "dc%3Adescription" in url or "dc:description" in url


def test_springer_reads_records_and_prefers_the_non_pdf_url() -> None:
    [doc] = parse_springer(SPRINGER_FIXTURE)

    assert doc.title == "A study on renewable energy storage"
    assert "grid-scale storage" in doc.raw_text
    assert doc.doi == "10.1007/s12345-67890"
    assert doc.pdf_url.endswith(".pdf")


def test_springer_survives_an_abstract_that_is_not_a_string() -> None:
    """Structured records nest the abstract under `p`.

    Asserting only that the text appears is not enough: `str({'p': ...})`
    also contains it, so a parser that stringified the dict would pass while
    storing `{'p': 'Nested abstract text.'}` as the document body.
    """
    payload = json.loads(SPRINGER_FIXTURE)
    payload["records"][0]["abstract"] = {"p": "Nested abstract text."}

    [doc] = parse_springer(json.dumps(payload))

    assert "Nested abstract text." in doc.raw_text
    assert "'p'" not in doc.raw_text, "the dict was stringified, not unwrapped"
    assert "{" not in doc.raw_text


def test_springer_falls_back_to_the_article_page_not_the_pdf(tmp_path) -> None:
    """`source_uri` identifies the work; `pdf_url` is where the file is.

    Collapsing them would make the document's identity a file URL, and the
    fixture's DOI hides it — this record deliberately has none.
    """
    payload = json.loads(SPRINGER_FIXTURE)
    del payload["records"][0]["doi"]

    [doc] = parse_springer(json.dumps(payload))

    assert doc.source_uri == (
        "https://link.springer.com/article/10.1007/s12345-67890"
    )
    assert not doc.source_uri.endswith(".pdf")
    assert doc.pdf_url.endswith(".pdf")


def test_an_elsevier_entry_carrying_an_error_is_never_a_document() -> None:
    """Scopus reports an empty search as an `entry` with an `error` key.

    The entry is given a title *and* a URL here on purpose. Without those it
    would be dropped by the "no title, no abstract" and "no source_uri"
    checks anyway, and the test would pass with the `error` guard deleted —
    proving nothing. An entry that says it is an error is not a paper no
    matter what else it carries, and that is the rule being pinned.
    """
    payload = json.dumps({
        "search-results": {
            "entry": [{
                "error": "Result set was empty",
                "dc:title": "Result set was empty",
                "prism:url": "https://api.elsevier.com/content/search/scopus",
            }]
        }
    })

    assert parse_elsevier(payload) == []


def test_core_reads_results_and_keeps_the_download_url() -> None:
    [doc] = parse_core(CORE_FIXTURE)

    assert doc.title == "Open access aggregation at scale"
    assert doc.doi == "10.1000/core-example"
    assert doc.pdf_url == "https://core.ac.uk/download/pdf/12345.pdf"


@pytest.mark.parametrize(
    ("parse", "text"),
    [
        (parse_elsevier, '{"search-results": {}}'),
        (parse_springer, "{}"),
        (parse_core, '{"results": []}'),
        (parse_elsevier, '{"search-results": {"entry": [{"error": "no results"}]}}'),
        (parse_springer, '{"records": [null, 5]}'),
        (parse_core, '{"results": [{"title": ""}]}'),
    ],
)
def test_an_empty_or_odd_response_is_no_documents_not_a_crash(parse, text) -> None:
    assert parse(text) == []


# --------------------------------------------------------------------------
# The key travels in a header and nowhere else
# --------------------------------------------------------------------------


def _connect(tmp_path, monkeypatch, key: str = KEY) -> None:
    """Connect every publisher, each as its own registry row.

    One row per publisher because the row's `id` is what selects the
    credential. An earlier version registered a single `id="journals"` row
    and resolved on `role`, which returned that one key for all three
    vendors — see `test_each_publisher_gets_only_its_own_key`.

    The env path is used deliberately: it exercises the same
    `resolve_source_key` seam as the Keychain without writing to the user's
    real credential store.
    """
    monkeypatch.setenv("TEST_PUBLISHER_KEY", key)
    for name in KEYED_SOURCES:
        add_source(
            tmp_path,
            Source(id=name, role="literature", api_key_env="TEST_PUBLISHER_KEY"),
        )


@pytest.mark.parametrize(
    ("source", "fixture", "header"),
    [
        (ELSEVIER_SOURCE, ELSEVIER_FIXTURE, "X-ELS-APIKey"),
        (SPRINGER_SOURCE, SPRINGER_FIXTURE, "X-API-Key"),
        (CORE_SOURCE, CORE_FIXTURE, "Authorization"),
    ],
)
def test_the_key_goes_in_the_documented_header_never_the_url(
    tmp_path, monkeypatch, source, fixture, header
) -> None:
    """A key in a query string reaches four durable sinks at once.

    The offline-refusal message, `provenance.jsonl`, `status.json`'s
    `last_payload`, and the job log are all written by code that does not
    know a URL might be a secret. Elsevier and Springer both accept a query
    parameter; this is the test that says we do not use it.
    """
    seen = {}

    def _capture(url, headers=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return fixture

    monkeypatch.setattr(paper_api, "_http_get_text", _capture)
    _connect(tmp_path, monkeypatch)

    docs = asyncio.run(PaperApiConnector().fetch(
        {"source": source, "query": "knowledge graphs", "data_dir": tmp_path}
    ))

    assert docs, "the fixture should have parsed"
    assert KEY not in seen["url"], f"the key reached the URL: {seen['url']}"
    assert any(KEY in value for value in seen["headers"].values()), seen["headers"]
    assert header in seen["headers"]


def test_the_header_actually_reaches_the_outgoing_request(monkeypatch) -> None:
    """The test above stubs `_http_get_text`, so it proves the connector
    *computes* the header — not that the header is ever sent.

    This one drives the real `_http_get_text` and inspects the `Request` it
    builds. Without it, deleting the header merge from the request
    construction leaves every other test green.
    """
    captured = {}

    class _Response:
        headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()

        def read(self, _n=None):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    def _fake_urlopen(request, timeout=None):
        captured["headers"] = dict(request.headers)
        captured["url"] = request.full_url
        return _Response()

    monkeypatch.setattr(paper_api, "assert_network_allowed", lambda _m: None)
    monkeypatch.setattr(paper_api, "urlopen", _fake_urlopen)

    paper_api._http_get_text(
        "https://api.elsevier.com/content/search/scopus?query=x",
        {"X-ELS-APIKey": KEY},
    )

    # urllib capitalizes header names, so compare case-insensitively.
    lowered = {k.lower(): v for k, v in captured["headers"].items()}
    assert lowered.get("X-els-apikey".lower()) == KEY, captured["headers"]
    assert "user-agent" in lowered, "the UA must survive alongside the key"
    assert KEY not in captured["url"]


def test_a_keyless_fetch_sends_no_credential_header(monkeypatch) -> None:
    """The keyless five must not grow an empty auth header."""
    captured = {}

    class _Response:
        headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()

        def read(self, _n=None):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    monkeypatch.setattr(paper_api, "assert_network_allowed", lambda _m: None)
    monkeypatch.setattr(
        paper_api, "urlopen",
        lambda request, timeout=None: (
            captured.update(headers=dict(request.headers)) or _Response()
        ),
    )

    paper_api._http_get_text("https://api.crossref.org/works?query=x")

    lowered = {k.lower() for k in captured["headers"]}
    assert lowered == {"user-agent"}, captured["headers"]


def test_an_unconnected_publisher_source_is_refused_before_any_request(
    tmp_path, monkeypatch
) -> None:
    """An anonymous request is a 401 at best and an empty page at worst,
    and either would read as "this source found nothing"."""
    called = []
    monkeypatch.setattr(
        paper_api, "_http_get_text",
        lambda *a, **k: called.append(a) or "{}",
    )

    with pytest.raises(MissingSourceKey):
        asyncio.run(PaperApiConnector().fetch(
            {"source": ELSEVIER_SOURCE, "query": "x", "data_dir": tmp_path}
        ))

    assert not called, "a request was built without a credential"


def test_a_missing_key_is_reported_as_unconfigured_not_a_fetch_failure(
    tmp_path,
) -> None:
    """"Not connected" is a configuration state. Calling it `fetch_failed`
    sends the user looking for a network problem they do not have."""
    _batches, failures = asyncio.run(
        paper_api.fetch_sources([ELSEVIER_SOURCE], "q", 5, tmp_path)
    )

    assert [f.kind for f in failures] == ["unconfigured"]


def test_the_refusal_message_does_not_quote_the_key(tmp_path, monkeypatch) -> None:
    """`SourceFailure.error` reaches provenance, and the summary reaches the
    browser; neither may carry a credential."""
    _connect(tmp_path, monkeypatch)
    monkeypatch.setattr(
        paper_api, "_http_get_text",
        lambda *a, **k: (_ for _ in ()).throw(OSError(f"HTTP 401 with {KEY}")),
    )

    _batches, failures = asyncio.run(
        paper_api.fetch_sources([ELSEVIER_SOURCE], "q", 5, tmp_path)
    )

    # The connector's own message must be clean. (The exception text here is
    # the fake's, and `jobs.summarize_failure` is what redacts it on the way
    # to the browser — covered in test_error_disclosure.py.)
    assert failures
    assert failures[0].kind == "fetch_failed"
    # `SourceFailure.error` is written verbatim into provenance.jsonl and
    # mirrored into status.json — asserting only `kind` left the field that
    # actually carries text unchecked, so a connector that interpolated the
    # request URL into its message would have passed.
    assert KEY not in failures[0].error


def test_each_publisher_gets_only_its_own_key(tmp_path, monkeypatch) -> None:
    """The credential is selected by source id, never by role.

    Resolving on `role` returned the first literature row's key for every
    publisher, so connecting Springer put the Springer key into Elsevier's
    `X-ELS-APIKey` header and CORE's bearer token — a live credential handed
    to two other vendors, which is exactly the harm the redirect guard was
    written to stop.
    """
    keys = {name: f"KEY-FOR-{name.upper()}" for name in KEYED_SOURCES}
    for name, value in keys.items():
        monkeypatch.setenv(f"TEST_KEY_{name.upper()}", value)
        add_source(
            tmp_path,
            Source(id=name, role="literature",
                   api_key_env=f"TEST_KEY_{name.upper()}"),
        )

    for name, expected in keys.items():
        resolved = paper_api.resolve_source_key(name, tmp_path)
        assert resolved == expected, f"{name} resolved to another vendor's key"
        for other, other_key in keys.items():
            if other != name:
                assert resolved != other_key


def test_a_publisher_with_no_row_of_its_own_stays_disconnected(
    tmp_path, monkeypatch
) -> None:
    """Connecting one publisher must not silently enable the other two."""
    monkeypatch.setenv("TEST_KEY_ELSEVIER", "ELS-only")
    add_source(
        tmp_path,
        Source(id=ELSEVIER_SOURCE, role="literature",
               api_key_env="TEST_KEY_ELSEVIER"),
    )

    assert paper_api.resolve_source_key(ELSEVIER_SOURCE, tmp_path) == "ELS-only"
    assert paper_api.resolve_source_key(SPRINGER_SOURCE, tmp_path) == ""
    assert paper_api.resolve_source_key(CORE_SOURCE, tmp_path) == ""
    assert SPRINGER_SOURCE not in available_sources(tmp_path)


# --------------------------------------------------------------------------
# Which sources a run queries
# --------------------------------------------------------------------------


def test_collecting_from_an_unconnected_publisher_is_a_typed_refusal(
    tmp_path,
) -> None:
    """`/api/collect` promises 200 with an `error_kind`, never a 5xx.

    `MissingSourceKey` matched none of the route's handlers, so picking a
    publisher you have not connected — the ordinary first-use path, which
    both allowlist gates pass — answered 500 Internal Server Error.
    """
    from fastapi.testclient import TestClient

    from ontologylab.server import routes
    from ontologylab.server.app import create_app

    data_dir = tmp_path / "data"
    client = TestClient(create_app(data_dir=data_dir))

    response = client.post(
        "/api/collect",
        json={"paper_queries": ["knowledge graphs"], "paper_source": ELSEVIER_SOURCE},
    )

    assert response.status_code == 200, "the route must never 500"
    body = response.json()
    assert body["ok"] is False
    assert body["error_kind"] == "unconfigured"


def test_an_oversized_publisher_response_is_a_typed_refusal(
    tmp_path, monkeypatch
) -> None:
    """`ResponseTooLarge` was the other escapee from the same handler list."""
    from fastapi.testclient import TestClient

    from ontologylab.connectors.paper_api import ResponseTooLarge
    from ontologylab.server import routes
    from ontologylab.server.app import create_app

    data_dir = tmp_path / "data"
    _connect(data_dir, monkeypatch)
    monkeypatch.setattr(
        paper_api, "_http_get_text",
        lambda *a, **k: (_ for _ in ()).throw(ResponseTooLarge("too big")),
    )
    client = TestClient(create_app(data_dir=data_dir))

    response = client.post(
        "/api/collect",
        json={"paper_queries": ["q"], "paper_source": ELSEVIER_SOURCE},
    )

    assert response.status_code == 200
    assert response.json()["error_kind"] == "too_large"


def test_an_unconnected_publisher_is_not_queried_by_default(tmp_path) -> None:
    """Three permanent `unconfigured` rows on every run would be noise for a
    feature the user has not opted into."""
    assert available_sources(tmp_path) == [
        "arxiv", "crossref", "openalex", "semanticscholar", "europepmc",
        "clinicaltrials",
    ]


def test_a_connected_publisher_joins_the_default_set(tmp_path, monkeypatch) -> None:
    _connect(tmp_path, monkeypatch)

    # Every keyed source joins once connected. SearXNG does not: it is not
    # unlocked by a credential but by an address, which this test does not
    # set.
    from ontologylab.connectors.paper_api import SEARXNG_SOURCE

    assert set(available_sources(tmp_path)) == set(SOURCE_ORDER) - {
        SEARXNG_SOURCE
    }


def test_the_keyed_set_is_derived_from_the_auth_table() -> None:
    """A source added to the dispatch table but not to `_SOURCE_AUTH` would
    otherwise be queried anonymously, silently."""
    assert KEYED_SOURCES == frozenset(paper_api._SOURCE_AUTH)
    assert KEYED_SOURCES <= set(SOURCE_ORDER)
    assert KEYED_SOURCES == {ELSEVIER_SOURCE, SPRINGER_SOURCE, CORE_SOURCE}


def test_every_keyed_source_has_a_header_builder_and_a_parser() -> None:
    for name in KEYED_SOURCES:
        assert name in paper_api._SOURCE_DISPATCH
        headers = paper_api._SOURCE_AUTH[name]("SAMPLE")
        assert any("SAMPLE" in value for value in headers.values())
        assert all(isinstance(value, str) for value in headers.values())


def test_no_builder_puts_the_key_in_the_url_by_construction() -> None:
    """The builders take (query, limit) only, so a key cannot reach a URL
    even by mistake — this pins that signature."""
    import inspect

    for name in KEYED_SOURCES:
        build, _parse = paper_api._SOURCE_DISPATCH[name]
        params = list(inspect.signature(build).parameters)
        assert params == ["query", "limit"], f"{name}: {params}"


def test_every_publisher_host_is_on_the_redirect_allowlist() -> None:
    """C2's guard has to cover the hosts that will carry a key."""
    for url in (paper_api.ELSEVIER_API_URL, paper_api.SPRINGER_API_URL,
                paper_api.CORE_API_URL):
        assert paper_api.check_paper_host(url) == url


def test_the_publisher_endpoints_are_https() -> None:
    for url in (paper_api.ELSEVIER_API_URL, paper_api.SPRINGER_API_URL,
                paper_api.CORE_API_URL):
        assert url.startswith("https://")


def test_a_publisher_query_is_percent_encoded_like_the_others(tmp_path) -> None:
    """M3's contract test covers `_SOURCE_DISPATCH`, so these are already
    included — this states the expectation locally for the keyed three."""
    for name in KEYED_SOURCES:
        build, _parse = paper_api._SOURCE_DISPATCH[name]
        url = build("x&injected=1 y#z/../", 5)
        assert "&injected=1" not in url
        assert "#z" not in url
        assert "/../" not in url
