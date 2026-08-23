"""SQLite schema and caller-owned persistence for extraction receipts."""

from __future__ import annotations

import sqlite3
import time

from ontologylab.extraction_receipt_ids import (
    plan_receipt_id,
    receipt_set,
    run_receipt_id,
)
from ontologylab.extraction_receipt_types import (
    ChunkSpan,
    CoordinateProfile,
    ExtractionReceiptRefusalCode,
    ExtractionReceiptSet,
    ExtractionRunBinding,
    ExtractionRunReceipt,
    refuse,
)
from ontologylab.file_lifecycle import (
    FileIntegrityError,
    FileLifecycleError,
    FileNotReady,
    PathEscapeError,
    content_hash_for,
    read_ready_text,
    store_root_from_conn,
)


def put_once(
    conn: sqlite3.Connection,
    binding: ExtractionRunBinding,
    chunks: tuple[ChunkSpan, ...],
) -> ExtractionReceiptSet:
    _require_binding(binding)
    document_text, content_hash = _document_text(conn, binding.representation_id)
    validated = _validated_chunks(document_text, chunks)
    plan_id = plan_receipt_id(binding, validated)
    run_id = run_receipt_id(binding, content_hash, plan_id)
    expected = receipt_set(
        binding, content_hash, plan_id, run_id, validated, created=True,
    )
    existing = _existing_conflicts(conn, binding, expected)
    if existing is not None:
        return existing
    _insert_receipts(conn, binding, content_hash, plan_id, run_id, expected)
    return expected


def _require_binding(binding: ExtractionRunBinding) -> None:
    if not (
        binding.representation_id.strip()
        and binding.policy_identity.strip()
        and binding.config_identity.strip()
    ):
        refuse(
            ExtractionReceiptRefusalCode.MISSING_BINDING,
            "representation, policy, and config identities are required",
        )


def _document_text(
    conn: sqlite3.Connection, representation_id: str,
) -> tuple[str, str]:
    row = conn.execute(
        "SELECT content_hash FROM documents WHERE id = ?",
        (representation_id,),
    ).fetchone()
    if row is None:
        refuse(
            ExtractionReceiptRefusalCode.UNKNOWN_REPRESENTATION,
            f"unknown representation {representation_id!r}",
        )
    try:
        text = read_ready_text(
            conn, store_root_from_conn(conn), representation_id,
        )
    except FileLifecycleError as exc:
        match exc:
            case FileNotReady() | PathEscapeError():
                refuse(ExtractionReceiptRefusalCode.NOT_READY, str(exc))
            case FileIntegrityError():
                refuse(ExtractionReceiptRefusalCode.INVALID_HASH, str(exc))
            case FileLifecycleError():
                refuse(ExtractionReceiptRefusalCode.NOT_READY, str(exc))
    return text, str(row["content_hash"])


def _validated_chunks(
    document_text: str, chunks: tuple[ChunkSpan, ...],
) -> tuple[ChunkSpan, ...]:
    if not chunks:
        refuse(
            ExtractionReceiptRefusalCode.INVALID_RANGE,
            "at least one chunk is required",
        )
    seen: set[int] = set()
    ordered = tuple(sorted(chunks, key=lambda chunk: chunk.index))
    for chunk in ordered:
        if chunk.index in seen or chunk.index < 0:
            refuse(
                ExtractionReceiptRefusalCode.INVALID_RANGE,
                "chunk indexes must be unique nonnegative integers",
            )
        seen.add(chunk.index)
        try:
            CoordinateProfile(chunk.coordinate_profile)
        except ValueError:
            refuse(
                ExtractionReceiptRefusalCode.INVALID_PROFILE,
                f"unknown coordinate profile {chunk.coordinate_profile!r}",
            )
        if (
            chunk.start_offset < 0
            or chunk.end_offset <= chunk.start_offset
            or chunk.end_offset > len(document_text)
        ):
            refuse(
                ExtractionReceiptRefusalCode.INVALID_RANGE,
                "chunk offsets must be a document-relative half-open range",
            )
        expected_text = document_text[chunk.start_offset:chunk.end_offset]
        if chunk.text != expected_text:
            refuse(
                ExtractionReceiptRefusalCode.INVALID_RANGE,
                "chunk text does not match the stated document range",
            )
        expected_hash = content_hash_for(expected_text.encode("utf-8"))
        if chunk.text_hash != expected_hash:
            refuse(
                ExtractionReceiptRefusalCode.INVALID_HASH,
                "chunk text hash does not match chunk text",
            )
    return ordered


