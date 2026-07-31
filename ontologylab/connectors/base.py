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


def normalize_doi(raw: Any) -> str | None:
    """Reduce a DOI to its bare, comparable form, or None if there isn't one.

    The five paper sources hand back four different shapes for the same
    identifier — Crossref and Europe PMC give a bare ``10.x/y``, OpenAlex
    gives ``https://doi.org/10.x/y``, Semantic Scholar nests it under
    ``externalIds``. Cross-source de-duplication compares these, so they have
    to be reduced to one form first: strip any resolver prefix, casefold
    (DOIs are case-insensitive), and drop trailing punctuation a citation
    string tends to carry.

    arXiv is deliberately absent from that list: its entries have no DOI, so
    it must fall back to ``source_uri`` rather than inventing a key.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/",
                   "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    value = value.strip().rstrip(".,;)")
    if not value.startswith("10."):
        # Not a DOI. Returning None keeps a malformed value out of the
        # de-duplication key rather than making it collide with others.
        return None
    return value.casefold()


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


def collapse_duplicates(
    batches: Sequence[tuple[str, Sequence[RawDocument]]],
    source_order: Sequence[str] = (),
) -> list[RawDocument]:
    """Keep one document per identity, preferring the fullest abstract.

    Fanning out across sources returns the same paper several times, and
    keeping all of them would put five rows in the store for one work. The
    winner has to be chosen by a *stated* rule, not by arrival order: the
    abstracts differ per source, `content_hash` follows whichever text won,
    and `UNIQUE(content_hash)` cannot catch a re-run that picked differently.
    Without a rule, running the same query twice inserts the same paper
    twice, because the second run hashed a different abstract.

    The rule: longest `raw_text` wins, since the sources differ mainly in how
    much abstract survived their normalization. Ties break on `source_order`
    — the declaration order of the fetch dispatch — so the outcome is fixed
    rather than dependent on which request returned first. Arrival order is
    the last resort, and only among documents already equal on both.

    Input is `(source_name, documents)` pairs because `RawDocument.source_kind`
    is `"paper_api"` for all five: only the caller that dispatched the fetch
    knows which source answered.
    """
    rank = {name: index for index, name in enumerate(source_order)}
    unranked = len(rank)
    best: dict[str, tuple[tuple[int, int], int, RawDocument]] = {}
    arrival = 0
    for source_name, documents in batches:
        for doc in documents:
            # Lower sorts better, so negate length and read rank directly.
            score = (-len(doc.raw_text), rank.get(source_name, unranked))
            current = best.get(doc.dedupe_key)
            if current is None or (score, arrival) < (current[0], current[1]):
                best[doc.dedupe_key] = (score, arrival, doc)
            arrival += 1
    return [entry[2] for entry in sorted(best.values(), key=lambda e: e[1])]


@runtime_checkable
class Connector(Protocol):
    """A document-ingest backend. Must enforce the allowlist BEFORE any I/O."""

    def name(self) -> str:
        ...

    async def fetch(self, source_spec: dict[str, Any]) -> list[RawDocument]:
        ...
