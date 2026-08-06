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

* **Collect files may not come from the store's own directory.** Reading a
  file is not a network act, so it is not a host question — but a collected
  document becomes extraction input, and extraction sends it to an LLM
  provider. Anything under ``data/`` (``kg.sqlite``, ``providers.json``, and
  the publisher keys planned for ``sources.json``) would therefore leave the
  machine. ``check_collect_file`` is a *negative* gate for exactly that
  reason: a researcher's notes live anywhere on disk, so enumerating what
  they may read is impossible; enumerating what they may not is not.

Shipped defaults remain neutral domains: software, technical documentation,
and open scholarly metadata.
"""

from __future__ import annotations

import re
from pathlib import Path
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
    # EPPO registry surfaces. Exact hosts only: the import-first registry
    # command uses data.eppo.int, while gd.eppo.int is the manual-download
    # surface users are directed to when no API token is configured.
    "data.eppo.int",
    "gd.eppo.int",
}

# Paper-API sources: every entry corresponds to exactly one fixed endpoint
# constant in connectors/paper_api.py (all keyless public metadata APIs).
PAPER_API_SOURCES: set[str] = {
    "arxiv",
    "crossref",
    "openalex",
    "semanticscholar",
    "europepmc",
        "biorxiv",
        "pubmed",
    # Publisher APIs (2026-07). Keyed, but still one fixed host each, which
    # is why they fit an exact-match allowlist at all. Reaching full text by
    # crawling document pages was rejected for the opposite reason: a
    # doi.org -> publisher -> CDN chain cannot be enumerated in advance, so
    # allowing it would have meant giving up exact matching.
    "elsevier",
    "springer",
    "core",
    # Trial registrations, not papers. Same document shape (a title
    # plus a prose summary) but a different kind of evidence: what was
    # actually attempted on people, including what never got published.
    "clinicaltrials",
    # A metasearch engine the user runs themselves. The exception to "one
    # source, one fixed host": its address is configuration, so the host
    # gate is `check_searxng_base_url` (loopback/private only) rather than
    # a constant in paper_api.py. Reaches Google Scholar, which has no API.
    "searxng",
}

# Back-compat alias: earlier code/tests read PAPER_API_ALLOWED["sources"].
PAPER_API_ALLOWED: dict[str, set[str]] = {"sources": PAPER_API_SOURCES}

# Query validation bounds (see module docstring for the rationale).
MAX_PAPER_QUERY_LEN = 200
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

# How many values of one input list reach the provenance record (see
# `loggable_collect_inputs`). Well above any real collect; low enough that a
# single request cannot append megabytes to an append-only file.
MAX_LOGGED_VALUES = 50


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


# SearXNG is the one source whose endpoint is not a constant in this
# repository: it is a metasearch engine the user runs themselves, so its
# address is configuration. That breaks the invariant every other paper
# source rests on — "one source, one fixed host" — and the exact-match
# allowlist cannot express it.
#
# What replaces the invariant is a narrower one: the instance must be on
# this machine or this network. A loopback or private address cannot carry
# a research query to a third party, which is the property the host
# allowlist exists to guarantee. A public SearXNG instance is deliberately
# refused: it would be a keyless, user-supplied, arbitrary internet
# endpoint receiving every query this tool makes, which is exactly what
# deny-by-default is for. Someone who genuinely wants that adds the host
# to WEB_CRAWL_ALLOWED_HOSTS-style review here, on purpose.
_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa")


def check_searxng_base_url(url: str) -> str:
    """Validate a self-hosted SearXNG base URL; return it without its path.

    Raises NotAllowlisted for a scheme other than http(s), for credentials
    embedded in the URL, or for any host that is not loopback/private.
    """
    import ipaddress

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise NotAllowlisted(
            f"SearXNG URL scheme {parsed.scheme!r} is not allowed "
            f"(http/https only)"
        )
    # A userinfo section would put a credential into every logged URL — the
    # same reason publisher keys travel as headers and never as query
    # parameters.
    if parsed.username or parsed.password:
        raise NotAllowlisted(
            "SearXNG URL must not embed credentials; it would be written to "
            "the job log and the provenance record"
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise NotAllowlisted("SearXNG URL has no host")

    allowed = host == "localhost" or host.endswith(_PRIVATE_HOST_SUFFIXES)
    if not allowed:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        allowed = address is not None and (
            address.is_loopback or address.is_private
        )
    if not allowed:
        raise NotAllowlisted(
            f"SearXNG host {host!r} is not loopback or private. This tool "
            f"only queries a SearXNG you run yourself — a public instance "
            f"would receive every research query you make"
        )
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


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


def loggable_collect_inputs(values: list[str]) -> list[str]:
    """Bound one collect input list for the permanent provenance record.

    M2. A collect run logs its inputs under `collect.start` **before** the
    gates run, which is the right order — a rejected attempt must leave a
    trace — but it means the recorded value has passed no validation at all.
    `MAX_PAPER_QUERY_LEN` bounds what may be *searched for*; until now
    nothing bounded what may be *written down*, so a 5000-character query
    was refused by `check_paper_query` and archived in full on the way out.

    Where it lands is the reason this matters. `provenance.log` serializes
    any payload with `default=str` into an append-only `provenance.jsonl`
    and mirrors it into `status.json` as `last_payload`; `Settings.
    cost_summary()` then re-reads every `data/jobs/*/provenance.jsonl` on
    the machine. A research topic is a statement of what someone wanted to
    know, and this is the one place it is kept forever, so it is kept at the
    length the system was willing to act on and no more.

    Truncation is not redaction. A valid query is under the bound and is
    recorded verbatim — the audit trail stays faithful for every input that
    actually reached a connector. Only inputs already destined for rejection
    are clipped, and the clip is marked so a reader is never misled about
    having the whole value.
    """
    kept = [
        value
        if len(value) <= MAX_PAPER_QUERY_LEN
        else value[:MAX_PAPER_QUERY_LEN] + "…[truncated]"
        for value in values[:MAX_LOGGED_VALUES]
    ]
    dropped = len(values) - len(kept)
    if dropped > 0:
        kept.append(f"…[{dropped} more omitted]")
    return kept


def check_collect_file(file_arg: str, data_dir: str | Path) -> Path:
    """Validate a collect file argument; return its resolved path.

    Refuses any file inside ``data_dir``. A collected document becomes
    extraction input and extraction sends it to an LLM provider, so
    collecting the store's own directory would mail out `kg.sqlite`,
    `providers.json`, or the publisher keys — and `packbuilder` would copy
    its `source_uri` into distributed packs. Enforced BEFORE any read.

    Both sides are resolved, so a symlink cannot disguise the destination:
    it refuses whether the caller names the real path or a link to it, and
    whether `data_dir` itself is a real path or a link. `Path.resolve` is
    non-strict, so a file that does not exist yet is refused too — the guard
    holds before `sources.json` is ever created.

    This deliberately refuses only `data_dir`'s interior. An earlier attempt
    allowed *only* an uploads directory; that broke every caller that reads
    a researcher's own notes, which is the feature's whole point.
    """
    resolved = Path(file_arg).resolve()
    root = Path(data_dir).resolve()
    if resolved == root or resolved.is_relative_to(root):
        raise NotAllowlisted(
            f"{file_arg!r} is inside the store directory ({root}); "
            f"collecting it would send its contents to an LLM provider. "
            f"Copy the file outside {root} to collect it."
        )
    return resolved
