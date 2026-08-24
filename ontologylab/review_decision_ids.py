"""Deterministic review-decision and citation-set identities."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ontologylab.extraction_receipt_ids import digest


def citation_set_hash(receipt_ids: Iterable[str]) -> str:
    ordered = tuple(sorted(receipt_ids))
    return digest(("citation-set-v1", *ordered))


def legacy_span_token(
    *,
    fact_kind: str,
    fact_id: str,
    source_doc_id: str | None,
    source_span_json: str | None,
) -> str:
    return digest((
        "legacy-span-v1",
        fact_kind,
        fact_id,
        source_doc_id or "",
        source_span_json or "",
    ))


def fact_revision_hash(
    *,
    fact_kind: str,
    fact_id: str,
    body_fingerprint: str,
) -> str:
    return digest((
        "fact-revision-v1",
        fact_kind,
        fact_id,
        body_fingerprint,
    ))


def review_batch_id(
    *,
    decision_kind: str,
    actor: str,
    member_ids: Sequence[str],
    reason: str | None,
) -> str:
    return digest((
        "review-batch-v1",
        decision_kind,
        actor,
        reason or "",
        *sorted(member_ids),
    ))


def review_decision_id(
    *,
    batch_id: str,
    decision_kind: str,
    fact_kind: str,
    fact_id: str,
    fact_revision: str,
    citation_set_hash_value: str,
    grounding_class: str,
    actor: str,
    reason: str | None,
) -> str:
    return digest((
        "review-decision-v1",
        batch_id,
        decision_kind,
        fact_kind,
        fact_id,
        fact_revision,
        citation_set_hash_value,
        grounding_class,
        actor,
        reason or "",
    ))
