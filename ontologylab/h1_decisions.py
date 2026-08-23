"""Build verified or quarantined H1 decisions."""

from __future__ import annotations

import json
from dataclasses import replace

from ontologylab.h1_inventory import family_of
from ontologylab.h1_types import (
    H1Anchor,
    H1Classification,
    H1Decision,
    H1QuarantineReason,
)


def quarantine(
    anchor: H1Anchor,
    reason: H1QuarantineReason,
    *,
    representation_id: str | None,
    evidence: dict[str, str | int | None],
) -> H1Decision:
    return H1Decision(
        anchor_id=anchor.anchor_id,
        family=family_of(anchor),
        legacy_pk=anchor.legacy_pk,
        classification=H1Classification.QUARANTINED,
        reason=reason,
        representation_id=representation_id,
        family_receipt_id=None,
        raw_byte_seal=None,
        file_hash=None,
        span_hash=None,
        evidence_json=evidence_json(evidence),
    )


def verified(
    anchor: H1Anchor,
    *,
    representation_id: str | None,
    raw_byte_seal: str | None,
    file_hash: str | None,
    span_hash: str | None,
    evidence: dict[str, str | int | None],
    family_receipt_id: str | None = None,
) -> H1Decision:
    return H1Decision(
        anchor_id=anchor.anchor_id,
        family=family_of(anchor),
        legacy_pk=anchor.legacy_pk,
        classification=H1Classification.VERIFIED,
        reason=None,
        representation_id=representation_id,
        family_receipt_id=family_receipt_id,
        raw_byte_seal=raw_byte_seal,
        file_hash=file_hash,
        span_hash=span_hash,
        evidence_json=evidence_json(evidence),
    )


def evidence_json(payload: dict[str, str | int | None]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def with_family_receipt(decision: H1Decision, family_receipt_id: str) -> H1Decision:
    return replace(decision, family_receipt_id=family_receipt_id)
