"""Exact classified Task 2 run receipt lookup for H1 family linking."""

from __future__ import annotations

import json
import sqlite3

from ontologylab.extraction_receipt_ids import plan_receipt_id, run_receipt_id
from ontologylab.extraction_receipt_types import (
    DOCUMENT_UTF8_V1,
    ChunkSpan,
    ExtractionRunBinding,
)
from ontologylab.file_lifecycle import content_hash_for
from ontologylab.h1_bytes import load_document
from ontologylab.h1_ids import LEGACY_POLICY, run_config_identity
from ontologylab.h1_types import (
    H1ChunkAnchor,
    H1Decision,
    H1QuarantineReason,
    H1RunAnchor,
)


def existing_run_receipt(
    conn: sqlite3.Connection,
    run: H1RunAnchor,
    chunks: tuple[tuple[H1ChunkAnchor, H1Decision], ...],
) -> str | None:
    if not has_table(conn, "extraction_run_receipts"):
        return None
    loaded = load_document(conn, run.representation_id)
    if isinstance(loaded, H1QuarantineReason):
        return None
    if loaded.content_hash != run.stored_content_hash:
        return None
    selected = selection_run_receipt(
        conn, run.representation_id, loaded.content_hash,
    )
    if selected is not None:
        return selected
    expected = _expected_run_id(run, loaded.text, loaded.content_hash, chunks)
    if expected is not None and _legacy_row_matches(
        conn, expected, run, loaded.content_hash,
    ):
        return expected
    return None


def selection_run_receipt(
    conn: sqlite3.Connection, representation_id: str, content_hash: str,
) -> str | None:
    policy = selection_policy(conn, representation_id)
    if policy is None:
        return None
    row = conn.execute(
        "SELECT * FROM extraction_run_receipts "
        "WHERE representation_id = ? AND document_content_hash = ? "
        "AND policy_identity = ?",
        (representation_id, content_hash, policy),
    ).fetchone()
    if row is None or not _run_identity_matches(row):
        return None
    return str(row["receipt_id"])


def current_run_receipt_id(
    conn: sqlite3.Connection, representation_id: str, content_hash: str,
) -> str | None:
    selected = selection_run_receipt(conn, representation_id, content_hash)
    if selected is not None:
        return selected
    return _linked_run(conn, representation_id)


def selection_policy(
    conn: sqlite3.Connection, representation_id: str,
) -> str | None:
    if not has_table(conn, "preferred_selection_receipts"):
        return None
    row = conn.execute(
        "SELECT policy_hash FROM preferred_selection_receipts "
        "WHERE selected_representation_id = ? "
        "ORDER BY created_ts DESC, receipt_id",
        (representation_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def selection_receipt_id(
    conn: sqlite3.Connection, representation_id: str,
) -> str | None:
    if not has_table(conn, "preferred_selection_receipts"):
        return None
    row = conn.execute(
        "SELECT receipt_id FROM preferred_selection_receipts "
        "WHERE selected_representation_id = ? "
        "ORDER BY created_ts DESC, receipt_id",
        (representation_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone() is not None


def _linked_run(conn: sqlite3.Connection, representation_id: str) -> str | None:
    if not has_table(conn, "h1_anchor_receipts"):
        return None
    rows = conn.execute(
        "SELECT family_receipt_id FROM h1_anchor_receipts "
        "WHERE family = 'run' AND classification = 'verified' "
        "AND representation_id = ? AND family_receipt_id IS NOT NULL "
        "ORDER BY family_receipt_id",
        (representation_id,),
    ).fetchall()
    ids = {str(row[0]) for row in rows}
    if len(ids) != 1:
        return None
    return next(iter(ids))


def _expected_run_id(
    run: H1RunAnchor,
    text: str,
    content_hash: str,
    chunks: tuple[tuple[H1ChunkAnchor, H1Decision], ...],
) -> str | None:
    spans = _spans(text, chunks)
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
    return run_receipt_id(binding, content_hash, plan_receipt_id(binding, spans))


def _spans(
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


def _legacy_row_matches(
    conn: sqlite3.Connection,
    receipt_id: str,
    run: H1RunAnchor,
    content_hash: str,
) -> bool:
    row = conn.execute(
        "SELECT * FROM extraction_run_receipts WHERE receipt_id = ?",
        (receipt_id,),
    ).fetchone()
    if row is None:
        return False
    return (
        str(row["representation_id"]) == run.representation_id
        and str(row["document_content_hash"]) == content_hash
        and str(row["policy_identity"]) == LEGACY_POLICY
        and str(row["config_identity"]) == run_config_identity(run)
        and str(row["extractor_engine"]) == run.extractor_engine
        and str(row["extractor_model"]) == run.extractor_model
        and str(row["prompt_version"]) == run.prompt_version
        and str(row["decode_params_json"]) == run.decode_params
        and _run_identity_matches(row)
    )


def _run_identity_matches(row: sqlite3.Row) -> bool:
    binding = ExtractionRunBinding(
        representation_id=str(row["representation_id"]),
        policy_identity=str(row["policy_identity"]),
        config_identity=str(row["config_identity"]),
        schema_version_id=int(row["schema_version_id"]),
        extractor_engine=str(row["extractor_engine"]),
        extractor_model=str(row["extractor_model"]),
        prompt_version=str(row["prompt_version"]),
        decode_params_json=str(row["decode_params_json"]),
    )
    expected = run_receipt_id(
        binding,
        str(row["document_content_hash"]),
        str(row["chunk_plan_receipt_id"]),
    )
    return expected == str(row["receipt_id"])
