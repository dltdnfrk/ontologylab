"""Open-access full text: what gets fetched, what gets kept, what never leaks.

Collecting stopped at the abstract, so extraction was reading conclusions
without the evidence for them. The route taken is Europe PMC's JATS
endpoint, chosen because it is served from the host the search API already
uses — full text at zero cost to the allowlist.

Two properties carry the security argument and both are tested here: the
fetch goes through the same guarded helper as every other request, and a
`pmcid` from a third-party response can never become an arbitrary path.
"""

from __future__ import annotations

import pytest

from ontologylab.connectors import paper_api
from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.fulltext import (
    MAX_FULLTEXT_CHARS,
    MIN_FULLTEXT_CHARS,
    enrich_with_fulltext,
    fetch_fulltext,
    jats_to_text,
)
from ontologylab.connectors.paper_api import (
    EUROPEPMC_API_URL,
    PAPER_API_HOSTS,
    europepmc_fulltext_url,
    parse_europepmc,
)

BODY_SENTENCE = "The RecA protein catalyses strand exchange during repair. "

JATS = f"""<?xml version="1.0"?>
<article>
  <front>
    <journal-meta>
      <journal-id journal-id-type="pmc-domain-id">3993</journal-id>
      <journal-title>BMC Genomic Data</journal-title>
      <issn>2730-6844</issn>
    </journal-meta>
    <article-meta>
      <article-id pub-id-type="pmc">PMC999</article-id>
      <contrib-group>
        <contrib><name><surname>Larmande</surname>
        <given-names>Pierre</given-names></name></contrib>
      </contrib-group>
      <abstract><p>We measured repair efficiency.</p></abstract>
    </article-meta>
  </front>
  <body>
    <sec><title>Methods</title>
      <p>{BODY_SENTENCE * 12}<xref ref-type="bibr" rid="b1">[1]</xref> Done.</p>
    </sec>
  </body>
  <back>
    <ref-list><ref><mixed-citation>Nobody Cited 2020</mixed-citation></ref></ref-list>
  </back>
</article>
"""


def _doc(**overrides) -> RawDocument:
    base = {
        "source_kind": "paper_api",
        "source_uri": "https://doi.org/10.1/a",
        "title": "A paper",
        "raw_text": "A paper\n\nShort abstract.",
        "doi": "10.1/a",
    }
    base.update(overrides)
    return RawDocument(**base)


# --------------------------------------------------------------------------
# The URL: a third-party id must never become a path
# --------------------------------------------------------------------------


def test_a_valid_pmcid_builds_a_url_on_the_known_host() -> None:
    url = europepmc_fulltext_url("PMC13262414")

    assert url.endswith("/PMC13262414/fullTextXML")
    from urllib.parse import urlparse

    assert urlparse(url).hostname == urlparse(EUROPEPMC_API_URL).hostname


def test_the_fulltext_host_adds_nothing_to_the_allowlist() -> None:
    """The whole reason this endpoint was chosen over crawling PDFs."""
    from urllib.parse import urlparse

    assert urlparse(europepmc_fulltext_url("PMC1")).hostname in PAPER_API_HOSTS


@pytest.mark.parametrize(
    "pmcid",
    [
        "../../../etc/passwd",
        "PMC1/../../secret",
        "PMC1?x=1",
        "PMC1#frag",
        "PMC 1",
        "pmc123",
        "12345",
        "",
        "PMC" + "9" * 40,
        "PMC1;rm -rf /",
        "https://evil.example.com/x",
    ],
)
def test_anything_that_is_not_a_pmcid_builds_no_url(pmcid: str) -> None:
    assert europepmc_fulltext_url(pmcid) == ""


# --------------------------------------------------------------------------
# JATS → prose
# --------------------------------------------------------------------------


def test_the_body_survives_and_the_journal_metadata_does_not() -> None:
    """The bug the first implementation shipped with.

    Walking `<article>` whole flattened journal-meta and article-meta, whose
    elements carry no separators, into runs like
    `3993BMC Genomic Data2730-6844`. Those would have been proposed as
    entities — noise wearing a real source span.
    """
    text = jats_to_text(JATS)

    assert "RecA protein" in text
    assert "We measured repair efficiency." in text
    assert "3993" not in text
    assert "2730-6844" not in text
    assert "Larmande" not in text


def test_the_reference_list_is_dropped() -> None:
    """References can outweigh the body and carry no findings.

    The ref-list here sits INSIDE `<body>`, which some JATS producers do.
    Asserting against the one in `<back>` proved nothing: `<back>` is
    already outside the walked subtrees, so that assertion held with the
    skip list emptied — it was testing the scoping, not the skip.
    """
    nested = (
        "<article><body><sec><p>Real finding here.</p></sec>"
        "<ref-list><ref><mixed-citation>Nobody Cited 2020</mixed-citation>"
        "</ref></ref-list></body></article>"
    )

    text = jats_to_text(nested)

    assert "Real finding here." in text
    assert "Nobody Cited" not in text


