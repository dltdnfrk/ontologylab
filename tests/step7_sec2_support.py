"""Helpers for Step 7 security-repair-2 colliding plants."""

from __future__ import annotations

from ontologylab.grounded_review_ids import build_decision
from ontologylab.grounded_review_store import persist_decision
from ontologylab.grounded_review_types import ReviewAction, ReviewDecision
from ontologylab.kgstore import KGStore


def plant_colliding(
    store: KGStore,
    live: ReviewDecision,
    *,
    action: ReviewAction,
    cite_ids: tuple[str, ...],
    scoped: tuple[str, ...] = (),
    waived: tuple[str, ...] = (),
    pack: bool = True,
    selection: str | None = "wrong-sel",
    policy: str = "wrong-policy-v0",
    run: str = "sha256:wrong-run",
    smaller_than: str | None = None,
    larger_than: str | None = None,
) -> str:
    for n in range(400):
        used_scoped = scoped
        if smaller_than is not None or larger_than is not None:
            used_scoped = (
                tuple(f"{item}:{n:03d}" for item in scoped)
                if scoped
                else (f"stale:{n:03d}",)
            )
        decision = build_decision(
            fact_kind=live.fact_kind,
            fact_id=live.fact_id,
            fact_revision=live.fact_revision,
            action=action,
            actor=live.actor,
            reason=live.reason,
            now=live.decided_ts,
            citation_ids=cite_ids,
            representation_id=live.representation_id,
            selection_receipt_id=selection,
            policy_identity=policy,
            run_receipt_id=run,
            predecessor_receipt_id=None,
            pack_ineligible=pack,
            waived_fact_ids=waived,
            scoped_defects=used_scoped,
        )
        receipt_id = decision.receipt_id
        if smaller_than is not None and receipt_id >= smaller_than:
            continue
        if larger_than is not None and receipt_id <= larger_than:
            continue
        persist_decision(store.conn, decision)
        store.conn.commit()
        return receipt_id
    raise AssertionError("no ordered colliding receipt id")


def eligible_approve_ids(store: KGStore, fact_id: str) -> list[str]:
    return [
        str(row[0])
        for row in store.conn.execute(
            "SELECT receipt_id FROM grounded_review_decisions "
            "WHERE fact_id = ? AND action = 'approve' AND pack_ineligible = 0",
            (fact_id,),
        )
    ]


def drop_pointer(store: KGStore) -> None:
    store.conn.execute("DELETE FROM grounded_review_current")
    store.conn.commit()
