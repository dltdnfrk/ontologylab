"""Pure typed validation and envelope helpers for Method MCP queries."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, TypedDict

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_POINTER = re.compile(r"(?:/(?:[^~/\x00-\x1f]|~[01])*)+\Z")
MAX_METHOD_RESULTS = 100


class MethodQueryError(ValueError):
    """A Method MCP query is invalid or cannot resolve selected content."""


class MethodCapabilityUnavailable(MethodQueryError):
    """The immutable pack has no selected methodology-v1 capability."""


class PackProvenance(TypedDict):
    pack_id: str
    content_hash: str


class MethodListRow(TypedDict):
    method_id: str
    release_id: str
    version: int
    name: str
    content_hash: str
    gap_count: int
    assumption_count: int


class MethodListResult(TypedDict):
    methods: list[MethodListRow]
    count: int
    query: str | None
    limit: int
    publication_receipt_hash: str
    pack: PackProvenance


class MethodDetailResult(TypedDict):
    method: Mapping[str, Any]
    release: Mapping[str, Any]
    compiler_receipt: Mapping[str, Any]
    publication_receipt: Mapping[str, Any]
    publication_receipt_hash: str
    pack: PackProvenance


class MethodTraceResult(TypedDict):
    method_id: str
    release_id: str
    field_path: str | None
    sources: list[dict[str, Any]]
    links: list[Mapping[str, Any]]
    assumptions: list[Mapping[str, Any]]
    publication_receipt_hash: str
    pack: PackProvenance


class MethodGapsResult(TypedDict):
    method_id: str
    release_id: str
    gaps: list[Mapping[str, Any]]
    count: int
    publication_receipt_hash: str
    pack: PackProvenance


def json_object(value: str, label: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise MethodQueryError(f"packed {label} is invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise MethodQueryError(f"packed {label} is not an object")
    return parsed


def json_rows(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise MethodQueryError(f"packed {label} is not an array")
    if not all(isinstance(row, dict) for row in value):
        raise MethodQueryError(f"packed {label} contains a non-object")
    return list(value)


def method_id(value: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise MethodQueryError("invalid Method id")
    return value


def list_inputs(search: str | None, limit: int) -> str | None:
    if type(limit) is not int or not 1 <= limit <= MAX_METHOD_RESULTS:
        raise MethodQueryError(
            f"limit must be an integer from 1 to {MAX_METHOD_RESULTS}"
        )
    if search is not None and (
        not isinstance(search, str)
        or not search.strip()
        or len(search) > 200
    ):
        raise MethodQueryError(
            "query must be non-empty and at most 200 characters"
        )
    return search.casefold() if search is not None else None


def selected_version(requested: int | None, selected: int) -> None:
    if requested is not None and (
        type(requested) is not int or requested != selected
    ):
        raise MethodQueryError(
            "requested version is not the selected Method release version"
        )


def field_path(value: str | None) -> str | None:
    if value is not None and (
        not isinstance(value, str) or _POINTER.fullmatch(value) is None
    ):
        raise MethodQueryError("field_path must be an RFC 6901 pointer")
    return value


def list_row(row: Any, method: Mapping[str, Any]) -> MethodListRow:
    gaps = json_rows(method.get("gaps", []), "Method gaps")
    assumptions = json_rows(
        method.get("bridge_assumptions", []),
        "Method bridge assumptions",
    )
    return MethodListRow(
        release_id=str(row[0]),
        method_id=str(row[1]),
        version=int(row[2]),
        name=str(row[3]),
        content_hash=str(row[7]),
        gap_count=len(gaps),
        assumption_count=len(assumptions),
    )


def source_envelope(source: Any) -> dict[str, Any]:
    return {
        "field_path": str(source[0]),
        "epistemic_class": str(source[7]),
        "evidence_role": str(source[6]),
        "selector": {
            "document_id": str(source[1]),
            "document_content_hash": str(source[2]),
            "span_start": int(source[3]),
            "span_end": int(source[4]),
            "selected_text_hash": str(source[5]),
        },
        "statement_occurrence_id": str(source[8]),
        "receipt_ref": str(source[9]),
    }


def ordered_rows(
    method: Mapping[str, Any],
    key: str,
    label: str,
) -> list[Mapping[str, Any]]:
    return sorted(
        json_rows(method.get(key, []), label),
        key=lambda row: str(row.get("id")),
    )
