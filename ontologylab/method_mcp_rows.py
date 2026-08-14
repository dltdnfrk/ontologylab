"""Compiled Method release-row validation for MCP publication reads."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ontologylab.method_mcp_queries import (
    MethodQueryError,
    json_object,
    json_rows,
)
from ontologylab.method_pack_contract import COMPILER_VERSION, SCHEMA_VERSION
from ontologylab.method_release_validation import canonical_release_envelope
from ontologylab.method_snapshot import compiler_receipt_from_json
from ontologylab.method_validation import canonical_json


def canonical_row(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, str):
        raise MethodQueryError(f"packed {label} is not canonical JSON")
    parsed = json_object(value, label)
    if canonical_json(parsed) != value:
        raise MethodQueryError(f"packed {label} is not canonical JSON")
    return parsed


def release_payloads(
    method_rows: tuple[tuple[Any, ...], ...],
) -> tuple[
    list[Mapping[str, Any]],
    list[list[Mapping[str, Any]]],
    list[Any],
]:
    methods: list[Mapping[str, Any]] = []
    source_indexes: list[list[Mapping[str, Any]]] = []
    gates: list[Any] = []
    for row in method_rows:
        if len(row) != 8:
            raise MethodQueryError("packed compiled Method row is invalid")
        method = canonical_row(row[4], "Method")
        sources = json_rows(
            json.loads(str(row[5])),
            "Method source index",
        )
        if canonical_json(sources) != row[5]:
            raise MethodQueryError(
                "packed Method source index is not canonical JSON"
            )
        receipt = compiler_receipt_from_json(str(row[6]))
        if receipt is None:
            raise MethodQueryError(
                "packed compiler receipt is not canonical"
            )
        envelope = canonical_release_envelope(method, sources, receipt)
        if (
            method.get("id") != row[1]
            or method.get("version") != row[2]
            or method.get("name") != row[3]
            or envelope.receipt.release_id != row[0]
            or envelope.method_json != row[4]
            or envelope.source_index != row[5]
            or envelope.content_hash != row[7]
            or envelope.receipt.method_schema_version != SCHEMA_VERSION
            or envelope.receipt.compiler_version != COMPILER_VERSION
        ):
            raise MethodQueryError(
                "publication receipt does not bind compiled Method rows"
            )
        methods.append(method)
        source_indexes.append(sources)
        gates.append(json.loads(str(row[6]))["gates"])
    return methods, source_indexes, gates


def derived_source_rows(
    method_rows: tuple[tuple[Any, ...], ...],
    source_indexes: list[list[Mapping[str, Any]]],
) -> tuple[tuple[Any, ...], ...]:
    rows: list[tuple[Any, ...]] = []
    try:
        for method, sources in zip(
            method_rows,
            source_indexes,
            strict=True,
        ):
            rows.extend(
                (
                    method[0],
                    method[1],
                    source["field_path"],
                    source["document_id"],
                    source["document_content_hash"],
                    source["span_start"],
                    source["span_end"],
                    source["selected_text_hash"],
                    source["evidence_role"],
                    source["epistemic_class"],
                    source["occurrence_id"],
                    source["receipt_ref"],
                )
                for source in sources
            )
    except KeyError as exc:
        raise MethodQueryError(
            "packed Method source index is invalid"
        ) from exc
    return tuple(sorted(
        rows,
        key=lambda row: (str(row[1]), str(row[0]), str(row[2]), str(row[10])),
    ))
