"""Paper-metadata API connectors (stdlib only).

Fetches public metadata + abstracts from paper APIs, in three categories:

* **Keyless** — arXiv (Atom XML), Crossref, Europe PMC (REST JSON). No
  credential exists to give them.
* **Optionally keyed** — OpenAlex and Semantic Scholar answer anonymously
  but share one pool with every other anonymous client, and both were
  measured returning `429 Too Many Requests` on an ordinary query from an
  unconfigured install. A key moves them out of that pool; its absence is
  not an error.
* **Keyed** — Elsevier (Scopus), Springer Nature, CORE. These refuse
  outright without a credential, so an unconfigured install does not
  query them at all rather than collecting three failures per run.

Each (source, query) pair is checked against the allowlist **before** any
network I/O (deny-by-default), mirroring the web_crawl connector's
enforcement point.

Three properties hold the keyed half together:

* **Fixed hosts.** Every endpoint is one constant, so `PAPER_API_HOSTS` is
  derived from them and exact-match stays possible. Full text is reached
  through publisher *APIs* for exactly this reason — crawling document pages
  would mean following `doi.org -> publisher -> CDN`, whose intermediate
  hosts cannot be enumerated ahead of time.
* **Credentials travel in headers wherever the API offers a header.** A key
  in a query string would reach the offline-refusal message,
  `provenance.jsonl`, `status.json`'s last_payload and the job log, none of
  which know a URL might be a secret. Elsevier and Springer also accept a
  query parameter; that route is not offered here. OpenAlex documents no
  header form at all, so it is the one exception — and it is contained
  rather than waived: `_with_query_key` splices the key on inside
  `_http_get_text`, after every string that might be logged has already
  been built without it.
* **Nothing crosses an origin.** `_AllowlistedPaperRedirect` re-checks every
  redirect hop and drops any header outside `_REDIRECT_SAFE_HEADERS` when the
  host changes, because `urllib` forwards credentials across origins where
  `requests`/`urllib3` would not.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ontologylab.connectors.allowlist import NotAllowlisted, check_paper_query
from ontologylab.paths import NetworkBlocked, assert_network_allowed
from ontologylab.connectors.base import (
    FETCH_TIMEOUT_S as _FETCH_TIMEOUT_S,
    USER_AGENT as _USER_AGENT,
    RawDocument,
    normalize_doi,
)

_ATOM_NS = "{http://www.w3.org/2005/Atom}"

# The only external endpoints this system ever fetches (all keyless).
ARXIV_API_URL = "https://export.arxiv.org/api/query"
CROSSREF_API_URL = "https://api.crossref.org/works"
OPENALEX_API_URL = "https://api.openalex.org/works"
SEMANTIC_SCHOLAR_API_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
)
# ClinicalTrials.gov REST v2. Keyless, and `query.term` is the same kind of
# free-text search the paper APIs take, so it fits the one-request source
# contract exactly as they do.
CLINICALTRIALS_API_URL = "https://clinicaltrials.gov/api/v2/studies"

EUROPEPMC_API_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
)
# Full text for the PMC open-access subset, served from the SAME host as the
# search above. That is the whole reason this is the full-text route: it adds
# no host to the allowlist, needs no PDF parser (the payload is JATS XML),
# and keeps the "fixed endpoints only" property that ruled out crawling
# doi.org -> publisher -> CDN. `{pmcid}` is the only interpolated part and it
# is validated by `_PMCID_RE` before it ever reaches a URL.
EUROPEPMC_FULLTEXT_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
)
# PMC identifiers are "PMC" followed by digits. Anchored because this value
# comes from a third-party API response and is interpolated into a path.
_PMCID_RE = re.compile(r"^PMC[0-9]{1,12}$")


def europepmc_fulltext_url(pmcid: str) -> str:
    """URL for one PMC article's full text, or "" when the id is not one.

    Refusing an unrecognised id here means a malformed or hostile `pmcid`
    can never become a path segment.
    """
    pmcid = (pmcid or "").strip()
    if not _PMCID_RE.match(pmcid):
        return ""
    return EUROPEPMC_FULLTEXT_URL.format(pmcid=pmcid)


# Publisher APIs — keyed, but still fixed hosts, which is what keeps them
# inside the exact-match allowlist. Reaching full text by crawling document
# pages instead would mean following doi.org -> publisher -> CDN, and those
# intermediate hosts cannot be enumerated ahead of time.
ELSEVIER_API_URL = "https://api.elsevier.com/content/search/scopus"
SPRINGER_API_URL = "https://api.springernature.com/meta/v2/json"
CORE_API_URL = "https://api.core.ac.uk/v3/search/works"

# Scopus omits `dc:description` from its STANDARD view, so the abstract has
# to be requested by name or the parser sees titles only.
_ELSEVIER_FIELDS = (
    "dc:title",
    "dc:description",
    "dc:creator",
    "prism:doi",
    "prism:publicationName",
    "prism:url",
)

# DOI resolver base for items that carry a DOI but no URL field.
DOI_BASE_URL = "https://doi.org/"
DEFAULT_LIMIT = 5
MAX_LIMIT = 25
_MAX_LIMIT = MAX_LIMIT  # back-compat alias

# The most a single paper API may hand back. 25 abstracts are a few hundred
# kilobytes, so this is generous for a legitimate answer while keeping a
# hostile or broken endpoint from being multiplied by a five-source fan-out.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# Canonical source names: the fetch dispatch, IMPLEMENTED_SOURCES, and the
# default all reference these — never re-type the strings.
ARXIV_SOURCE = "arxiv"
CROSSREF_SOURCE = "crossref"
OPENALEX_SOURCE = "openalex"
SEMANTIC_SCHOLAR_SOURCE = "semanticscholar"
CLINICALTRIALS_SOURCE = "clinicaltrials"
EUROPEPMC_SOURCE = "europepmc"
ELSEVIER_SOURCE = "elsevier"
SPRINGER_SOURCE = "springer"
CORE_SOURCE = "core"
DEFAULT_PAPER_SOURCE = ARXIV_SOURCE

# IMPLEMENTED_SOURCES is DERIVED from _SOURCE_DISPATCH, further down this
# file. It cannot be written here: the dispatch table references builders and
# parsers defined below. Everything in this module reads the name at call
# time, so the later binding is the one they see.

# Crossref fields we request AND the exact keys parse_crossref reads —
# dropping one here silently empties the corresponding parsed value, so the
# two stay coupled through this tuple.
_CROSSREF_SELECT_FIELDS = ("DOI", "URL", "title", "abstract")


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


def check_paper_host(url: str) -> str:
    """Validate a paper-API URL's host; return it unchanged.

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
    host = (parsed.hostname or "").lower()
    if host not in PAPER_API_HOSTS:
        raise NotAllowlisted(
            f"paper API redirect to host {host!r} is not on the allowlist "
            f"(allowed: {sorted(PAPER_API_HOSTS)})"
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
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        old_host = (urlparse(req.full_url).hostname or "").lower()
        new_host = (urlparse(newurl).hostname or "").lower()
        if old_host != new_host:
            for name in list(new.headers):
                if name.lower() not in _REDIRECT_SAFE_HEADERS:
                    del new.headers[name]
        return new


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

    OpenAlex leaves no choice: its documented mechanism is `api_key=` and
    there is no header form. So the exception is contained rather than
    waived: this returns a string that goes straight into `urlopen` and is
    bound to no name that anything else reads. Its one caller is the line
    below `assert_network_allowed`, so the keyless `url` remains what the
    guard, the size error and any raised exception are built from.
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


def _build_query_url(query: str, limit: int) -> str:
    return (
        f"{ARXIV_API_URL}"
        f"?search_query=all:{quote_plus(query)}"
        f"&start=0&max_results={limit}"
    )


def _build_crossref_url(query: str, limit: int) -> str:
    # `select` keeps the payload to exactly the fields we ingest.
    return (
        f"{CROSSREF_API_URL}"
        f"?query={quote_plus(query)}"
        f"&rows={limit}"
        "&select=" + ",".join(_CROSSREF_SELECT_FIELDS)
    )


# OpenAlex routes requests carrying a contact `mailto` into a faster,
# more lenient "polite pool". The address is read from the environment at
# request time (never hard-coded / committed); absent -> the common pool.
OPENALEX_MAILTO_ENV = "OPENALEX_MAILTO"


def _openalex_mailto() -> str:
    return os.environ.get(OPENALEX_MAILTO_ENV, "").strip()


def _build_openalex_url(query: str, limit: int) -> str:
    url = (
        f"{OPENALEX_API_URL}"
        f"?search={quote_plus(query)}"
        f"&per-page={limit}"
        "&select=id,doi,display_name,abstract_inverted_index"
    )
    mailto = _openalex_mailto()
    if mailto:
        url += f"&mailto={quote_plus(mailto)}"
    return url


def _build_semanticscholar_url(query: str, limit: int) -> str:
    return (
        f"{SEMANTIC_SCHOLAR_API_URL}"
        f"?query={quote_plus(query)}"
        f"&limit={limit}"
        "&fields=title,abstract,url,externalIds"
    )


def _build_europepmc_url(query: str, limit: int) -> str:
    return (
        f"{EUROPEPMC_API_URL}"
        f"?query={quote_plus(query)}"
        f"&pageSize={limit}"
        "&format=json&resultType=core"
    )


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_atom(xml_text: str) -> list[RawDocument]:
    """Parse an arXiv Atom feed into RawDocuments (title + abstract only)."""
    # Why the stdlib parser is enough here — stated accurately, because the
    # earlier justification was not. `ET.fromstring` DOES expand internal
    # entities, so "no external entities" was never the protection. What
    # actually bounds a billion-laughs payload is libexpat's amplification
    # limit (100x, 8 MiB threshold, expat >= 2.4), measured: a seven-stage
    # bomb is refused with `ParseError: limit on input amplification factor
    # breached`. A four-stage one stays under the threshold and parses, which
    # is why `_http_get_text` caps the input that expansion multiplies.
    root = ET.fromstring(xml_text)
    documents: list[RawDocument] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        title = _normalize(entry.findtext(f"{_ATOM_NS}title"))
        abstract = _normalize(entry.findtext(f"{_ATOM_NS}summary"))
        if not title and not abstract:
            continue
        source_uri = _normalize(entry.findtext(f"{_ATOM_NS}id"))
        if not source_uri:
            # No <id> -> no usable source_uri -> no provenance trail;
            # such an entry must never become a document row.
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                # arXiv Atom entries carry no DOI. Leaving it None makes the
                # entry de-duplicate on its `<id>` URL instead of colliding
                # with every other DOI-less document under a shared key.
                doi=None,
            )
        )
    return documents


