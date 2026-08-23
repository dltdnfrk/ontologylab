"""Shared persistence seam for every document-ingestion entrypoint."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ontologylab.connectors.base import RawDocument
from ontologylab.kgstore import KGStore
from ontologylab.models import Document
from ontologylab.provenance import Provenance


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    """One persistence outcome, including duplicate status."""

    document: Document
    created: bool


@dataclass(frozen=True, slots=True)
class IdentityConflict:
    """One refused merge: same bytes under two different explicit DOIs."""

    source_uri: str
    incoming_doi: str | None
    existing_doc_id: str
    existing_doi: str | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Complete result for one bounded ingestion batch."""

    entries: tuple[IngestedDocument, ...]
    created_count: int
    conflicts: tuple[IdentityConflict, ...] = ()

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(entry.document.id for entry in self.entries)

    @property
    def document_count(self) -> int:
        return len(self.entries)

    @property
    def duplicate_count(self) -> int:
        return self.document_count - self.created_count


def finalize_shadow_writes(
    store: KGStore,
    representation_ids: Sequence[str] = (),
) -> None:
    """Caller-owned commit plus file/outbox projection after shadow persist."""
    from ontologylab.file_lifecycle import FileIntegrityError, reconcile_files
    from ontologylab.provenance_outbox import project_outbox

    if store.conn.in_transaction:
        store.conn.commit()
    decisions = reconcile_files(store.conn)
    project_outbox(store.conn)
    if store.conn.in_transaction:
        store.conn.commit()
    current_ids = frozenset(representation_ids)
    quarantined = tuple(
        decision.representation_id
        for decision in decisions
        if (
            decision.classification == "quarantined"
            and decision.representation_id is not None
            and decision.representation_id in current_ids
        )
    )
    if quarantined:
        raise FileIntegrityError(
            "quarantined",
            "shadow file finalization quarantined: " + ", ".join(quarantined),
        )


def ingest_documents(
    store: KGStore,
    documents: Sequence[RawDocument],
    provenance: Provenance,
) -> IngestionResult:
    """Persist documents through the legacy-compatible v2 shadow adapter."""
    from ontologylab import ingestion_shadow as shadow

    result = shadow.shadow_persist(store, documents, provenance)
    finalize_shadow_writes(store, result.document_ids)
    return result


def ingest_sample(
    store: KGStore, *, title: str, text: str
) -> dict[str, Any]:
    """Persist the onboarding sample through the same shadow adapter."""
    from ontologylab import ingestion_shadow as shadow

    payload = shadow.shadow_ingest_sample(store, title=title, text=text)
    document_id = payload.get("document_id")
    finalize_shadow_writes(
        store,
        (document_id,) if isinstance(document_id, str) else (),
    )
    return payload
