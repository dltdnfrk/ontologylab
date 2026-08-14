"""Canonical selected-release row assembly."""

from __future__ import annotations

from typing import Any, Mapping

from ontologylab.method_pack_contract import MethodPackError


def method_row(
    values: tuple[Any, ...],
    method: Mapping[str, Any],
    receipt_json: str,
) -> tuple[Any, ...]:
    name = method.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MethodPackError(f"release {values[0]!r} Method name is invalid")
    return (
        values[0],
        values[2],
        values[3],
        name,
        values[4],
        values[5],
        receipt_json,
        values[6],
    )


def source_rows(
    values: tuple[Any, ...],
    sources: tuple[Mapping[str, Any], ...],
) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            values[0],
            values[2],
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
