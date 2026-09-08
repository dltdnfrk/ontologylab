"""Research consumer: F9-selected ready Representation plus Task 2 receipts."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ontologylab.connectors.base import RawDocument
from ontologylab.extraction_receipt_ids import digest
from ontologylab.extraction_receipt_types import (
    ChunkSpan,
    ExtractionRunBinding,
)
from ontologylab.extraction_state import put_extraction_receipts
from ontologylab.extractor import (
    PROMPT_VERSION,
    ExtractionOutcome,
    chunk_document,
    run_extraction,
)
from ontologylab.file_lifecycle import (
    content_hash_for,
    read_ready_text,
    store_root_from_conn,
)
from ontologylab.ingestion import finalize_ingest_writes
from ontologylab.ingestion_service import IngestItem, RepresentationInput, ingest_item
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps
from ontologylab.selection import put_selection_receipt
from ontologylab.selection_types import (
    PolicyVersion,
    SelectionReceipt,
    SelectionRefusalCode,
    SelectionRefused,
)


class SupportsGenerate(Protocol):
    async def generate(
        self, prompt: str, *, model: str | None = None,
    ) -> tuple[str, dict[str, str | int | float]]:
        ...


@dataclass(frozen=True, slots=True)
class ResearchExtractSession:
    engine: SupportsGenerate
    provenance: Provenance
    caps: Caps
    extractor_engine: str
    extractor_model: str
    on_progress: Callable[[str], None]
    on_stats: Callable[[dict[str, int]], None]
    should_abort: Callable[[], str] | None = None
    decode_params_json: str = "{}"
    raw_documents: tuple[RawDocument, ...] = ()


def attach_explicit_completeness_variants(
    store: KGStore, documents: Sequence[RawDocument],
) -> None:
    """Persist explicit abstract/full-text siblings onto the collected Work."""
    explicit = [doc for doc in documents if doc.content_kind and doc.doi]
    if not explicit:
        return
    by_doi: dict[str, list[RawDocument]] = {}
    for doc in explicit:
        doi = doc.doi
        if doi is None:
            continue
        by_doi.setdefault(doi, []).append(doc)
    created: list[str] = []
    for doi, group in by_doi.items():
        if len({doc.content_kind for doc in group}) < 2:
            continue
        existing = store.conn.execute(
            "SELECT work_id FROM work_identifiers WHERE scheme = 'doi' "
            "AND normalized_value = ? AND status = 'accepted'",
            (doi,),
        ).fetchone()
        if existing is None or existing["work_id"] is None:
            by_doc = store.conn.execute(
                "SELECT work_id FROM documents WHERE doi = ? LIMIT 1",
                (doi,),
            ).fetchone()
            if by_doc is None or by_doc["work_id"] is None:
                continue
            work_id = str(by_doc["work_id"])
        else:
            work_id = str(existing["work_id"])
        known = {
            str(row["content_hash"])
            for row in store.conn.execute(
                "SELECT content_hash FROM documents WHERE work_id = ?",
                (work_id,),
            )
        }
        for doc in group:
            if doc.content_hash in known:
                continue
            receipt = ingest_item(
                store.conn,
                IngestItem(
                    idempotency_key=f"research-variant-{doi}-{doc.content_hash}",
                    scheme="doi",
                    normalized_value=doi,
                    source=doc.source,
                    evidence_grade=doc.evidence_grade,
                    work_id=work_id,
                    representation=RepresentationInput(
                        source_kind=doc.source_kind,
                        source_uri=doc.source_uri,
                        title=doc.title,
                        content_hash=doc.content_hash,
                        raw_text=doc.raw_text,
                    ),
                    stage=doc.stage or "unknown",
                    content_kind=doc.content_kind,
                ),
            )
            if receipt.representation_id is None:
                continue
            created.append(receipt.representation_id)
            known.add(doc.content_hash)
    if created:
        finalize_ingest_writes(store, created)


async def extract_research_documents(
    store: KGStore,
    collected_ids: tuple[str, ...],
    session: ResearchExtractSession,
) -> ExtractionOutcome:
    """Select F9 preferred ready full text per Work, then extract only those."""
    if session.raw_documents:
        attach_explicit_completeness_variants(store, session.raw_documents)
    selected: list[str] = []
    for work_id in _work_ids(store, collected_ids):
        receipt = put_selection_receipt(store.conn, work_id, PolicyVersion.V1)
        if receipt.selected_representation_id is None:
            raise SelectionRefused(
                SelectionRefusalCode.NO_ELIGIBLE_READY_FULL_TEXT,
                work_id,
                f"no eligible ready full text for work {work_id}",
            )
        _bind_run_receipt(store, receipt, session)
        selected.append(receipt.selected_representation_id)
    if store.conn.in_transaction:
        store.conn.commit()
    if not selected:
        return ExtractionOutcome("")
    decode_params = json.loads(session.decode_params_json)
    return await run_extraction(
        store,
        session.engine,
        session.provenance,
        session.caps,
        selected,
        extractor_engine=session.extractor_engine,
        extractor_model=session.extractor_model or None,
        on_progress=session.on_progress,
        on_stats=session.on_stats,
        should_abort=session.should_abort,
        decode_params=decode_params if decode_params else None,
    )


def _work_ids(store: KGStore, collected_ids: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    known: set[str] = set()
    for doc_id in collected_ids:
        row = store.conn.execute(
            "SELECT work_id FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None or row["work_id"] is None:
            continue
        work_id = str(row["work_id"])
        if work_id in known:
            continue
        known.add(work_id)
        seen.append(work_id)
    return tuple(seen)


def _bind_run_receipt(
    store: KGStore,
    selection: SelectionReceipt,
    session: ResearchExtractSession,
) -> None:
    representation_id = selection.selected_representation_id
    if representation_id is None:
        return
    text = read_ready_text(
        store.conn, store_root_from_conn(store.conn), representation_id,
    )
    chunks = chunk_document(text)
    spans = tuple(
        ChunkSpan(
            index=chunk.index,
            start_offset=chunk.char_offset,
            end_offset=chunk.char_offset + len(chunk.text),
            text=chunk.text,
            text_hash=content_hash_for(chunk.text.encode("utf-8")),
            coordinate_profile="document-utf8-v1",
        )
        for chunk in chunks
    )
    schema = store.get_schema()
    put_extraction_receipts(
        store.conn,
        ExtractionRunBinding(
            representation_id=representation_id,
            policy_identity=selection.policy_hash,
            config_identity=digest((
                "research-extract-config-v1",
                session.extractor_engine,
                session.extractor_model,
                PROMPT_VERSION,
                session.decode_params_json,
            )),
            schema_version_id=int(schema["schema_version_id"]),
            extractor_engine=session.extractor_engine,
            extractor_model=session.extractor_model,
            prompt_version=PROMPT_VERSION,
            decode_params_json=session.decode_params_json,
        ),
        spans,
    )
