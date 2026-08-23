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
    from ontologylab.h1_existing_cite import expected_cite_ids, verified_citation

    cite_ids = expected_cite_ids(conn, anchor.fact_kind, anchor.fact_id)
    if not cite_ids:
        return quarantine(
            anchor, H1QuarantineReason.UNGROUNDED,
            representation_id=anchor.representation_id,
            evidence=_review_evidence(anchor),
        )
    hashes = set()
    for receipt_id in cite_ids:
        loaded = verified_citation(conn, receipt_id)
        if loaded is None:
            return quarantine(
                anchor, H1QuarantineReason.UNGROUNDED,
                representation_id=anchor.representation_id,
                evidence=_review_evidence(anchor),
            )
        hashes.add(loaded.representation_content_hash)
    digest = citation_set_digest(cite_ids)
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
    from ontologylab.file_lifecycle import (
        FileLifecycleError,
        content_hash_for,
        read_ready_text,
        store_root_from_conn,
    )
    from ontologylab.h1_existing import current_run_receipt_id

    try:
        text = read_ready_text(
            conn, store_root_from_conn(conn), representation_id,
        )
    except FileLifecycleError:
        text = None
    run_id = None
    if text is not None:
        run_id = current_run_receipt_id(
            conn, representation_id, content_hash_for(text.encode("utf-8")),
        )
    if run_id is not None:
        stored = conn.execute(
            "SELECT c.receipt_id FROM extraction_chunk_receipts c "
            "WHERE c.run_receipt_id = ? AND c.start_offset <= ? "
            "AND c.end_offset >= ?",
            (run_id, start, end),
        ).fetchone()
    else:
        stored = None
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
