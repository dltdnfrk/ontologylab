"""Legacy-compatible v2 shadow adapter for production collect entrypoints.

Pre-fence only: representable outcomes atomically write the legacy document
row plus a v2 Observation/outbox event. Richer or conflicting outcomes go
to a durable queue or typed not_ready. This is not full semantic dual-write;
full v2 authority stays off until Step 9.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ontologylab.authority_repo import create_work
from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.ingestion_service import (
    IngestItem,
    RepresentationInput,
    ingest_item,
)
from ontologylab.kgstore import DocumentIdentityConflict, KGStore
from ontologylab.models import Document
from ontologylab.provenance import Provenance
from ontologylab.provenance_outbox import canonical_json


SHADOW_MODE = "legacy_compatible"
FULL_V2_AUTHORITY = False
MAX_SHADOW_BATCH = 100
SAMPLE_SOURCE_URI = "sample://onboarding/order-system"
SAMPLE_OPERATION_KEY = "collect.sample:sample://onboarding/order-system"
QUEUE_TABLE = "shadow_ingest_queue"


class ShadowBatchBoundError(ValueError):
    """A collect batch exceeded the frozen 100-document bound."""

    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__("batch exceeds 100 documents")


class ShadowIngestError(RuntimeError):
    """Typed failure at the production shadow seam; no exception text."""


@dataclass(frozen=True, slots=True)
class ShadowQueueItem:
    id: str
    operation_id: str
    reason: str
    status: str
    payload_json: str
    created_ts: float


def _ensure_queue(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS shadow_ingest_queue ("
        "id TEXT PRIMARY KEY, "
        "operation_id TEXT NOT NULL, "
        "reason TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'queued', "
        "payload_json TEXT NOT NULL, "
        "created_ts REAL NOT NULL"
        ")"
    )


def load_shadow_queue(conn: sqlite3.Connection) -> tuple[ShadowQueueItem, ...]:
    _ensure_queue(conn)
    rows = conn.execute(
        "SELECT id, operation_id, reason, status, payload_json, created_ts "
        "FROM shadow_ingest_queue ORDER BY created_ts ASC, id ASC"
    ).fetchall()
    return tuple(
        ShadowQueueItem(
            id=str(row[0]),
            operation_id=str(row[1]),
            reason=str(row[2]),
            status=str(row[3]),
            payload_json=str(row[4]),
            created_ts=float(row[5]),
        )
        for row in rows
    )


def _operation_id(
    provenance: Provenance | None, operation_id: str | None
) -> str:
    if operation_id:
        return operation_id
    if provenance is not None:
        return provenance.run_dir.name
    return "collect"


def _idempotency_key(operation_id: str, raw: RawDocument) -> str:
    if operation_id == SAMPLE_OPERATION_KEY:
        return SAMPLE_OPERATION_KEY
    digest = hashlib.sha256(
        canonical_json(
            {
                "connector": raw.source or raw.source_kind,
                "operation_id": operation_id,
                "representation_hash": raw.content_hash,
                "source_uri": raw.source_uri,
            }
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _canonical_doi(raw: RawDocument) -> str | None:
    return normalize_doi(raw.doi)


def _row_document(store: KGStore, doc_id: str) -> Document:
    return store.get_document(doc_id)


def _existing_by_doi(
    conn: sqlite3.Connection, doi: str | None
) -> sqlite3.Row | None:
    if doi is None:
        return None
    return conn.execute(
        "SELECT * FROM documents WHERE doi = ?", (doi,)
    ).fetchone()


def _existing_by_hash(
    conn: sqlite3.Connection, content_hash: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documents WHERE content_hash = ?", (content_hash,)
    ).fetchone()


def _work_id_for(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    keys = set(row.keys())
    if "work_id" in keys and row["work_id"]:
        return str(row["work_id"])
    work_id = create_work(conn)
    conn.execute(
        "UPDATE documents SET work_id = ? WHERE id = ? AND work_id IS NULL",
        (work_id, row["id"]),
    )
    return work_id


def _enqueue(
    conn: sqlite3.Connection,
    *,
    operation_id: str,
    reason: str,
    raw: RawDocument,
    doi: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    _ensure_queue(conn)
    payload = {
        "content_hash": raw.content_hash,
        "doi": doi,
        "reason": reason,
        "source_uri": raw.source_uri,
        "title": raw.title,
        "raw_text": raw.raw_text,
    }
    if extra:
        payload.update(extra)
    conn.execute(
        "INSERT INTO shadow_ingest_queue "
        "(id, operation_id, reason, status, payload_json, created_ts) "
        "VALUES (?, ?, ?, 'queued', ?, ?)",
        (
            f"queue-{uuid.uuid4().hex[:12]}",
            operation_id,
            reason,
            canonical_json(payload),
            time.time(),
        ),
    )


def _item_for(
    raw: RawDocument,
    *,
    operation_id: str,
    doi: str | None,
    work_id: str | None = None,
    representation_id: str | None = None,
) -> IngestItem:
    representation = None
    if representation_id is None:
        representation = RepresentationInput(
            source_kind=raw.source_kind,
            source_uri=raw.source_uri,
            title=raw.title,
            content_hash=raw.content_hash,
            raw_text=raw.raw_text,
        )
    return IngestItem(
        idempotency_key=_idempotency_key(operation_id, raw),
        scheme="doi" if doi else "",
        normalized_value=doi or "",
        source=raw.source,
        evidence_grade=raw.evidence_grade,
        work_id=work_id,
        representation_id=representation_id,
        representation=representation,
        stage="unknown",
        content_kind="fulltext" if raw.raw_text else "metadata_only",
    )


def _register_artifact(store: KGStore, document: Document) -> None:
    store._artifact_insert(
        uuid.uuid4().hex,
        kind="source_doc",
        source_doc_id=document.id,
        run_id=None,
        filename=document.title or document.source_uri or document.id,
        created_ts=document.fetched_ts,
    )


def _mirror_create(
    store: KGStore,
    raw: RawDocument,
    *,
    operation_id: str,
    doi: str | None,
) -> Any:
    from ontologylab.ingestion import IngestedDocument
    conn = store.conn
    conn.execute("SAVEPOINT shadow_item")
    try:
        receipt = ingest_item(
            conn,
            _item_for(raw, operation_id=operation_id, doi=doi),
        )
        if (
            receipt.status not in {"created", "staged"}
            or receipt.representation_id is None
        ):
            conn.execute("ROLLBACK TO SAVEPOINT shadow_item")
            conn.execute("RELEASE SAVEPOINT shadow_item")
            raise ShadowIngestError("internal_error")
        if doi is not None:
            conn.execute(
                "UPDATE documents SET doi = ? WHERE id = ?",
                (doi, receipt.representation_id),
            )
        document = _row_document(store, receipt.representation_id)
        _register_artifact(store, document)
        conn.execute("RELEASE SAVEPOINT shadow_item")
        return IngestedDocument(document=document, created=True)
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT shadow_item")
        conn.execute("RELEASE SAVEPOINT shadow_item")
        raise


def _mirror_duplicate(
    store: KGStore,
    raw: RawDocument,
    existing: sqlite3.Row,
    *,
    operation_id: str,
    doi: str | None,
) -> Any:
    from ontologylab.ingestion import IngestedDocument
    conn = store.conn
    work_id = _work_id_for(conn, existing)
    conn.execute("SAVEPOINT shadow_item")
    try:
        receipt = ingest_item(
            conn,
            _item_for(
                raw,
                operation_id=operation_id,
                doi=doi if doi is not None else (
                    existing["doi"] if "doi" in existing.keys() else None
                ),
                work_id=work_id,
                representation_id=str(existing["id"]),
            ),
        )
        if receipt.status not in {"created", "duplicate"}:
            conn.execute("ROLLBACK TO SAVEPOINT shadow_item")
            conn.execute("RELEASE SAVEPOINT shadow_item")
            raise ShadowIngestError("internal_error")
        conn.execute("RELEASE SAVEPOINT shadow_item")
        return IngestedDocument(
            document=_row_document(store, str(existing["id"])),
            created=False,
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT shadow_item")
        conn.execute("RELEASE SAVEPOINT shadow_item")
        raise


def _identity_conflict(
    existing: sqlite3.Row, raw: RawDocument, doi: str
) -> Any:
    from ontologylab.ingestion import IdentityConflict
    existing_doi = existing["doi"] if "doi" in existing.keys() else None
    return IdentityConflict(
        source_uri=raw.source_uri,
        incoming_doi=doi,
        existing_doc_id=str(existing["id"]),
        existing_doi=str(existing_doi) if existing_doi is not None else None,
        content_hash=raw.content_hash,
    )


def _persist_one(
    store: KGStore,
    raw: RawDocument,
    *,
    operation_id: str,
) -> tuple[Any, Any]:
    from ontologylab.ingestion import IngestedDocument
    conn = store.conn
    doi = _canonical_doi(raw)
    by_doi = _existing_by_doi(conn, doi)
    if by_doi is not None:
        if str(by_doi["content_hash"]) == raw.content_hash:
            return (
                _mirror_duplicate(
                    store, raw, by_doi, operation_id=operation_id, doi=doi
                ),
                None,
            )
        _enqueue(
            conn,
            operation_id=operation_id,
            reason="richer",
            raw=raw,
            doi=doi,
            extra={"existing_doc_id": str(by_doi["id"])},
        )
        return (
            IngestedDocument(
                document=_row_document(store, str(by_doi["id"])),
                created=False,
            ),
            None,
        )

    by_hash = _existing_by_hash(conn, raw.content_hash)
    if by_hash is not None:
        existing_doi = by_hash["doi"] if "doi" in by_hash.keys() else None
        if (
            doi is not None
            and existing_doi is not None
            and str(existing_doi) != doi
        ):
            _enqueue(
                conn,
                operation_id=operation_id,
                reason="conflict",
                raw=raw,
                doi=doi,
                extra={
                    "existing_doc_id": str(by_hash["id"]),
                    "existing_doi": str(existing_doi),
                },
            )
            return None, _identity_conflict(by_hash, raw, doi)
        return (
            _mirror_duplicate(
                store, raw, by_hash, operation_id=operation_id, doi=doi
            ),
            None,
        )

    return _mirror_create(store, raw, operation_id=operation_id, doi=doi), None


def shadow_persist(
    store: KGStore,
    documents: Sequence[RawDocument],
    provenance: Provenance | None,
    *,
    operation_id: str | None = None,
) -> Any:
    """Persist one bounded batch. Never commits or rolls back the caller."""
    from ontologylab.ingestion import IdentityConflict, IngestedDocument, IngestionResult
    if len(documents) > MAX_SHADOW_BATCH:
        raise ShadowBatchBoundError(len(documents))
    if not store.conn.in_transaction:
        store.conn.execute("BEGIN IMMEDIATE")
    _ensure_queue(store.conn)
    op_id = _operation_id(provenance, operation_id)
    entries: list[IngestedDocument] = []
    conflicts: list[IdentityConflict] = []
    created_count = 0
    for raw in documents:
        try:
            entry, conflict = _persist_one(store, raw, operation_id=op_id)
        except (ShadowIngestError, DocumentIdentityConflict):
            raise
        except Exception:
            if provenance is not None:
                provenance.log("collect.failed", {"error": "internal_error"})
            continue
        if conflict is not None:
            conflicts.append(conflict)
            if provenance is not None:
                provenance.log(
                    "collect.identity_conflict",
                    {
                        "source_uri": conflict.source_uri,
                        "incoming_doi": conflict.incoming_doi,
                        "existing_doc_id": conflict.existing_doc_id,
                        "existing_doi": conflict.existing_doi,
                    },
                )
            continue
        if entry is None:
            continue
        entries.append(entry)
        created_count += int(entry.created)
        if provenance is not None:
            provenance.log(
                "collect.doc",
                {
                    "doc_id": entry.document.id,
                    "source_uri": entry.document.source_uri,
                    "created": entry.created,
                    "chars": len(raw.raw_text),
                },
            )
    if provenance is not None:
        provenance.log(
            "collect.end",
            {
                "documents": len(documents),
                "created": created_count,
                "identity_conflicts": len(conflicts),
            },
        )
    return IngestionResult(
        entries=tuple(entries),
        created_count=created_count,
        conflicts=tuple(conflicts),
    )


def shadow_ingest_sample(
    store: KGStore, *, title: str, text: str
) -> dict[str, Any]:
    raw = RawDocument(
        source_kind="upload",
        source_uri=SAMPLE_SOURCE_URI,
        title=title,
        raw_text=text,
    )
    result = shadow_persist(
        store, [raw], None, operation_id=SAMPLE_OPERATION_KEY
    )
    if not result.entries:
        return {
            "ok": False,
            "created": False,
            "document_id": "",
            "title": title,
        }
    entry = result.entries[0]
    return {
        "ok": True,
        "created": entry.created,
        "document_id": entry.document.id,
        "title": entry.document.title,
    }


__all__ = [
    "FULL_V2_AUTHORITY",
    "MAX_SHADOW_BATCH",
    "SAMPLE_OPERATION_KEY",
    "SAMPLE_SOURCE_URI",
    "SHADOW_MODE",
    "ShadowBatchBoundError",
    "ShadowIngestError",
    "ShadowQueueItem",
    "load_shadow_queue",
    "shadow_ingest_sample",
    "shadow_persist",
]