# JATS/XML markup inside Crossref abstracts ("<jats:p>...</jats:p>").
_MARKUP_TAG_RE = re.compile(r"<[^>]+>")


def parse_crossref(json_text: str) -> list[RawDocument]:
    """Parse a Crossref /works JSON response into RawDocuments.

    Same ingest contract as parse_atom: title + abstract only, and an item
    with no usable source URI (URL or DOI) never becomes a document row —
    no provenance trail, no ingestion. Abstracts arrive as JATS XML
    fragments; markup is stripped to plain text.
    """
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"crossref response is not valid JSON: {exc}") from exc
    items = ((payload.get("message") or {}).get("items")) or []
    documents: list[RawDocument] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        titles = item.get("title") or []
        title = _normalize(" ".join(titles) if isinstance(titles, list) else titles)
        abstract = _normalize(_MARKUP_TAG_RE.sub(" ", item.get("abstract") or ""))
        if not title and not abstract:
            continue
        doi = _normalize(item.get("DOI"))
        source_uri = _normalize(item.get("URL")) or (
            f"{DOI_BASE_URL}{doi}" if doi else ""
        )
        if not source_uri:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
            )
        )
    return documents


def _load_json(json_text: str, source: str) -> Any:
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{source} response is not valid JSON: {exc}"
        ) from exc


