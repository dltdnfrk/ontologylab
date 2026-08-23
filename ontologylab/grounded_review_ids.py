"""Deterministic grounded ReviewDecision identities."""

from __future__ import annotations

from ontologylab.extraction_receipt_ids import digest
from ontologylab.grounded_review_types import ReviewAction, ReviewDecision


def citation_set_digest(receipt_ids: tuple[str, ...]) -> str:
    return digest(("citation-set-v1", *sorted(receipt_ids)))


def review_decision_id(
    *,
    fact_kind: str,
    fact_id: str,
    fact_revision: str,
    action: ReviewAction,
    digest_value: str,
    actor: str,
    reason: str,
    predecessor_receipt_id: str | None,
    waived_fact_ids: tuple[str, ...],
    waived_citation_ids: tuple[str, ...],
    scoped_defects: tuple[str, ...],
) -> str:
    return digest((
        "grounded-review-v1",
        fact_kind,
        fact_id,
        fact_revision,
        action.value,
        digest_value,
        actor,
        reason,
        predecessor_receipt_id or "",
        *waived_fact_ids,
        *waived_citation_ids,
        *scoped_defects,
    ))


def build_decision(
    *,
    fact_kind: str,
    fact_id: str,
    fact_revision: str,
    action: ReviewAction,
    actor: str,
    reason: str,
    now: float,
    citation_ids: tuple[str, ...],
    representation_id: str | None,
    selection_receipt_id: str | None,
    policy_identity: str | None,
    run_receipt_id: str | None,
    predecessor_receipt_id: str | None,
    pack_ineligible: bool,
    waived_fact_ids: tuple[str, ...] = (),
    waived_citation_ids: tuple[str, ...] = (),
    scoped_defects: tuple[str, ...] = (),
) -> ReviewDecision:
    digest_value = citation_set_digest(citation_ids)
    return ReviewDecision(
        receipt_id=review_decision_id(
            fact_kind=fact_kind,
            fact_id=fact_id,
            fact_revision=fact_revision,
            action=action,
            digest_value=digest_value,
            actor=actor,
            reason=reason,
            predecessor_receipt_id=predecessor_receipt_id,
            waived_fact_ids=waived_fact_ids,
            waived_citation_ids=waived_citation_ids,
            scoped_defects=scoped_defects,
        ),
        fact_kind=fact_kind,
        fact_id=fact_id,
        proposal_id=fact_id,
        fact_revision=fact_revision,
        action=action,
        actor=actor,
        reason=reason,
        decided_ts=now,
        as_of_ts=now,
        citation_set_digest=digest_value,
        citation_receipt_ids=tuple(sorted(citation_ids)),
        representation_id=representation_id,
        selection_receipt_id=selection_receipt_id,
        policy_identity=policy_identity,
        run_receipt_id=run_receipt_id,
        predecessor_receipt_id=predecessor_receipt_id,
        pack_ineligible=pack_ineligible,
        waived_fact_ids=waived_fact_ids,
        waived_citation_ids=waived_citation_ids,
        scoped_defects=scoped_defects,
    )
