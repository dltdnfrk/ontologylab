"""Guarded paper acquisition with pure source-specific URL and parser leaves.

This facade owns the twelve-source registry, credentials, guarded HTTP,
harvest sequencing and partial-success fan-out. Public parser and builder
names are direct imports; the leaves never import this facade or perform I/O.

arXiv, Crossref, Europe PMC, bioRxiv and ClinicalTrials need no key.
OpenAlex, Semantic Scholar and PubMed accept optional keys. Elsevier,
Springer and CORE refuse without a configured key; SearXNG is explicit-only
and requires a validated private or loopback instance.

Query checks precede outbound work. Credentials enter headers or query
parameters only inside the guarded transport, never the logged builder URL.
Redirects recheck hosts and strip cross-origin credentials. The same HTTP
seam also serves resources and fulltext; its callers retain their own gates.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import (
    parse_qsl,
    quote_plus,
    urlencode,
    urlparse,
    urlsplit,
    urlunsplit,
)
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ontologylab import evidence
from ontologylab.connectors.allowlist import (
    NotAllowlisted,
    check_paper_query,
    check_searxng_base_url,
)
from ontologylab.paths import NetworkBlocked, assert_network_allowed
from ontologylab.connectors.base import (
    FETCH_TIMEOUT_S as _FETCH_TIMEOUT_S,
    USER_AGENT as _USER_AGENT,
    RawDocument,
    normalize_doi,
)
from ontologylab.connectors.paper_common import (
    ARXIV_SOURCE as ARXIV_SOURCE,
    CROSSREF_SOURCE as CROSSREF_SOURCE,
    OPENALEX_SOURCE as OPENALEX_SOURCE,
    SEMANTIC_SCHOLAR_SOURCE as SEMANTIC_SCHOLAR_SOURCE,
    EUROPEPMC_SOURCE as EUROPEPMC_SOURCE,
    BIORXIV_SOURCE as BIORXIV_SOURCE,
    PUBMED_SOURCE as PUBMED_SOURCE,
    CLINICALTRIALS_SOURCE as CLINICALTRIALS_SOURCE,
    ELSEVIER_SOURCE as ELSEVIER_SOURCE,
    SPRINGER_SOURCE as SPRINGER_SOURCE,
    CORE_SOURCE as CORE_SOURCE,
    SEARXNG_SOURCE as SEARXNG_SOURCE,
    DOI_BASE_URL as DOI_BASE_URL,
    MAX_LIMIT as MAX_LIMIT,
    _normalize as _normalize,
    _load_json as _load_json,
    _json_object as _json_object,
    _integer as _integer,
    _year_from_parts as _year_from_parts,
    _MARKUP_TAG_RE as _MARKUP_TAG_RE,
)
from ontologylab.connectors.paper_urls import (
    _build_query_url as _build_query_url,
    _build_crossref_url as _build_crossref_url,
    _build_openalex_url as _build_openalex_url,
    _build_semanticscholar_url as _build_semanticscholar_url,
    _build_europepmc_url as _build_europepmc_url,
    _build_elsevier_url as _build_elsevier_url,
    _build_springer_url as _build_springer_url,
    _build_core_url as _build_core_url,
    europepmc_fulltext_url as europepmc_fulltext_url,
    _openalex_mailto as _openalex_mailto,
    _paginate_url as _paginate_url,
    ARXIV_API_URL as ARXIV_API_URL,
    CROSSREF_API_URL as CROSSREF_API_URL,
    OPENALEX_API_URL as OPENALEX_API_URL,
    SEMANTIC_SCHOLAR_API_URL as SEMANTIC_SCHOLAR_API_URL,
    EUROPEPMC_API_URL as EUROPEPMC_API_URL,
    EUROPEPMC_FULLTEXT_URL as EUROPEPMC_FULLTEXT_URL,
    ELSEVIER_API_URL as ELSEVIER_API_URL,
    SPRINGER_API_URL as SPRINGER_API_URL,
    CORE_API_URL as CORE_API_URL,
    _CROSSREF_SELECT_FIELDS as _CROSSREF_SELECT_FIELDS,
    _ELSEVIER_FIELDS as _ELSEVIER_FIELDS,
    _PMCID_RE as _PMCID_RE,
    OPENALEX_MAILTO_ENV as OPENALEX_MAILTO_ENV,
    _PAGE_PARAMETER as _PAGE_PARAMETER,
    PAGINATED_SOURCES as PAGINATED_SOURCES,
)
from ontologylab.connectors.paper_urls_special import (
    _build_biorxiv_url as _build_biorxiv_url,
    _build_pubmed_url as _build_pubmed_url,
    _build_clinicaltrials_url as _build_clinicaltrials_url,
    _build_searxng_url as _build_searxng_url,
    _searxng_base_url as _searxng_base_url,
    BIORXIV_API_URL as BIORXIV_API_URL,
    BIORXIV_WINDOW_DAYS as BIORXIV_WINDOW_DAYS,
    PUBMED_EUTILS_URL as PUBMED_EUTILS_URL,
    CLINICALTRIALS_API_URL as CLINICALTRIALS_API_URL,
    SEARXNG_URL_ENV as SEARXNG_URL_ENV,
    SEARXNG_ENGINES as SEARXNG_ENGINES,
    _biorxiv_cursor_url,
    _clinicaltrials_page_url,
    _build_pubmed_efetch_url,
)
from ontologylab.connectors.paper_parsers_xml import (
    parse_atom as parse_atom,
    parse_pubmed as parse_pubmed,
    _ATOM_NS as _ATOM_NS,
)
from ontologylab.connectors.paper_parsers_discovery import (
    parse_crossref as parse_crossref,
    parse_openalex as parse_openalex,
    parse_semanticscholar as parse_semanticscholar,
    parse_searxng as parse_searxng,
    _restore_inverted_abstract as _restore_inverted_abstract,
)
from ontologylab.connectors.paper_parsers_biomedical import (
    parse_europepmc as parse_europepmc,
    parse_biorxiv as parse_biorxiv,
    parse_clinicaltrials as parse_clinicaltrials,
)
from ontologylab.connectors.paper_parsers_publishers import (
    parse_elsevier as parse_elsevier,
    parse_springer as parse_springer,
    parse_core as parse_core,
    _first_springer_url as _first_springer_url,
)

# Acquisition limits and defaults remain with the guarded transport.
DEFAULT_LIMIT = 5

_MAX_LIMIT = MAX_LIMIT  # back-compat alias
DEFAULT_HARVEST_LIMIT = 100
MAX_HARVEST_LIMIT = 500

# The most a single paper API may hand back. 25 abstracts are a few hundred
# kilobytes, so this is generous for a legitimate answer while keeping a
# hostile or broken endpoint from being multiplied by a five-source fan-out.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# Canonical source names: the fetch dispatch, IMPLEMENTED_SOURCES, and the
# default all reference these — never re-type the strings.
DEFAULT_PAPER_SOURCE = ARXIV_SOURCE

# IMPLEMENTED_SOURCES is derived from the single _SOURCE_DISPATCH below.
# Its builders and parsers are imported above; the registry stays here.


class UnsupportedPaperSource(NotImplementedError):
    """Raised for a source that is allowlisted but not implemented yet."""


def check_source_implemented(source: str) -> str:
    """Raise UnsupportedPaperSource unless the source has a real fetcher."""
    if source not in IMPLEMENTED_SOURCES:
        raise UnsupportedPaperSource(
            f"paper source {source!r} is allowlisted but not implemented yet "
            f"(supported: {sorted(IMPLEMENTED_SOURCES)})"
        )
    return source


class ResponseTooLarge(Exception):
    """Raised when a paper API answers with more bytes than we will read."""


# Every host `_http_get_text` may ever reach, derived from the endpoint
# constants rather than re-typed. A new source adds its constant to the
# dispatch table and to this tuple in the same edit; there is no third place
# to forget.
PAPER_API_HOSTS: frozenset[str] = frozenset(
    (urlparse(url).hostname or "").lower()
    for url in (
        ARXIV_API_URL,
        CROSSREF_API_URL,
        OPENALEX_API_URL,
        SEMANTIC_SCHOLAR_API_URL,
        EUROPEPMC_API_URL,
        BIORXIV_API_URL,
        PUBMED_EUTILS_URL,
        CLINICALTRIALS_API_URL,
        ELSEVIER_API_URL,
        SPRINGER_API_URL,
        CORE_API_URL,
    )
)

# Request headers allowed to survive a cross-host redirect.
#
# An allowlist, not a denylist. The plan proposed dropping a named set
# (`Authorization`, `X-Els-Apikey`, `X-Api-Key`), but that is backwards for
# this module: publisher APIs each name their key header differently, and the
# next one added would cross a host boundary in silence because nobody
# remembered to extend the list. Deny-by-default is the rule everywhere else
# in this package; a header is no different from a host.
_REDIRECT_SAFE_HEADERS = frozenset({"user-agent", "accept", "accept-encoding"})


def fetch_hosts() -> frozenset[str]:
    """Every host `_http_get_text` may reach, from both connector families.

    `_http_get_text` is shared with `connectors.resources`, so its redirect
    guard has to know that module's endpoints too — otherwise a plain 302
    from UniProt is refused as an off-allowlist hop.

    Imported at call time, not module scope: `resources` imports this module
    for the fetcher, so a top-level import here would close the cycle. Both
    sets stay DERIVED from endpoint constants; neither is hand-typed, which
    is the property that keeps exact-match viable.

    The union does mean a paper API could redirect to a resource host and be
    allowed. That is a real widening, and a small one: every host in it is
    already trusted enough to be fetched directly, and the handler still
    drops non-safe headers whenever the host changes.
    """
    from ontologylab.connectors.resources import RESOURCE_HOSTS

    return PAPER_API_HOSTS | RESOURCE_HOSTS


def check_paper_host(url: str) -> str:
    """Validate a fetch URL's host; return it unchanged.

    Exact match, https only. The scheme matters as much as the host: every
    endpoint constant is https, so a redirect to `http://` on an allowlisted
    host would still put a request — and, once step 4 lands, a key — on the
    wire in clear text.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise NotAllowlisted(
            f"paper API redirect to a non-https scheme "
            f"({parsed.scheme!r}) is refused"
        )
    allowed = fetch_hosts()
    host = (parsed.hostname or "").lower()
    if host not in allowed:
        raise NotAllowlisted(
            f"paper API redirect to host {host!r} is not on the allowlist "
            f"(allowed: {sorted(allowed)})"
        )
    return url


