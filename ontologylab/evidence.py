"""What kind of record a document is, and how sure we are of that.

Approving a proposal means judging whether the source says it. A reviewer
who cannot tell a peer-reviewed article from a preprint from a trial
registration is judging one of those questions blind — and until now the
store could not tell them apart either: thirteen of twenty-three documents
recorded `doi.org` as their host and nothing else.

The tempting design is a map from source to grade. Measured against the
live APIs, it is wrong for most documents:

* Crossref, asked for four BRCA1/PARP works, returned two `report`, one
  `book-chapter` and one `posted-content` (a preprint). No journal article
  at all.
* Europe PMC returns `source=MED` for PubMed records and `source=PPR` for
  preprints in the same result list.

So the grade is read from the record where the API states it, and only
falls back to what the source itself guarantees — arXiv is a preprint
server, ClinicalTrials.gov holds trial registrations, publisher APIs serve
their own journals. Everything else is `UNKNOWN`, which is a real answer
and displayed as one.

`UNKNOWN` is deliberately not collapsed into either side. Crossref assigns
DOIs to predatory journals, and a bioRxiv preprint can later appear in
Nature; a system that guessed would be confidently wrong in both
directions. Naming the uncertainty is what lets a reviewer decide whether
to go and look.
"""

from __future__ import annotations

from typing import Any, Optional

# The grades, ordered from most to least scrutiny. Deliberately coarse:
# these are distinctions a reviewer can act on, not a quality score. A
# journal article from a predatory publisher and one from Nature are both
# PEER_REVIEWED here — this records what kind of thing it is, and judging
# it stays the reviewer's job.
PEER_REVIEWED = "peer_reviewed"
PREPRINT = "preprint"
# Not a paper: a registered study, with no findings and no review.
REGISTRATION = "registration"
# Books, chapters, theses, datasets, reports — reviewed in some sense,
# but not through journal peer review, and not comparable to it.
OTHER = "other"
UNKNOWN = "unknown"

GRADES = (PEER_REVIEWED, PREPRINT, REGISTRATION, OTHER, UNKNOWN)

# Sources whose every record is one kind of thing, by construction.
_SOURCE_GRADE: dict[str, str] = {
    "arxiv": PREPRINT,
    "biorxiv": PREPRINT,
    "pubmed": PEER_REVIEWED,
    "medrxiv": PREPRINT,
    "clinicaltrials": REGISTRATION,
    # Publisher APIs search their own journal catalogues.
    "elsevier": PEER_REVIEWED,
    "springer": PEER_REVIEWED,
}

# Crossref `type`. `posted-content` is what Crossref calls a preprint —
# bioRxiv and medRxiv both register DOIs this way.
_CROSSREF_TYPE: dict[str, str] = {
    "journal-article": PEER_REVIEWED,
    "proceedings-article": PEER_REVIEWED,
    "posted-content": PREPRINT,
    "book": OTHER,
    "book-chapter": OTHER,
    "monograph": OTHER,
    "report": OTHER,
    "dissertation": OTHER,
    "dataset": OTHER,
}

# OpenAlex `type` (Crossref-derived, with its own spellings).
_OPENALEX_TYPE: dict[str, str] = {
    "article": PEER_REVIEWED,
    "preprint": PREPRINT,
    "book": OTHER,
    "book-chapter": OTHER,
    "dissertation": OTHER,
    "report": OTHER,
    "dataset": OTHER,
    "paratext": OTHER,
}

# Europe PMC states this in two places. `source` is the collection the
# record lives in (MED = PubMed, PPR = preprint server, CTX = books);
# `pubType` is free text that also says "preprint". `source` is checked
# first because it is a controlled code and `pubType` is not.
_EUROPEPMC_SOURCE: dict[str, str] = {
    "MED": PEER_REVIEWED,
    "PMC": PEER_REVIEWED,
    "AGR": PEER_REVIEWED,
    "CBA": PEER_REVIEWED,
    "PPR": PREPRINT,
    "CTX": OTHER,
    "ETH": OTHER,      # theses
    "HIR": OTHER,
    "NBK": OTHER,      # bookshelf
}


def grade_from_source(source: str) -> str:
    """What this source guarantees about every record it returns.

    `UNKNOWN` for the aggregators — Crossref, OpenAlex, Semantic Scholar,
    Europe PMC, CORE and SearXNG all return a mixture, so the source name
    alone says nothing and pretending otherwise mislabels most documents.
    """
    return _SOURCE_GRADE.get(source, UNKNOWN)


def grade_from_record(source: str, record: Any) -> str:
    """Read the grade off the record itself, falling back to the source.

    Takes the raw API item so each source's own vocabulary is read where
    it lives, rather than every parser having to learn this module's.
    """
    if not isinstance(record, dict):
        return grade_from_source(source)

    if source == "crossref":
        grade = _CROSSREF_TYPE.get(str(record.get("type", "")).lower())
    elif source == "openalex":
        grade = _OPENALEX_TYPE.get(str(record.get("type", "")).lower())
    elif source == "europepmc":
        grade = _EUROPEPMC_SOURCE.get(str(record.get("source", "")).upper())
        if grade is None and "preprint" in str(record.get("pubType", "")).lower():
            grade = PREPRINT
    elif source == "semanticscholar":
        types = record.get("publicationTypes") or []
        lowered = {str(t).lower() for t in types}
        if "journalarticle" in lowered or "conference" in lowered:
            grade = PEER_REVIEWED
        elif lowered:
            grade = OTHER
        else:
            grade = None
    else:
        grade = None

    return grade if grade else grade_from_source(source)


def normalize(grade: Optional[str]) -> str:
    """Any stored value, coerced to one this system knows.

    Old rows predate the column and read back as empty; a grade this build
    has never heard of would otherwise reach the browser and render as a
    raw string next to real ones.
    """
    return grade if grade in GRADES else UNKNOWN
