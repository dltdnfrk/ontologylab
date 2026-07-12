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


def test_paper_query_denied_off_list():
    with pytest.raises(NotAllowlisted):
        check_paper_query("arxiv", "medieval pottery")
    with pytest.raises(NotAllowlisted):
        check_paper_query("unknown-source", "databases")
    assert check_paper_query("arxiv", "databases") == ("arxiv", "databases")


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