class _AllowlistedPaperRedirect(HTTPRedirectHandler):
    """Re-checks every redirect hop, and never lets a credential leave a host.

    Two separate holes, both open by default in urllib:

    * **The hop itself.** Only the caller-supplied URL was ever checked, so
      an allowlisted endpoint could 3xx the fetch to any origin at all. Same
      defect `web_crawl._AllowlistedRedirectHandler` was written to close.

    * **The credentials.** `HTTPRedirectHandler.redirect_request` strips only
      `Content-Length` and `Content-Type`; every other header — including an
      API key — is carried to the new host unchanged. Credential stripping on
      a cross-origin redirect is requests/urllib3 behaviour, not urllib's.
      Today nothing here sends a key, which is exactly why this must land
      before step 4 rather than alongside it: one 302 from an endpoint to a
      maintenance page or a CDN would put a publisher key in that host's
      access log, with no attacker involved.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_paper_host(newurl)  # raises NotAllowlisted on a bad hop
        old_origin = _request_origin(req.full_url)
        new_origin = _request_origin(newurl)
        if old_origin != new_origin and _has_credential_query(newurl):
            raise NotAllowlisted(
                f"paper API redirect to origin {new_origin!r} "
                "is refused because its URL carries a credential"
            )
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if old_origin != new_origin:
            for name in list(new.headers):
                if name.lower() not in _REDIRECT_SAFE_HEADERS:
                    del new.headers[name]
        return new


def _request_origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


def _has_credential_query(url: str) -> bool:
    return any(
        name.casefold() in {"api_key", "apikey", "api-key", "access_token"}
        for name, _value in parse_qsl(
            urlparse(url).query,
            keep_blank_values=True,
        )
    )


_opener = build_opener(_AllowlistedPaperRedirect())

# The module-level seam the whole test suite patches — including the
# `qa_round2` / `qa_redteam` conftest fixtures whose entire job is to make
# any accidental real network call explode. Rebinding the name rather than
# calling `_opener.open` at the call site keeps that safety net intact while
# routing every fetch through the redirect guard above.
urlopen = _opener.open


def _with_query_key(url: str, param: str, key: str) -> str:
    """Append a credential query parameter at the moment of the request.

    This module's rule is that credentials travel in headers, because a URL
    reaches the offline-refusal message, `provenance.jsonl`, `status.json`'s
    `last_payload` and the job log, none of which know a URL might hold a
    secret. Elsevier and Springer both offer a query-parameter route and it
    is deliberately not used.

    OpenAlex and Springer leave no supported header choice; PubMed also
    benefits from its documented query key. The exception is contained
    rather than waived: this returns a string that goes straight into
    `urlopen` and is bound to no name that anything else reads. Its one
    caller is the line below `assert_network_allowed`, so the keyless `url`
    remains what the guard, size error and raised exception are built from.
    """
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{param}={quote_plus(key)}"


def _http_get_text(
    url: str,
    headers: dict[str, str] | None = None,
    query_key: tuple[str, str] | None = None,
) -> str:
    """Fetch one allowlist-checked API URL; separated for test monkeypatching.

    The single network boundary for BOTH paper sources (Atom or JSON).

    `headers` carries a publisher credential and nothing else. It is a
    keyword with a default so the ~25 existing monkeypatches spelled
    `lambda url: FIXTURE` keep working; callers pass it only for the keyed
    sources, which have their own fixtures.

    `query_key` is the one credential that cannot travel in a header
    (OpenAlex documents no header form). It arrives separately, rather than
    already spliced into `url`, precisely so that `url` — the value the
    offline guard names, the size error quotes, and any exception raised
    below carries — is keyless for the whole of this function. Splicing it
    upstream would put the secret in `HTTPError.url` and in every message
    built from the URL, leaving `redact_keys` as the only thing between a
    credential and an append-only log.

    The read is bounded. `MAX_RESPONSE_BYTES` is generous for the 25 abstracts
    a request can ask for, and it is the one place that bounds *unknown*
    input: a fan-out multiplies whatever a source sends by the number of
    sources, and `ET.fromstring` expands internal entities. libexpat's own
    amplification limit (100x, 8 MiB) stops the extreme case — that, not the
    "no external entities" claim, is what actually protects the XML path —
    but expansion only stays bounded if the input it multiplies is.
    """
    # Search terms leak research direction to third-party APIs; offline mode
    # refuses the whole channel. Only the host is named: a URL may carry a
    # publisher key in a query parameter, and this message reaches the HTTP
    # response, provenance, and the job log.
    assert_network_allowed(f"paper API fetch ({urlparse(url).hostname})")
    # Last possible moment, and deliberately not rebound onto `url`: the
    # credential exists on `target`, which is handed to `Request` and never
    # read again. Everything below still quotes `url`.
    target = url if query_key is None else _with_query_key(url, *query_key)
    request = Request(target, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    with urlopen(request, timeout=_FETCH_TIMEOUT_S) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        # Read one byte past the cap so an oversized body is detected rather
        # than silently truncated into a half-parsed document.
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge(
            f"{urlparse(url).hostname} returned more than "
            f"{MAX_RESPONSE_BYTES} bytes"
        )
    return payload.decode(charset, errors="replace")


def _relevant(document: RawDocument, terms: Sequence[str]) -> bool:
    """Require each query concept for APIs whose boolean search is loose."""
    if not terms:
        return True
    text = f"{document.title or ''} {document.raw_text}".casefold()
    if not text.strip():
        return True
    return all(
        term.casefold().rstrip("*")[:6] in text
        for term in terms
        if term.strip()
    )


_PUBMED_NS = "{http://www.w3.org/2005/Atom}"


# How each keyed source carries its credential. Headers are preferred:
# a key in a query string reaches the offline-refusal message, the
# provenance record, `status.json`'s last_payload and the job log, all of
# which this system writes without knowing a URL might be a secret. Elsevier
# Springer is the documented exception: its current API requires `api_key`
# in the request URL, so the value is passed separately to `_http_get_text`
# and appended only at the `urlopen` boundary.
_SOURCE_AUTH = {
    ELSEVIER_SOURCE: lambda key: {"X-ELS-APIKey": key, "Accept": "application/json"},
    CORE_SOURCE: lambda key: {"Authorization": f"Bearer {key}",
                              "Accept": "application/json"},
}
_SOURCE_QUERY_AUTH = {SPRINGER_SOURCE: "api_key"}


# source -> (url builder, response parser). Adding a source = one endpoint
# constant + one builder + one parser + one row here (+ the allowlist entry).
_SOURCE_DISPATCH = {
    ARXIV_SOURCE: (_build_query_url, parse_atom),
    CROSSREF_SOURCE: (_build_crossref_url, parse_crossref),
    OPENALEX_SOURCE: (_build_openalex_url, parse_openalex),
    SEMANTIC_SCHOLAR_SOURCE: (_build_semanticscholar_url, parse_semanticscholar),
    EUROPEPMC_SOURCE: (_build_europepmc_url, parse_europepmc),
    BIORXIV_SOURCE: (_build_biorxiv_url, parse_biorxiv),
    PUBMED_SOURCE: (_build_pubmed_url, parse_pubmed),
    CLINICALTRIALS_SOURCE: (_build_clinicaltrials_url, parse_clinicaltrials),
    ELSEVIER_SOURCE: (_build_elsevier_url, parse_elsevier),
    SPRINGER_SOURCE: (_build_springer_url, parse_springer),
    CORE_SOURCE: (_build_core_url, parse_core),
    SEARXNG_SOURCE: (_build_searxng_url, parse_searxng),
}

# Sources that cannot be queried without a credential. Kept derived from
# both transport tables so a keyed source can never be added and then
# silently queried anonymously.
KEYED_SOURCES: frozenset[str] = frozenset(_SOURCE_AUTH) | frozenset(
    _SOURCE_QUERY_AUTH
)

# Sources that answer WITHOUT a key but answer better WITH one.
#
# A third category, because the existing two could not express this. A
# publisher source refuses outright when unconfigured; these do not — they
# fall back to a shared anonymous pool and get 429ed out of it. Measured on
# this machine with no keys configured: OpenAlex and Semantic Scholar both
# returned `429 Too Many Requests` on an ordinary query, which is exactly
# the "did not answer (fetch_failed)" pair seen in a live research run.
# Treating them as required-key sources would hide them from a fresh
# install; leaving them keyless leaves two of eight sources rate-limited.
#
# Each entry says how the credential travels. Header is preferred and used
# wherever the API offers it; `query` exists only because OpenAlex documents
# no header form (see `_with_query_key`).
_OPTIONAL_AUTH: dict[str, tuple[str, str]] = {
    OPENALEX_SOURCE: ("query", "api_key"),
    SEMANTIC_SCHOLAR_SOURCE: ("header", "x-api-key"),
    PUBMED_SOURCE: ("query", "api_key"),
}
OPTIONAL_KEY_SOURCES: frozenset[str] = frozenset(_OPTIONAL_AUTH)

# Every source that can carry a credential at all — the set the settings
# screen offers to connect. Derived, so a new source cannot be added to one
# table and forgotten in the other.
CONNECTABLE_SOURCES: frozenset[str] = KEYED_SOURCES | OPTIONAL_KEY_SOURCES

# This dispatch table IS the registry. A paper source exists exactly when it
# has a URL builder and a parser, so deriving the set from it removes the
# possibility of a half-added source: one that answers
# `check_source_implemented` but has nothing to fetch with, or one that can
# fetch but is refused. Adding a sixth source is a single edit above.
IMPLEMENTED_SOURCES: frozenset[str] = frozenset(_SOURCE_DISPATCH)

# The order the UI offers, and the tie-break the fan-out planned in
# docs uses when two sources return the same paper. Declaration order in
# _SOURCE_DISPATCH is the single answer to both.
SOURCE_ORDER: tuple[str, ...] = tuple(_SOURCE_DISPATCH)

# Display names live beside the registry, not in the markup: the browser now
# renders its picker from the API, and a label kept only in HTML would be a
# fifth place a source has to be spelled out.
PAPER_SOURCE_LABELS: dict[str, str] = {
    ARXIV_SOURCE: "arXiv",
    CROSSREF_SOURCE: "Crossref",
    OPENALEX_SOURCE: "OpenAlex",
    SEMANTIC_SCHOLAR_SOURCE: "Semantic Scholar",
    EUROPEPMC_SOURCE: "Europe PMC (PubMed)",
    BIORXIV_SOURCE: "bioRxiv",
    PUBMED_SOURCE: "PubMed",
    CLINICALTRIALS_SOURCE: "ClinicalTrials.gov",
    ELSEVIER_SOURCE: "Elsevier (Scopus)",
    SPRINGER_SOURCE: "Springer Nature",
    CORE_SOURCE: "CORE",
    SEARXNG_SOURCE: "SearXNG (내 인스턴스)",
}


class MissingSourceKey(Exception):
    """Raised when a keyed publisher source has no credential configured.

    Its own type because "not connected" is a configuration state, not a
    fetch failure: `fetch_sources` reports it as `unconfigured` so a fan-out
    does not tell the user their network is broken when they simply have not
    connected Elsevier.
    """


def resolve_source_key(source: str, data_dir: Any) -> str:
    """Return the credential for a connectable source, or "" if none.

    Covers both categories: publisher sources that REQUIRE a key and the
    optional-key sources that merely prefer one. The caller decides what an
    empty string means — a refusal for the former, an anonymous request for
    the latter.

    Imported lazily: `sources` imports `keychain`, which shells out to
    `security`, and the sources that need no key must not pay for that at
    import time — nor should a non-macOS host fail to import this module.
    """
    if source not in CONNECTABLE_SOURCES or data_dir is None:
        return ""
    try:
        from ontologylab.sources import load_sources, resolve_source_key as _resolve
    except ImportError:  # pragma: no cover — registry is optional
        return ""
    # Matched on `id`, never on `role`. A role groups publishers for the UI
    # ("journal access"), and an earlier version resolved on it — which meant
    # the first literature row's key was returned for *every* publisher, so
    # connecting Springer sent the Springer key to Elsevier in `X-ELS-APIKey`
    # and to CORE as a bearer token. Handing a live credential to two other
    # vendors is precisely what the redirect guard exists to prevent; it must
    # not arrive through the front door instead.
    for entry in load_sources(data_dir):
        if entry.id == source:
            return _resolve(entry) or ""
    return ""


REDACTED = "«redacted»"


def redact_keys(text: str, data_dir: Any = None) -> str:
    """Remove any configured publisher key from ``text``.

    A fan-out failure's text is written verbatim into ``provenance.jsonl``
    and mirrored into ``status.json`` as ``last_payload``. Both live under
    ``data/``, which is the one place a key must never appear in plaintext —
    that premise is the entire reason for keeping keys in the Keychain, and
    an exception that happens to quote a request header would break it
    silently and permanently, because the log is append-only.

    Most keys travel in headers; OpenAlex has no header form and is spliced
    into the URL inside `_http_get_text`, so no logged string should carry it
    by construction. This is the belt to that braces: the guarantee should
    not depend on every future connector, HTTP library and error message
    being careful. Scrubbing the value we already hold is cheap and does not
    care where the text came from — and it iterates every CONNECTABLE
    source, so an optional key is scrubbed exactly like a required one.
    """
    if not text or data_dir is None:
        return text
    for name in CONNECTABLE_SOURCES:
        key = resolve_source_key(name, data_dir)
        if key and key in text:
            text = text.replace(key, REDACTED)
    return text


def available_sources(data_dir: Any = None) -> list[str]:
    """Sources a run can actually query right now, in declaration order.

    Scholarly APIs that work anonymously, plus any publisher whose key is
    configured. SearXNG is intentionally not automatic.
    Querying an unconnected publisher would add three `unconfigured`
    failures to every single research run — a permanent row of red for a
    feature the user has not opted into. Not connecting Elsevier is a
    choice, not a fault, so it should be silent.

    SearXNG remains explicit-only. It can still be selected for a targeted
    web search, but configuring its address must not silently mix generic
    web results into every automatic scholarly research run. A malformed
    configured URL still surfaces here rather than hiding a settings error.
    """
    configured_searxng = bool(_searxng_base_url())
    return [
        name
        for name in SOURCE_ORDER
        if (name not in KEYED_SOURCES or resolve_source_key(name, data_dir))
        and name != SEARXNG_SOURCE
    ]


class PaperApiConnector:
    """Queries a paper-metadata API.

    Five are keyless (arXiv/Crossref/OpenAlex/Semantic Scholar/Europe PMC);
    three are publisher APIs that carry a credential in a request header
    (Elsevier/Springer/CORE).
    """

    def name(self) -> str:
        return "paper_api"

    async def harvest(
        self,
        source_spec: dict[str, Any],
    ) -> list[RawDocument]:
        """Fetch bounded pages for one source, stopping on exhaustion."""
        source = source_spec.get("source") or DEFAULT_PAPER_SOURCE
        raw_cap = source_spec.get("max_records")
        cap = (
            DEFAULT_HARVEST_LIMIT if raw_cap is None
            else int(raw_cap)
        )
        cap = max(1, min(cap, MAX_HARVEST_LIMIT))
        raw_page_size = source_spec.get("page_size")
        page_size = (
            MAX_LIMIT if raw_page_size is None
            else int(raw_page_size)
        )
        page_size = max(1, min(page_size, MAX_LIMIT, cap))
        if source in {BIORXIV_SOURCE, CLINICALTRIALS_SOURCE}:
            check_paper_query(source, str(source_spec.get("query") or ""))
        if source == BIORXIV_SOURCE:
            documents = await self._harvest_biorxiv(source_spec, cap)
        elif source == CLINICALTRIALS_SOURCE:
            documents = await self._harvest_clinicaltrials(
                source_spec,
                cap,
                page_size,
            )
        else:
            max_pages = (
                (cap + page_size - 1) // page_size
                if source in PAGINATED_SOURCES
                else 1
            )
            documents = []
            seen: set[str] = set()
            for page in range(1, max_pages + 1):
                page_documents = await self.fetch(
                    {
                        **source_spec,
                        "limit": page_size,
                        "page": page,
                    }
                )
                new_documents = [
                    document
                    for document in page_documents
                    if document.dedupe_key not in seen
                ]
                for document in new_documents:
                    seen.add(document.dedupe_key)
                documents.extend(new_documents)
                if len(documents) >= cap:
                    break
                if len(page_documents) < page_size or not new_documents:
                    break
        axis = str(source_spec.get("search_axis") or "")
        original_query = str(
            source_spec.get("original_query")
            or source_spec.get("query")
            or ""
        )
        terms = tuple(
            str(term)
            for term in (source_spec.get("query_terms") or ())
            if str(term).strip()
        )
        if source in {
            ARXIV_SOURCE,
            CORE_SOURCE,
            ELSEVIER_SOURCE,
            SEMANTIC_SCHOLAR_SOURCE,
            SPRINGER_SOURCE,
        }:
            documents = [
                document
                for document in documents
                if _relevant(document, terms)
            ]
        return [
            replace(
                document,
                search_axis=axis,
                search_query=original_query,
            )
            for document in documents[:cap]
        ]

    async def _harvest_biorxiv(
        self,
        source_spec: dict[str, Any],
        cap: int,
    ) -> list[RawDocument]:
        """Iterate bioRxiv's fixed 30-record cursor pages."""
        query = str(source_spec.get("query") or "")
        build_url, parse = _SOURCE_DISPATCH[BIORXIV_SOURCE]
        base_url = build_url(query, 30)
        terms = {
            term.lower()
            for term in re.findall(r"[A-Za-z0-9가-힣]{3,}", query)
        }
        documents: list[RawDocument] = []
        seen: set[str] = set()
        cursor = 0
        total: int | None = None
        while len(documents) < cap:
            url = _biorxiv_cursor_url(base_url, cursor)
            body = await asyncio.to_thread(_http_get_text, url)
            payload = _json_object(body)
            collection = payload.get("collection")
            upstream_count = (
                len(collection) if isinstance(collection, list) else 0
            )
            messages = payload.get("messages")
            if isinstance(messages, list) and messages:
                message = messages[0]
                if isinstance(message, dict):
                    total = _integer(message.get("total")) or total
            page_documents = parse(body)
            for document in page_documents:
                if terms and not (
                    terms
                    & set(
                        re.findall(
                            r"[A-Za-z0-9가-힣]{3,}",
                            document.raw_text.lower(),
                        )
                    )
                ):
                    continue
                if document.dedupe_key in seen:
                    continue
                seen.add(document.dedupe_key)
                documents.append(document)
                if len(documents) == cap:
                    break
            cursor += 30
            if upstream_count < 30 or (total is not None and cursor >= total):
                break
        return documents

    async def _harvest_clinicaltrials(
        self,
        source_spec: dict[str, Any],
        cap: int,
        page_size: int,
    ) -> list[RawDocument]:
        """Follow ClinicalTrials.gov v2 `nextPageToken` pages."""
        query = str(source_spec.get("query") or "")
        build_url, parse = _SOURCE_DISPATCH[CLINICALTRIALS_SOURCE]
        base_url = build_url(query, page_size)
        documents: list[RawDocument] = []
        seen_documents: set[str] = set()
        seen_tokens: set[str] = set()
        token = ""
        while len(documents) < cap:
            url = _clinicaltrials_page_url(base_url, token)
            body = await asyncio.to_thread(_http_get_text, url)
            for document in parse(body):
                if document.dedupe_key in seen_documents:
                    continue
                seen_documents.add(document.dedupe_key)
                documents.append(document)
                if len(documents) == cap:
                    break
            next_token = str(
                _json_object(body).get("nextPageToken") or ""
            ).strip()
            if (
                not next_token
                or next_token == token
                or next_token in seen_tokens
            ):
                break
            seen_tokens.add(next_token)
            token = next_token
        return documents

    async def fetch(self, source_spec: dict[str, Any]) -> list[RawDocument]:
        source: str = source_spec.get("source") or DEFAULT_PAPER_SOURCE
        # Strip ONCE here so the allowlist check and the URL are built from
        # the same canonicalized query text.
        query: str = (source_spec.get("query") or "").strip()
        raw_limit = source_spec.get("limit")
        limit = DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
        limit = max(1, min(limit, _MAX_LIMIT))
        page = max(1, int(source_spec.get("page") or 1))
        # Allowlist BEFORE building a URL or touching the network.
        check_paper_query(source, query)
        check_source_implemented(source)
        build_url, parse = _SOURCE_DISPATCH[source]

        if source == SEARXNG_SOURCE:
            # No headers, no key, and one failure mode worth naming. Also
            # the only parser that needs `limit`: SearXNG takes no result
            # count, so the cap is applied to what came back rather than
            # asked for in the URL.
            return await self._fetch_searxng(
                build_url(query, limit), limit, parse
            )

        headers: dict[str, str] = {}
        data_dir = source_spec.get("data_dir")
        query_key: tuple[str, str] | None = None
        if source in KEYED_SOURCES:
            key = resolve_source_key(source, data_dir)
            if not key:
                # Refuse before the URL is built, let alone fetched. An
                # anonymous request to a publisher API is a 401 at best and
                # a silently empty page at worst, and either would read as
                # "this source found nothing".
                raise MissingSourceKey(
                    f"paper source {source!r} needs a publisher key; "
                    f"connect journal access first"
                )
            if source in _SOURCE_AUTH:
                headers = _SOURCE_AUTH[source](key)
            else:
                query_key = (_SOURCE_QUERY_AUTH[source], key)
        elif source in OPTIONAL_KEY_SOURCES:
            # No key is not an error here — it is the anonymous pool, which
            # works until it does not. Measured: OpenAlex and Semantic
            # Scholar both 429 from it on an ordinary query. So the key is
            # used when present and its absence is silent.
            key = resolve_source_key(source, data_dir)
            if key:
                where, name = _OPTIONAL_AUTH[source]
                if where == "header":
                    headers = {name: key}
                else:
                    query_key = (name, key)

        url = _paginate_url(source, build_url(query, limit), page, limit)
        if source == BIORXIV_SOURCE:
            # The API is a date-browse; the query filters this page locally.
            return await self._fetch_biorxiv(url, query, limit, parse)
        if source == PUBMED_SOURCE:
            # esearch gives PMIDs, efetch the abstracts: two requests.
            return await self._fetch_pubmed(url, parse, query_key)

        # `_http_get_text` is a blocking `urlopen`; this coroutine used to be
        # `async` in name only, so gathering five sources ran them one after
        # another — five serial 30s timeouts in the worst case. Handing the
        # whole helper to a thread keeps its internals in order: the offline
        # guard still runs inside it, before the socket, on that same thread.
        # `url` is keyless and stays that way. A query credential is handed
        # to the fetcher as data, not spliced into the string, so nothing
        # from here down — the failure text this coroutine raises, the
        # provenance line it becomes — can carry it.
        # Both extras are passed only when there is one, so the many
        # `lambda url: FIXTURE` monkeypatches in the suite keep matching.
        if headers and query_key is not None:
            body = await asyncio.to_thread(_http_get_text, url, headers, query_key)
        elif query_key is not None:
            body = await asyncio.to_thread(_http_get_text, url, None, query_key)
        elif headers:
            body = await asyncio.to_thread(_http_get_text, url, headers)
        else:
            body = await asyncio.to_thread(_http_get_text, url)
        return parse(body)

    async def _fetch_biorxiv(
        self, url: str, query: str, limit: int, parse: Any
    ) -> list[RawDocument]:
        """Browse one recent page of preprints, then filter it by the query.

        The API cannot search, so this is the documented pattern (narrow
        window + local filter): the builder fixes a 28-day window, this
        fetches the single most recent page of 100, and only preprints
        whose title or abstract shares a query term survive. `limit` caps
        the matches, mirroring what every other source's result count does.
        """
        body = await asyncio.to_thread(_http_get_text, url)
        docs = parse(body)
        terms = {
            t.lower() for t in re.findall(r"[A-Za-z0-9가-힣]{3,}", query)
        }
        if not terms:
            return []
        matched = [
            d for d in docs
            if terms & set(re.findall(r"[A-Za-z0-9가-힣]{3,}", d.raw_text.lower()))
        ]
        return matched[:limit]

    async def _fetch_pubmed(
        self,
        esearch_url: str,
        parse: Any,
        query_key: tuple[str, str] | None = None,
    ) -> list[RawDocument]:
        """esearch (keyword -> PMIDs), then efetch (PMIDs -> XML abstracts).

        Two requests, both to the same allowlisted host. An empty idlist is
        a normal answer, not an error: "PubMed found nothing" must read as
        a source that answered with nothing, exactly like the other sources.
        """
        async def _fetch_text(url: str) -> str:
            if query_key is None:
                return await asyncio.to_thread(_http_get_text, url)
            return await asyncio.to_thread(
                _http_get_text,
                url,
                query_key=query_key,
            )

        body = await _fetch_text(esearch_url)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{PUBMED_SOURCE} esearch response is not valid JSON"
            ) from exc
        ids = ((payload.get("esearchresult") or {}).get("idlist")) or []
        if not ids:
            return []
        efetch_url = _build_pubmed_efetch_url(ids)
        xml_body = await _fetch_text(efetch_url)
        return parse(xml_body)

    async def _fetch_searxng(
        self, url: str, limit: int, parse: Any
    ) -> list[RawDocument]:
        """Fetch SearXNG, naming the one misconfiguration everyone hits.

        A stock instance ships `formats: [html]` and answers `format=json`
        with `403` and an HTML body. Reported as `fetch_failed` that reads
        as a network problem, and the network is fine — so the refusal is
        recognised here and named.
        """
        from urllib.error import HTTPError

        try:
            body = await asyncio.to_thread(_http_get_text, url)
        except HTTPError as exc:
            if exc.code == 403:
                raise SearxngJsonDisabled(
                    "SearXNG refused format=json (403). Add `json` under "
                    "`search.formats` in its settings.yml and restart it — "
                    "a stock instance serves HTML only."
                ) from exc
            raise
        return parse(body, limit)


