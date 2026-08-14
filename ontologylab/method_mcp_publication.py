"""Canonical publication-authority validation for Method MCP reads."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from ontologylab.method_mcp_queries import (
    MethodQueryError,
    json_rows,
    method_id,
)
from ontologylab.method_pack_contract import (
    COMPILER_VERSION,
    PUBLICATION_SCHEMA_VERSION,
    SCHEMA_VERSION,
)
from ontologylab.method_pack_validation import (
    canonical_hash,
    copied_row_hashes,
)
from ontologylab.method_mcp_rows import (
    canonical_row,
    derived_source_rows,
    release_payloads,
)


_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PUBLICATION_KEYS = {
    "schema_version",
    "method_schema_version",
    "compiler_version",
    "source_snapshot_hash",
    "selection",
    "compiled_method_hash",
    "compiled_method_source_hash",
}
_METHODOLOGY_KEYS = {
    "schema_version",
    "compiler_version",
    "method_count",
    "selected_release_ids",
    "selected_release_hashes",
    "method_json_hash",
    "source_index_hash",
    "gate_receipt_hash",
    "selection_input_hash",
    "publication_receipt_hash",
}


@dataclass(frozen=True, slots=True)
class PackedPublication:
    receipt_json: str
    receipt_hash: str
    methodology: Mapping[str, Any]
    method_rows: tuple[tuple[Any, ...], ...]
    source_rows: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True, slots=True)
class PublicationSelection:
    method_id: str
    release_id: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class PublicationAuthority:
    receipt: Mapping[str, Any]
    receipt_hash: str
    selection: tuple[PublicationSelection, ...]

    def selected(self, value: str) -> PublicationSelection:
        value = method_id(value)
        for selected in self.selection:
            if selected.method_id == value:
                return selected
        raise MethodQueryError(f"selected Method {value!r} not found")


def _hash_value(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise MethodQueryError(f"packed {label} is not a SHA-256 receipt")
    return value


def _selection(value: object) -> tuple[PublicationSelection, ...]:
    rows = json_rows(value, "publication receipt selection")
    selected: list[PublicationSelection] = []
    for row in rows:
        if set(row) != {
            "method_id",
            "release_id",
            "release_content_hash",
        }:
            raise MethodQueryError(
                "packed publication receipt selection is invalid"
            )
        selected.append(PublicationSelection(
            method_id(str(row["method_id"])),
            method_id(str(row["release_id"])),
            _hash_value(
                row["release_content_hash"],
                "selected release content hash",
            ),
        ))
    if (
        not selected
        or len({row.method_id for row in selected}) != len(selected)
        or len({row.release_id for row in selected}) != len(selected)
    ):
        raise MethodQueryError(
            "packed publication receipt selection is ambiguous"
        )
    return tuple(selected)


def publication_authority(
    packed: PackedPublication,
) -> PublicationAuthority:
    receipt = canonical_row(
        packed.receipt_json,
        "publication receipt",
    )
    if (
        set(receipt) != _PUBLICATION_KEYS
        or receipt.get("schema_version") != PUBLICATION_SCHEMA_VERSION
        or receipt.get("method_schema_version") != SCHEMA_VERSION
        or receipt.get("compiler_version") != COMPILER_VERSION
        or canonical_hash(receipt) != packed.receipt_hash
    ):
        raise MethodQueryError("packed publication receipt is invalid")
    _hash_value(receipt.get("source_snapshot_hash"), "source snapshot hash")
    selected = _selection(receipt.get("selection"))
    methods, source_indexes, gates = release_payloads(packed.method_rows)
    if packed.source_rows != derived_source_rows(
        packed.method_rows,
        source_indexes,
    ):
        raise MethodQueryError(
            "publication receipt does not bind compiled Method sources"
        )
    method_hash, source_hash = copied_row_hashes(
        packed.method_rows,
        packed.source_rows,
    )
    actual = tuple(
        PublicationSelection(str(row[1]), str(row[0]), str(row[7]))
        for row in packed.method_rows
    )
    if (
        actual != selected
        or receipt.get("compiled_method_hash") != method_hash
        or receipt.get("compiled_method_source_hash") != source_hash
    ):
        raise MethodQueryError(
            "publication receipt does not bind compiled Method rows"
        )
    expected_methodology = {
        "schema_version": SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "method_count": len(selected),
        "selected_release_ids": [row.release_id for row in selected],
        "selected_release_hashes": {
            row.release_id: row.content_hash for row in selected
        },
        "method_json_hash": canonical_hash(methods),
        "source_index_hash": canonical_hash(source_indexes),
        "gate_receipt_hash": canonical_hash(gates),
        "selection_input_hash": canonical_hash([
            [row.release_id, row.content_hash]
            for row in selected
        ]),
        "publication_receipt_hash": packed.receipt_hash,
    }
    if (
        set(packed.methodology) != _METHODOLOGY_KEYS
        or dict(packed.methodology) != expected_methodology
    ):
        raise MethodQueryError(
            "pack manifest methodology does not bind publication receipt"
        )
    return PublicationAuthority(receipt, packed.receipt_hash, selected)
