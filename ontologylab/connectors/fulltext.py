"""Open-access full text, fetched without widening the network boundary.

Collecting stopped at the abstract. An abstract states conclusions; the
methods, the measurements and the caveats — the parts a knowledge graph is
actually built from — are in the body, so extraction was working from a
summary of the evidence rather than the evidence.

The obvious route to full text is the one the architecture already refused:
following a DOI to a publisher to a CDN cannot be reconciled with an
exact-match host allowlist, because the intermediate hosts are not knowable
in advance. This module takes the other route. Europe PMC serves the PMC
open-access subset as JATS XML **from the same host as its search API**, so
full text costs exactly zero new allowlist entries, needs no PDF parser, and
keeps every existing guarantee — the host check, the redirect handler, the
size cap and the offline kill switch all apply unchanged, because this is
the same `_http_get_text` every other fetch goes through.

What that buys and what it does not: the PMC OA subset is millions of
articles including open-access Nature-family and Springer titles, but it is
not everything. A paywalled work still yields its abstract and nothing more,
and `RawDocument.pdf_url` is populated but deliberately unused — those links
point at arbitrary hosts, and following them is the trade this design
declined to make.

JATS is parsed with the stdlib. `xml.etree` is safe enough here for the same
measured reason `parse_atom` documents: expat's amplification limit refuses
entity bombs, and `_http_get_text` caps the input that expansion multiplies.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from xml.etree.ElementTree import ParseError

from ontologylab.connectors.base import RawDocument

# Sections carrying no research content. Dropped because they are long,
# formulaic, and would dominate a chunk budget that should be spent on
# findings — references especially, which can outweigh the body.
_SKIP_SECTION_TAGS = frozenset({"ref-list", "back", "fn-group", "table-wrap-foot"})

# Elements whose text is not prose: labels, captions on floats we cannot
# render, and inline citation markers that would otherwise litter sentences.
_SKIP_INLINE_TAGS = frozenset({"xref", "label", "graphic", "media", "inline-formula"})

# A body shorter than this is a stub — a correction notice, a retraction, an
# abstract-only record — and replacing a real abstract with it would lose
# information rather than add it.
MIN_FULLTEXT_CHARS = 500

# Hard ceiling on stored full text. Extraction chunks at ~6000 chars, so this
# is roughly 40 chunks: enough for a long paper, bounded enough that one
# pathological article cannot consume an entire run's engine budget.
MAX_FULLTEXT_CHARS = 250_000

_WS_RE = re.compile(r"[ \t]+")
_BLANK_RE = re.compile(r"\n{3,}")


def _local(tag: str) -> str:
    """Tag name without its namespace, if any."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _walk(element: ET.Element, out: list[str]) -> None:
    name = _local(element.tag)
    if name in _SKIP_SECTION_TAGS:
        return
    if name in _SKIP_INLINE_TAGS:
        # Skip the element's own text but keep what follows it, or words
        # butt together where a citation marker was removed.
        if element.tail:
            out.append(element.tail)
        return
    if name in ("title", "p", "sec", "abstract", "body", "article"):
        out.append("\n")
    if element.text:
        out.append(element.text)
    for child in element:
        _walk(child, out)
    if element.tail:
        out.append(element.tail)


def _find_all(root: ET.Element, name: str) -> list[ET.Element]:
    """Every element with this local name, namespace-insensitively."""
    return [el for el in root.iter() if _local(el.tag) == name]


def jats_to_text(xml_text: str) -> str:
    """Flatten a JATS article into readable prose.

    Only `<abstract>` and `<body>` are walked. Walking `<article>` whole was
    the first attempt and it was wrong in a way that mattered: JATS `<front>`
    holds journal-meta and article-meta, whose ISSNs, journal ids, PMC ids
    and author name-parts carry no separators between elements, so they
    flattened into runs like `3993bmcgendatBMC Genomic DataBMC Genom Data`.
    Those are not sentences, and the extractor would have proposed them as
    entities — noise indistinguishable from a finding, sitting in the review
    queue with a real-looking source span.

    Returns "" when the payload is not parseable XML — a full-text fetch
    failing is a degradation to the abstract, never an error that should
    stop a collect.
    """
    try:
        root = ET.fromstring(xml_text)
    except ParseError:
        return ""
    parts: list[str] = []
    for section in _find_all(root, "abstract") + _find_all(root, "body"):
        _walk(section, parts)
    text = "".join(parts)
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_RE.sub("\n\n", text).strip()


def fetch_fulltext(url: str, *, http_get=None) -> str:
    """Fetch and flatten one full-text document; "" on any failure.

    `http_get` defaults to `paper_api._http_get_text`, which is what applies
    the host allowlist, the redirect guard, the size cap and the offline kill
    switch. Passing a substitute is for tests only — production must go
    through that function, not around it.
    """
    if not url:
        return ""
    if http_get is None:
        from ontologylab.connectors.paper_api import _http_get_text

        http_get = _http_get_text
    try:
        payload = http_get(url)
    except Exception:
        # Deliberately broad, and deliberately silent about the reason here:
        # the caller records a per-document outcome, and a failed enrichment
        # must never turn a successful collect into a failed one.
        return ""
    return jats_to_text(payload)[:MAX_FULLTEXT_CHARS]


def enrich_with_fulltext(
    documents: list[RawDocument], *, http_get=None
) -> tuple[list[RawDocument], dict[str, int]]:
    """Replace abstracts with full text where an open-access copy exists.

    Returns the (possibly rewritten) documents and a stats dict. A rewritten
    document keeps its identity — same `source_uri`, same `doi`, so
    de-duplication and provenance are unaffected — but its `content_hash`
    changes with `raw_text`, which is correct: it is a different document
    now, and re-collecting the same paper later will match on DOI rather
    than on hash.

    The title is preserved as the first line so the extractor sees the same
    shape it always has.
    """
    stats = {"eligible": 0, "fetched": 0, "too_short": 0, "failed": 0}
    enriched: list[RawDocument] = []
    for document in documents:
        if not document.fulltext_url:
            enriched.append(document)
            continue
        stats["eligible"] += 1
        body = fetch_fulltext(document.fulltext_url, http_get=http_get)
        if not body:
            stats["failed"] += 1
            enriched.append(document)
            continue
        if len(body) < MIN_FULLTEXT_CHARS:
            stats["too_short"] += 1
            enriched.append(document)
            continue
        stats["fetched"] += 1
        title = document.title or ""
        enriched.append(
            RawDocument(
                source_kind=document.source_kind,
                source_uri=document.source_uri,
                title=document.title,
                raw_text=f"{title}\n\n{body}" if title else body,
                doi=document.doi,
                pdf_url=document.pdf_url,
                fulltext_url=document.fulltext_url,
            )
        )
    return enriched, stats


__all__ = [
    "MAX_FULLTEXT_CHARS",
    "MIN_FULLTEXT_CHARS",
    "enrich_with_fulltext",
    "fetch_fulltext",
    "jats_to_text",
]
