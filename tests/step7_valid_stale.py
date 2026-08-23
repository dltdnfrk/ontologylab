"""Plant valid self-consistent stale Task 2/4/5 receipts (wrong policy)."""

from __future__ import annotations

from ontologylab.citation import CitationBinding, put_citation_receipts
from ontologylab.citation_ids import fact_revision_id
from ontologylab.extraction_receipt_types import DOCUMENT_UTF8_V1, ChunkSpan
from ontologylab.extraction_receipts import put_extraction_receipts
from ontologylab.extraction_state import ExtractionRunBinding
from ontologylab.file_lifecycle import (
    content_hash_for,
    read_ready_text,
    store_root_from_conn,
)
from ontologylab.grounded_review_ids import build_decision
from ontologylab.grounded_review_store import persist_decision
from ontologylab.grounded_review_types import ReviewAction, ReviewDecision
from ontologylab.kgstore import KGStore


_WRONG_POLICY = "wrong-policy-v0"
_WRONG_CONFIG = "wrong-config-v0"


def plant_valid_stale_run(store: KGStore, representation_id: str) -> str:
    text = read_ready_text(
        store.conn, store_root_from_conn(store.conn), representation_id,
    )
    body = text.encode("utf-8")
    body_hash = content_hash_for(body)
    receipts = put_extraction_receipts(
        store.conn,
        ExtractionRunBinding(
            representation_id=representation_id,
            policy_identity=_WRONG_POLICY,
            config_identity=_WRONG_CONFIG,
            schema_version_id=1,
            extractor_engine="mock",
            extractor_model="",
            prompt_version="extract-v1",
            decode_params_json="{}",
        ),
        (
            ChunkSpan(
                index=0,
                start_offset=0,
                end_offset=len(text),
                text=text,
                text_hash=body_hash,
                coordinate_profile=DOCUMENT_UTF8_V1,
            ),
        ),
    )
    store.conn.commit()
    return receipts.run.receipt_id


def plant_valid_stale_citation(
    store: KGStore,
    *,
    live,
    stale_run_id: str,
) -> str:
    chunk = store.conn.execute(
        "SELECT receipt_id, start_offset, end_offset, chunk_text_hash, "
        "plan_receipt_id FROM extraction_chunk_receipts "
        "WHERE run_receipt_id = ? ORDER BY chunk_index",
        (stale_run_id,),
    ).fetchone()
    assert chunk is not None
    selected = live.selected_text
    written = put_citation_receipts(
        store.conn,
        (
            CitationBinding(
                representation_id=live.representation_id,
                representation_content_hash=live.representation_content_hash,
                run_receipt_id=stale_run_id,
                chunk_receipt_id=str(chunk[0]),
                chunk_start_offset=int(chunk[1]),
                chunk_end_offset=int(chunk[2]),
                coordinate_profile=DOCUMENT_UTF8_V1,
                chunk_text_hash=str(chunk[3]),
                chunk_plan_receipt_id=str(chunk[4]),
                selection_receipt_id=None,
                policy_identity=_WRONG_POLICY,
                fact_kind=live.fact_kind,
                fact_id=live.fact_id,
                proposal_id=live.fact_id,
                fact_revision=fact_revision_id(live.fact_kind, live.fact_id),
                start_offset=live.start_offset,
                end_offset=live.end_offset,
                selected_text=selected,
                selected_text_hash=live.selected_text_hash,
            ),
        ),
    )
    store.conn.commit()
    return written[0].receipt_id


def plant_valid_stale_review(
    store: KGStore,
    *,
    live: ReviewDecision,
    stale_cite_id: str,
    stale_run_id: str,
) -> str:
    decision = build_decision(
        fact_kind=live.fact_kind,
        fact_id=live.fact_id,
        fact_revision=live.fact_revision,
        action=ReviewAction.APPROVE,
        actor=live.actor,
        reason=live.reason,
        now=live.decided_ts,
        citation_ids=(stale_cite_id,),
        representation_id=live.representation_id,
        selection_receipt_id="wrong-sel",
        policy_identity=_WRONG_POLICY,
        run_receipt_id=stale_run_id,
        predecessor_receipt_id="sha256:wrong-pred",
        pack_ineligible=True,
        waived_fact_ids=(live.fact_id,),
        scoped_defects=("stale",),
    )
    persist_decision(store.conn, decision)
    store.conn.commit()
    return decision.receipt_id