@dataclass(frozen=True)
class SourceFailure:
    """One source that did not answer, and why — kept, not discarded."""

    source: str
    error: str
    # rejected | unsupported | too_large | unconfigured | no_json |
    # fetch_failed
    kind: str


class SearxngJsonDisabled(Exception):
    """A SearXNG that answered, but refuses to answer in JSON.

    Its own default configuration ships `formats: [html]`, so this is the
    first thing a new instance does — a `403` with an HTML body, measured.
    Left as `fetch_failed` it reads as "the network is down" and sends the
    user to check a connection that is working perfectly.
    """


def _classify(exc: BaseException) -> str:
    if isinstance(exc, MissingSourceKey):
        # Not a failure to report as one: the source is simply not
        # connected, and calling that "fetch_failed" would send the user
        # looking for a network problem they do not have.
        return "unconfigured"
    if isinstance(exc, UnsupportedPaperSource):
        return "unsupported"
    if isinstance(exc, NotAllowlisted):
        return "rejected"
    if isinstance(exc, ResponseTooLarge):
        return "too_large"
    if isinstance(exc, SearxngJsonDisabled):
        return "no_json"
    return "fetch_failed"


async def fetch_sources(
    sources: Sequence[str],
    query: str,
    limit: int | None = None,
    data_dir: Any = None,
    on_event: Callable[[str, str, Any], None] | None = None,
    source_queries: Mapping[str, str] | None = None,
    search_axis: str = "",
    query_terms: Sequence[str] = (),
) -> tuple[list[tuple[str, list[RawDocument]]], list[SourceFailure]]:
    """Query several sources at once; keep what answered, report what did not.

    Returns `(batches, failures)` where `batches` is `(source, documents)` in
    the order given — the shape `collapse_duplicates` needs to break ties by
    declared source order.

    `on_event(kind, source, detail)` reports each source as it happens —
    `source_start` / `source_ok` (detail: document count) / `source_failed`
    (detail: failure kind). The return value cannot substitute for it: every
    source resolves together in `gather`, so a caller that waits for it sees
    nothing for the whole fan-out and then everything at once.

    Partial success is the point. Semantic Scholar rate-limits unauthenticated
    clients aggressively, and the previous all-or-nothing behaviour meant one
    429 discarded the other four sources' results. A failed source becomes a
    `SourceFailure` the caller can report beside the documents it did get.

    Offline mode is deliberately NOT handled here. Under
    `return_exceptions=True` a `NetworkBlocked` would arrive once per source
    and read as "five sources failed", losing the fact that the kill switch
    is what stopped them. The caller checks `paths.offline_mode()` before
    calling this, and the per-fetch `assert_network_allowed` stays as defence
    in depth.
    """
    connector = PaperApiConnector()
    max_records = DEFAULT_LIMIT if limit is None else limit
    specs = [
        {
            "source": name,
            "query": (
                source_queries.get(name, query)
                if source_queries is not None
                else query
            ),
            "original_query": query,
            "search_axis": search_axis,
            "query_terms": tuple(query_terms),
            "max_records": max_records,
            "page_size": MAX_LIMIT,
            "data_dir": data_dir,
        }
        for name in sources
    ]

    async def _traced(name: str, spec: dict[str, Any]) -> list[RawDocument]:
        """Fetch one source, announcing when it starts and how it ended.

        The events exist because the aggregate cannot be reconstructed into
        them afterwards. `gather` returns everything at once, so a caller
        watching only the return value learns "5 sources, 12 documents" and
        never which source was slow, which answered first, or that anything
        was happening at all during the wait — the run looked frozen.

        `on_event` is called for its side effect only and must not raise;
        a progress reporter that can fail the fetch it reports on would be
        worse than no reporter.
        """
        if on_event is not None:
            on_event("source_start", name, None)
        try:
            docs = await connector.harvest(spec)
        except BaseException as exc:
            if on_event is not None:
                on_event("source_failed", name, _classify(exc))
            raise
        if on_event is not None:
            on_event("source_ok", name, len(docs))
        return docs

    results = await asyncio.gather(
        *(_traced(name, spec) for name, spec in zip(sources, specs, strict=True)),
        return_exceptions=True,
    )
    batches: list[tuple[str, list[RawDocument]]] = []
    failures: list[SourceFailure] = []
    for name, result in zip(sources, results, strict=True):
        if isinstance(result, BaseException):
            if isinstance(result, NetworkBlocked):
                # The kill switch is not a per-source failure; surfacing it
                # as one would hide why nothing was fetched.
                raise result
            if isinstance(result, asyncio.CancelledError):
                raise result
            failures.append(
                SourceFailure(
                    source=name,
                    error=redact_keys(str(result), data_dir),
                    kind=_classify(result),
                )
            )
            continue
        batches.append((name, result))
    return batches, failures
