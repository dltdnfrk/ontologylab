"""Deny-by-default source allowlist, shared by ALL ingest connectors.

This is a **positive** allowlist: a request is permitted only if it matches
an entry below; anything else is rejected with a clear ``NotAllowlisted``
error (never silently skipped). Both connectors import from this one module,
so the enforcement point is identical for web crawling and (post-MVP) the
paper-API connector.

Shipped defaults are neutral domains only: software, technical
documentation, and general knowledge. Extending the allowlist is an
explicit, reviewable edit to this file.
"""

from __future__ import annotations

from urllib.parse import urlparse


class NotAllowlisted(Exception):
    """Raised when a source/query is not on the positive allowlist."""


# deny-by-default: a request is allowed ONLY if it matches an entry below.
WEB_CRAWL_ALLOWED_HOSTS: set[str] = {
    "docs.python.org",
    "developer.mozilla.org",
    "www.rfc-editor.org",
    "peps.python.org",
    "raw.githubusercontent.com",  # project READMEs / docs
}

PAPER_API_ALLOWED: dict[str, set[str]] = {
    # allowed API sources ...
    "sources": {"arxiv", "crossref"},
    # ... and allowed query categories/terms (positive list, not an open field)
    "queries": {
        "distributed systems",
        "software architecture",
        "programming languages",
        "databases",
        "operating systems",
    },
}


def check_url(url: str) -> str:
    """Validate a crawl URL against the host allowlist; return it unchanged.

    Raises NotAllowlisted if the scheme is not http(s) or the host is not
    an allowlisted entry.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise NotAllowlisted(
            f"URL scheme {parsed.scheme!r} is not allowed (http/https only): {url}"
        )
    host = (parsed.hostname or "").lower()
    if host not in WEB_CRAWL_ALLOWED_HOSTS:
        raise NotAllowlisted(
            f"host {host!r} is not on the crawl allowlist; "
            f"add it to connectors/allowlist.py to permit it explicitly"
        )
    return url


def check_paper_query(source: str, query: str) -> tuple[str, str]:
    """Validate a paper-API (source, query) pair; return them unchanged.

    Both the API source and the query term must appear on the positive
    lists. Raises NotAllowlisted otherwise. Enforced BEFORE any network call.
    """
    if source not in PAPER_API_ALLOWED["sources"]:
        raise NotAllowlisted(
            f"paper source {source!r} is not on the allowlist "
            f"(allowed: {sorted(PAPER_API_ALLOWED['sources'])})"
        )
    if query.strip().lower() not in PAPER_API_ALLOWED["queries"]:
        raise NotAllowlisted(
            f"paper query {query!r} is not on the allowed-query list; "
            f"add it to connectors/allowlist.py to permit it explicitly"
        )
    return source, query
