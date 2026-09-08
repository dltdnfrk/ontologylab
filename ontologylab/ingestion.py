"""Raw-document Acquire orchestration over the v2 item writer."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, Literal, assert_never

from ontologylab.authority_repo import create_work
from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.file_lifecycle import (
    FileIntegrityError,
    FileLifecycleError,
    finalize_representation,
    store_root_from_conn,
    sync_documents_directory,
    sync_staging_operation,
)
from ontologylab.ingestion_service import (
    IngestItem,
    RepresentationInput,
    ingest_item,
)
from ontologylab.kgstore import KGStore
from ontologylab.models import Document
from ontologylab.provenance import Provenance
from ontologylab.provenance_outbox import OutboxError, canonical_json, project_outbox
from ontologylab.research_assessment import classify_document_content

MAX_INGEST_BATCH: Final = 100
_SAMPLE_OPERATION_KEY: Final = "collect.sample:sample://onboarding/order-system"
SAMPLE_SOURCE_URI: Final = "sample://onboarding/order-system"
IngestFailureKind = Literal["internal_error", "identity", "integrity"]


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    document: Document
    created: bool


class PartialIngestionError(Exception):
    def __init__(
        self,
        *,
        kind: str,
        completed_batches: int,
        created_count: int,
    ) -> None:
        super().__init__("batched ingestion stopped after committed partial progress")
        self.kind = kind
        self.completed_batches = completed_batches
        self.created_count = created_count


class IngestBatchBoundError(ValueError):
    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__("batch exceeds 100 documents")


@dataclass(frozen=True, slots=True)
class IdentityConflict:
    source_uri: str
    incoming_doi: str | None
    existing_doc_id: str
    existing_doi: str | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class IngestFailure:
    source_uri: str
    error_class: str
    kind: IngestFailureKind


@dataclass(frozen=True, slots=True)
class IngestionResult:
    entries: tuple[IngestedDocument, ...]
    created_count: int
    conflicts: tuple[IdentityConflict, ...] = ()
    failures: tuple[IngestFailure, ...] = ()

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(entry.document.id for entry in self.entries)

    @property
    def document_count(self) -> int:
        return len(self.entries)

    @property
    def duplicate_count(self) -> int:
        return self.document_count - self.created_count


@dataclass(frozen=True, slots=True)
class _ReceiptRejected(Exception):
    status: str

    def __str__(self) -> str:
        return self.status


def _idempotency_key(operation_id: str, raw: RawDocument) -> str:
    if operation_id == _SAMPLE_OPERATION_KEY:
        return _SAMPLE_OPERATION_KEY
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


def _existing_by_doi(
    conn: sqlite3.Connection,
    doi: str | None,
    content_hash: str,
) -> sqlite3.Row | None:
    if doi is None:
        return None
    return conn.execute(
        "SELECT * FROM documents WHERE doi = ? ORDER BY content_hash = ? DESC LIMIT 1",
        (doi, content_hash),
    ).fetchone()


def _existing_by_hash(
    conn: sqlite3.Connection, content_hash: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documents WHERE content_hash = ?", (content_hash,)
    ).fetchone()


def _work_id_for(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    if row["work_id"]:
        return str(row["work_id"])
    work_id = create_work(conn)
    conn.execute(
        "UPDATE documents SET work_id = ? WHERE id = ? AND work_id IS NULL",
        (work_id, row["id"]),
    )
    return work_id


def item_from_raw(raw: RawDocument, *, operation_id: str) -> IngestItem:
    doi = normalize_doi(raw.doi)
    return IngestItem(
        idempotency_key=_idempotency_key(operation_id, raw),
        scheme="doi" if doi else "",
        normalized_value=doi or "",
        staging_operation_id=operation_id,
        source=raw.source,
        evidence_grade=raw.evidence_grade,
        representation=RepresentationInput(
            source_kind=raw.source_kind,
            source_uri=raw.source_uri,
            title=raw.title,
            content_hash=raw.content_hash,
            raw_text=raw.raw_text,
        ),
        stage=raw.stage or "unknown",
        content_kind=classify_document_content(raw).value,
    )


def _hash_doi_conflict(
    raw: RawDocument,
    by_hash: sqlite3.Row | None,
) -> IdentityConflict | None:
    if by_hash is None:
        return None
    doi = normalize_doi(raw.doi)
    existing_doi = by_hash["doi"]
    if doi is None or existing_doi is None or str(existing_doi) == doi:
        return None
    return IdentityConflict(
        source_uri=raw.source_uri,
        incoming_doi=doi,
        existing_doc_id=str(by_hash["id"]),
        existing_doi=str(existing_doi),
        content_hash=raw.content_hash,
    )


def detect_hash_doi_conflict(
    conn: sqlite3.Connection, raw: RawDocument
) -> IdentityConflict | None:
    return _hash_doi_conflict(raw, _existing_by_hash(conn, raw.content_hash))


def project_legacy_doi(
    conn: sqlite3.Connection, representation_id: str, doi: str
) -> None:
    conn.execute(
        "UPDATE documents SET doi = ? WHERE id = ?",
        (doi, representation_id),
    )


def register_source_artifact(store: KGStore, document: Document) -> None:
    store._artifact_insert(
        uuid.uuid4().hex,
        kind="source_doc",
        source_doc_id=document.id,
        run_id=None,
        filename=document.title or document.source_uri or document.id,
        created_ts=document.fetched_ts,
    )


def _persist_create(
    store: KGStore,
    raw: RawDocument,
    *,
    operation_id: str,
    doi: str | None,
    work_id: str | None,
) -> IngestedDocument:
    conn = store.conn
    item = item_from_raw(raw, operation_id=operation_id)
    if work_id is not None:
        item = replace(item, work_id=work_id)
    receipt = ingest_item(conn, item)
    if receipt.status not in {"created", "staged"} or receipt.representation_id is None:
        raise _ReceiptRejected(receipt.status)
    if doi is not None and work_id is None:
        project_legacy_doi(conn, receipt.representation_id, doi)
    document = store.get_document(receipt.representation_id)
    register_source_artifact(store, document)
    return IngestedDocument(document=document, created=True)


def _persist_duplicate(
    store: KGStore,
    raw: RawDocument,
    existing: sqlite3.Row,
    *,
    operation_id: str,
    doi: str | None,
) -> IngestedDocument:
    conn = store.conn
    work_id = _work_id_for(conn, existing)
    existing_doi = existing["doi"]
    doi_for_item = (
        doi
        if doi is not None
        else (str(existing_doi) if existing_doi is not None else None)
    )
    item = replace(
        item_from_raw(raw, operation_id=operation_id),
        scheme="doi" if doi_for_item else "",
        normalized_value=doi_for_item or "",
        work_id=work_id,
        representation_id=str(existing["id"]),
        representation=None,
    )
    duplicate = conn.execute(
        "SELECT 1 FROM document_observations WHERE idempotency_key = ?",
        (item.idempotency_key,),
    ).fetchone()
    if duplicate is not None:
        return IngestedDocument(
            document=store._row_to_document(existing),
            created=False,
        )
    receipt = ingest_item(conn, item)
    if receipt.status not in {"created", "duplicate"}:
        raise _ReceiptRejected(receipt.status)
    return IngestedDocument(
        document=store._row_to_document(existing),
        created=False,
    )


def persist_raw_document(
    store: KGStore,
    raw: RawDocument,
    *,
    operation_id: str,
    provenance: Provenance,
) -> IngestedDocument | IdentityConflict:
    del provenance
    conn = store.conn
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    doi = normalize_doi(raw.doi)
    by_doi = _existing_by_doi(conn, doi, raw.content_hash)
    if by_doi is not None and str(by_doi["content_hash"]) == raw.content_hash:
        return _persist_duplicate(
            store,
            raw,
            by_doi,
            operation_id=operation_id,
            doi=doi,
        )
    by_hash = _existing_by_hash(conn, raw.content_hash)
    conflict = _hash_doi_conflict(raw, by_hash)
    if conflict is not None:
        return conflict
    if by_hash is not None:
        return _persist_duplicate(
            store,
            raw,
            by_hash,
            operation_id=operation_id,
            doi=doi,
        )
    return _persist_create(
        store,
        raw,
        operation_id=operation_id,
        doi=doi,
        work_id=_work_id_for(conn, by_doi) if by_doi is not None else None,
    )


def ingest_raw_documents(
    store: KGStore,
    documents: Sequence[RawDocument],
    provenance: Provenance,
    *,
    operation_id: str | None = None,
) -> IngestionResult:
    if len(documents) > MAX_INGEST_BATCH:
        raise IngestBatchBoundError(len(documents))
    conn = store.conn
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    op_id = operation_id or provenance.run_dir.name
    entries: list[IngestedDocument] = []
    conflicts: list[IdentityConflict] = []
    failures: list[IngestFailure] = []
    provenance_entries: list[tuple[str, dict[str, Any]]] = []
    created_count = 0
    for raw in documents:
        conn.execute("SAVEPOINT ingest_raw_item")
        try:
            outcome = persist_raw_document(
                store,
                raw,
                operation_id=op_id,
                provenance=provenance,
            )
            conn.execute("RELEASE SAVEPOINT ingest_raw_item")
        except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            conn.execute("ROLLBACK TO SAVEPOINT ingest_raw_item")
            conn.execute("RELEASE SAVEPOINT ingest_raw_item")
            error_class = type(exc).__name__
            failures.append(
                IngestFailure(
                    source_uri=raw.source_uri,
                    error_class=error_class,
                    kind="internal_error",
                )
            )
            provenance_entries.append(
                (
                    "collect.failed",
                    {
                        "source_uri": raw.source_uri,
                        "error_class": error_class,
                    },
                )
            )
            continue
        match outcome:
            case IdentityConflict():
                conflicts.append(outcome)
                provenance_entries.append(
                    (
                        "collect.identity_conflict",
                        {
                            "source_uri": outcome.source_uri,
                            "incoming_doi": outcome.incoming_doi,
                            "existing_doc_id": outcome.existing_doc_id,
                            "existing_doi": outcome.existing_doi,
                        },
                    )
                )
            case IngestedDocument():
                entries.append(outcome)
                created_count += int(outcome.created)
                provenance_entries.append(
                    (
                        "collect.doc",
                        {
                            "doc_id": outcome.document.id,
                            "source_uri": outcome.document.source_uri,
                            "created": outcome.created,
                            "chars": len(raw.raw_text),
                        },
                    )
                )
            case _ as unreachable:
                assert_never(unreachable)
    sync_staging_operation(store_root_from_conn(conn), op_id)
    provenance_entries.append(
        (
            "collect.end",
            {
                "documents": len(documents),
                "created": created_count,
                "identity_conflicts": len(conflicts),
            },
        )
    )
    provenance.log_many(provenance_entries)
    return IngestionResult(
        entries=tuple(entries),
        created_count=created_count,
        conflicts=tuple(conflicts),
        failures=tuple(failures),
    )


def finalize_ingest_writes(
    store: KGStore,
    representation_ids: Sequence[str] = (),
    *,
    staging_operation_id: str | None = None,
) -> None:
    if store.conn.in_transaction:
        store.conn.commit()
    current_ids = tuple(dict.fromkeys(representation_ids))
    root = store_root_from_conn(store.conn)
    decisions = ()
    if current_ids:
        store.conn.execute("BEGIN IMMEDIATE")
        try:
            decisions = tuple(
                finalize_representation(
                    store.conn,
                    root,
                    representation_id,
                    sync_documents_dir=False,
                    staging_operation_id=staging_operation_id,
                )
                for representation_id in current_ids
            )
            sync_documents_directory(root)
        except (FileLifecycleError, OSError, sqlite3.Error):
            store.conn.rollback()
            raise
    try:
        has_unprojected = store.conn.execute(
            "SELECT 1 FROM provenance_outbox WHERE mirrored_ts IS NULL LIMIT 1"
        ).fetchone()
        if has_unprojected is not None:
            project_outbox(store.conn)
        if store.conn.in_transaction:
            store.conn.commit()
    except (FileLifecycleError, OutboxError, OSError, sqlite3.Error):
        if store.conn.in_transaction:
            store.conn.rollback()
        raise
    current_id_set = frozenset(current_ids)
    quarantined = tuple(
        decision.representation_id
        for decision in decisions
        if (
            decision.classification == "quarantined"
            and decision.representation_id is not None
            and decision.representation_id in current_id_set
        )
    )
    if quarantined:
        raise FileIntegrityError(
            "quarantined",
            "file finalization quarantined: " + ", ".join(quarantined),
        )


def ingest_raw_documents_and_finalize(
    store: KGStore,
    documents: Sequence[RawDocument],
    provenance: Provenance,
    *,
    operation_id: str | None = None,
) -> IngestionResult:
    result = ingest_raw_documents(
        store,
        documents,
        provenance,
        operation_id=operation_id,
    )
    created_ids = tuple(entry.document.id for entry in result.entries if entry.created)
    finalize_ingest_writes(
        store,
        created_ids,
        staging_operation_id=operation_id or provenance.run_dir.name,
    )
    return result


def ingest_raw_documents_batched(
    store: KGStore,
    documents: Sequence[RawDocument],
    provenance: Provenance,
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> IngestionResult:
    entries: list[IngestedDocument] = []
    conflicts: list[IdentityConflict] = []
    failures: list[IngestFailure] = []
    created_count = 0
    for completed_batches, start in enumerate(
        range(0, len(documents), MAX_INGEST_BATCH)
    ):
        if should_cancel is not None and should_cancel():
            raise PartialIngestionError(
                kind="cancelled",
                completed_batches=completed_batches,
                created_count=created_count,
            )
        try:
            result = ingest_raw_documents_and_finalize(
                store,
                documents[start : start + MAX_INGEST_BATCH],
                provenance,
            )
        except Exception as exc:
            provenance.log(
                "collect.batches.partial",
                {
                    "completed_batches": completed_batches,
                    "created": created_count,
                    "error_kind": type(exc).__name__,
                },
            )
            raise PartialIngestionError(
                kind="failed",
                completed_batches=completed_batches,
                created_count=created_count,
            ) from exc
        entries.extend(result.entries)
        conflicts.extend(result.conflicts)
        failures.extend(result.failures)
        created_count += result.created_count
    provenance.log(
        "collect.batches",
        {
            "documents": len(documents),
            "batches": ((len(documents) + MAX_INGEST_BATCH - 1) // MAX_INGEST_BATCH),
            "created": created_count,
        },
    )
    return IngestionResult(
        entries=tuple(entries),
        created_count=created_count,
        conflicts=tuple(conflicts),
        failures=tuple(failures),
    )


def ingest_onboarding_sample(
    store: KGStore, *, title: str, text: str
) -> dict[str, Any]:
    raw = RawDocument(
        source_kind="upload",
        source_uri=SAMPLE_SOURCE_URI,
        title=title,
        raw_text=text,
    )
    root = store_root_from_conn(store.conn)
    provenance = Provenance(str(root / "jobs" / "collect-sample"), seed=0)
    result = ingest_raw_documents_and_finalize(
        store,
        (raw,),
        provenance,
        operation_id=_SAMPLE_OPERATION_KEY,
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
