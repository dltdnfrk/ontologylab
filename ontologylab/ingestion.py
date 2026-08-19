"""Shared persistence seam for every document-ingestion entrypoint."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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
class IngestionResult:
    """Complete result for one bounded ingestion batch."""

    entries: tuple[IngestedDocument, ...]
    created_count: int

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
    created_count = 0
    for raw in documents:
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
        {"documents": len(documents), "created": created_count},
    )
    return IngestionResult(entries=tuple(entries), created_count=created_count)