def test_citation_markers_go_but_the_words_around_them_stay() -> None:
    text = jats_to_text(JATS)

    assert "[1]" not in text
    assert "Done." in text, "text following a dropped xref was lost"


def test_unparseable_xml_is_empty_not_an_exception() -> None:
    """A failed enrichment degrades to the abstract; it never fails a run."""
    assert jats_to_text("<article><unclosed>") == ""
    assert jats_to_text("") == ""


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def test_a_fetch_goes_through_the_guarded_helper(monkeypatch) -> None:
    """`_http_get_text` is what applies the host allowlist, the redirect
    handler, the size cap and the offline kill switch. Reaching around it
    with a bare urlopen would silently drop all four."""
    seen: list[str] = []
    monkeypatch.setattr(
        paper_api, "_http_get_text", lambda url, **k: seen.append(url) or JATS
    )

    text = fetch_fulltext(europepmc_fulltext_url("PMC999"))

    assert seen == [europepmc_fulltext_url("PMC999")]
    assert "RecA protein" in text


def test_a_failed_fetch_is_empty_not_an_exception(monkeypatch) -> None:
    def _boom(url, **kwargs):
        raise OSError("HTTP 404")

    monkeypatch.setattr(paper_api, "_http_get_text", _boom)

    assert fetch_fulltext("https://www.ebi.ac.uk/x") == ""


def test_an_empty_url_never_reaches_the_network(monkeypatch) -> None:
    monkeypatch.setattr(
        paper_api, "_http_get_text",
        lambda *a, **k: pytest.fail("a fetch was attempted for no URL"),
    )

    assert fetch_fulltext("") == ""


def test_full_text_is_capped(monkeypatch) -> None:
    """One pathological article must not consume a whole run's budget."""
    huge = f"<article><body><p>{'x' * (MAX_FULLTEXT_CHARS * 2)}</p></body></article>"
    monkeypatch.setattr(paper_api, "_http_get_text", lambda *a, **k: huge)

    assert len(fetch_fulltext("https://www.ebi.ac.uk/x")) == MAX_FULLTEXT_CHARS


# --------------------------------------------------------------------------
# Enrichment
# --------------------------------------------------------------------------


def test_an_open_access_document_gains_its_body(monkeypatch) -> None:
    monkeypatch.setattr(paper_api, "_http_get_text", lambda *a, **k: JATS)
    document = _doc(fulltext_url=europepmc_fulltext_url("PMC999"))

    [enriched], stats = enrich_with_fulltext([document])

    assert stats == {"eligible": 1, "fetched": 1, "too_short": 0, "failed": 0}
    assert len(enriched.raw_text) > len(document.raw_text)
    assert "RecA protein" in enriched.raw_text


def test_identity_survives_enrichment(monkeypatch) -> None:
    """De-duplication keys on DOI, so a rewritten body must not move it."""
    monkeypatch.setattr(paper_api, "_http_get_text", lambda *a, **k: JATS)
    document = _doc(fulltext_url=europepmc_fulltext_url("PMC999"))

    [enriched], _ = enrich_with_fulltext([document])

    assert enriched.doi == document.doi
    assert enriched.source_uri == document.source_uri
    assert enriched.dedupe_key == document.dedupe_key
    assert enriched.title == document.title
    assert enriched.raw_text.startswith(document.title)


def test_a_document_with_no_open_access_copy_is_untouched(monkeypatch) -> None:
    monkeypatch.setattr(
        paper_api, "_http_get_text",
        lambda *a, **k: pytest.fail("fetched for a document with no full text"),
    )
    document = _doc()

    [unchanged], stats = enrich_with_fulltext([document])

    assert unchanged is document
    assert stats["eligible"] == 0


def test_a_stub_body_does_not_replace_a_real_abstract(monkeypatch) -> None:
    """Corrections and retraction notices have bodies of a few words.

    Swapping a 1200-character abstract for "This corrects the article..."
    would lose information rather than add it.
    """
    stub = "<article><body><p>This corrects the article.</p></body></article>"
    monkeypatch.setattr(paper_api, "_http_get_text", lambda *a, **k: stub)
    abstract = "A paper\n\n" + ("A real abstract sentence. " * 40)
    document = _doc(raw_text=abstract, fulltext_url=europepmc_fulltext_url("PMC9"))

    [kept], stats = enrich_with_fulltext([document])

    assert kept.raw_text == abstract
    assert stats["too_short"] == 1
    assert stats["fetched"] == 0
    assert len(stub) < MIN_FULLTEXT_CHARS


