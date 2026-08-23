"""Deterministic H1 anchor and classification receipt identities."""

from __future__ import annotations

from ontologylab.extraction_receipt_ids import digest
from ontologylab.h1_types import (
    H1Classification,
    H1Family,
    H1QuarantineReason,
    H1RunAnchor,
)


LEGACY_POLICY = "legacy-h1-v1"


def run_config_identity(anchor: H1RunAnchor) -> str:
    return digest((
        "legacy-h1-config",
        str(anchor.schema_version_id),
        anchor.extractor_engine,
        anchor.extractor_model,
        anchor.prompt_version,
        anchor.decode_params,
        anchor.chunk_plan_hash,
    ))


def anchor_id(family: H1Family, *parts: str) -> str:
    return digest(("h1-anchor-v1", family.value, *parts))


def classification_receipt_id(
    *,
    family: H1Family,
    anchor: str,
    classification: H1Classification,
    reason: H1QuarantineReason | None,
    family_receipt_id: str | None,
    raw_byte_seal: str | None,
    file_hash: str | None,
    span_hash: str | None,
) -> str:
    return digest((
        "h1-receipt-v1",
        family.value,
        anchor,
        classification.value,
        "" if reason is None else reason.value,
        family_receipt_id or "",
        raw_byte_seal or "",
        file_hash or "",
        span_hash or "",
    ))
