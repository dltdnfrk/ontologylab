"""Shared persistence seam for every document-ingestion entrypoint."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ontologylab.connectors.base import RawDocument
from ontologylab.kgstore import DocumentIdentityConflict, KGStore
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


def ingest_documents(
    store: KGStore,
    documents: Sequence[RawDocument],
    provenance: Provenance,
) -> IngestionResult:
    """Persist documents without dropping identity or evidence metadata."""
    entries: list[IngestedDocument] = []
    conflicts: list[IdentityConflict] = []
    created_count = 0
    for raw in documents:
        try:
            document, created = store.insert_document(
                source_kind=raw.source_kind,
                source_uri=raw.source_uri,
                title=raw.title,
                raw_text=raw.raw_text,
                content_hash=raw.content_hash,
                source=raw.source,
                evidence_grade=raw.evidence_grade,
                doi=raw.doi,
            )
        except DocumentIdentityConflict as conflict:
            # A refused merge is a typed per-document outcome, not a batch
            # failure: the rest of the run still persists, and the conflict
            # is recorded for the caller and the provenance trail.
            conflicts.append(
                IdentityConflict(
                    source_uri=raw.source_uri,
                    incoming_doi=conflict.incoming_doi,
                    existing_doc_id=conflict.existing_doc_id,
                    existing_doi=conflict.existing_doi,
                    content_hash=conflict.content_hash,
                )
            )
            provenance.log(
                "collect.identity_conflict",
                {
                    "source_uri": raw.source_uri,
                    "incoming_doi": conflict.incoming_doi,
                    "existing_doc_id": conflict.existing_doc_id,
                    "existing_doi": conflict.existing_doi,
                },
            )
            continue
        entries.append(IngestedDocument(document=document, created=created))
        created_count += int(created)
        provenance.log(
            "collect.doc",
            {
                "doc_id": document.id,
                "source_uri": document.source_uri,
                "created": created,
                "chars": len(raw.raw_text),
            },
        )
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
