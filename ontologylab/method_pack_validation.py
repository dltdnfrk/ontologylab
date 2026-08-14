"""Selected Method pack row and receipt validation."""

from __future__ import annotations

from typing import Any, Mapping
import json

from ontologylab.method_pack_contract import (
    COMPILER_VERSION,
    PUBLICATION_SCHEMA_VERSION,
    SCHEMA_VERSION,
    MethodPackError,
    MethodPackSelection,
)
from ontologylab.method_release_validation import canonical_release_envelope
from ontologylab.method_snapshot import compiler_receipt_from_json
from ontologylab.method_validation import canonical_json


METHOD_COLUMNS = (
    "release_id", "method_id", "version", "name", "canonical_json",
    "source_index_json", "compiler_receipt_json", "content_hash",
)
SOURCE_COLUMNS = (
    "release_id", "method_id", "field_path", "document_id",
    "document_content_hash", "span_start", "span_end",
    "selected_text_hash", "evidence_role", "epistemic_class",
    "statement_occurrence_id", "receipt_ref",
)


def canonical_hash(value: object) -> str:
    import hashlib

    payload = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def copied_row_hashes(
    method_rows: tuple[tuple[Any, ...], ...],
    source_rows: tuple[tuple[Any, ...], ...],
) -> tuple[str, str]:
    return (
        canonical_hash([
            dict(zip(METHOD_COLUMNS, row, strict=True))
            for row in method_rows
        ]),
        canonical_hash([
            dict(zip(SOURCE_COLUMNS, row, strict=True))
            for row in source_rows
        ]),
    )


def _object(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise MethodPackError("publication receipt must be a JSON object")
    return value


def _columns(owner: Any, table: str) -> tuple[str, ...]:
    return tuple(
        str(row[1])
        for row in owner.execute(f"PRAGMA table_info({table})")
    )


def _derived_source_rows(
    method_rows: tuple[tuple[Any, ...], ...],
) -> tuple[tuple[Any, ...], ...]:
    rows = []
    for method in method_rows:
        sources = json.loads(str(method[5]))
        if not isinstance(sources, list):
            raise MethodPackError("packed source index is not an array")
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
    return tuple(sorted(
        rows,
        key=lambda row: (str(row[1]), str(row[0]), str(row[2]), str(row[10])),
    ))


def _validate_release_rows(
    method_rows: tuple[tuple[Any, ...], ...],
) -> None:
    for row in method_rows:
        method = _object(json.loads(str(row[4])))
        sources = json.loads(str(row[5]))
        receipt = compiler_receipt_from_json(str(row[6]))
        if not isinstance(sources, list) or receipt is None:
            raise MethodPackError("packed release envelope is invalid")
        envelope = canonical_release_envelope(method, sources, receipt)
        if (
            row[1] != method.get("id")
            or row[2] != method.get("version")
            or row[3] != method.get("name")
            or row[4] != envelope.method_json
            or row[5] != envelope.source_index
            or row[7] != envelope.content_hash
            or receipt.method_schema_version != SCHEMA_VERSION
            or receipt.compiler_version != COMPILER_VERSION
        ):
            raise MethodPackError("packed release envelope is invalid")


def validate_method_pack(
    owner: Any,
    selection: MethodPackSelection,
) -> None:
    if (
        _columns(owner, "compiled_method") != METHOD_COLUMNS
        or _columns(owner, "compiled_method_source") != SOURCE_COLUMNS
        or _columns(owner, "methodology_publication_receipt")
        != ("receipt_json", "receipt_hash")
    ):
        raise MethodPackError("selected pack Method schema is invalid")
    method_rows = tuple(map(tuple, owner.execute(
        "SELECT release_id,method_id,version,name,canonical_json,"
        "source_index_json,compiler_receipt_json,content_hash "
        "FROM compiled_method ORDER BY method_id,release_id"
    )))
    source_rows = tuple(map(tuple, owner.execute(
        "SELECT release_id,method_id,field_path,document_id,"
        "document_content_hash,span_start,span_end,selected_text_hash,"
        "evidence_role,epistemic_class,statement_occurrence_id,receipt_ref "
        "FROM compiled_method_source "
        "ORDER BY method_id,release_id,field_path,statement_occurrence_id"
    )))
    _validate_release_rows(method_rows)
    if source_rows != _derived_source_rows(method_rows):
        raise MethodPackError("packed source rows do not match source indexes")
    receipts = tuple(owner.execute(
        "SELECT receipt_json,receipt_hash "
        "FROM methodology_publication_receipt"
    ))
    if len(receipts) != 1:
        raise MethodPackError("selected pack requires one publication receipt")
    receipt_json, receipt_hash = map(str, receipts[0])
    try:
        receipt = _object(json.loads(receipt_json))
    except json.JSONDecodeError as exc:
        raise MethodPackError("publication receipt is not JSON") from exc
    if (
        canonical_json(receipt) != receipt_json
        or canonical_hash(receipt) != receipt_hash
    ):
        raise MethodPackError("publication receipt hash is invalid")
    method_hash, source_hash = copied_row_hashes(method_rows, source_rows)
    release_ids = tuple(str(row[0]) for row in method_rows)
    release_hashes = tuple(str(row[7]) for row in method_rows)
    method_json_hash = canonical_hash([
        json.loads(str(row[4]))
        for row in method_rows
    ])
    source_index_hash = canonical_hash([
        json.loads(str(row[5]))
        for row in method_rows
    ])
    gate_receipt_hash = canonical_hash([
        json.loads(str(row[6]))["gates"]
        for row in method_rows
    ])
    selection_input_hash = canonical_hash([
        [release_id, release_hash]
        for release_id, release_hash in zip(
            release_ids,
            release_hashes,
            strict=True,
        )
    ])
    if (
        receipt.get("schema_version") != PUBLICATION_SCHEMA_VERSION
        or receipt.get("method_schema_version") != SCHEMA_VERSION
        or receipt.get("compiler_version") != COMPILER_VERSION
        or receipt.get("compiled_method_hash") != method_hash
        or receipt.get("compiled_method_source_hash") != source_hash
        or receipt.get("source_snapshot_hash")
        != selection.source_snapshot_hash
        or receipt_hash != selection.publication_receipt_hash
        or release_ids != selection.release_ids
        or release_hashes != selection.release_hashes
        or method_json_hash != selection.method_json_hash
        or source_index_hash != selection.source_index_hash
        or gate_receipt_hash != selection.gate_receipt_hash
        or selection_input_hash != selection.selection_input_hash
    ):
        raise MethodPackError("publication receipt does not bind copied rows")
    expected = [
        {
            "method_id": str(row[1]),
            "release_id": str(row[0]),
            "release_content_hash": str(row[7]),
        }
        for row in method_rows
    ]
    if receipt.get("selection") != expected:
        raise MethodPackError("publication receipt selection is invalid")
