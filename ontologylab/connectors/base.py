"""Connector Protocol + the raw-document record connectors return.

Modeled after (not copied from) drylab's clean domain Protocol style. A
connector fetches raw documents for a source spec; persistence into the
``documents`` table is the caller's job (main.collect), so connectors stay
side-effect-free apart from network I/O.
"""

from __future__ import annotations

import hashlib

from ontologylab import __version__

# Shared outbound HTTP identity + timeout for ALL connectors (single
# definition so the version tracks __version__ and the timeout can't drift).
USER_AGENT = f"ontologylab/{__version__} (+local, single-user)"
FETCH_TIMEOUT_S = 30.0
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


_RESOLVER_PREFIXES = ("https://doi.org/", "http://doi.org/",
                      "https://dx.doi.org/", "http://dx.doi.org/", "doi:")


def _strip_resolver_prefix(value: str) -> str:
    for prefix in _RESOLVER_PREFIXES:
        if value.lower().startswith(prefix):
            return value[len(prefix):].strip()
    return value


def normalize_doi(raw: Any) -> str | None:
    """Reduce a structured DOI *field* to its bare, comparable form.

    The five paper sources hand back four different shapes for the same
    identifier — Crossref and Europe PMC give a bare ``10.x/y``, OpenAlex
    gives ``https://doi.org/10.x/y``, Semantic Scholar nests it under
    ``externalIds``. Cross-source de-duplication compares these, so they
    have to be reduced to one form first: strip any resolver prefix and
    casefold (DOIs are case-insensitive).

    This is identifier-field semantics: the value IS the identifier, so no
    citation punctuation is peeled — registered DOIs legitimately end in
    ``)`` (e.g. ``10.1002/0471221929.ch26(vii)``) and stripping it corrupts
    the stored identity (C-029). Peeling the punctuation citation prose
    carries is `doi_from_citation_text`'s job. A value that does not look
    like a DOI (no ``10.`` prefix, no ``/`` between prefix and suffix, or
    whitespace/control characters inside) is refused rather than turned
    into a colliding de-duplication key.

    arXiv is deliberately absent from the resolver list: its entries have
    no DOI, so it must fall back to ``source_uri`` rather than inventing a
    key.
    """
    if not isinstance(raw, str):
        return None
    value = _strip_resolver_prefix(raw.strip())
    if not value.startswith("10.") or "/" not in value:
        return None
    if not value.isprintable() or any(ch.isspace() for ch in value):
        return None
    return value.casefold()


def doi_from_citation_text(text: Any) -> str | None:
    """Recover a DOI from a citation-prose fragment, or None.

    Prose carries sentence punctuation the identifier does not own: ``.``,
    ``,`` and ``;`` at the end are citation artifacts and are peeled. A
    trailing ``)`` is peeled only while the candidate holds more ``)`` than
    ``(`` — the one case where the parenthesis is provably not part of the
    DOI — so registered terminal-paren identifiers survive intact.
    """
    if not isinstance(text, str):
        return None
    candidate = _strip_resolver_prefix(text.strip())
    while candidate and candidate[-1] in ".,;":
        candidate = candidate[:-1]
    while candidate.endswith(")") and candidate.count(")") > candidate.count("("):
        candidate = candidate[:-1]
        while candidate and candidate[-1] in ".,;":
            candidate = candidate[:-1]
    return normalize_doi(candidate)


@dataclass
class RawDocument:
    """One fetched document, pre-persistence."""

    source_kind: str  # "paper_api" | "web_crawl" | "upload"
    source_uri: str
    title: str | None
    raw_text: str
    doi: str | None = None
    pdf_url: str | None = None
    # Which connector fetched this, and what kind of record it is. The URI
    # cannot answer either: thirteen of the first twenty-three documents
    # recorded `doi.org` as their host, which names neither the source that
    # found them nor whether anyone reviewed them.
    source: str = ""
    evidence_grade: str = ""
    # An allowlisted endpoint that serves this work's FULL TEXT, distinct
    # from `pdf_url`: a PDF link points wherever the publisher hosts it and
    # so cannot be reached without giving up exact-match host checking,
    # whereas this is always one of the fixed API hosts already in use.
    # Empty for everything outside the open-access subset.
    fulltext_url: str | None = None
    stage: str = ""
    content_kind: str = ""
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str | None = None
    cited_by: int | None = None
    publication_type: str | None = None
    retracted: bool | None = None
    search_axis: str = ""
    search_query: str = ""
    all_sources: tuple[str, ...] = ()
    search_axes: tuple[str, ...] = ()
    search_queries: tuple[str, ...] = ()

    @property
    def content_hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()

    @property
    def dedupe_key(self) -> str:
        """The identity two sources must agree on to be the same paper.

        `content_hash` cannot serve here: each source normalizes an abstract
        differently (Crossref strips JATS, OpenAlex rebuilds an inverted
        index, Semantic Scholar returns it verbatim), so the same paper
        hashes five ways. The DOI is the identity; the URI is the fallback
        for sources that have none.
        """
        return f"doi:{self.doi}" if self.doi else f"uri:{self.source_uri}"

    @property
    def source_count(self) -> int:
        return len(self.all_sources) or int(bool(self.source))


def collapse_duplicates(
    batches: Sequence[tuple[str, Sequence[RawDocument]]],
    source_order: Sequence[str] = (),
) -> list[RawDocument]:
    """Merge same-work records while retaining corroborating metadata."""
    from ontologylab.connectors.dedup import merge_document_batches

    return merge_document_batches(batches, source_order)


@runtime_checkable
class Connector(Protocol):
    """A document-ingest backend. Must enforce the allowlist BEFORE any I/O."""

    def name(self) -> str:
        ...

    async def fetch(self, source_spec: dict[str, Any]) -> list[RawDocument]:
        ...
