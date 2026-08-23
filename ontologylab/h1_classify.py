"""Classify one H1 anchor. Never guess, clamp, or rewrite spans."""

from __future__ import annotations

import sqlite3
from typing import assert_never

from ontologylab.file_lifecycle import content_hash_for
from ontologylab.h1_bytes import (
    H1DocumentBytes as H1DocumentBytes,
    load_document as load_document,
    run_for_representation as run_for_representation,
)
from ontologylab.h1_classify_cite import (
    classify_citation,
    classify_offsets as classify_offsets,
    classify_review,
    parse_span as parse_span,
)
from ontologylab.h1_decisions import quarantine, verified
from ontologylab.h1_types import (
    H1Anchor,
    H1ChunkAnchor,
    H1CitationAnchor,
    H1Decision,
    H1QuarantineReason,
    H1ReviewAnchor,
    H1RunAnchor,
)


def classify_anchor(conn: sqlite3.Connection, anchor: H1Anchor) -> H1Decision:
    match anchor:
        case H1RunAnchor():
            return _classify_run(conn, anchor)
        case H1ChunkAnchor():
            return _classify_chunk(conn, anchor)
        case H1CitationAnchor():
            return classify_citation(conn, anchor)
        case H1ReviewAnchor():
            return classify_review(conn, anchor)
        case unreachable:
            assert_never(unreachable)


def chunk_end_candidate(
    conn: sqlite3.Connection, anchor: H1ChunkAnchor, text_len: int,
) -> int:
    nxt = conn.execute(
        "SELECT char_offset FROM extraction_chunks WHERE run_id = ? "
        "AND chunk_index > ? ORDER BY chunk_index LIMIT 1",
        (anchor.run_id, anchor.chunk_index),
    ).fetchone()
    if nxt is None:
        return text_len
    return int(nxt[0])


def _classify_run(conn: sqlite3.Connection, anchor: H1RunAnchor) -> H1Decision:
    loaded = load_document(conn, anchor.representation_id)
    if isinstance(loaded, H1QuarantineReason):
        return quarantine(
            anchor, loaded, representation_id=anchor.representation_id,
            evidence={"run_id": anchor.run_id},
        )
    if anchor.stored_content_hash != loaded.content_hash:
        return quarantine(
            anchor, H1QuarantineReason.HASH_MISMATCH,
            representation_id=anchor.representation_id,
            evidence={"run_id": anchor.run_id},
        )
    return verified(
        anchor,
        representation_id=anchor.representation_id,
        raw_byte_seal=loaded.content_hash,
        file_hash=loaded.content_hash,
        span_hash=loaded.content_hash,
        evidence={"run_id": anchor.run_id},
    )


def _classify_chunk(conn: sqlite3.Connection, anchor: H1ChunkAnchor) -> H1Decision:
    loaded = load_document(conn, anchor.representation_id)
    if isinstance(loaded, H1QuarantineReason):
        return quarantine(
            anchor, loaded, representation_id=anchor.representation_id,
            evidence={"run_id": anchor.run_id, "chunk_index": anchor.chunk_index},
        )
    end = chunk_end_candidate(conn, anchor, len(loaded.text))
    ranged = classify_offsets(anchor.start_offset, end, len(loaded.text))
    if ranged is not None:
        reason = (
            H1QuarantineReason.MISSING_END
            if end <= anchor.start_offset
            else ranged
        )
        return quarantine(
            anchor, reason, representation_id=anchor.representation_id,
            evidence=_chunk_evidence(anchor, end),
        )
    slice_text = loaded.text[anchor.start_offset:end]
    digest = content_hash_for(slice_text.encode("utf-8"))
    if digest != anchor.stored_hash:
        return quarantine(
            anchor, H1QuarantineReason.MISMATCHED_SPAN,
            representation_id=anchor.representation_id,
            evidence=_chunk_evidence(anchor, end),
        )
    return verified(
        anchor,
        representation_id=anchor.representation_id,
        raw_byte_seal=loaded.content_hash,
        file_hash=loaded.content_hash,
        span_hash=digest,
        evidence=_chunk_evidence(anchor, end),
    )


def _chunk_evidence(anchor: H1ChunkAnchor, end: int) -> dict[str, str | int | None]:
    return {
        "run_id": anchor.run_id,
        "chunk_index": anchor.chunk_index,
        "start": anchor.start_offset,
        "end": end,
    }