def _restore_inverted_abstract(inverted: Any) -> str:
    """Rebuild plain text from OpenAlex's abstract_inverted_index.

    The index maps each word to the list of positions where it occurs;
    placing every word at its positions and joining restores the abstract.
    """
    if not isinstance(inverted, dict) or not inverted:
        return ""
    slots: dict[int, str] = {}
    for word, positions in inverted.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int) and pos >= 0:
                slots[pos] = str(word)
    return " ".join(slots[i] for i in sorted(slots))


def parse_openalex(json_text: str) -> list[RawDocument]:
    """Parse an OpenAlex /works JSON response into RawDocuments."""
    payload = _load_json(json_text, OPENALEX_SOURCE)
    documents: list[RawDocument] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("display_name"))
        abstract = _normalize(
            _restore_inverted_abstract(item.get("abstract_inverted_index"))
        )
        if not title and not abstract:
            continue
        # OpenAlex serves `doi` as a full https://doi.org/... URL and `id`
        # as a canonical openalex.org URL — either is a provenance trail.
        # The URL form is why `normalize_doi` strips resolver prefixes: this
        # is the one source whose DOI does not arrive bare.
        source_uri = _normalize(item.get("doi")) or _normalize(item.get("id"))
        if not source_uri:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(item.get("doi")),
            )
        )
    return documents


