"""Verify citation bindings against ready Representation bytes."""

from __future__ import annotations

import sqlite3
from typing import assert_never

from ontologylab.citation_types import (
    CitationBinding,
    CitationRefusalCode,
    FactKind,
    refuse,
)
from ontologylab.extraction_receipt_types import CoordinateProfile
from ontologylab.file_lifecycle import (
    FileIntegrityError,
    FileLifecycleError,
    FileNotReady,
    PathEscapeError,
    content_hash_for,
    read_ready_text,
    store_root_from_conn,
)


def ready_document(
    conn: sqlite3.Connection, representation_id: str,
) -> tuple[str, str]:
    row = conn.execute(
        "SELECT content_hash FROM documents WHERE id = ?",
        (representation_id,),
    ).fetchone()
    if row is None:
        refuse(
            CitationRefusalCode.UNKNOWN_REPRESENTATION,
            f"unknown representation {representation_id!r}",
        )
    try:
        text = read_ready_text(
            conn, store_root_from_conn(conn), representation_id,
        )
    except FileLifecycleError as exc:
        match exc:
            case FileNotReady() | PathEscapeError():
                refuse(CitationRefusalCode.NOT_READY, str(exc))
            case FileIntegrityError():
                refuse(CitationRefusalCode.INVALID_HASH, str(exc))
            case FileLifecycleError():
                refuse(CitationRefusalCode.NOT_READY, str(exc))
            case unreachable:
                assert_never(unreachable)
    stored_hash = str(row["content_hash"])
    if content_hash_for(text.encode("utf-8")) != stored_hash:
        refuse(
            CitationRefusalCode.INVALID_HASH,
            "representation content hash does not match ready bytes",
        )
    return text, stored_hash


def verify_binding(
    conn: sqlite3.Connection,
    binding: CitationBinding,
    document_text: str,
    content_hash: str,
) -> None:
    _require_fields(binding)
    try:
        FactKind(binding.fact_kind)
    except ValueError:
        refuse(
            CitationRefusalCode.MISSING_BINDING,
            "fact kind must be node or edge",
        )
    try:
        CoordinateProfile(binding.coordinate_profile)
    except ValueError:
        refuse(
            CitationRefusalCode.INVALID_PROFILE,
            f"unknown coordinate profile {binding.coordinate_profile!r}",
        )
    start = binding.start_offset
    end = binding.end_offset
    if start < 0 or end <= start or end > len(document_text):
        refuse(
            CitationRefusalCode.INVALID_RANGE,
            "citation offsets must be a document-relative half-open range",
        )
    slice_text = document_text[start:end]
    if binding.selected_text != slice_text:
        refuse(
            CitationRefusalCode.INVALID_TEXT,
            "selected text does not match the stated document range",
        )
    expected_hash = content_hash_for(slice_text.encode("utf-8"))
    if binding.selected_text_hash != expected_hash:
        refuse(
            CitationRefusalCode.INVALID_HASH,
            "selected text hash does not match selected text",
        )
    if binding.representation_content_hash != content_hash:
        refuse(
            CitationRefusalCode.INVALID_HASH,
            "representation content hash is not the authoritative hash",
        )
    _verify_run_chunk(conn, binding)
    _verify_selection(conn, binding)


def _require_fields(binding: CitationBinding) -> None:
    if not (
        binding.representation_id.strip()
        and binding.run_receipt_id.strip()
        and binding.chunk_receipt_id.strip()
        and binding.fact_id.strip()
        and binding.selected_text
        and binding.selected_text_hash.strip()
        and binding.representation_content_hash.strip()
        and binding.chunk_text_hash.strip()
        and binding.chunk_plan_receipt_id.strip()
        and binding.coordinate_profile.strip()
    ):
        refuse(
            CitationRefusalCode.MISSING_BINDING,
            "citation receipt fields are required",
        )


