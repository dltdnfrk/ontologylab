"""Machine receipts for grounded ReviewDecision HTTP/CLI payloads."""

from __future__ import annotations

from typing import Any, assert_never

from ontologylab.grounded_review_types import (
    ReviewAction,
    ReviewBatchResult,
    ReviewDecision,
)


def machine_receipt(decision: ReviewDecision) -> dict[str, Any]:
    return {
        "receipt_id": decision.receipt_id,
        "fact_kind": decision.fact_kind,
        "fact_id": decision.fact_id,
        "fact_revision": decision.fact_revision,
        "action": decision.action.value,
        "actor": decision.actor,
        "reason": decision.reason,
        "decided_ts": decision.decided_ts,
        "as_of_ts": decision.as_of_ts,
        "citation_set_digest": decision.citation_set_digest,
        "citation_receipt_ids": list(decision.citation_receipt_ids),
        "representation_id": decision.representation_id,
        "selection_receipt_id": decision.selection_receipt_id,
        "policy_identity": decision.policy_identity,
        "run_receipt_id": decision.run_receipt_id,
        "predecessor_receipt_id": decision.predecessor_receipt_id,
        "pack_ineligible": decision.pack_ineligible,
        "waived_fact_ids": list(decision.waived_fact_ids),
        "waived_citation_ids": list(decision.waived_citation_ids),
        "scoped_defects": list(decision.scoped_defects),
    }


def batch_payload(
    result: ReviewBatchResult, action: ReviewAction,
) -> dict[str, Any]:
    ids = list(result.item_ids)
    payload: dict[str, Any] = {
        "kind": result.kind,
        "decision_receipt_ids": [
            item.receipt_id for item in result.decisions
        ],
        "decisions": [machine_receipt(item) for item in result.decisions],
    }
    match action:
        case ReviewAction.APPROVE | ReviewAction.APPROVE_WITH_GROUNDING_WAIVER:
            payload["approved_ids"] = ids
        case (
            ReviewAction.REJECT
            | ReviewAction.QUARANTINE
            | ReviewAction.RETRACT
            | ReviewAction.COMPENSATE
        ):
            payload["rejected_ids"] = ids
        case unreachable:
            assert_never(unreachable)
    return payload
