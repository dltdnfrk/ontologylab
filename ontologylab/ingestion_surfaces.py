"""CLI / HTTP / queue / sample seam over the v2 ingestion service.

Surfaces serialize the same receipt and conflict ids. Queue mode never
writes. Sample collect calls ingest_work_items; a partial batch cannot
report ok.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ontologylab.ingestion_service import (
    IngestItem,
    IngestReceipt,
    RepresentationInput,
    ingest_work_items,
)


SurfaceMode = Literal["write", "queue", "sample"]
MAX_INGEST_BATCH = 100
CONFLICT_CLASS_NAMES: dict[str, str] = {
    "identifier_owned": "IdentifierOwnedConflict",
    "second_doi": "SecondDoiAttachConflict",
}
_SUCCESS_STATUSES = frozenset({"created", "staged", "duplicate", "queued"})
_NOT_FOUND_ERRORS = frozenset({"unknown_work", "unknown_representation"})


@dataclass(frozen=True, slots=True)
class SurfaceBatch:
    ok: bool
    receipts: tuple[dict[str, Any], ...]
    http_status: int
    error_classes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "receipts": list(self.receipts),
            "error_class": self.error_classes[0] if self.error_classes else None,
            "error_classes": list(self.error_classes),
        }


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _as_opt_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_item(raw: object) -> IngestItem:
    if not isinstance(raw, Mapping):
        return IngestItem(idempotency_key="", scheme="", normalized_value="")
    representation = None
    raw_representation = raw.get("representation")
    if isinstance(raw_representation, Mapping):
        fetched = raw_representation.get("fetched_ts")
        raw_text = raw_representation.get("raw_text")
        representation = RepresentationInput(
            source_kind=_as_str(raw_representation.get("source_kind")) or "upload",
            source_uri=_as_str(raw_representation.get("source_uri")),
            title=_as_opt_str(raw_representation.get("title")),
            content_hash=_as_str(raw_representation.get("content_hash")),
            raw_text_path=_as_str(raw_representation.get("raw_text_path")),
            raw_text=raw_text if isinstance(raw_text, (bytes, str)) else None,
            fetched_ts=fetched if isinstance(fetched, (int, float)) else None,
        )
    return IngestItem(
        idempotency_key=_as_str(raw.get("idempotency_key")),
        scheme=_as_str(raw.get("scheme")),
        normalized_value=_as_str(raw.get("normalized_value")),
        source=_as_str(raw.get("source")),
        evidence_grade=_as_str(raw.get("evidence_grade")),
        work_id=_as_opt_str(raw.get("work_id")),
        representation_id=_as_opt_str(raw.get("representation_id")),
        representation=representation,
        stage=_as_str(raw.get("stage")) or "unknown",
        content_kind=_as_str(raw.get("content_kind")) or "metadata_only",
    )


def _error_class(receipt: IngestReceipt | dict[str, Any]) -> str | None:
    if isinstance(receipt, dict):
        conflict = receipt.get("conflict")
        if isinstance(conflict, dict) and conflict.get("class_name"):
            return str(conflict["class_name"])
        error_class = receipt.get("error_class")
        return str(error_class) if error_class else None
    if receipt.conflict is not None:
        return CONFLICT_CLASS_NAMES[receipt.conflict.kind]
    if receipt.error:
        return receipt.error.split(":", 1)[0]
    return None


def _safe_error(receipt: IngestReceipt, error_class: str | None) -> str | None:
    if receipt.conflict is not None:
        return error_class
    if receipt.status != "failed":
        return None
    detail = receipt.error or ""
    if "unknown work_id" in detail:
        return "unknown_work"
    if "unknown representation_id" in detail:
        return "unknown_representation"
    if error_class == "InvalidIngestItem":
        return "invalid_item"
    return error_class or "internal_error"


def receipt_to_dict(receipt: IngestReceipt) -> dict[str, Any]:
    error_class = _error_class(receipt)
    conflict = None
    if receipt.conflict is not None:
        conflict = {
            "kind": receipt.conflict.kind,
            "work_id": receipt.conflict.work_id,
            "existing_work_id": receipt.conflict.existing_work_id,
            "scheme": receipt.conflict.scheme,
            "existing_value": receipt.conflict.existing_value,
            "incoming_value": receipt.conflict.incoming_value,
            "class_name": error_class,
        }
    return {
        "status": receipt.status,
        "idempotency_key": receipt.idempotency_key,
        "work_id": receipt.work_id,
        "representation_id": receipt.representation_id,
        "observation_id": receipt.observation_id,
        "identifier_id": receipt.identifier_id,
        "work_created": receipt.work_created,
        "representation_created": receipt.representation_created,
        "observation_created": receipt.observation_created,
        "conflict": conflict,
        "error": _safe_error(receipt, error_class),
        "error_class": error_class,
    }


def _queued_receipt(raw: object) -> dict[str, Any]:
    key = ""
    if isinstance(raw, Mapping):
        key = _as_str(raw.get("idempotency_key"))
    return {
        "status": "queued",
        "idempotency_key": key,
        "work_id": None,
        "representation_id": None,
        "observation_id": None,
        "identifier_id": None,
        "work_created": False,
        "representation_created": False,
        "observation_created": False,
        "conflict": None,
        "error": None,
        "error_class": None,
    }


def _is_not_found(receipt: dict[str, Any]) -> bool:
    error = receipt.get("error") or ""
    return receipt.get("status") == "failed" and error in _NOT_FOUND_ERRORS


def _http_status(receipts: tuple[dict[str, Any], ...]) -> int:
    if not receipts:
        return 400
    if any(receipt["status"] in _SUCCESS_STATUSES for receipt in receipts):
        return 200
    if all(receipt["status"] == "conflict" for receipt in receipts):
        return 409
    if all(_is_not_found(receipt) for receipt in receipts):
        return 404
    return 400


def _batch_from_payloads(receipts: tuple[dict[str, Any], ...]) -> SurfaceBatch:
    ok = bool(receipts) and all(
        receipt["status"] in _SUCCESS_STATUSES for receipt in receipts
    )
    error_classes = tuple(
        error_class
        for receipt in receipts
        if (error_class := receipt.get("error_class"))
    )
    return SurfaceBatch(
        ok=ok,
        receipts=receipts,
        http_status=_http_status(receipts),
        error_classes=error_classes,
    )


def _batch_from_receipts(receipts: Iterable[IngestReceipt]) -> SurfaceBatch:
    return _batch_from_payloads(tuple(receipt_to_dict(receipt) for receipt in receipts))


def run_ingest(
    conn: sqlite3.Connection,
    items: Iterable[object],
    *,
    mode: SurfaceMode = "write",
) -> SurfaceBatch:
    materialized = list(items)
    if len(materialized) > MAX_INGEST_BATCH:
        return SurfaceBatch(
            ok=False,
            receipts=(),
            http_status=400,
            error_classes=("InvalidIngestItem",),
        )
    if mode == "queue":
        return _batch_from_payloads(tuple(_queued_receipt(raw) for raw in materialized))
    if mode == "sample":
        return collect_sample(conn, materialized)
    if not materialized:
        return SurfaceBatch(
            ok=False,
            receipts=(),
            http_status=400,
            error_classes=("InvalidIngestItem",),
        )
    return _batch_from_receipts(
        ingest_work_items(conn, (_parse_item(raw) for raw in materialized))
    )


def collect_sample(
    conn: sqlite3.Connection,
    items: Iterable[object],
) -> SurfaceBatch:
    materialized = list(items)
    if len(materialized) > MAX_INGEST_BATCH:
        return SurfaceBatch(
            ok=False,
            receipts=(),
            http_status=400,
            error_classes=("InvalidIngestItem",),
        )
    if not materialized:
        return SurfaceBatch(
            ok=False,
            receipts=(),
            http_status=400,
            error_classes=("InvalidIngestItem",),
        )
    return _batch_from_receipts(
        ingest_work_items(conn, (_parse_item(raw) for raw in materialized))
    )


__all__ = [
    "CONFLICT_CLASS_NAMES",
    "SurfaceBatch",
    "collect_sample",
    "receipt_to_dict",
    "run_ingest",
]
