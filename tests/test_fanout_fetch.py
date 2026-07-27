"""Fan-out: five sources at once, and one failure must not discard the rest.

Two things were wrong before. `PaperApiConnector.fetch` was `async` in name
only — no `await`, a blocking `urlopen` inside — so gathering five sources ran
them serially, up to five 30-second timeouts back to back. And a single
failure took the whole run with it, which matters because Semantic Scholar
rate-limits unauthenticated clients aggressively: one 429 discarded the other
four sources' results.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from ontologylab.connectors import paper_api
from ontologylab.connectors.allowlist import NotAllowlisted
from ontologylab.connectors.paper_api import (
    SOURCE_ORDER,
    available_sources,
    PaperApiConnector,
    ResponseTooLarge,
    fetch_sources,
)
from ontologylab.paths import NetworkBlocked

CROSSREF_BODY = """{"message": {"items": [
  {"DOI": "10.1/a", "URL": "https://doi.org/10.1/a",
   "title": ["A"], "abstract": "Body A"}]}}"""


# These tests connect no publisher key, so the set under test is
# whatever a run could query without one — the keyless five. Using
# SOURCE_ORDER instead would add three `unconfigured` failures to
# every assertion and test the absence of a key rather than the fan-out.
KEYLESS = available_sources()


def _atom(entry_id: str = "https://arxiv.org/abs/2401.1") -> str:
    return f"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>T</title><summary>S</summary><id>{entry_id}</id></entry>
    </feed>"""


# Each source has its own response shape; handing them all one body would make
# four of five fail to parse and quietly turn a fan-out test into a
# partial-failure test.
_BODIES = {
    "arxiv": _atom(),
    "crossref": CROSSREF_BODY,
    "openalex": """{"results": [{"doi": "https://doi.org/10.1/b",
      "id": "https://openalex.org/W1", "display_name": "B",
      "abstract_inverted_index": {"Body": [0]}}]}""",
    "semanticscholar": """{"data": [{"title": "C", "abstract": "Body C",
      "url": "https://www.semanticscholar.org/paper/c",
      "externalIds": {"DOI": "10.1/c"}}]}""",
    "europepmc": """{"resultList": {"result": [{"title": "D",
      "abstractText": "Body D", "doi": "10.1/d", "source": "MED", "id": "1"}]}}""",
    "clinicaltrials": """{"studies": [{"protocolSection": {
      "identificationModule": {"nctId": "NCT1", "briefTitle": "E"},
      "descriptionModule": {"briefSummary": "Body E"}}}]}""",
}


# Built from the endpoint constants themselves, so a changed URL surfaces as
# a missing fixture rather than a body silently served to the wrong parser.
_HOSTS = {
    paper_api.ARXIV_API_URL: "arxiv",
    paper_api.CROSSREF_API_URL: "crossref",
    paper_api.OPENALEX_API_URL: "openalex",
    paper_api.SEMANTIC_SCHOLAR_API_URL: "semanticscholar",
    paper_api.EUROPEPMC_API_URL: "europepmc",
    paper_api.CLINICALTRIALS_API_URL: "clinicaltrials",
}


def _source_of(url: str) -> str:
    for endpoint, name in _HOSTS.items():
        if url.startswith(endpoint):
            return name
    raise AssertionError(f"unrecognized endpoint: {url}")


def _body_for(url: str) -> str:
    return _BODIES[_source_of(url)]


def _serve(monkeypatch, handler) -> None:
    """Replace the one network boundary; `handler(url) -> str` or raises."""
    monkeypatch.setattr(paper_api, "_http_get_text", handler)


# --------------------------------------------------------------------------
# Genuinely concurrent, not async in name only
# --------------------------------------------------------------------------


def test_the_sources_are_fetched_concurrently(monkeypatch) -> None:
    """Five 100ms fetches must overlap, not add up.

    The blocking helper is handed to a thread, so this measures whether that
    actually happened. Serial execution would take 500ms; the assertion has
    generous headroom so it fails on the structural change, not on timing
    noise.
    """
    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def _slow(url: str) -> str:
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.1)
        with lock:
            in_flight -= 1
        return _body_for(url)

    _serve(monkeypatch, _slow)
    started = time.monotonic()
    batches, failures = asyncio.run(fetch_sources(KEYLESS, "q"))
    elapsed = time.monotonic() - started

    assert not failures
    assert len(batches) == len(KEYLESS)
    assert peak > 1, "the fetches never overlapped: still serial"
    assert elapsed < 0.4, f"serial execution would take ~0.5s, took {elapsed:.2f}s"


def test_the_offline_guard_still_runs_before_the_socket(monkeypatch) -> None:
    """Moving the helper to a thread must not reorder its internals."""
    order: list[str] = []

    monkeypatch.setattr(
        paper_api,
        "assert_network_allowed",
        lambda _: order.append("guard"),
    )
    monkeypatch.setattr(
        paper_api,
        "urlopen",
        lambda *a, **k: order.append("socket") or _FakeResponse(),
    )

    asyncio.run(PaperApiConnector().fetch({"source": "crossref", "query": "q"}))

    assert order == ["guard", "socket"]


