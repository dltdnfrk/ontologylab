"""Build citation bindings from one extracted chunk."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ontologylab.citation_ids import fact_revision_id
from ontologylab.citation_store import put_once
from ontologylab.citation_types import (
    ChunkCitationBatch,
    CitationBinding,
    CitationReceipt,
    CitationRefusalCode,
    FactKind,
    refuse,
)
from ontologylab.citation_verify import ready_document
from ontologylab.file_lifecycle import content_hash_for
from ontologylab.models import ProposedRelation, SourceSpan


@dataclass(frozen=True, slots=True)
class _GroundingContext:
    text: str
    content_hash: str
    run_id: str
    chunk: sqlite3.Row
    selection_id: str | None
    policy_identity: str | None


def persist_once(
    conn: sqlite3.Connection, batch: ChunkCitationBatch,
) -> tuple[CitationReceipt, ...]:
    context = _load_context(conn, batch)
    if context is None:
        return ()
    bindings = (
        *_entity_bindings(batch, context),
        *_relation_bindings(conn, batch, context),
    )
    if not bindings:
        return ()
    return put_once(conn, bindings)


def _load_context(
    conn: sqlite3.Connection, batch: ChunkCitationBatch,
) -> _GroundingContext | None:
    runs = conn.execute(
        "SELECT receipt_id, policy_identity FROM extraction_run_receipts "
        "WHERE representation_id = ? ORDER BY created_ts DESC",
        (batch.representation_id,),
    ).fetchall()
    if not runs:
        return None
    chunk = conn.execute(
        "SELECT c.receipt_id, c.run_receipt_id, c.start_offset, c.end_offset, "
        "c.coordinate_profile, c.chunk_text_hash, c.plan_receipt_id "
        "FROM extraction_chunk_receipts c "
        "JOIN extraction_run_receipts r ON r.receipt_id = c.run_receipt_id "
        "WHERE r.representation_id = ? AND c.chunk_index = ? "
        "AND c.start_offset = ? ORDER BY r.created_ts DESC",
        (
            batch.representation_id,
            batch.chunk_index,
            batch.chunk_start_offset,
        ),
    ).fetchone()
    if chunk is None:
        refuse(
            CitationRefusalCode.MISSING_RECEIPT,
            "extraction chunk receipt is required for grounded citations",
        )
    text, content_hash = ready_document(conn, batch.representation_id)
    run_id = str(chunk["run_receipt_id"])
    policy_row = None
    for row in runs:
        if str(row["receipt_id"]) == run_id:
            policy_row = row
            break
    if policy_row is None:
        refuse(
            CitationRefusalCode.MISSING_RECEIPT,
            "chunk run receipt is not bound to the representation",
        )
    policy = str(policy_row["policy_identity"])
    selection = conn.execute(
        "SELECT receipt_id, policy_hash FROM preferred_selection_receipts "
        "WHERE selected_representation_id = ? AND policy_hash = ? "
        "ORDER BY created_ts DESC",
        (batch.representation_id, policy),
    ).fetchone()
    if selection is None:
        selection = conn.execute(
            "SELECT receipt_id, policy_hash FROM preferred_selection_receipts "
            "WHERE selected_representation_id = ? ORDER BY created_ts DESC",
            (batch.representation_id,),
        ).fetchone()
    return _GroundingContext(
        text=text,
        content_hash=content_hash,
        run_id=run_id,
        chunk=chunk,
        selection_id=None if selection is None else str(selection["receipt_id"]),
        policy_identity=None if selection is None else str(selection["policy_hash"]),
    )


def _entity_bindings(
    batch: ChunkCitationBatch, context: _GroundingContext,
) -> tuple[CitationBinding, ...]:
    built: list[CitationBinding] = []
    for entity in batch.entities:
        if entity.source_span is None:
            continue
        fact_id = batch.id_map.get(entity.id)
        if fact_id is None:
            refuse(
                CitationRefusalCode.MISSING_BINDING,
                f"entity {entity.id} has no resolved fact identity",
            )
        built.append(
            _span_binding(
                batch, context, FactKind.NODE, fact_id,
                entity.id, entity.source_span,
            )
        )
    return tuple(built)


def _relation_bindings(
    conn: sqlite3.Connection,
    batch: ChunkCitationBatch,
    context: _GroundingContext,
) -> tuple[CitationBinding, ...]:
    built: list[CitationBinding] = []
    for relation in batch.relations:
        if relation.source_span is None:
            continue
        built.append(
            _span_binding(
                batch, context, FactKind.EDGE,
                _edge_id(conn, batch, relation),
                relation.id, relation.source_span,
            )
        )
    return tuple(built)


def _edge_id(
    conn: sqlite3.Connection,
    batch: ChunkCitationBatch,
    relation: ProposedRelation,
) -> str:
    try:
        src = batch.id_map[relation.src_entity_id]
        dst = batch.id_map[relation.dst_entity_id]
    except KeyError as exc:
        refuse(
            CitationRefusalCode.MISSING_BINDING,
            f"relation {relation.id} references unknown entity {exc}",
        )
    row = conn.execute(
        "SELECT id FROM edges WHERE relation_type = ? AND src_node_id = ? "
        "AND dst_node_id = ? AND status IN ('proposed','verified')",
        (relation.relation_type, src, dst),
    ).fetchone()
    if row is None:
        refuse(
            CitationRefusalCode.MISSING_BINDING,
            f"relation {relation.id} has no resolved edge identity",
        )
    return str(row["id"])


def _span_binding(
    batch: ChunkCitationBatch,
    context: _GroundingContext,
    kind: FactKind,
    fact_id: str,
    proposal_id: str,
    span: SourceSpan,
) -> CitationBinding:
    selected = context.text[span.start:span.end]
    chunk = context.chunk
    return CitationBinding(
        representation_id=batch.representation_id,
        representation_content_hash=context.content_hash,
        run_receipt_id=context.run_id,
        chunk_receipt_id=str(chunk["receipt_id"]),
        chunk_start_offset=int(chunk["start_offset"]),
        chunk_end_offset=int(chunk["end_offset"]),
        coordinate_profile=str(chunk["coordinate_profile"]),
        chunk_text_hash=str(chunk["chunk_text_hash"]),
        chunk_plan_receipt_id=str(chunk["plan_receipt_id"]),
        selection_receipt_id=context.selection_id,
        policy_identity=context.policy_identity,
        fact_kind=str(kind),
        fact_id=fact_id,
        proposal_id=proposal_id,
        fact_revision=fact_revision_id(str(kind), fact_id),
        start_offset=span.start,
        end_offset=span.end,
        selected_text=selected,
        selected_text_hash=content_hash_for(selected.encode("utf-8")),
    )
