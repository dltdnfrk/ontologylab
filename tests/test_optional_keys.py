"""Sources that work without a key, and work better with one.

Two categories existed: keyless, and keyed-or-refuse. Neither fit OpenAlex
or Semantic Scholar, which answer anonymously from a pool shared with every
other anonymous client — and both were measured returning `429 Too Many
Requests` on an ordinary query from an unconfigured install, which is
exactly the "did not answer (fetch_failed)" pair a live research run
produced. Filing them as keyed would hide them from a fresh install;
leaving them keyless leaves two of eight sources rate-limited.

The security question this raises is the interesting one. This module's
rule is that credentials travel in headers, because a URL reaches the
offline-refusal message, `provenance.jsonl`, `status.json` and the job log.
OpenAlex documents no header form — only `api_key=`. So the exception is
contained rather than waived: the key is spliced on inside
`_http_get_text`, after every string that could be logged has already been
built. These tests hold that line.
"""

from __future__ import annotations

import asyncio

import pytest

from ontologylab.connectors import paper_api
from ontologylab.connectors.paper_api import (
    CONNECTABLE_SOURCES,
    KEYED_SOURCES,
    OPENALEX_SOURCE,
    OPTIONAL_KEY_SOURCES,
    SEMANTIC_SCHOLAR_SOURCE,
    SOURCE_ORDER,
    _with_query_key,
    available_sources,
    fetch_sources,
    resolve_source_key,
)
from ontologylab.sources import Source, add_source

SECRET = "KEY-must-never-be-logged-9f3a"


def _connect(tmp_path, source_id, monkeypatch, key=SECRET):
    env = f"TEST_KEY_{source_id.upper()}"
    monkeypatch.setenv(env, key)
    add_source(tmp_path, Source(id=source_id, role="literature", api_key_env=env))


def _capture_wire(monkeypatch):
    """Record the `Request` that would have gone out.

    Deliberately patched at `urlopen` rather than at `_http_get_text`: the
    question these tests ask is what reaches the network and what reaches a
    log, and those two differ by exactly one splice inside `_http_get_text`.
    Patching above it would hide the thing under test.
    """
    sent = []

    def _fake_urlopen(request, timeout=None):
        sent.append(request)
        raise AssertionError("stop here — the request is all we need")

    monkeypatch.setattr(paper_api, "urlopen", _fake_urlopen)
    return sent


def _capture_fetch_arg(monkeypatch):
    """Record the URL string `_http_get_text` is handed."""
    seen = []

    def _fake(url, headers=None, query_key=None):
        seen.append({"url": url, "headers": dict(headers or {}), "key": query_key})
        raise RuntimeError(f"HTTP 500 while fetching {url}")

    monkeypatch.setattr(paper_api, "_http_get_text", _fake)
    return seen


# --------------------------------------------------------------------------
# The categories
# --------------------------------------------------------------------------


def test_the_three_categories_do_not_overlap() -> None:
    """A source refuses without a key, or prefers one, or takes none. Not two."""
    assert not (KEYED_SOURCES & OPTIONAL_KEY_SOURCES)
    assert CONNECTABLE_SOURCES == KEYED_SOURCES | OPTIONAL_KEY_SOURCES
    assert CONNECTABLE_SOURCES <= set(SOURCE_ORDER)


def test_the_rate_limited_pair_is_the_optional_set() -> None:
    """Named rather than inferred: these are the two that measured 429."""
    assert OPTIONAL_KEY_SOURCES == {OPENALEX_SOURCE, SEMANTIC_SCHOLAR_SOURCE}


def test_an_optional_source_stays_available_with_no_key(tmp_path) -> None:
    """The whole point of the third category.

    Filed as keyed, these would vanish from a fresh install's source list —
    a rate limit is not the same as "not configured".
    """
    usable = available_sources(tmp_path)

    assert OPENALEX_SOURCE in usable
    assert SEMANTIC_SCHOLAR_SOURCE in usable
    for keyed in KEYED_SOURCES:
        assert keyed not in usable, "a publisher source needs its key first"


def test_an_optional_key_resolves_like_a_publisher_key(
    tmp_path, monkeypatch
) -> None:
    _connect(tmp_path, SEMANTIC_SCHOLAR_SOURCE, monkeypatch)

    assert resolve_source_key(SEMANTIC_SCHOLAR_SOURCE, tmp_path) == SECRET
    assert resolve_source_key(OPENALEX_SOURCE, tmp_path) == ""


# --------------------------------------------------------------------------
# Each key travels by the mechanism its API documents
# --------------------------------------------------------------------------


