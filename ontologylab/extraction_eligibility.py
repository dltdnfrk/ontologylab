"""Whether a document may be extracted directly: full text, or the user's own.

Research runs pick representations through the F9 selection policy, which
refuses abstract-only Works (``NO_ELIGIBLE_READY_FULL_TEXT``). The direct
entries — ``POST /api/extract`` and ``ontologylab extract`` — take explicit
document ids and, until todo 15, never asked; an abstract-only paper went
through them to completion. This module is the one answer for both entries,
for the implicit "every document" path they share, and for the
``/api/documents`` rows the dashboard keys its 추출 button on.

Eligible: the best Observation for the document (lowest
``usable_full_text_rank``) is ``fulltext``, or the document has no
Observation at all — a direct upload or manual ingest is the user's own full
document. Ineligible: it has Observations and the best is abstract, excerpt,
metadata_only, or a kind the policy does not know.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ontologylab.selection_policy import usable_full_text_rank
from ontologylab.selection_types import ContentKind

# A kind the policy does not know sorts after every kind it does and keeps
# its raw value; collapsing it to metadata_only (what selection_policy's
# parse_kind does for ranking) would hide what the store really holds.
UNKNOWN_CONTENT_KIND_RANK = len(ContentKind)

NOT_FULL_TEXT = "not_full_text"
UNKNOWN_DOCUMENT = "unknown_document"


@dataclass(frozen=True, slots=True)
class ExtractionEligibility:
    document_id: str
    eligible: bool
    # Best observed kind; None when the document has no Observation.
    content_kind: str | None
    # "" when eligible, else NOT_FULL_TEXT or UNKNOWN_DOCUMENT.
    code: str
    reason: str


def content_kind_rank(raw: str) -> int:
    try:
        return usable_full_text_rank(ContentKind(raw))
    except ValueError:
        return UNKNOWN_CONTENT_KIND_RANK


def best_content_kinds(
    conn: sqlite3.Connection, doc_ids: Iterable[str] | None = None
) -> dict[str, str]:
    """Best ``document_observations.content_kind`` per document.

    Best is the lowest ``usable_full_text_rank``; among equal ranks the newest
    Observation wins, so two reads give the same answer. A document with no
    Observation is absent from the result.
    """
    sql = (
        "SELECT representation_id, content_kind FROM document_observations "
        "WHERE representation_id IS NOT NULL"
    )
    params: tuple[str, ...] = ()
    if doc_ids is not None:
        ids = tuple(dict.fromkeys(doc_ids))
        if not ids:
            return {}
        sql += f" AND representation_id IN ({','.join('?' * len(ids))})"
        params = ids
    best: dict[str, tuple[int, str]] = {}
    for row in conn.execute(sql + " ORDER BY created_ts DESC, id DESC", params):
        kind = str(row["content_kind"])
        rank = content_kind_rank(kind)
        current = best.get(row["representation_id"])
        if current is None or rank < current[0]:
            best[row["representation_id"]] = (rank, kind)
    return {doc_id: kind for doc_id, (_rank, kind) in best.items()}


def eligibility_for_kind(doc_id: str, kind: str | None) -> ExtractionEligibility:
    if kind is None:
        return ExtractionEligibility(doc_id, True, None, "", "")
    if content_kind_rank(kind) == usable_full_text_rank(ContentKind.FULLTEXT):
        return ExtractionEligibility(doc_id, True, kind, "", "")
    return ExtractionEligibility(
        doc_id,
        False,
        kind,
        NOT_FULL_TEXT,
        f"held text is {kind!r}, not full text; abstract-only extraction is "
        "not allowed",
    )


def extraction_eligibilities(
    conn: sqlite3.Connection, doc_ids: Sequence[str]
) -> list[ExtractionEligibility]:
    """One verdict per requested id, in request order; unknown ids refuse."""
    ids = list(dict.fromkeys(doc_ids))
    if not ids:
        return []
    known: set[str] = set()
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        known.update(
            row["id"]
            for row in conn.execute(
                f"SELECT id FROM documents WHERE id IN "
                f"({','.join('?' * len(chunk))})",
                chunk,
            )
        )
    kinds = best_content_kinds(conn, [doc_id for doc_id in ids if doc_id in known])
    verdicts = []
    for doc_id in ids:
        if doc_id not in known:
            verdicts.append(
                ExtractionEligibility(
                    doc_id, False, None, UNKNOWN_DOCUMENT, "unknown document id"
                )
            )
        else:
            verdicts.append(eligibility_for_kind(doc_id, kinds.get(doc_id)))
    return verdicts


def extraction_eligibility(
    conn: sqlite3.Connection, doc_id: str
) -> tuple[bool, str]:
    verdict = extraction_eligibilities(conn, [doc_id])[0]
    return verdict.eligible, verdict.reason


def refused_extractions(
    conn: sqlite3.Connection, doc_ids: Sequence[str]
) -> list[ExtractionEligibility]:
    return [v for v in extraction_eligibilities(conn, doc_ids) if not v.eligible]


def refusal_message(refused: Sequence[ExtractionEligibility]) -> str:
    """The sentence /api/extract puts in its 4xx and the CLI prints."""
    parts = [
        f"{v.document_id} ({v.content_kind if v.content_kind is not None else 'no document'}): {v.reason}"
        for v in refused
    ]
    return (
        f"extraction refused for {len(refused)} document(s): " + "; ".join(parts)
    )
