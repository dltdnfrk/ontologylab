"""Enumerate every legacy run, chunk, citation, and review anchor."""

from __future__ import annotations

import sqlite3
from typing import assert_never

from ontologylab.h1_ids import anchor_id
from ontologylab.h1_types import (
    H1Anchor,
    H1ChunkAnchor,
    H1CitationAnchor,
    H1Family,
    H1ReviewAnchor,
    H1RunAnchor,
)


_FAMILY_ORDER = {
    H1Family.RUN: 0,
    H1Family.CHUNK: 1,
    H1Family.CITATION: 2,
    H1Family.REVIEW: 3,
}


def family_of(anchor: H1Anchor) -> H1Family:
    match anchor:
        case H1RunAnchor():
            return H1Family.RUN
        case H1ChunkAnchor():
            return H1Family.CHUNK
        case H1CitationAnchor():
            return H1Family.CITATION
        case H1ReviewAnchor():
            return H1Family.REVIEW
        case unreachable:
            assert_never(unreachable)


def list_anchors(conn: sqlite3.Connection) -> tuple[H1Anchor, ...]:
    anchors: list[H1Anchor] = []
    anchors.extend(_runs(conn))
    anchors.extend(_chunks(conn))
    anchors.extend(_citations(conn))
    anchors.extend(_reviews(conn))
    return tuple(
        sorted(
            anchors,
            key=lambda item: (_FAMILY_ORDER[family_of(item)], item.anchor_id),
        )
    )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _runs(conn: sqlite3.Connection) -> tuple[H1RunAnchor, ...]:
    if not _table_exists(conn, "extraction_runs"):
        return ()
    rows = conn.execute(
        "SELECT id, document_id, document_content_hash, schema_version_id, "
        "extractor_engine, IFNULL(extractor_model, ''), prompt_version, "
        "decode_params, chunk_plan_hash FROM extraction_runs ORDER BY id"
    ).fetchall()
    return tuple(
        H1RunAnchor(
            anchor_id=anchor_id(H1Family.RUN, str(row[0])),
            legacy_pk=str(row[0]),
            run_id=str(row[0]),
            representation_id=str(row[1]),
            stored_content_hash=str(row[2]),
            schema_version_id=int(row[3]),
            extractor_engine=str(row[4]),
            extractor_model=str(row[5]),
            prompt_version=str(row[6]),
            decode_params=str(row[7]),
            chunk_plan_hash=str(row[8]),
        )
        for row in rows
    )


def _chunks(conn: sqlite3.Connection) -> tuple[H1ChunkAnchor, ...]:
    if not _table_exists(conn, "extraction_chunks"):
        return ()
    rows = conn.execute(
        "SELECT c.run_id, c.chunk_index, c.char_offset, c.content_hash, "
        "r.document_id FROM extraction_chunks c "
        "JOIN extraction_runs r ON r.id = c.run_id "
        "ORDER BY c.run_id, c.chunk_index"
    ).fetchall()
    return tuple(
        H1ChunkAnchor(
            anchor_id=anchor_id(
                H1Family.CHUNK, str(row[0]), str(int(row[1])),
            ),
            legacy_pk=f"{row[0]}:{int(row[1])}",
            run_id=str(row[0]),
            chunk_index=int(row[1]),
            start_offset=int(row[2]),
            stored_hash=str(row[3]),
            representation_id=str(row[4]),
        )
        for row in rows
    )


def _citations(conn: sqlite3.Connection) -> tuple[H1CitationAnchor, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    items: list[H1CitationAnchor] = []
    if _table_exists(conn, "citations"):
        for row in conn.execute(
            "SELECT kind, item_id, source_doc_id, source_span FROM citations "
            "ORDER BY kind, item_id, source_doc_id, IFNULL(source_span, '')"
        ):
            key = (str(row[0]), str(row[1]), str(row[2]), row[3] or "")
            if key in seen:
                continue
            seen.add(key)
            items.append(_citation_anchor(key[0], key[1], key[2], row[3]))
    for table, kind in (("nodes", "node"), ("edges", "edge")):
        if not _table_exists(conn, table):
            continue
        for row in conn.execute(
            f"SELECT id, source_doc_id, source_span FROM {table} "
            "ORDER BY id"
        ):
            key = (kind, str(row[0]), str(row[1]), row[2] or "")
            if key in seen:
                continue
            seen.add(key)
            items.append(_citation_anchor(kind, key[1], key[2], row[2]))
    return tuple(items)


def _citation_anchor(
    kind: str, fact_id: str, representation_id: str, source_span: str | None,
) -> H1CitationAnchor:
    span = None if source_span is None else str(source_span)
    legacy = f"{kind}:{fact_id}:{representation_id}:{span or ''}"
    return H1CitationAnchor(
        anchor_id=anchor_id(H1Family.CITATION, legacy),
        legacy_pk=legacy,
        fact_kind=kind,
        fact_id=fact_id,
        representation_id=representation_id,
        source_span=span,
    )


def _reviews(conn: sqlite3.Connection) -> tuple[H1ReviewAnchor, ...]:
    items: list[H1ReviewAnchor] = []
    for table, kind in (("nodes", "node"), ("edges", "edge")):
        if not _table_exists(conn, table):
            continue
        rows = conn.execute(
            f"SELECT id, status, verified_by, review_note, verified_ts, "
            f"source_doc_id FROM {table} WHERE status IN "
            f"('verified', 'rejected') OR verified_by IS NOT NULL "
            f"ORDER BY id"
        )
        for row in rows:
            fact_id = str(row[0])
            legacy = f"{kind}:{fact_id}"
            decided = None if row[4] is None else float(row[4])
            items.append(
                H1ReviewAnchor(
                    anchor_id=anchor_id(H1Family.REVIEW, legacy),
                    legacy_pk=legacy,
                    fact_kind=kind,
                    fact_id=fact_id,
                    status=str(row[1]),
                    actor="" if row[2] is None else str(row[2]),
                    reason="" if row[3] is None else str(row[3]),
                    decided_ts=decided,
                    representation_id=None if row[5] is None else str(row[5]),
                )
            )
    return tuple(items)