def test_one_failure_does_not_stop_the_others(monkeypatch) -> None:
    calls = {"n": 0}

    def _flaky(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("HTTP 500")
        return JATS

    monkeypatch.setattr(paper_api, "_http_get_text", _flaky)
    documents = [
        _doc(source_uri="https://doi.org/10.1/a", doi="10.1/a",
             fulltext_url=europepmc_fulltext_url("PMC1")),
        _doc(source_uri="https://doi.org/10.1/b", doi="10.1/b",
             fulltext_url=europepmc_fulltext_url("PMC2")),
    ]

    enriched, stats = enrich_with_fulltext(documents)

    assert stats == {"eligible": 2, "fetched": 1, "too_short": 0, "failed": 1}
    assert "RecA protein" in enriched[1].raw_text


# --------------------------------------------------------------------------
# The parser feeds it
# --------------------------------------------------------------------------


def _epmc_payload(**overrides) -> str:
    import json

    item = {
        "title": "A paper", "abstractText": "Short.", "doi": "10.1/a",
        "source": "MED", "id": "1", "pmcid": "PMC13262414", "inEPMC": "Y",
        "isOpenAccess": "Y",
        "fullTextUrlList": {"fullTextUrl": [
            {"documentStyle": "pdf", "availability": "Open access",
             "url": "https://europepmc.org/articles/PMC13262414?pdf=render"},
            {"documentStyle": "doi", "availability": "Subscription required",
             "url": "https://doi.org/10.1/a"},
        ]},
    }
    item.update(overrides)
    return json.dumps({"resultList": {"result": [item]}})


def test_the_parser_captures_the_full_text_url() -> None:
    [document] = parse_europepmc(_epmc_payload())

    assert document.fulltext_url == europepmc_fulltext_url("PMC13262414")


def test_only_the_open_access_pdf_link_is_taken() -> None:
    """A paywalled PDF listed first must not win.

    The original fixture put the only PDF entry at open access, so dropping
    the availability check changed nothing — the test was reading
    `documentStyle` and calling it a licence check.
    """
    payload = _epmc_payload(
        fullTextUrlList={"fullTextUrl": [
            {"documentStyle": "pdf", "availability": "Subscription required",
             "url": "https://paywalled.example.com/a.pdf"},
            {"documentStyle": "pdf", "availability": "Open access",
             "url": "https://europepmc.org/articles/PMC13262414?pdf=render"},
        ]}
    )

    [document] = parse_europepmc(payload)

    assert document.pdf_url == "https://europepmc.org/articles/PMC13262414?pdf=render"
    assert "paywalled" not in (document.pdf_url or "")


def test_an_article_europe_pmc_does_not_host_gets_no_full_text_url() -> None:
    """`isOpenAccess: Y` is not enough — the text has to be *here*."""
    [document] = parse_europepmc(_epmc_payload(inEPMC="N"))

    assert document.fulltext_url is None


def test_a_missing_pmcid_gets_no_full_text_url() -> None:
    [document] = parse_europepmc(_epmc_payload(pmcid=None))

    assert document.fulltext_url is None


def test_a_hostile_pmcid_in_the_response_builds_no_url() -> None:
    """The id is a third party's string interpolated into a path."""
    [document] = parse_europepmc(_epmc_payload(pmcid="../../../etc/passwd"))

    assert document.fulltext_url is None


# --------------------------------------------------------------------------
# Wired into the research run
# --------------------------------------------------------------------------


def _research(tmp_path, monkeypatch, *, fulltext: bool):
    """Drive the real research worker; return the document it stored."""
    import time

    from fastapi.testclient import TestClient

    from ontologylab import paths
    from ontologylab.kgstore import KGStore
    from ontologylab.server import jobs as jobs_module
    from ontologylab.server import routes
    from ontologylab.server.app import create_app
    from ontologylab.server.jobs import TERMINAL_STATUSES

    document = _doc(
        raw_text="A paper\n\n" + ("A real abstract sentence. " * 40),
        fulltext_url=europepmc_fulltext_url("PMC999"),
    )

    async def _fetch(sources, query, limit=None, data_dir=None):
        return [("europepmc", [document])], []

    monkeypatch.setattr(jobs_module, "fetch_sources", _fetch)
    monkeypatch.setattr(paper_api, "_http_get_text", lambda *a, **k: JATS)

    data_dir = tmp_path / "data"
    routes.attach_data_dir(data_dir)
    client = TestClient(create_app(data_dir=data_dir))
    started = client.post(
        "/api/research",
        json={"topic": "dna repair", "engine": "mock", "fulltext": fulltext},
    ).json()
    assert started["ok"] is True, started
    job = routes._registry().get(started["job_id"])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and job.status not in TERMINAL_STATUSES:
        time.sleep(0.02)

    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        [stored] = store.list_documents()
        return job, store.document_raw_text(stored.id)
    finally:
        store.close()


def test_a_research_run_stores_the_full_text(tmp_path, monkeypatch) -> None:
    """The end of the wire. Everything above tests the parts; this is the
    only thing that fails if the worker stops calling them."""
    job, text = _research(tmp_path, monkeypatch, fulltext=True)

    assert job.status == "complete"
    assert "RecA protein" in text, "the stored document is still the abstract"
    assert any("full text for 1/1" in line for line in job.progress)


def test_turning_it_off_stores_the_abstract(tmp_path, monkeypatch) -> None:
    """The control — without it, the assertion above could hold because the
    fixture's abstract happened to contain the body text."""
    _job, text = _research(tmp_path, monkeypatch, fulltext=False)

    assert "RecA protein" not in text
    assert "A real abstract sentence." in text
