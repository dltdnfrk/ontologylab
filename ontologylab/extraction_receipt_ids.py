"""Deterministic extraction run, chunk, and plan receipt identities."""

from __future__ import annotations

import hashlib

from ontologylab.extraction_receipt_types import (
    ChunkSpan,
    ExtractionChunkReceipt,
    ExtractionRunBinding,
    ExtractionRunReceipt,
    ExtractionReceiptSet,
)


def digest(parts: tuple[str, ...]) -> str:
    body = hashlib.sha256()
    for part in parts:
        body.update(part.encode("utf-8"))
        body.update(b"\n")
    return "sha256:" + body.hexdigest()


def plan_receipt_id(
    binding: ExtractionRunBinding, chunks: tuple[ChunkSpan, ...],
) -> str:
    rows = tuple(
        f"{chunk.index}:{chunk.start_offset}:{chunk.end_offset}:"
        f"{chunk.coordinate_profile}:{chunk.text_hash}"
        for chunk in chunks
    )
    return digest((
        "extraction-plan-v1",
        binding.representation_id,
        binding.policy_identity,
        binding.config_identity,
        *rows,
    ))


def run_receipt_id(
    binding: ExtractionRunBinding, content_hash: str, plan_id: str,
) -> str:
    return digest((
        "extraction-run-v1",
        binding.representation_id,
        content_hash,
        binding.policy_identity,
        binding.config_identity,
        plan_id,
    ))


def chunk_receipt_id(run_id: str, plan_id: str, chunk: ChunkSpan) -> str:
    return digest((
        "extraction-chunk-v1",
        run_id,
        str(chunk.index),
        str(chunk.start_offset),
        str(chunk.end_offset),
        chunk.coordinate_profile,
        chunk.text_hash,
        plan_id,
    ))


def receipt_set(
    binding: ExtractionRunBinding,
    content_hash: str,
    plan_id: str,
    run_id: str,
    chunks: tuple[ChunkSpan, ...],
    *,
    created: bool,
) -> ExtractionReceiptSet:
    return ExtractionReceiptSet(
        ExtractionRunReceipt(
            receipt_id=run_id,
            representation_id=binding.representation_id,
            document_content_hash=content_hash,
            policy_identity=binding.policy_identity,
            config_identity=binding.config_identity,
            chunk_plan_receipt_id=plan_id,
            created=created,
        ),
        tuple(
            ExtractionChunkReceipt(
                receipt_id=chunk_receipt_id(run_id, plan_id, chunk),
                run_receipt_id=run_id,
                chunk_index=chunk.index,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                coordinate_profile=chunk.coordinate_profile,
                chunk_text_hash=chunk.text_hash,
                plan_receipt_id=plan_id,
            )
            for chunk in chunks
        ),
    )
