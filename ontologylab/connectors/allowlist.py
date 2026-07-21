"""Deny-by-default source allowlist, shared by ALL ingest connectors.

Two different gates, matched to where the actual risk lives:

* **Hosts and sources are a positive allowlist.** The network boundary —
  which endpoints this system may ever talk to — is a closed list. A crawl
  URL must match ``WEB_CRAWL_ALLOWED_HOSTS`` exactly, and a paper source
  must be one of ``PAPER_API_SOURCES`` (each maps to one fixed, keyless
  endpoint constant in ``paper_api.py``). Extending either is an explicit,
  reviewable edit to this file.

* **Paper queries are validated, not enumerated.** The query is only ever a
  percent-encoded search term inside one of those fixed endpoints — it can
  not redirect the request anywhere. The original MVP shipped a five-phrase
  positive list as a training wheel; it made the feature unusable for real
  research, so it was deliberately replaced (2026-07) with validation:
  non-empty, bounded length, no control characters, no embedded URLs.

Shipped defaults remain neutral domains: software, technical documentation,
and open scholarly metadata.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


class NotAllowlisted(Exception):
    """Raised when a source/query is not permitted by this module."""


# deny-by-default: a crawl is allowed ONLY if the host matches exactly.
WEB_CRAWL_ALLOWED_HOSTS: set[str] = {
    "docs.python.org",
    "developer.mozilla.org",
    "www.rfc-editor.org",
    "peps.python.org",
    "raw.githubusercontent.com",  # project READMEs / docs
}

# Paper-API sources: every entry corresponds to exactly one fixed endpoint
# constant in connectors/paper_api.py (all keyless public metadata APIs).
PAPER_API_SOURCES: set[str] = {
    "arxiv",
    "crossref",
    "openalex",
    "semanticscholar",
    "europepmc",
}

# Back-compat alias: earlier code/tests read PAPER_API_ALLOWED["sources"].
PAPER_API_ALLOWED: dict[str, set[str]] = {"sources": PAPER_API_SOURCES}

# Query validation bounds (see module docstring for the rationale).
MAX_PAPER_QUERY_LEN = 200
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


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

    The source must be on the positive list (it selects a fixed endpoint);
    the query must pass validation (it is only a search term). Enforced
    BEFORE any network I/O.
    """
    if source not in PAPER_API_SOURCES:
        raise NotAllowlisted(
            f"paper source {source!r} is not on the allowlist "
            f"(allowed: {sorted(PAPER_API_SOURCES)})"
        )
    stripped = query.strip()
    if not stripped:
        raise NotAllowlisted("paper query is empty")
    if len(stripped) > MAX_PAPER_QUERY_LEN:
        raise NotAllowlisted(
            f"paper query is too long ({len(stripped)} chars; "
            f"max {MAX_PAPER_QUERY_LEN})"
        )
    if _CONTROL_CHARS_RE.search(stripped):
        raise NotAllowlisted("paper query contains control characters")
    if "://" in stripped:
        raise NotAllowlisted(
            "paper query must be a search term, not a URL; "
            "use --url for allowlisted web pages"
        )
    return source, query