def _verify_run_chunk(
    conn: sqlite3.Connection, binding: CitationBinding,
) -> None:
    run = conn.execute(
        "SELECT representation_id, document_content_hash, policy_identity, "
        "chunk_plan_receipt_id FROM extraction_run_receipts "
        "WHERE receipt_id = ?",
        (binding.run_receipt_id,),
    ).fetchone()
    if run is None:
        refuse(
            CitationRefusalCode.MISSING_RECEIPT,
            f"unknown extraction run {binding.run_receipt_id!r}",
        )
    if str(run["representation_id"]) != binding.representation_id:
        refuse(
            CitationRefusalCode.CROSS_BIND,
            "run receipt is bound to a different representation",
        )
    if str(run["document_content_hash"]) != binding.representation_content_hash:
        refuse(
            CitationRefusalCode.INVALID_HASH,
            "run content hash does not match the representation",
        )
    if str(run["chunk_plan_receipt_id"]) != binding.chunk_plan_receipt_id:
        refuse(
            CitationRefusalCode.MISSING_RECEIPT,
            "chunk plan receipt does not match the extraction run",
        )
    if (
        binding.policy_identity is not None
        and binding.policy_identity != str(run["policy_identity"])
    ):
        refuse(
            CitationRefusalCode.CROSS_BIND,
            "policy identity does not match the extraction run",
        )
    chunk = conn.execute(
        "SELECT run_receipt_id, start_offset, end_offset, coordinate_profile, "
        "chunk_text_hash, plan_receipt_id FROM extraction_chunk_receipts "
        "WHERE receipt_id = ?",
        (binding.chunk_receipt_id,),
    ).fetchone()
    if chunk is None:
        refuse(
            CitationRefusalCode.MISSING_RECEIPT,
            f"unknown extraction chunk {binding.chunk_receipt_id!r}",
        )
    if str(chunk["run_receipt_id"]) != binding.run_receipt_id:
        refuse(
            CitationRefusalCode.CROSS_BIND,
            "chunk receipt is bound to a different extraction run",
        )
    if (
        int(chunk["start_offset"]) != binding.chunk_start_offset
        or int(chunk["end_offset"]) != binding.chunk_end_offset
        or str(chunk["coordinate_profile"]) != binding.coordinate_profile
        or str(chunk["chunk_text_hash"]) != binding.chunk_text_hash
        or str(chunk["plan_receipt_id"]) != binding.chunk_plan_receipt_id
    ):
        refuse(
            CitationRefusalCode.MISSING_RECEIPT,
            "chunk receipt fields do not match the citation binding",
        )
    if (
        binding.start_offset < binding.chunk_start_offset
        or binding.end_offset > binding.chunk_end_offset
    ):
        refuse(
            CitationRefusalCode.INVALID_RANGE,
            "citation span must lie inside the chunk receipt range",
        )


def _verify_selection(
    conn: sqlite3.Connection, binding: CitationBinding,
) -> None:
    if binding.selection_receipt_id is None:
        return
    if not binding.selection_receipt_id.strip():
        refuse(
            CitationRefusalCode.MISSING_RECEIPT,
            "selection receipt identity is empty",
        )
    row = conn.execute(
        "SELECT selected_representation_id, selected_content_hash, "
        "policy_hash FROM preferred_selection_receipts WHERE receipt_id = ?",
        (binding.selection_receipt_id,),
    ).fetchone()
    if row is None:
        refuse(
            CitationRefusalCode.MISSING_RECEIPT,
            f"unknown selection receipt {binding.selection_receipt_id!r}",
        )
    if str(row["selected_representation_id"]) != binding.representation_id:
        refuse(
            CitationRefusalCode.CROSS_BIND,
            "selection receipt is bound to a different representation",
        )
    if str(row["selected_content_hash"]) != binding.representation_content_hash:
        refuse(
            CitationRefusalCode.INVALID_HASH,
            "selection content hash does not match the representation",
        )
    if (
        binding.policy_identity is not None
        and binding.policy_identity != str(row["policy_hash"])
    ):
        refuse(
            CitationRefusalCode.CROSS_BIND,
            "policy identity does not match the selection receipt",
        )