def _existing_conflicts(
    conn: sqlite3.Connection,
    binding: ExtractionRunBinding,
    expected: ExtractionReceiptSet,
) -> ExtractionReceiptSet | None:
    row = conn.execute(
        "SELECT receipt_id, document_content_hash, chunk_plan_receipt_id "
        "FROM extraction_run_receipts WHERE representation_id = ? AND "
        "policy_identity = ? AND config_identity = ?",
        (
            binding.representation_id,
            binding.policy_identity,
            binding.config_identity,
        ),
    ).fetchone()
    if row is None:
        return None
    stored = conn.execute(
        "SELECT receipt_id, chunk_index, start_offset, end_offset, "
        "coordinate_profile, chunk_text_hash, plan_receipt_id "
        "FROM extraction_chunk_receipts WHERE run_receipt_id = ? "
        "ORDER BY chunk_index",
        (row["receipt_id"],),
    ).fetchall()
    same_run = (
        row["receipt_id"] == expected.run.receipt_id
        and row["document_content_hash"] == expected.run.document_content_hash
        and row["chunk_plan_receipt_id"] == expected.run.chunk_plan_receipt_id
    )
    same_chunks = [
        (
            item["receipt_id"], item["chunk_index"], item["start_offset"],
            item["end_offset"], item["coordinate_profile"],
            item["chunk_text_hash"], item["plan_receipt_id"],
        )
        for item in stored
    ] == [
        (
            chunk.receipt_id, chunk.chunk_index, chunk.start_offset,
            chunk.end_offset, chunk.coordinate_profile,
            chunk.chunk_text_hash, chunk.plan_receipt_id,
        )
        for chunk in expected.chunks
    ]
    if same_run and same_chunks:
        return ExtractionReceiptSet(
            ExtractionRunReceipt(
                receipt_id=expected.run.receipt_id,
                representation_id=expected.run.representation_id,
                document_content_hash=expected.run.document_content_hash,
                policy_identity=expected.run.policy_identity,
                config_identity=expected.run.config_identity,
                chunk_plan_receipt_id=expected.run.chunk_plan_receipt_id,
                created=False,
            ),
            expected.chunks,
        )
    refuse(
        ExtractionReceiptRefusalCode.CONFLICT,
        "retry does not match the immutable extraction receipt",
    )


def _insert_receipts(
    conn: sqlite3.Connection,
    binding: ExtractionRunBinding,
    content_hash: str,
    plan_id: str,
    run_id: str,
    expected: ExtractionReceiptSet,
) -> None:
    conn.execute(
        "INSERT INTO extraction_run_receipts ("
        "receipt_id, representation_id, document_content_hash, "
        "policy_identity, config_identity, chunk_plan_receipt_id, "
        "schema_version_id, extractor_engine, extractor_model, "
        "prompt_version, decode_params_json, created_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id, binding.representation_id, content_hash,
            binding.policy_identity, binding.config_identity, plan_id,
            binding.schema_version_id, binding.extractor_engine,
            binding.extractor_model, binding.prompt_version,
            binding.decode_params_json, time.time(),
        ),
    )
    conn.executemany(
        "INSERT INTO extraction_chunk_receipts ("
        "receipt_id, run_receipt_id, chunk_index, start_offset, end_offset, "
        "coordinate_profile, chunk_text_hash, plan_receipt_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                chunk.receipt_id, chunk.run_receipt_id, chunk.chunk_index,
                chunk.start_offset, chunk.end_offset,
                chunk.coordinate_profile, chunk.chunk_text_hash,
                chunk.plan_receipt_id,
            )
            for chunk in expected.chunks
        ],
    )