def parse_semanticscholar(json_text: str) -> list[RawDocument]:
    """Parse a Semantic Scholar /paper/search JSON response."""
    payload = _load_json(json_text, SEMANTIC_SCHOLAR_SOURCE)
    documents: list[RawDocument] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        abstract = _normalize(item.get("abstract"))
        if not title and not abstract:
            continue
        external = item.get("externalIds") or {}
        doi = _normalize(
            external.get("DOI") if isinstance(external, dict) else ""
        )
        source_uri = _normalize(item.get("url")) or (
            f"{DOI_BASE_URL}{doi}" if doi else ""
        )
        if not source_uri:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
            )
        )
    return documents


def _build_clinicaltrials_url(query: str, limit: int) -> str:
    # `fields` keeps the payload to what the parser reads. Without it a
    # study record is tens of kilobytes of arms, eligibility and locations,
    # and a five-source fan-out multiplies that.
    fields = ",".join(
        (
            "NCTId",
            "BriefTitle",
            "OfficialTitle",
            "BriefSummary",
            "DetailedDescription",
            "OverallStatus",
            "Condition",
        )
    )
    return (
        f"{CLINICALTRIALS_API_URL}"
        f"?query.term={quote_plus(query)}"
        f"&pageSize={limit}"
        f"&fields={fields}"
        "&format=json"
    )


