from __future__ import annotations

import importlib

from ontologylab.citation_ids import fact_revision_id


def _api():
    return importlib.import_module("ontologylab.post_extraction_assessment")


def _fact(
    fact_id: str = "fact-a",
    *,
    fact_kind: str = "node",
    subject_key: str = "subject",
    target_key: str | None = None,
    field_key: str = "dose",
    value: str | float | bool | None = "10",
    location: str = "property",
    type_name: str | None = None,
):
    api = _api()
    return api.FactRow(
        fact_kind=fact_kind,
        fact_id=fact_id,
        schema_version_id=1,
        type_name=type_name
        or ("Measurement" if fact_kind == "node" else "measures"),
        subject_key=subject_key,
        target_key=target_key,
        source_document_id=f"doc-{fact_id}",
        fields=(api.SemanticField(location, field_key, value),),
    )


def _rule(
    *,
    fact_kind: str = "node",
    type_name: str | None = None,
    location: str = "property",
    key: str = "dose",
):
    api = _api()
    return api.SingleValueRule(
        fact_kind=fact_kind,
        type_name=type_name
        or ("Measurement" if fact_kind == "node" else "measures"),
        location=location,
        semantic_key=key,
    )


def _linked_rows(fact):
    api = _api()
    suffix = fact.fact_id
    citation = api.CitationRow(
        receipt_id=f"citation-{suffix}",
        fact_kind=fact.fact_kind,
        fact_id=fact.fact_id,
        fact_revision=fact_revision_id(fact.fact_kind, fact.fact_id),
        representation_id=fact.source_document_id,
        representation_content_hash=f"hash-{suffix}",
        run_receipt_id=f"run-{suffix}",
        chunk_receipt_id=f"chunk-{suffix}",
    )
    return (
        citation,
        api.RunReceiptRow(
            receipt_id=citation.run_receipt_id,
            representation_id=fact.source_document_id,
            document_content_hash=citation.representation_content_hash,
        ),
        api.ChunkReceiptRow(
            receipt_id=citation.chunk_receipt_id,
            run_receipt_id=citation.run_receipt_id,
        ),
        api.DocumentRow(
            representation_id=fact.source_document_id,
            content_hash=citation.representation_content_hash,
        ),
    )


def _assessment(
    facts,
    *,
    rules=(),
    citations=(),
    runs=(),
    chunks=(),
    documents=(),
    root_before: str = "inventory-stable",
    root_after: str = "inventory-stable",
):
    api = _api()
    value = api.AssessmentInput(
        facts=tuple(facts),
        schema_rules=tuple(rules),
        receipts=api.ReceiptSnapshot(
            citations=tuple(citations),
            runs=tuple(runs),
            chunks=tuple(chunks),
            documents=tuple(documents),
            inventory_root_before=root_before,
            inventory_root_after=root_after,
            issues=(),
        ),
    )
    return api.derive_post_extraction_assessment(value)


def _linked_assessment(*facts, rules=()):
    rows = [_linked_rows(fact) for fact in facts]
    return _assessment(
        facts,
        rules=rules,
        citations=(row[0] for row in rows),
        runs=(row[1] for row in rows),
        chunks=(row[2] for row in rows),
        documents=(row[3] for row in rows),
    )
