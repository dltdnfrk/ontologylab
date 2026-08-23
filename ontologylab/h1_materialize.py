"""Write Task 2/4 family receipts for one verified H1 unit."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from ontologylab.citation import put_citation_receipts
from ontologylab.citation_ids import fact_revision_id
from ontologylab.citation_types import CitationBinding, CitationRefused
from ontologylab.extraction_receipt_types import (
    DOCUMENT_UTF8_V1,
    ChunkSpan,
    ExtractionReceiptRefused,
    ExtractionReceiptSet,
    ExtractionRunBinding,
)
from ontologylab.extraction_receipts import put_extraction_receipts
from ontologylab.file_lifecycle import content_hash_for
from ontologylab.h1_bytes import load_document
from ontologylab.h1_existing import current_run_receipt_id, selection_policy, selection_receipt_id
from ontologylab.h1_existing_cite import existing_citation_receipt
from ontologylab.h1_ids import LEGACY_POLICY, run_config_identity
from ontologylab.h1_types import (
    H1ChunkAnchor,
    H1Decision,
    H1QuarantineReason,
    H1RunAnchor,
)


@dataclass(frozen=True, slots=True)
class _CitationSeed:
    representation_id: str
    content_hash: str
    fact_kind: str
    fact_id: str
    start: int
    end: int
    span_hash: str


def materialize_run(
    conn: sqlite3.Connection,
    run: H1RunAnchor,
    chunks: tuple[tuple[H1ChunkAnchor, H1Decision], ...],
) -> ExtractionReceiptSet | None:
    loaded = load_document(conn, run.representation_id)
    if isinstance(loaded, H1QuarantineReason):
        return None
    spans = _spans_from_decisions(loaded.text, chunks)
    if spans is None:
        return None
    binding = ExtractionRunBinding(
        representation_id=run.representation_id,
        policy_identity=LEGACY_POLICY,
        config_identity=run_config_identity(run),
        schema_version_id=run.schema_version_id,
        extractor_engine=run.extractor_engine,
        extractor_model=run.extractor_model,
        prompt_version=run.prompt_version,
        decode_params_json=run.decode_params,
    )
    try:
        return put_extraction_receipts(conn, binding, spans)
    except ExtractionReceiptRefused:
        return None


def materialize_citation(conn: sqlite3.Connection, decision: H1Decision) -> str | None:
    seed = _seed_from_decision(decision)
    if seed is None:
        return None
    existing = existing_citation_receipt(conn, decision)
    if existing is not None:
        return existing
    binding = _citation_binding(conn, seed)
    if binding is None:
        return None
    try:
        written = put_citation_receipts(conn, (binding,))
    except CitationRefused:
        return None
    if not written:
        return None
    return written[0].receipt_id


def lookup_chunk_receipt(
    conn: sqlite3.Connection, chunk: H1ChunkAnchor, decision: H1Decision,
) -> str | None:
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'extraction_chunk_receipts'"
    ).fetchone() is None:
        return None
    evidence = json.loads(decision.evidence_json)
    start = evidence.get("start")
    end = evidence.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    loaded = load_document(conn, chunk.representation_id)
    if isinstance(loaded, H1QuarantineReason):
        return None
    run_id = current_run_receipt_id(
        conn, chunk.representation_id, loaded.content_hash,
    )
    if run_id is None:
        return None
    rows = conn.execute(
        "SELECT c.receipt_id FROM extraction_chunk_receipts c "
        "WHERE c.run_receipt_id = ? AND c.chunk_index = ? "
        "AND c.start_offset = ? AND c.end_offset = ?",
        (run_id, chunk.chunk_index, start, end),
    ).fetchall()
    if len(rows) != 1:
        return None
    return str(rows[0][0])


def _spans_from_decisions(
    text: str, chunks: tuple[tuple[H1ChunkAnchor, H1Decision], ...],
) -> tuple[ChunkSpan, ...] | None:
    built: list[ChunkSpan] = []
    ordered = tuple(sorted(chunks, key=lambda item: item[0].chunk_index))
    for chunk, decision in ordered:
        evidence = json.loads(decision.evidence_json)
        start = evidence.get("start")
        end = evidence.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        slice_text = text[start:end]
        built.append(
            ChunkSpan(
                index=chunk.chunk_index,
                start_offset=start,
                end_offset=end,
                text=slice_text,
                text_hash=content_hash_for(slice_text.encode("utf-8")),
                coordinate_profile=DOCUMENT_UTF8_V1,
            )
        )
    if not built:
        return None
    return tuple(built)


def _seed_from_decision(decision: H1Decision) -> _CitationSeed | None:
    evidence = json.loads(decision.evidence_json)
    start = evidence.get("start")
    end = evidence.get("end")
    fact_kind = evidence.get("fact_kind")
    fact_id = evidence.get("fact_id")
    representation_id = decision.representation_id
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or not isinstance(fact_kind, str)
        or not isinstance(fact_id, str)
        or representation_id is None
        or decision.raw_byte_seal is None
        or decision.span_hash is None
    ):
        return None
    return _CitationSeed(
        representation_id=representation_id,
        content_hash=decision.raw_byte_seal,
        fact_kind=fact_kind,
        fact_id=fact_id,
        start=start,
        end=end,
        span_hash=decision.span_hash,
    )


def _citation_binding(
    conn: sqlite3.Connection, seed: _CitationSeed,
) -> CitationBinding | None:
    loaded = load_document(conn, seed.representation_id)
    if isinstance(loaded, H1QuarantineReason):
        return None
    run_id = current_run_receipt_id(
        conn, seed.representation_id, seed.content_hash,
    )
    if run_id is None:
        return None
    pair = conn.execute(
        "SELECT r.receipt_id, r.chunk_plan_receipt_id, c.receipt_id, "
        "c.start_offset, c.end_offset, c.chunk_text_hash "
        "FROM extraction_run_receipts r "
        "JOIN extraction_chunk_receipts c ON c.run_receipt_id = r.receipt_id "
        "WHERE r.receipt_id = ? AND c.start_offset <= ? "
        "AND c.end_offset >= ?",
        (run_id, seed.start, seed.end),
    ).fetchone()
    if pair is None:
        return None
    policy = selection_policy(conn, seed.representation_id)
    if policy is None:
        policy = LEGACY_POLICY
    return CitationBinding(
        representation_id=seed.representation_id,
        representation_content_hash=seed.content_hash,
        run_receipt_id=str(pair[0]),
        chunk_receipt_id=str(pair[2]),
        chunk_start_offset=int(pair[3]),
        chunk_end_offset=int(pair[4]),
        coordinate_profile=DOCUMENT_UTF8_V1,
        chunk_text_hash=str(pair[5]),
        chunk_plan_receipt_id=str(pair[1]),
        selection_receipt_id=selection_receipt_id(conn, seed.representation_id),
        policy_identity=policy,
        fact_kind=seed.fact_kind,
        fact_id=seed.fact_id,
        proposal_id=seed.fact_id,
        fact_revision=fact_revision_id(seed.fact_kind, seed.fact_id),
        start_offset=seed.start,
        end_offset=seed.end,
        selected_text=loaded.text[seed.start:seed.end],
        selected_text_hash=seed.span_hash,
    )