class _FakeResponse:
    headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()

    def read(self, amount: int | None = None) -> bytes:
        return CROSSREF_BODY.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


# --------------------------------------------------------------------------
# Partial success
# --------------------------------------------------------------------------


def test_one_failing_source_does_not_discard_the_others(monkeypatch) -> None:
    def _flaky(url: str) -> str:
        if _source_of(url) == "semanticscholar":
            raise OSError("HTTP 429 Too Many Requests")
        return _body_for(url)

    _serve(monkeypatch, _flaky)
    batches, failures = asyncio.run(fetch_sources(KEYLESS, "q"))

    assert len(batches) == len(KEYLESS) - 1
    assert [f.source for f in failures] == ["semanticscholar"]
    assert failures[0].kind == "fetch_failed"
    assert "429" in failures[0].error


def test_every_source_failing_reports_every_reason(monkeypatch) -> None:
    _serve(monkeypatch, lambda url: (_ for _ in ()).throw(OSError("down")))
    batches, failures = asyncio.run(fetch_sources(KEYLESS, "q"))

    assert batches == []
    assert len(failures) == len(KEYLESS)


def test_batches_keep_the_declared_source_order(monkeypatch) -> None:
    """`collapse_duplicates` breaks ties on this order, so it must survive."""
    _serve(monkeypatch, _body_for)
    batches, _ = asyncio.run(fetch_sources(KEYLESS, "q"))

    assert [name for name, _ in batches] == list(KEYLESS)


def test_an_oversized_response_is_classified_as_such(monkeypatch) -> None:
    def _huge(url: str) -> str:
        if _source_of(url) == "crossref":
            raise ResponseTooLarge("api.crossref.org returned too much")
        return _body_for(url)

    _serve(monkeypatch, _huge)
    _, failures = asyncio.run(fetch_sources(KEYLESS, "q"))

    assert [f.kind for f in failures] == ["too_large"]


def test_a_rejected_query_is_classified_apart_from_a_fetch_failure() -> None:
    """The gate refuses before any network call, so no handler is needed."""
    _, failures = asyncio.run(fetch_sources(["crossref"], "x" * 5000))

    assert [f.kind for f in failures] == ["rejected"]


# --------------------------------------------------------------------------
# H3: offline is a kill switch, not five source failures
# --------------------------------------------------------------------------


def test_offline_mode_raises_instead_of_reporting_five_failures(
    monkeypatch,
) -> None:
    """Reporting it per source would hide why nothing was fetched.

    A caller seeing five `fetch_failed` entries would report "all sources
    failed" — a network problem — when the truth is that the operator turned
    egress off.
    """
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")

    with pytest.raises(NetworkBlocked):
        asyncio.run(fetch_sources(KEYLESS, "q"))


def test_the_offline_message_still_names_only_the_host(monkeypatch) -> None:
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")

    with pytest.raises(NetworkBlocked) as caught:
        asyncio.run(fetch_sources(["crossref"], "q"))

    assert "api.crossref.org" in str(caught.value)
    assert "query=" not in str(caught.value)


def test_an_unknown_source_is_rejected_not_raised() -> None:
    """An unknown name is `rejected`, not `unsupported`.

    `check_paper_query` runs first and refuses anything outside
    `PAPER_API_SOURCES`, so the name never reaches the implemented-source
    check. Since those two lists are now pinned equal, `unsupported` is
    unreachable in practice — it survives as defence in depth for a source
    allowlisted ahead of its implementation, and the contract test in
    test_source_registry is what would catch that state.
    """
    _, failures = asyncio.run(fetch_sources(["not-a-real-source"], "q"))

    assert [f.kind for f in failures] == ["rejected"]


def test_a_mixed_run_reports_both_kinds(monkeypatch) -> None:
    def _flaky(url: str) -> str:
        if _source_of(url) == "crossref":
            raise OSError("boom")
        return _body_for(url)

    _serve(monkeypatch, _flaky)
    batches, failures = asyncio.run(
        fetch_sources(["arxiv", "crossref", "not-a-real-source"], "q")
    )

    assert [name for name, _ in batches] == ["arxiv"]
    assert {f.kind for f in failures} == {"fetch_failed", "rejected"}


def test_a_gate_failure_never_reaches_the_network(monkeypatch) -> None:
    called: list[str] = []
    _serve(monkeypatch, lambda url: called.append(url) or _body_for(url))

    _, failures = asyncio.run(fetch_sources(["not-a-real-source"], "q"))

    assert failures
    assert called == [], "an unsupported source must not be fetched"


def test_the_connector_still_raises_for_a_single_source_caller() -> None:
    """`fetch` keeps its all-or-nothing contract; only the fan-out softens it."""
    with pytest.raises(NotAllowlisted):
        asyncio.run(PaperApiConnector().fetch({"source": "crossref", "query": ""}))
