"""Read-only KGStore adapter for post-extraction advisory inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TypeAlias

from ontologylab.kgstore import KGStore
from ontologylab.pack_receipt_seal import ReceiptSealRefused, seal_receipt_inventory
from ontologylab.post_extraction_types import (
    AssessmentInput,
    ChunkReceiptRow,
    CitationRow,
    DocumentRow,
    FactRow,
    ReceiptIssue,
    ReceiptSnapshot,
    RunReceiptRow,
    SemanticField,
    SingleValueRule,
)
from ontologylab.research_spec import JsonValue

FactIdentity: TypeAlias = tuple[str, str]


@dataclass(frozen=True, slots=True)
class DocumentScope:
    representation_ids: frozenset[str]
    work_ids: frozenset[str]


def snapshot_fact_ids(store: KGStore) -> frozenset[FactIdentity]:
    return frozenset(
        (kind, str(row[0]))
        for kind, table in (("node", "nodes"), ("edge", "edges"))
        for row in store.conn.execute(f"SELECT id FROM {table}")
    )


def current_document_scope(
    store: KGStore,
    document_ids: tuple[str, ...],
) -> DocumentScope:
    works: set[str] = set()
    for document_id in document_ids:
        row = store.conn.execute(
            "SELECT work_id FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if row is not None and row["work_id"] is not None:
            works.add(str(row["work_id"]))
    return DocumentScope(frozenset(document_ids), frozenset(works))


def post_extraction_input(
    store: KGStore,
    before: frozenset[FactIdentity],
    scope: DocumentScope,
) -> AssessmentInput:
    facts = _new_fact_rows(store, before, scope)
    return AssessmentInput(
        facts,
        _single_value_rules(store, facts),
        _receipt_snapshot(store, facts),
    )


def _json_fields(raw: str | None, location: str) -> tuple[SemanticField, ...]:
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return ()
    if not isinstance(value, dict):
        return ()
    return tuple(
        SemanticField(location, str(key), item)
        for key, item in sorted(value.items())
    )


def _new_fact_rows(
    store: KGStore,
    before: frozenset[FactIdentity],
    scope: DocumentScope,
) -> tuple[FactRow, ...]:
    facts: list[FactRow] = []
    for kind, table in (("node", "nodes"), ("edge", "edges")):
        rows = store.conn.execute(
            f"SELECT fact.*, document.work_id FROM {table} fact "
            "JOIN documents document ON document.id = fact.source_doc_id "
            "ORDER BY fact.id"
        ).fetchall()
        for stored in rows:
            fact_id = str(stored["id"])
            work_id = (
                None if stored["work_id"] is None else str(stored["work_id"])
            )
            if (
                (kind, fact_id) in before
                or (
                    str(stored["source_doc_id"]) not in scope.representation_ids
                    and work_id not in scope.work_ids
                )
            ):
                continue
            if kind == "node":
                subject, target = str(stored["normalized_name"]), None
                fields = _json_fields(stored["properties_json"], "property")
                type_name = str(stored["entity_type"])
            else:
                subject = str(stored["src_node_id"])
                target = str(stored["dst_node_id"])
                fields = (
                    *_json_fields(stored["properties_json"], "property"),
                    *_json_fields(stored["qualifiers_json"], "qualifier"),
                )
                type_name = str(stored["relation_type"])
            facts.append(
                FactRow(
                    kind,
                    fact_id,
                    int(stored["schema_version_id"]),
                    type_name,
                    subject,
                    target,
                    str(stored["source_doc_id"]),
                    fields,
                )
            )
    return tuple(sorted(facts, key=lambda item: (item.fact_kind, item.fact_id)))


def _declares_single(value: JsonValue) -> bool:
    if not isinstance(value, dict):
        return False
    cardinality = value.get("cardinality")
    return (
        value.get("single_value") is True
        or value.get("max_items") == 1
        or value.get("maxItems") == 1
        or cardinality in {"one", "single"}
    )


def _single_value_rules(
    store: KGStore,
    facts: tuple[FactRow, ...],
) -> tuple[SingleValueRule, ...]:
    rules: set[SingleValueRule] = set()
    for schema_id in sorted({fact.schema_version_id for fact in facts}):
        schema = store.get_schema(schema_id)
        for entity in schema["entity_types"]:
            for key, value in entity["attributes"].items():
                if _declares_single(value):
                    rules.add(
                        SingleValueRule(
                            "node", str(entity["name"]), "property", str(key)
                        )
                    )
        for relation in schema["relation_types"]:
            for key, value in relation["qualifiers"].items():
                if _declares_single(value):
                    rules.add(
                        SingleValueRule(
                            "edge",
                            str(relation["name"]),
                            "qualifier",
                            str(key),
                        )
                    )
    return tuple(
        sorted(
            rules,
            key=lambda item: (
                item.fact_kind,
                item.type_name,
                item.location,
                item.semantic_key,
            ),
        )
    )


def _inventory_root(store: KGStore) -> str | None:
    try:
        return seal_receipt_inventory(store.conn).root
    except ReceiptSealRefused:
        return None


def _receipt_snapshot(
    store: KGStore,
    facts: tuple[FactRow, ...],
) -> ReceiptSnapshot:
    root_before = _inventory_root(store)
    citations: list[CitationRow] = []
    for fact in facts:
        rows = store.conn.execute(
            "SELECT receipt_id, fact_kind, fact_id, fact_revision, "
            "representation_id, representation_content_hash, "
            "run_receipt_id, chunk_receipt_id FROM citation_receipts "
            "WHERE fact_kind = ? AND fact_id = ? ORDER BY receipt_id",
            (fact.fact_kind, fact.fact_id),
        ).fetchall()
        citations.extend(CitationRow(*map(str, row)) for row in rows)
    runs = tuple(
        RunReceiptRow(
            str(row["receipt_id"]),
            str(row["representation_id"]),
            str(row["document_content_hash"]),
        )
        for receipt_id in sorted({row.run_receipt_id for row in citations})
        if (
            row := store.conn.execute(
                "SELECT receipt_id, representation_id, document_content_hash "
                "FROM extraction_run_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        )
        is not None
    )
    chunks = tuple(
        ChunkReceiptRow(str(row["receipt_id"]), str(row["run_receipt_id"]))
        for receipt_id in sorted({row.chunk_receipt_id for row in citations})
        if (
            row := store.conn.execute(
                "SELECT receipt_id, run_receipt_id "
                "FROM extraction_chunk_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        )
        is not None
    )
    documents = tuple(
        DocumentRow(str(row["id"]), str(row["content_hash"]))
        for representation_id in sorted(
            {row.representation_id for row in citations}
        )
        if (
            row := store.conn.execute(
                "SELECT id, content_hash FROM documents WHERE id = ?",
                (representation_id,),
            ).fetchone()
        )
        is not None
    )
    root_after = _inventory_root(store)
    issues = (
        tuple(
            ReceiptIssue(
                fact.fact_kind, fact.fact_id, "receipt_inventory_unverifiable"
            )
            for fact in facts
        )
        if root_before is None or root_after is None
        else ()
    )
    return ReceiptSnapshot(
        tuple(citations),
        runs,
        chunks,
        documents,
        root_before,
        root_after,
        issues,
    )


__all__ = [
    "DocumentScope",
    "current_document_scope",
    "post_extraction_input",
    "snapshot_fact_ids",
]