def parse_clinicaltrials(json_text: str) -> list[RawDocument]:
    """Parse a ClinicalTrials.gov v2 /studies response.

    A trial is not a paper and the difference is the point: this is what was
    attempted on people, including the arms that never produced a
    publication. The registry's prose fields — brief summary and detailed
    description — are what the extractor can ground spans in, so a record
    with neither is skipped rather than stored as a bare title.

    No DOI: trials are identified by NCT number, and inventing a DOI-shaped
    key would collide with the paper de-duplicator.
    """
    payload = _load_json(json_text, CLINICALTRIALS_SOURCE)
    studies = payload.get("studies") or []
    documents: list[RawDocument] = []
    for study in studies:
        if not isinstance(study, dict):
            continue
        protocol = study.get("protocolSection") or {}
        ident = protocol.get("identificationModule") or {}
        desc = protocol.get("descriptionModule") or {}

        nct_id = _normalize(ident.get("nctId"))
        if not nct_id:
            continue
        title = _normalize(
            ident.get("briefTitle") or ident.get("officialTitle")
        )
        summary = _normalize(desc.get("briefSummary"))
        detail = _normalize(desc.get("detailedDescription"))
        body = "\n\n".join(part for part in (summary, detail) if part)
        if not body:
            # Title-only records give the extractor nothing to cite.
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=f"https://clinicaltrials.gov/study/{nct_id}",
                title=title or nct_id,
                raw_text=body,
            )
        )
    return documents


def parse_europepmc(json_text: str) -> list[RawDocument]:
    """Parse a Europe PMC /search JSON response (resultType=core)."""
    payload = _load_json(json_text, EUROPEPMC_SOURCE)
    results = ((payload.get("resultList") or {}).get("result")) or []
    documents: list[RawDocument] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        abstract = _normalize(
            _MARKUP_TAG_RE.sub(" ", item.get("abstractText") or "")
        )
        if not title and not abstract:
            continue
        doi = _normalize(item.get("doi"))
        src = _normalize(item.get("source"))
        ext_id = _normalize(item.get("id"))
        # `resultType=core` already carries the open-access flags; the
        # earlier parser read the response and threw them away, so every
        # collect stopped at the abstract even for articles whose full text
        # was one request further on. `inEPMC` is the one that matters:
        # isOpenAccess can be Y while the text lives somewhere Europe PMC
        # does not serve, and only the EPMC-hosted subset is reachable
        # without leaving the allowlisted host.
        fulltext_url = ""
        if _normalize(item.get("inEPMC")).upper() == "Y":
            fulltext_url = europepmc_fulltext_url(_normalize(item.get("pmcid")))
        oa_pdf = ""
        for entry in (item.get("fullTextUrlList") or {}).get("fullTextUrl", []):
            if not isinstance(entry, dict):
                continue
            if (
                _normalize(entry.get("documentStyle")).lower() == "pdf"
                and _normalize(entry.get("availability")).lower() == "open access"
            ):
                oa_pdf = _normalize(entry.get("url"))
                break
        source_uri = (
            f"{DOI_BASE_URL}{doi}" if doi
            else (
                f"https://europepmc.org/abstract/{src}/{ext_id}"
                if src and ext_id else ""
            )
        )
        if not source_uri:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                pdf_url=oa_pdf or None,
                fulltext_url=fulltext_url or None,
            )
        )
    return documents


# source -> (url builder, response parser). Adding a source = one endpoint
# constant + one builder + one parser + one row here (+ the allowlist entry).
# ---------------------------------------------------------------------------
# Publisher APIs (keyed). Endpoints are fixed hosts, exactly like the keyless
# five — which is the whole reason full text is reached through APIs and not
# by crawling document pages, whose doi.org -> publisher -> CDN redirect
# chains cannot be enumerated in advance.
# ---------------------------------------------------------------------------


def _build_elsevier_url(query: str, limit: int) -> str:
    # `field` is required to get an abstract: the STANDARD view omits
    # `dc:description`, so without this the parser would return titles only.
    return (
        f"{ELSEVIER_API_URL}"
        f"?query={quote_plus(query)}"
        f"&count={limit}"
        "&field=" + ",".join(_ELSEVIER_FIELDS)
    )


def _build_springer_url(query: str, limit: int) -> str:
    return f"{SPRINGER_API_URL}?q={quote_plus(query)}&p={limit}"


def _build_core_url(query: str, limit: int) -> str:
    return f"{CORE_API_URL}?q={quote_plus(query)}&limit={limit}"