def test_semantic_scholar_sends_its_key_as_a_header(tmp_path, monkeypatch) -> None:
    """`x-api-key`, quoted from Semantic Scholar's own tutorial."""
    _connect(tmp_path, SEMANTIC_SCHOLAR_SOURCE, monkeypatch)
    sent = _capture_wire(monkeypatch)

    asyncio.run(fetch_sources([SEMANTIC_SCHOLAR_SOURCE], "crispr", 3, tmp_path))

    [request] = sent
    assert request.get_header("X-api-key") == SECRET
    assert SECRET not in request.full_url, "a header key must not also enter the URL"


def test_openalex_sends_its_key_as_a_query_parameter(tmp_path, monkeypatch) -> None:
    """OpenAlex documents `api_key=` and no header form.

    Asserted explicitly so that if they ever ship a header, this test fails
    and the exception can be retired rather than quietly outliving its
    reason.
    """
    _connect(tmp_path, OPENALEX_SOURCE, monkeypatch)
    sent = _capture_wire(monkeypatch)

    asyncio.run(fetch_sources([OPENALEX_SOURCE], "crispr", 3, tmp_path))

    [request] = sent
    assert f"api_key={SECRET}" in request.full_url
    assert request.get_header("Api-key") is None, "OpenAlex takes no credential header"


def test_no_key_means_an_anonymous_request_not_a_refusal(
    tmp_path, monkeypatch
) -> None:
    """A publisher source refuses; these just go without."""
    sent = _capture_wire(monkeypatch)

    _batches, failures = asyncio.run(
        fetch_sources(list(OPTIONAL_KEY_SOURCES), "crispr", 3, tmp_path)
    )

    assert len(sent) == 2, "both were still attempted"
    for request in sent:
        assert "api_key=" not in request.full_url
        assert request.get_header("X-api-key") is None
    # They failed here only because the fake raises — never `unconfigured`.
    assert {f.kind for f in failures} == {"fetch_failed"}


# --------------------------------------------------------------------------
# The containment: a query-param key must not reach anything that is logged
# --------------------------------------------------------------------------


def test_the_builder_returns_a_url_without_the_key(tmp_path, monkeypatch) -> None:
    """The URL the builder hands back is keyless."""
    _connect(tmp_path, OPENALEX_SOURCE, monkeypatch)
    build, _parse = paper_api._SOURCE_DISPATCH[OPENALEX_SOURCE]

    assert SECRET not in build("crispr", 3)
    assert "api_key" not in build("crispr", 3)


def test_the_fetcher_is_handed_a_keyless_url_and_the_key_beside_it(
    tmp_path, monkeypatch
) -> None:
    """Where the containment actually lives.

    The credential travels as an argument, not inside the string. So every
    stand-in for the fetcher — a test double, a retry wrapper, a logging
    decorator, whatever gets added later — receives a URL it can safely
    print.
    """
    _connect(tmp_path, OPENALEX_SOURCE, monkeypatch)
    seen = _capture_fetch_arg(monkeypatch)

    asyncio.run(fetch_sources([OPENALEX_SOURCE], "crispr", 3, tmp_path))

    [call] = seen
    assert SECRET not in call["url"]
    assert call["key"] == ("api_key", SECRET), "handed over as data, not text"


def test_a_failure_message_is_clean_with_redaction_switched_off(
    tmp_path, monkeypatch
) -> None:
    """The difference between "by construction" and "by redaction".

    `redact_keys` scrubs the value afterwards and would mask a leak here, so
    it is neutralised: what survives is the construction alone. This is the
    test that fails if the splice ever moves back upstream — the earlier
    version of this code passed only because the redactor caught it.
    """
    _connect(tmp_path, OPENALEX_SOURCE, monkeypatch)
    monkeypatch.setattr(paper_api, "redact_keys", lambda text, data_dir=None: text)

    def _boom(url, headers=None, query_key=None):
        # The worst realistic case: an error that quotes the URL it was given.
        raise RuntimeError(f"HTTP 429 from {url}")

    monkeypatch.setattr(paper_api, "_http_get_text", _boom)

    _batches, failures = asyncio.run(
        fetch_sources([OPENALEX_SOURCE], "crispr", 3, tmp_path)
    )

    assert failures
    assert SECRET not in failures[0].error, "the key reached the provenance log"


def test_redaction_still_covers_what_construction_cannot(
    tmp_path, monkeypatch
) -> None:
    """The wire URL does hold the key, and `HTTPError.url` is the wire URL.

    Construction protects every string this module builds; it cannot
    protect a string urllib builds from the request it was given. That
    residual case is exactly what the redactor is for, so it is pinned
    rather than left as an assumption.
    """
    _connect(tmp_path, OPENALEX_SOURCE, monkeypatch)
    wire = f"https://api.openalex.org/works?search=x&api_key={SECRET}"

    scrubbed = paper_api.redact_keys(f"HTTP Error 429 for url: {wire}", tmp_path)

    assert SECRET not in scrubbed
    assert paper_api.REDACTED in scrubbed


