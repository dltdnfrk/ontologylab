"""Deny-by-default allowlist: the safety boundary every connector shares."""

import pytest

from ontologylab.connectors.allowlist import (
    NotAllowlisted,
    WEB_CRAWL_ALLOWED_HOSTS,
    check_paper_query,
    check_url,
)
from ontologylab.connectors.web_crawl import WebCrawlConnector


def test_allowlisted_host_passes():
    url = "https://docs.python.org/3/library/sqlite3.html"
    assert check_url(url) == url


def test_unknown_host_denied():
    with pytest.raises(NotAllowlisted):
        check_url("https://evil.example.com/page")


def test_subdomain_of_allowlisted_host_denied():
    # exact-host match only; no suffix matching that could be spoofed
    assert "docs.python.org" in WEB_CRAWL_ALLOWED_HOSTS
    with pytest.raises(NotAllowlisted):
        check_url("https://docs.python.org.evil.example/page")


def test_non_http_scheme_denied():
    with pytest.raises(NotAllowlisted):
        check_url("file:///etc/passwd")
    with pytest.raises(NotAllowlisted):
        check_url("ftp://docs.python.org/x")


def test_paper_source_positive_list_still_enforced():
    """Sources stay a closed list — they select fixed network endpoints."""
    with pytest.raises(NotAllowlisted):
        check_paper_query("unknown-source", "databases")
    assert check_paper_query("arxiv", "databases") == ("arxiv", "databases")
    # 2026-07 expansion: three more keyless sources
    for source in ("openalex", "semanticscholar", "europepmc"):
        assert check_paper_query(source, "databases") == (source, "databases")


def test_paper_query_free_text_validated_not_enumerated():
    """Queries are validated (they are only search terms), not enumerated."""
    # arbitrary research topics now pass
    assert check_paper_query("arxiv", "medieval pottery")[1] == "medieval pottery"
    assert check_paper_query("openalex", "knowledge graph extraction")
    # ... but degenerate/dangerous shapes are still rejected
    with pytest.raises(NotAllowlisted):
        check_paper_query("arxiv", "   ")  # empty
    with pytest.raises(NotAllowlisted):
        check_paper_query("arxiv", "x" * 201)  # over MAX_PAPER_QUERY_LEN
    with pytest.raises(NotAllowlisted):
        check_paper_query("arxiv", "bad\x00query")  # control chars
    with pytest.raises(NotAllowlisted):
        check_paper_query("arxiv", "https://evil.example/x")  # embedded URL


def test_connector_checks_before_any_io(monkeypatch):
    """fetch() must raise NotAllowlisted without ever touching the network."""
    import ontologylab.connectors.web_crawl as wc

    def boom(url):  # pragma: no cover - must not be reached
        raise AssertionError("network I/O attempted for non-allowlisted URL")

    monkeypatch.setattr(wc, "_fetch_url", boom)
    connector = WebCrawlConnector()
    import asyncio

    with pytest.raises(NotAllowlisted):
        asyncio.run(connector.fetch({"urls": ["https://evil.example.com/"]}))