def parse_elsevier(json_text: str) -> list[RawDocument]:
    """Parse a Scopus Search response (`search-results.entry`).

    Scopus keys are OpenSearch/PRISM-namespaced, so the field names carry
    their prefixes literally: `dc:title`, `dc:description`, `prism:doi`.
    """
    payload = _load_json(json_text, ELSEVIER_SOURCE)
    entries = ((payload.get("search-results") or {}).get("entry")) or []
    documents: list[RawDocument] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        # An error entry carries `error` instead of a record; skipping keeps
        # one bad row from emptying an otherwise good page.
        if item.get("error"):
            continue
        title = _normalize(item.get("dc:title"))
        abstract = _normalize(item.get("dc:description"))
        if not title and not abstract:
            continue
        doi = _normalize(item.get("prism:doi"))
        source_uri = f"{DOI_BASE_URL}{doi}" if doi else _normalize(item.get("prism:url"))
        if not source_uri:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
            )
        )
    return documents


def parse_springer(json_text: str) -> list[RawDocument]:
    """Parse a Springer Nature Meta v2 response (`records`)."""
    payload = _load_json(json_text, SPRINGER_SOURCE)
    records = payload.get("records") or []
    documents: list[RawDocument] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        # `abstract` is a string on most records but an object with `p` on
        # structured ones; neither shape is worth a crash.
        raw_abstract = item.get("abstract")
        if isinstance(raw_abstract, dict):
            raw_abstract = raw_abstract.get("p") or ""
        if isinstance(raw_abstract, list):
            raw_abstract = " ".join(str(part) for part in raw_abstract)
        abstract = _normalize(_MARKUP_TAG_RE.sub(" ", str(raw_abstract or "")))
        if not title and not abstract:
            continue
        doi = _normalize(item.get("doi"))
        source_uri = f"{DOI_BASE_URL}{doi}" if doi else _first_springer_url(item)
        if not source_uri:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                pdf_url=_first_springer_url(item, want_pdf=True) or None,
            )
        )
    return documents


def _first_springer_url(item: dict, *, want_pdf: bool = False) -> str:
    """Springer's `url` is a list of {format, platform, value} objects."""
    urls = item.get("url")
    if not isinstance(urls, list):
        return ""
    for entry in urls:
        if not isinstance(entry, dict):
            continue
        fmt = str(entry.get("format") or "").lower()
        if want_pdf and fmt != "pdf":
            continue
        if not want_pdf and fmt == "pdf":
            continue
        value = _normalize(entry.get("value"))
        if value:
            return value
    return ""


def parse_core(json_text: str) -> list[RawDocument]:
    """Parse a CORE v3 `search/works` response (`results`)."""
    payload = _load_json(json_text, CORE_SOURCE)
    results = payload.get("results") or []
    documents: list[RawDocument] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = _normalize(item.get("title"))
        abstract = _normalize(item.get("abstract"))
        if not title and not abstract:
            continue
        doi = _normalize(item.get("doi"))
        source_uri = (
            f"{DOI_BASE_URL}{doi}" if doi
            else _normalize(item.get("fullTextIdentifier"))
        )
        if not source_uri:
            continue
        documents.append(
            RawDocument(
                source_kind="paper_api",
                source_uri=source_uri,
                title=title or None,
                raw_text=f"{title}\n\n{abstract}",
                doi=normalize_doi(doi),
                pdf_url=_normalize(item.get("downloadUrl")) or None,
            )
        )
    return documents


# How each keyed source carries its credential. Header-only, deliberately:
# a key in a query string reaches the offline-refusal message, the
# provenance record, `status.json`'s last_payload and the job log, all of
# which this system writes without knowing a URL might be a secret. Elsevier
# and Springer both accept a query parameter as well; that route is not
# offered here.
_SOURCE_AUTH = {
    ELSEVIER_SOURCE: lambda key: {"X-ELS-APIKey": key, "Accept": "application/json"},
    SPRINGER_SOURCE: lambda key: {"X-API-Key": key, "Accept": "application/json"},
    CORE_SOURCE: lambda key: {"Authorization": f"Bearer {key}",
                              "Accept": "application/json"},
}


