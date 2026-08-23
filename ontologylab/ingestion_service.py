"""Transactional Work / Representation / Observation ingestion core.

The service is deliberately connection-oriented: its SAVEPOINT composes with
the caller's transaction and it never commits or rolls back that transaction.
Every item returns an explicit created, duplicate, conflict, or failed receipt.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Literal

from pathlib import Path

from ontologylab.authority_repo import (
    IdentifierOwnedConflict,
    SecondDoiAttachConflict,
    attach_identifier,
    create_work,
    insert_observation,
)
from ontologylab.connectors.base import normalize_doi
from ontologylab.file_lifecycle import (
    READY,
    FileIntegrityError,
    FileLifecycleError,
    STAGED,
    content_hash_for,
    final_raw_text_path,
    prepare_representation_payload,
    store_root_from_conn,
)
from ontologylab.provenance_outbox import insert_observation_event


ReceiptStatus = Literal["created", "staged", "duplicate", "conflict", "failed"]
Failpoint = Callable[[str], None]
BatchFailpoint = Callable[[str, "IngestItem"], None]
SUPPORTED_IDENTIFIER_SCHEMES = frozenset(
    {"arxiv", "doi", "isbn", "openalex", "pmcid", "pmid"}
)


@dataclass(frozen=True, slots=True)
class RepresentationInput:
    source_kind: str
    source_uri: str
    title: str | None
    content_hash: str
    raw_text_path: str = ""
    raw_text: bytes | str | None = None
    fetched_ts: float | None = None


@dataclass(frozen=True, slots=True)
class IngestItem:
    idempotency_key: str
    scheme: str
    normalized_value: str
    source: str = ""
    evidence_grade: str = ""
    work_id: str | None = None
    representation_id: str | None = None
    representation: RepresentationInput | None = None
    stage: str = "unknown"
    content_kind: str = "metadata_only"


@dataclass(frozen=True, slots=True)
class ConflictDetail:
    kind: Literal["identifier_owned", "second_doi"]
    work_id: str | None
    existing_work_id: str | None
    scheme: str
    existing_value: str | None
    incoming_value: str


@dataclass(frozen=True, slots=True)
class IngestReceipt:
    status: ReceiptStatus
    idempotency_key: str
    work_id: str | None = None
    representation_id: str | None = None
    observation_id: str | None = None
    identifier_id: str | None = None
    work_created: bool = False
    representation_created: bool = False
    observation_created: bool = False
    conflict: ConflictDetail | None = None
    error: str | None = None


class InvalidIngestItem(ValueError):
    """The item cannot identify an operation, identifier, or Representation."""


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def canonicalize_identifier(scheme: str, value: str) -> str:
    if scheme == "doi":
        normalized = normalize_doi(value)
        if normalized is None:
            raise InvalidIngestItem("identifier does not normalize")
        return normalized
    cleaned = value.strip()
    if not cleaned:
        raise InvalidIngestItem("normalized_value must be non-empty")
    return cleaned


def _with_canonical_identifier(item: IngestItem) -> IngestItem:
    if not item.scheme:
        if item.normalized_value.strip():
            raise InvalidIngestItem("identifier value without scheme")
        return item
    return replace(
        item,
        normalized_value=canonicalize_identifier(item.scheme, item.normalized_value),
    )


def _validate(item: IngestItem) -> None:
    if not item.idempotency_key.strip():
        raise InvalidIngestItem("idempotency_key must be non-empty")
    if item.scheme:
        if item.scheme not in SUPPORTED_IDENTIFIER_SCHEMES:
            raise InvalidIngestItem(f"unsupported identifier scheme: {item.scheme!r}")
        if not item.normalized_value.strip():
            raise InvalidIngestItem("normalized_value must be non-empty")
    elif item.normalized_value.strip():
        raise InvalidIngestItem("identifier value without scheme")
    if item.representation_id is not None and item.representation is not None:
        raise InvalidIngestItem(
            "provide representation_id or representation, not both"
        )


def _duplicate_receipt(
    conn: sqlite3.Connection, item: IngestItem
) -> IngestReceipt | None:
    row = conn.execute(
        "SELECT o.id, o.representation_id, ia.identifier_id, wi.work_id "
        "FROM document_observations o "
        "LEFT JOIN identifier_assertions ia ON ia.observation_id = o.id "
        "LEFT JOIN work_identifiers wi ON wi.id = ia.identifier_id "
        "WHERE o.idempotency_key = ?",
        (item.idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    return IngestReceipt(
        status="duplicate",
        idempotency_key=item.idempotency_key,
        work_id=row[3],
        representation_id=row[1],
        observation_id=row[0],
        identifier_id=row[2],
    )


def _resolve_work(
    conn: sqlite3.Connection,
    item: IngestItem,
    failpoint: Failpoint | None = None,
) -> tuple[str, bool]:
    if item.work_id is not None:
        row = conn.execute(
            "SELECT id FROM works WHERE id = ?", (item.work_id,)
        ).fetchone()
        if row is None:
            raise InvalidIngestItem(f"unknown work_id: {item.work_id}")
        return item.work_id, False

    owner = conn.execute(
        "SELECT work_id FROM work_identifiers WHERE scheme = ? "
        "AND normalized_value = ? AND status = 'accepted'",
        (item.scheme, item.normalized_value),
    ).fetchone()
    if failpoint is not None:
        failpoint("after_owner_lookup")
    if owner is not None:
        return str(owner[0]), False
    return create_work(conn), True


def _resolve_representation(
    conn: sqlite3.Connection,
    item: IngestItem,
    work_id: str,
    staged_paths: list[Path],
) -> tuple[str | None, bool]:
    if item.representation_id is not None:
        row = conn.execute(
            "SELECT work_id FROM documents WHERE id = ?",
            (item.representation_id,),
        ).fetchone()
        if row is None:
            raise InvalidIngestItem(
                f"unknown representation_id: {item.representation_id}"
            )
        if row[0] not in (None, work_id):
            raise InvalidIngestItem(
                f"representation {item.representation_id} belongs to another Work"
            )
        if row[0] is None:
            conn.execute(
                "UPDATE documents SET work_id = ? WHERE id = ? AND work_id IS NULL",
                (work_id, item.representation_id),
            )
        return item.representation_id, False

    representation = item.representation
    if representation is None:
        return None, False
    existing = conn.execute(
        "SELECT id FROM documents WHERE work_id = ? AND content_hash = ?",
        (work_id, representation.content_hash),
    ).fetchone()
    if existing is not None:
        return str(existing[0]), False

    # The additive v1 schema still has global content-hash uniqueness. Never
    # reinterpret its collision as Work equality.
    foreign = conn.execute(
        "SELECT id, work_id FROM documents WHERE content_hash = ?",
        (representation.content_hash,),
    ).fetchone()
    if foreign is not None:
        raise InvalidIngestItem(
            f"content hash already belongs to representation {foreign[0]} "
            f"of work {foreign[1]}"
        )

    representation_id = _new_id("rep")
    store_root = store_root_from_conn(conn)
    staged = prepare_representation_payload(
        store_root,
        item.idempotency_key,
        representation_id,
        raw_text=representation.raw_text,
        raw_text_path=representation.raw_text_path,
    )
    if staged is not None:
        if content_hash_for(staged.read_bytes()) != representation.content_hash:
            raise FileIntegrityError(
                "hash_mismatch",
                "staged file hash does not match Representation content_hash",
            )
        staged_paths.append(staged)
    raw_text_path = (
        final_raw_text_path(representation_id) if staged is not None else ""
    )
    representation_state = STAGED if staged is not None else READY
    conn.execute(
        "INSERT INTO documents "
        "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
        "raw_text_path, source, evidence_grade, doi, work_id, "
        "representation_state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
        (
            representation_id,
            representation.source_kind,
            representation.source_uri,
            representation.title,
            representation.fetched_ts
            if representation.fetched_ts is not None
            else time.time(),
            representation.content_hash,
            raw_text_path,
            item.source,
            item.evidence_grade,
            work_id,
            representation_state,
        ),
    )
    return representation_id, True


def _discard_staged(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass


def _rollback_item(conn: sqlite3.Connection) -> None:
    conn.execute("ROLLBACK TO SAVEPOINT ingestion_service_v2")
    conn.execute("RELEASE SAVEPOINT ingestion_service_v2")


def ingest_item(
    conn: sqlite3.Connection,
    item: IngestItem,
    *,
    failpoint: Failpoint | None = None,
) -> IngestReceipt:
    """Ingest one item atomically and return a typed, non-raising outcome."""
    # Never become the outermost savepoint: RELEASE of that is COMMIT.
    # IMMEDIATE avoids WAL BUSY_SNAPSHOT (two deferred readers upgrading).
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        item = _with_canonical_identifier(item)
    except InvalidIngestItem as exc:
        return IngestReceipt(
            status="failed",
            idempotency_key=item.idempotency_key,
            work_id=item.work_id,
            representation_id=item.representation_id,
            error=f"{type(exc).__name__}: {exc}",
        )
    receipt = _ingest_once(conn, item, failpoint=failpoint)
    if (
        receipt.status == "conflict"
        and item.work_id is None
        and receipt.conflict is not None
        and receipt.conflict.kind == "identifier_owned"
        and receipt.conflict.existing_work_id
    ):
        # Same-family reservation loser: re-resolve onto the winner's Work.
        return _ingest_once(
            conn,
            replace(item, work_id=receipt.conflict.existing_work_id),
            failpoint=failpoint,
        )
    return receipt


def _ingest_once(
    conn: sqlite3.Connection,
    item: IngestItem,
    *,
    failpoint: Failpoint | None = None,
) -> IngestReceipt:
    conn.execute("SAVEPOINT ingestion_service_v2")
    work_id: str | None = item.work_id
    representation_id: str | None = item.representation_id
    staged_paths: list[Path] = []
    try:
        _validate(item)
        if failpoint is not None:
            failpoint("after_validate")
        duplicate = _duplicate_receipt(conn, item)
        if duplicate is not None:
            conn.execute("RELEASE SAVEPOINT ingestion_service_v2")
            return duplicate

        work_id, work_created = _resolve_work(conn, item, failpoint=failpoint)
        if failpoint is not None:
            failpoint("after_work")
        representation_id, representation_created = _resolve_representation(
            conn, item, work_id, staged_paths
        )
        if failpoint is not None:
            failpoint("after_representation")

        if item.scheme:
            attached = attach_identifier(
                conn,
                work_id=work_id,
                scheme=item.scheme,
                normalized_value=item.normalized_value,
                idempotency_key=item.idempotency_key,
                source=item.source,
                evidence_grade=item.evidence_grade,
                representation_id=representation_id,
                stage=item.stage,
                content_kind=item.content_kind,
                failpoint=failpoint,
            )
            observation_id = attached.observation_id
            identifier_id = attached.identifier_id
            observation_created = attached.created
        else:
            observation_id = insert_observation(
                conn,
                idempotency_key=item.idempotency_key,
                source=item.source,
                evidence_grade=item.evidence_grade,
                representation_id=representation_id,
                stage=item.stage,
                content_kind=item.content_kind,
            )
            identifier_id = None
            observation_created = True
        if failpoint is not None:
            failpoint("after_authority")
        insert_observation_event(
            conn,
            observation_id=observation_id,
            work_id=work_id,
            representation_id=representation_id,
            identifier_id=identifier_id,
            idempotency_key=item.idempotency_key,
        )
        if failpoint is not None:
            failpoint("after_outbox")
        conn.execute("RELEASE SAVEPOINT ingestion_service_v2")
        return IngestReceipt(
            status="staged" if staged_paths else "created",
            idempotency_key=item.idempotency_key,
            work_id=work_id,
            representation_id=representation_id,
            observation_id=observation_id,
            identifier_id=identifier_id,
            work_created=work_created,
            representation_created=representation_created,
            observation_created=observation_created,
        )
    except FileLifecycleError as exc:
        _discard_staged(staged_paths)
        _rollback_item(conn)
        return IngestReceipt(
            status="failed",
            idempotency_key=item.idempotency_key,
            work_id=item.work_id,
            representation_id=item.representation_id,
            error=f"{type(exc).__name__}: {exc}",
        )
    except IdentifierOwnedConflict as exc:
        _discard_staged(staged_paths)
        _rollback_item(conn)
        return IngestReceipt(
            status="conflict",
            idempotency_key=item.idempotency_key,
            work_id=work_id,
            representation_id=representation_id,
            conflict=ConflictDetail(
                kind="identifier_owned",
                work_id=work_id,
                existing_work_id=exc.existing_work_id,
                scheme=exc.scheme,
                existing_value=exc.normalized_value,
                incoming_value=exc.normalized_value,
            ),
        )
    except SecondDoiAttachConflict as exc:
        _discard_staged(staged_paths)
        _rollback_item(conn)
        return IngestReceipt(
            status="conflict",
            idempotency_key=item.idempotency_key,
            work_id=exc.work_id,
            representation_id=representation_id,
            conflict=ConflictDetail(
                kind="second_doi",
                work_id=exc.work_id,
                existing_work_id=exc.work_id,
                scheme="doi",
                existing_value=exc.existing_doi,
                incoming_value=exc.incoming_doi,
            ),
        )
    except Exception as exc:
        _discard_staged(staged_paths)
        _rollback_item(conn)
        return IngestReceipt(
            status="failed",
            idempotency_key=item.idempotency_key,
            work_id=item.work_id,
            representation_id=item.representation_id,
            error=f"{type(exc).__name__}: {exc}",
        )


def ingest_work_items(
    conn: sqlite3.Connection,
    items: Iterable[IngestItem],
    *,
    failpoint: BatchFailpoint | None = None,
) -> tuple[IngestReceipt, ...]:
    """Process a batch as per-item atomic units with no hidden failures."""
    receipts: list[IngestReceipt] = []
    for item in items:
        item_failpoint = (
            (lambda stage, current=item: failpoint(stage, current))
            if failpoint is not None
            else None
        )
        receipts.append(ingest_item(conn, item, failpoint=item_failpoint))
    return tuple(receipts)


def ingest_items(
    conn: sqlite3.Connection,
    items: Iterable[IngestItem],
    *,
    failpoint: BatchFailpoint | None = None,
) -> tuple[IngestReceipt, ...]:
    return ingest_work_items(conn, items, failpoint=failpoint)


__all__ = [
    "ConflictDetail",
    "IngestItem",
    "IngestReceipt",
    "InvalidIngestItem",
    "RepresentationInput",
    "canonicalize_identifier",
    "ingest_item",
    "ingest_items",
    "ingest_work_items",
]
