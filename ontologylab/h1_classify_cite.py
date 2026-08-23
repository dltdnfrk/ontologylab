"""Classify citation and review H1 anchors."""

from __future__ import annotations

import json
import sqlite3

from ontologylab.file_lifecycle import content_hash_for
from ontologylab.grounded_review_ids import citation_set_digest
from ontologylab.h1_bytes import load_document, run_for_representation
from ontologylab.h1_decisions import quarantine, verified
from ontologylab.h1_types import (
    H1CitationAnchor,
    H1Classification,
    H1Decision,
    H1Family,
    H1QuarantineReason,
    H1ReviewAnchor,
)


def classify_offsets(start: int, end: int, length: int) -> H1QuarantineReason | None:
    if start < 0 or end <= start or end > length:
        return H1QuarantineReason.OUT_OF_RANGE
    return None


def parse_span(raw: str | None) -> tuple[int, int] | H1QuarantineReason:
    if raw is None or raw == "":
        return H1QuarantineReason.MISSING_SPAN
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return H1QuarantineReason.MALFORMED_SPAN
    if not isinstance(payload, dict):
        return H1QuarantineReason.MALFORMED_SPAN
    start = payload.get("start")
    end = payload.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return H1QuarantineReason.MALFORMED_SPAN
    return start, end


def classify_citation(
    conn: sqlite3.Connection, anchor: H1CitationAnchor,
) -> H1Decision:
    parsed = parse_span(anchor.source_span)
    if isinstance(parsed, H1QuarantineReason):
        return quarantine(
            anchor, parsed, representation_id=anchor.representation_id,
            evidence=_cite_evidence(anchor, None, None),
        )
    start, end = parsed
    loaded = load_document(conn, anchor.representation_id)
    if isinstance(loaded, H1QuarantineReason):
        return quarantine(
            anchor, loaded, representation_id=anchor.representation_id,
            evidence=_cite_evidence(anchor, start, end),
        )
    ranged = classify_offsets(start, end, len(loaded.text))
    if ranged is not None:
        return quarantine(
            anchor, ranged, representation_id=anchor.representation_id,
            evidence=_cite_evidence(anchor, start, end),
        )
    if run_for_representation(conn, anchor.representation_id) is None:
        return quarantine(
            anchor, H1QuarantineReason.MISSING_RUN,
            representation_id=anchor.representation_id,
            evidence=_cite_evidence(anchor, start, end),
        )
    if containing_chunk(conn, anchor.representation_id, start, end) is None:
        return quarantine(
            anchor, H1QuarantineReason.MISSING_CHUNK,
            representation_id=anchor.representation_id,
            evidence=_cite_evidence(anchor, start, end),
        )
    selected = loaded.text[start:end]
    return verified(
        anchor,
        representation_id=anchor.representation_id,
        raw_byte_seal=loaded.content_hash,
        file_hash=loaded.content_hash,
        span_hash=content_hash_for(selected.encode("utf-8")),
        evidence=_cite_evidence(anchor, start, end),
    )


def classify_review(
    conn: sqlite3.Connection, anchor: H1ReviewAnchor,
) -> H1Decision:
    if anchor.decided_ts is None:
        return quarantine(
            anchor, H1QuarantineReason.MISSING_TIMESTAMP,
            representation_id=anchor.representation_id,
            evidence=_review_evidence(anchor),
        )
    if not anchor.actor.strip():
        return quarantine(
            anchor, H1QuarantineReason.MISSING_ACTOR,
            representation_id=anchor.representation_id,
            evidence=_review_evidence(anchor),
        )
    if not anchor.reason.strip():
        return quarantine(
            anchor, H1QuarantineReason.MISSING_REASON,
            representation_id=anchor.representation_id,
            evidence=_review_evidence(anchor),
        )
    rows = conn.execute(
        "SELECT classification FROM h1_anchor_receipts "
        "WHERE family = ? AND json_extract(evidence_json, '$.fact_id') = ? "
        "AND json_extract(evidence_json, '$.fact_kind') = ?",
        (H1Family.CITATION.value, anchor.fact_id, anchor.fact_kind),
    ).fetchall()
    if not rows:
        return quarantine(
            anchor, H1QuarantineReason.MISSING_SPAN,
            representation_id=anchor.representation_id,
            evidence=_review_evidence(anchor),
        )
    if any(str(row[0]) != H1Classification.VERIFIED.value for row in rows):
        return quarantine(
            anchor, H1QuarantineReason.UNGROUNDED,
            representation_id=anchor.representation_id,
            evidence=_review_evidence(anchor),
        )
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'citation_receipts'"
    ).fetchone() is None:
        return quarantine(
            anchor, H1QuarantineReason.UNGROUNDED,
            representation_id=anchor.representation_id,
            evidence=_review_evidence(anchor),
        )
    cite_rows = conn.execute(
        "SELECT receipt_id, representation_content_hash FROM citation_receipts "
        "WHERE fact_kind = ? AND fact_id = ? ORDER BY receipt_id",
        (anchor.fact_kind, anchor.fact_id),
    ).fetchall()
    if not cite_rows:
        return quarantine(
            anchor, H1QuarantineReason.UNGROUNDED,
            representation_id=anchor.representation_id,
            evidence=_review_evidence(anchor),
        )
    digest = citation_set_digest(tuple(str(row[0]) for row in cite_rows))
    hashes = {str(row[1]) for row in cite_rows}
    file_hash = next(iter(hashes)) if len(hashes) == 1 else digest
    return verified(
        anchor,
        representation_id=anchor.representation_id,
        raw_byte_seal=file_hash,
        file_hash=file_hash,
        span_hash=digest,
        evidence=_review_evidence(anchor),
    )


def containing_chunk(
    conn: sqlite3.Connection, representation_id: str, start: int, end: int,
) -> sqlite3.Row | None:
    stored = conn.execute(
        "SELECT c.receipt_id FROM extraction_chunk_receipts c "
        "JOIN extraction_run_receipts r ON r.receipt_id = c.run_receipt_id "
        "WHERE r.representation_id = ? AND c.start_offset <= ? "
        "AND c.end_offset >= ? ORDER BY c.receipt_id",
        (representation_id, start, end),
    ).fetchone()
    if stored is not None:
        return stored
    for row in conn.execute(
        "SELECT evidence_json FROM h1_anchor_receipts "
        "WHERE family = ? AND classification = ? AND representation_id = ?",
        (
            H1Family.CHUNK.value,
            H1Classification.VERIFIED.value,
            representation_id,
        ),
    ):
        evidence = json.loads(str(row[0]))
        chunk_start = evidence.get("start")
        chunk_end = evidence.get("end")
        if (
            isinstance(chunk_start, int)
            and isinstance(chunk_end, int)
            and chunk_start <= start
            and end <= chunk_end
        ):
            return row
    return None


def _cite_evidence(
    anchor: H1CitationAnchor, start: int | None, end: int | None,
) -> dict[str, str | int | None]:
    return {
        "fact_kind": anchor.fact_kind,
        "fact_id": anchor.fact_id,
        "source_doc_id": anchor.representation_id,
        "start": start,
        "end": end,
    }


def _review_evidence(anchor: H1ReviewAnchor) -> dict[str, str | int | None]:
    return {
        "fact_kind": anchor.fact_kind,
        "fact_id": anchor.fact_id,
        "status": anchor.status,
        "actor": anchor.actor,
        "reason": anchor.reason,
    }
