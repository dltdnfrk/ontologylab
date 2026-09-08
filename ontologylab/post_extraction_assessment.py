"""Pure receipt correlation over immutable snapshots, with no claim authority."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import replace

from ontologylab.citation_ids import fact_revision_id
from ontologylab.post_extraction_types import (
    AdvisoryRecord,
    AssessmentInput,
    ChunkReceiptRow,
    CitationRow,
    ContradictionState,
    DocumentRow,
    FactRow,
    PostExtractionAssessment,
    ReceiptIssue,
    ReceiptSnapshot,
    RunReceiptRow,
    SemanticField,
    SingleValueRule,
    SupportResult,
    SupportState,
)
from ontologylab.research_spec import JsonObject, JsonValue

_SCHEMA = "post-extraction-assessment-v1"
__all__ = [
    "AdvisoryRecord",
    "AssessmentInput",
    "ChunkReceiptRow",
    "CitationRow",
    "ContradictionState",
    "DocumentRow",
    "FactRow",
    "PostExtractionAssessment",
    "ReceiptIssue",
    "ReceiptSnapshot",
    "RunReceiptRow",
    "SemanticField",
    "SingleValueRule",
    "SupportState",
    "derive_post_extraction_assessment",
    "post_extraction_assessment_value",
]


def _canonical(value: JsonValue) -> bytes:
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return unicodedata.normalize("NFC", text).encode()


def _fact_value(fact: FactRow) -> JsonObject:
    return {
        "fact_kind": fact.fact_kind, "fact_id": fact.fact_id,
        "schema_version_id": fact.schema_version_id,
        "type_name": fact.type_name, "subject_key": fact.subject_key,
        "target_key": fact.target_key, "source_document_id": fact.source_document_id,
        "fields": [
            {"location": item.location, "semantic_key": item.semantic_key, "value": item.value}
            for item in sorted(
                fact.fields,
                key=lambda field: (
                    field.location,
                    field.semantic_key,
                    _canonical(field.value),
                ),
            )
        ],
    }


def _record_value(record: AdvisoryRecord) -> JsonObject:
    return {
        "proposed_fact_id": record.proposed_fact_id, "fact_kind": record.fact_kind,
        "fact_revision": record.fact_revision, "fact_hash": record.fact_hash,
        "citation_receipt_ids": list(record.citation_receipt_ids),
        "extraction_run_receipt_ids": list(record.extraction_run_receipt_ids),
        "extraction_chunk_receipt_ids": list(record.extraction_chunk_receipt_ids),
        "support_state": record.support_state.value,
        "contradiction_state": record.contradiction_state.value,
        "reason_codes": list(record.reason_codes),
    }


def _support(fact: FactRow, snapshot: ReceiptSnapshot) -> SupportResult:
    if fact.fact_kind not in {"node", "edge"}:
        return SupportState.NOT_ASSESSED, (), (), (), ("unmappable_fact_kind",)
    key = (fact.fact_kind, fact.fact_id)
    issues = tuple(issue.reason_code for issue in snapshot.issues if (issue.fact_kind, issue.fact_id) == key)
    citations = tuple(row for row in snapshot.citations if (row.fact_kind, row.fact_id) == key)
    citation_ids = tuple(sorted(row.receipt_id for row in citations))
    run_ids = tuple(sorted({row.run_receipt_id for row in citations}))
    chunk_ids = tuple(sorted({row.chunk_receipt_id for row in citations}))
    if issues:
        issue_reasons = tuple(sorted(set(issues)))
        return (SupportState.NOT_ASSESSED, citation_ids, run_ids, chunk_ids,
                issue_reasons)
    if None in {snapshot.inventory_root_before, snapshot.inventory_root_after}:
        return (SupportState.NOT_ASSESSED, citation_ids, run_ids, chunk_ids,
                ("receipt_inventory_unverifiable",))
    if snapshot.inventory_root_before != snapshot.inventory_root_after:
        return (SupportState.NOT_ASSESSED, citation_ids, run_ids, chunk_ids,
                ("receipt_inventory_drift",))
    if not citations:
        return SupportState.RECEIPT_MISSING, (), (), (), ("citation_receipt_missing",)
    if (
        len({row.receipt_id for row in snapshot.runs}) != len(snapshot.runs)
        or len({row.receipt_id for row in snapshot.chunks}) != len(snapshot.chunks)
        or len({row.representation_id for row in snapshot.documents})
        != len(snapshot.documents)
    ):
        return (
            SupportState.NOT_ASSESSED,
            citation_ids,
            run_ids,
            chunk_ids,
            ("duplicate_receipt_id",),
        )
    rejected_reasons: list[str] = []
    valid: list[CitationRow] = []
    revision = fact_revision_id(fact.fact_kind, fact.fact_id)
    run_rows = {row.receipt_id: row for row in snapshot.runs}
    chunk_rows = {row.receipt_id: row for row in snapshot.chunks}
    document_rows = {row.representation_id: row for row in snapshot.documents}
    for citation in citations:
        reasons: list[str] = []
        run = run_rows.get(citation.run_receipt_id)
        chunk = chunk_rows.get(citation.chunk_receipt_id)
        document = document_rows.get(citation.representation_id)
        if citation.fact_revision != revision:
            reasons.append("stale_fact_revision")
        if citation.representation_id != fact.source_document_id:
            reasons.append("citation_binding_mismatch")
        if run is None:
            reasons.append("run_receipt_missing")
        elif run.representation_id != citation.representation_id:
            reasons.append("run_binding_mismatch")
        elif run.document_content_hash != citation.representation_content_hash:
            reasons.append("run_hash_mismatch")
        if chunk is None:
            reasons.append("chunk_receipt_missing")
        elif chunk.run_receipt_id != citation.run_receipt_id:
            reasons.append("chunk_binding_mismatch")
        if document is None or document.content_hash != citation.representation_content_hash:
            reasons.append("representation_hash_mismatch")
        if reasons:
            rejected_reasons.extend(reasons)
        else:
            valid.append(citation)
    if valid:
        valid_citations = tuple(sorted(row.receipt_id for row in valid))
        valid_runs = tuple(sorted({row.run_receipt_id for row in valid}))
        valid_chunks = tuple(sorted({row.chunk_receipt_id for row in valid}))
        return (
            SupportState.RECEIPT_LINKED,
            valid_citations,
            valid_runs,
            valid_chunks,
            (),
        )
    if rejected_reasons:
        return (SupportState.NOT_ASSESSED, citation_ids, run_ids, chunk_ids,
                tuple(sorted(set(rejected_reasons))))
    return SupportState.NOT_ASSESSED, citation_ids, run_ids, chunk_ids, ()


def _normalized(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFC", value or "").split()).casefold()


def _claim_key(fact: FactRow, field: SemanticField) -> tuple[str, ...]:
    return (
        fact.fact_kind, str(fact.schema_version_id), _normalized(fact.type_name),
        _normalized(fact.subject_key), _normalized(fact.target_key),
        _normalized(field.location), _normalized(field.semantic_key),
    )


def _rule_exists(
    fact: FactRow, field: SemanticField, rules: tuple[SingleValueRule, ...],
) -> bool:
    key = tuple(map(_normalized, (
        fact.fact_kind, fact.type_name, field.location, field.semantic_key,
    )))
    return any(
        tuple(map(_normalized, (
            rule.fact_kind, rule.type_name, rule.location, rule.semantic_key,
        ))) == key
        for rule in rules
    )


def _rule_reason(
    fact: FactRow, fields: tuple[SemanticField, ...], rules: tuple[SingleValueRule, ...],
) -> str:
    if any(field.location not in {"property", "qualifier"} for field in fields):
        return "unsupported_semantic_key"
    same_schema = any(
        tuple(map(_normalized, (rule.fact_kind, rule.type_name, rule.location)))
        == tuple(map(_normalized, (fact.fact_kind, fact.type_name, field.location)))
        for field in fields
        for rule in rules
    )
    return "unsupported_semantic_key" if same_schema else "single_value_schema_missing"


def derive_post_extraction_assessment(input_value: AssessmentInput) -> PostExtractionAssessment:
    facts = tuple(sorted(input_value.facts, key=lambda item: (item.fact_kind, item.fact_id)))
    records: list[AdvisoryRecord] = []
    for fact in facts:
        support, citations, runs, chunks, reasons = _support(fact, input_value.receipts)
        material = _canonical(_fact_value(fact))
        records.append(AdvisoryRecord(
            fact.fact_id, fact.fact_kind, fact_revision_id(fact.fact_kind, fact.fact_id),
            "sha256:" + hashlib.sha256(material).hexdigest(), citations, runs, chunks, support,
            ContradictionState.NOT_ASSESSED, reasons,
        ))
    linked = {(record.fact_kind, record.proposed_fact_id) for record in records
              if record.support_state is SupportState.RECEIPT_LINKED}
    for index, (fact, record) in enumerate(zip(facts, records, strict=True)):
        if (fact.fact_kind, fact.fact_id) not in linked:
            continue
        unsupported = tuple(field for field in fact.fields
                            if field.location not in {"property", "qualifier"}
                            or isinstance(field.value, (list, dict))
                            or not _rule_exists(fact, field, input_value.schema_rules))
        if not fact.fields or unsupported:
            code = _rule_reason(fact, unsupported or fact.fields, input_value.schema_rules)
            records[index] = replace(record, reason_codes=tuple(sorted({*record.reason_codes, code})))
            continue
        conflict = False
        for field in fact.fields:
            if field.value is None:
                continue
            values = {_canonical(candidate.value).decode() for other in facts
                      if (other.fact_kind, other.fact_id) in linked
                      for candidate in other.fields if candidate.value is not None
                      and _claim_key(other, candidate) == _claim_key(fact, field)}
            conflict = conflict or len(values) > 1
        state = ContradictionState.POTENTIAL_CONFLICT if conflict else ContradictionState.NOT_OBSERVED
        extra = ("distinct_single_values",) if conflict else ()
        records[index] = replace(record, contradiction_state=state,
                                 reason_codes=tuple(sorted({*record.reason_codes, *extra})))
    envelope: JsonObject = {
        "schema_version": _SCHEMA,
        "records": [_record_value(record) for record in records],
    }
    assessment_hash = "sha256:" + hashlib.sha256(_canonical(envelope)).hexdigest()
    return PostExtractionAssessment(tuple(records), assessment_hash)


def post_extraction_assessment_value(value: PostExtractionAssessment) -> JsonObject:
    support = {state.value: 0 for state in SupportState}
    contradiction = {state.value: 0 for state in ContradictionState}
    for record in value.records:
        support[record.support_state.value] += 1
        contradiction[record.contradiction_state.value] += 1
    support_values: JsonObject = {}
    contradiction_values: JsonObject = {}
    for key, count in support.items():
        support_values[key] = count
    for key, count in contradiction.items():
        contradiction_values[key] = count
    count_values: JsonObject = {
        "support": support_values,
        "contradiction": contradiction_values,
    }
    return {"schema_version": _SCHEMA, "assessment_hash": value.assessment_hash,
            "counts": count_values,
            "records": [_record_value(record) for record in value.records]}