_SOURCE_DISPATCH = {
    ARXIV_SOURCE: (_build_query_url, parse_atom),
    CROSSREF_SOURCE: (_build_crossref_url, parse_crossref),
    OPENALEX_SOURCE: (_build_openalex_url, parse_openalex),
    SEMANTIC_SCHOLAR_SOURCE: (_build_semanticscholar_url, parse_semanticscholar),
    EUROPEPMC_SOURCE: (_build_europepmc_url, parse_europepmc),
    CLINICALTRIALS_SOURCE: (_build_clinicaltrials_url, parse_clinicaltrials),
    ELSEVIER_SOURCE: (_build_elsevier_url, parse_elsevier),
    SPRINGER_SOURCE: (_build_springer_url, parse_springer),
    CORE_SOURCE: (_build_core_url, parse_core),
}

# Sources that cannot be queried without a credential. Kept derived from
# `_SOURCE_AUTH` so a keyed source can never be added to the dispatch table
# and then silently queried anonymously.
KEYED_SOURCES: frozenset[str] = frozenset(_SOURCE_AUTH)

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
    CLINICALTRIALS_SOURCE: "ClinicalTrials.gov",
    ELSEVIER_SOURCE: "Elsevier (Scopus)",
    SPRINGER_SOURCE: "Springer Nature",
    CORE_SOURCE: "CORE",
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

    The keyless five, plus any publisher source whose key is configured.
    Querying an unconnected publisher would add three `unconfigured`
    failures to every single research run — a permanent row of red for a
    feature the user has not opted into. Not connecting Elsevier is a
    choice, not a fault, so it should be silent.
    """
    return [
        name
        for name in SOURCE_ORDER
        if name not in KEYED_SOURCES or resolve_source_key(name, data_dir)
    ]


class PaperApiConnector:
    """Queries a paper-metadata API.

    Five are keyless (arXiv/Crossref/OpenAlex/Semantic Scholar/Europe PMC);
    three are publisher APIs that carry a credential in a request header
    (Elsevier/Springer/CORE).
    """

    def name(self) -> str:
        return "paper_api"

    async def fetch(self, source_spec: dict[str, Any]) -> list[RawDocument]:
        source: str = source_spec.get("source") or DEFAULT_PAPER_SOURCE
        # Strip ONCE here so the allowlist check and the URL are built from
        # the same canonicalized query text.
        query: str = (source_spec.get("query") or "").strip()
        raw_limit = source_spec.get("limit")
        limit = DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
        limit = max(1, min(limit, _MAX_LIMIT))
        # Allowlist BEFORE building a URL or touching the network.
        check_paper_query(source, query)
        check_source_implemented(source)
        build_url, parse = _SOURCE_DISPATCH[source]

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
            headers = _SOURCE_AUTH[source](key)
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

        # `_http_get_text` is a blocking `urlopen`; this coroutine used to be
        # `async` in name only, so gathering five sources ran them one after
        # another — five serial 30s timeouts in the worst case. Handing the
        # whole helper to a thread keeps its internals in order: the offline
        # guard still runs inside it, before the socket, on that same thread.
        url = build_url(query, limit)
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


@dataclass(frozen=True)
class SourceFailure:
    """One source that did not answer, and why — kept, not discarded."""

    source: str
    error: str
    kind: str  # rejected | unsupported | too_large | unconfigured | fetch_failed


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
    return "fetch_failed"


async def fetch_sources(
    sources: Sequence[str],
    query: str,
    limit: int | None = None,
    data_dir: Any = None,
    on_event: Callable[[str, str, Any], None] | None = None,
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
    specs = [
        {"source": name, "query": query, "limit": limit, "data_dir": data_dir}
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
            docs = await connector.fetch(spec)
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