def test_redaction_covers_optional_keys_too(tmp_path, monkeypatch) -> None:
    """And it covers the header-borne optional key just the same."""
    _connect(tmp_path, SEMANTIC_SCHOLAR_SOURCE, monkeypatch)

    scrubbed = paper_api.redact_keys(f"boom: {SECRET} happened", tmp_path)

    assert SECRET not in scrubbed
    assert paper_api.REDACTED in scrubbed


@pytest.mark.parametrize(
    ("url", "expected_separator"),
    [
        ("https://api.openalex.org/works?search=x", "&"),
        ("https://api.openalex.org/works", "?"),
    ],
)
def test_the_key_is_appended_with_the_right_separator(url, expected_separator):
    result = _with_query_key(url, "api_key", "abc")

    assert result == f"{url}{expected_separator}api_key=abc"


def test_a_key_needing_escaping_is_encoded() -> None:
    """A raw `&` would split one parameter into two and silently truncate."""
    result = _with_query_key("https://x/y?a=1", "api_key", "a&b=c d")

    assert "a%26b%3Dc+d" in result
    assert result.count("&") == 1


# --------------------------------------------------------------------------
# Through the endpoint the settings screen reads
# --------------------------------------------------------------------------


def test_the_endpoint_marks_optional_sources_connectable_but_not_keyed(
    tmp_path,
) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server import routes
    from ontologylab.server.app import create_app

    data_dir = tmp_path / "data"
    client = TestClient(create_app(data_dir=data_dir))

    by_id = {
        item["id"]: item
        for item in client.get("/api/paper-sources").json()["sources"]
    }

    for name in OPTIONAL_KEY_SOURCES:
        assert by_id[name]["connectable"] is True
        assert by_id[name]["keyed"] is False
        assert by_id[name]["available"] is True, "usable without a key"
    for name in KEYED_SOURCES:
        assert by_id[name]["connectable"] is True
        assert by_id[name]["keyed"] is True
        assert by_id[name]["available"] is False


def test_a_key_filed_under_an_unknown_name_is_never_used(
    tmp_path, monkeypatch
) -> None:
    """The failure the settings screen used to invite.

    Keys resolve on the source **id**, so a key stored under any other name
    is written to the Keychain and then read by nothing — no error, no
    warning, and a research run that keeps hitting the anonymous rate limit
    while the screen says a key is connected. The form's free-text field
    defaulted to `journals`, which is precisely such a name; it is a
    fixed-choice list now, and this is what makes that necessary rather
    than tidy.
    """
    _connect(tmp_path, "journals", monkeypatch)

    assert resolve_source_key("journals", tmp_path) == ""
    assert resolve_source_key(OPENALEX_SOURCE, tmp_path) == ""
    assert resolve_source_key(SEMANTIC_SCHOLAR_SOURCE, tmp_path) == ""


def test_the_form_offers_the_connectable_sources_and_no_free_text() -> None:
    """Guards the fix above at the only place a user can reach it.

    There is no JS test harness here, so this checks the one structural
    property that keeps the trap shut: the source is chosen from a list.
    """
    import re

    from ontologylab.server.app import WEB_DIR

    markup = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    # The rule is "chosen from a list", not one exact spelling of the tag —
    # an earlier version matched `<select id="source-id">` literally and
    # broke the moment the element gained an aria-label, which changes
    # nothing about the rule.
    assert re.search(r'<select[^>]*\bid="source-id"', markup)
    assert not re.search(r'<input[^>]*\bid="source-id"', markup), \
        "a free-text name would let a key be filed where nothing reads it"


def test_the_endpoint_never_returns_a_key_value(tmp_path, monkeypatch) -> None:
    """`key_present` is a boolean for the same reason providers are."""
    import json

    from fastapi.testclient import TestClient

    from ontologylab.server import routes
    from ontologylab.server.app import create_app

    data_dir = tmp_path / "data"
    _connect(data_dir, OPENALEX_SOURCE, monkeypatch)
    client = TestClient(create_app(data_dir=data_dir))

    body = client.get("/api/paper-sources").json()

    assert SECRET not in json.dumps(body)
    by_id = {item["id"]: item for item in body["sources"]}
    assert by_id[OPENALEX_SOURCE]["key_present"] is True
    assert by_id[SEMANTIC_SCHOLAR_SOURCE]["key_present"] is False
