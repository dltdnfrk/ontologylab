"""Baseline and contract tests for append-only grounded ReviewDecision."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.citation import CitationBinding, put_citation_receipts
from ontologylab.citation_ids import fact_revision_id
from ontologylab.file_lifecycle import content_hash_for, finalize_representation
from ontologylab.ingestion_service import IngestItem, RepresentationInput, ingest_item
from ontologylab.kgstore import EndpointNotVerified, InvalidTransition, KGStore
from ontologylab.models import SourceSpan
from ontologylab.selection import put_selection_receipt
from ontologylab.selection_types import PolicyVersion
from tests.conftest import insert
from tests.factories import make_entity, make_relation


_TEXT = "The PaymentGateway uses the DatabaseService."
_GATEWAY = (4, 18)
_SERVICE = (28, 44)


def _decision_count(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'grounded_review_decisions'"
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) FROM grounded_review_decisions"
    ).fetchone()
    return int(row[0])


def _status(store: KGStore, item_id: str) -> str:
    kind, row = store._find_kind(item_id)
    assert kind in {"node", "edge"}
    return str(row["status"])


def test_baseline_approve_and_reject_record_actor_and_status(store, doc) -> None:
    gateway, limiter = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [gateway, limiter])
    store.approve(gateway.id, by="tester")
    store.reject(limiter.id, by="tester", note="wrong extraction")
    counts = store.counts()
    assert counts["nodes_verified"] == 1
    assert counts["nodes_rejected"] == 1
    approved = store.conn.execute(
        "SELECT status, verified_by FROM nodes WHERE id = ?",
        (gateway.id,),
    ).fetchone()
    rejected = store.conn.execute(
        "SELECT status, verified_by FROM nodes WHERE id = ?",
        (limiter.id,),
    ).fetchone()
    assert tuple(approved) == ("verified", "tester")
    assert tuple(rejected) == ("rejected", "tester")


def test_baseline_cascade_approves_endpoints_together(store, doc) -> None:
    src, dst = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [src, dst], [make_relation(src, dst)])
    edge_id = store.pending_review(kind="edge")[0]["id"]
    with pytest.raises(EndpointNotVerified):
        store.approve(edge_id)
    result = store.approve(edge_id, cascade=True, by="tester")
    assert result["kind"] == "edge"
    assert src.id in result["approved_ids"]
    assert dst.id in result["approved_ids"]
    assert edge_id in result["approved_ids"]
    assert store.counts()["nodes_verified"] == 2
    assert store.counts()["edges_verified"] == 1


def test_baseline_cascade_rejected_endpoint_is_atomic(store, doc) -> None:
    src, dst = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [src, dst], [make_relation(src, dst)])
    store.reject(dst.id, by="tester")
    edge_id = store.pending_review(kind="edge")[0]["id"]
    with pytest.raises(InvalidTransition):
        store.approve(edge_id, cascade=True)
    assert store.counts()["nodes_verified"] == 0
    assert store.counts()["edges_verified"] == 0
    assert _status(store, src.id) == "proposed"
    assert _status(store, edge_id) == "proposed"


def test_baseline_critic_never_changes_status(store, doc) -> None:
    from ontologylab.critic import critic_review
    from ontologylab.engines import MockEngine
    from tests.test_critic import run

    insert(store, doc, [make_entity("ApiGateway")])
    before = store.counts()
    run(critic_review(store, MockEngine()))
    after = store.counts()
    assert before == after
    assert after["nodes_verified"] == 0 and after["nodes_rejected"] == 0


def test_baseline_approval_without_citation_receipt_succeeds(store, doc) -> None:
    entity = make_entity("ApiGateway")
    insert(store, doc, [entity])
    result = store.approve(entity.id, by="tester")
    assert result["kind"] == "node"
    assert result["approved_ids"] == [entity.id]
    assert _status(store, entity.id) == "verified"
    assert _decision_count(store.conn) == 0


def test_baseline_latest_action_overwrites_status_without_history(
    store, doc,
) -> None:
    entity = make_entity("ApiGateway")
    insert(store, doc, [entity])
    store.approve(entity.id, by="first")
    store.reopen(entity.id, by="first")
    store.reject(entity.id, by="second", note="changed mind")
    row = store.conn.execute(
        "SELECT status, verified_by, review_note FROM nodes WHERE id = ?",
        (entity.id,),
    ).fetchone()
    assert tuple(row) == ("rejected", "second", "changed mind")
    assert _decision_count(store.conn) == 0


def test_baseline_insert_proposed_commit_false_is_caller_owned(
    store, doc,
) -> None:
    entity = make_entity("ApiGateway")
    store.insert_proposed(
        [entity],
        [],
        source_doc_id=doc.id,
        extractor_engine="mock",
        commit=False,
    )
    assert store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
    store.conn.rollback()
    assert store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0


def test_baseline_task4_citation_validation_still_round_trips(
    tmp_path: Path,
) -> None:
    store, _work_id, representation_id, run, chunk, selection = _plant_ready(
        tmp_path,
    )
    try:
        stored = put_citation_receipts(
            store.conn,
            (
                _binding(
                    representation_id,
                    run,
                    chunk,
                    fact_id="fact-gateway",
                    start=_GATEWAY[0],
                    end=_GATEWAY[1],
                    selection_id=selection.receipt_id,
                    policy=selection.policy_hash,
                ),
            ),
        )
        assert stored[0].selected_text == "PaymentGateway"
        assert stored[0].representation_id == representation_id
        assert stored[0].selection_receipt_id == selection.receipt_id
        assert stored[0].run_receipt_id == run.receipt_id
    finally:
        store.close()


def _plant_ready(tmp_path: Path):
    from ontologylab.extraction_state import (
        ChunkSpan,
        ExtractionRunBinding,
        put_extraction_receipts,
    )

    store = KGStore.open(tmp_path / "kg.sqlite")
    body = _TEXT.encode("utf-8")
    receipt = ingest_item(
        store.conn,
        IngestItem(
            idempotency_key="grounded-review-plant",
            scheme="doi",
            normalized_value="10.1000/grounded.review",
            source="pmc",
            evidence_grade="A",
            representation=RepresentationInput(
                source_kind="paper_api",
                source_uri="https://example.invalid/pmc/grounded",
                title="grounded",
                content_hash=content_hash_for(body),
                raw_text=body,
            ),
            stage="unknown",
            content_kind="fulltext",
        ),
    )
    assert receipt.work_id is not None
    assert receipt.representation_id is not None
    store.conn.commit()
    finalize_representation(store.conn, tmp_path, receipt.representation_id)
    store.conn.commit()
    selection = put_selection_receipt(
        store.conn, receipt.work_id, PolicyVersion.V1,
    )
    runs = put_extraction_receipts(
        store.conn,
        ExtractionRunBinding(
            representation_id=receipt.representation_id,
            policy_identity=selection.policy_hash,
            config_identity="config-grounded-review",
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
                end_offset=len(_TEXT),
                text=_TEXT,
                text_hash=content_hash_for(body),
                coordinate_profile="document-utf8-v1",
            ),
        ),
    )
    store.conn.commit()
    return (
        store,
        receipt.work_id,
        receipt.representation_id,
        runs.run,
        runs.chunks[0],
        selection,
    )


def _binding(
    representation_id: str,
    run,
    chunk,
    *,
    fact_id: str,
    start: int,
    end: int,
    selection_id: str,
    policy: str,
    fact_kind: str = "node",
    proposal_id: str | None = None,
    revision: str | None = None,
) -> CitationBinding:
    selected = _TEXT[start:end]
    return CitationBinding(
        representation_id=representation_id,
        representation_content_hash=run.document_content_hash,
        run_receipt_id=run.receipt_id,
        chunk_receipt_id=chunk.receipt_id,
        chunk_start_offset=chunk.start_offset,
        chunk_end_offset=chunk.end_offset,
        coordinate_profile=chunk.coordinate_profile,
        chunk_text_hash=chunk.chunk_text_hash,
        chunk_plan_receipt_id=chunk.plan_receipt_id,
        selection_receipt_id=selection_id,
        policy_identity=policy,
        fact_kind=fact_kind,
        fact_id=fact_id,
        proposal_id=proposal_id or fact_id,
        fact_revision=revision or fact_revision_id(fact_kind, fact_id),
        start_offset=start,
        end_offset=end,
        selected_text=selected,
        selected_text_hash=content_hash_for(selected.encode("utf-8")),
    )


def _cite(
    store: KGStore,
    representation_id: str,
    run,
    chunk,
    selection,
    *,
    fact_kind: str,
    fact_id: str,
    start: int,
    end: int,
):
    return put_citation_receipts(
        store.conn,
        (
            _binding(
                representation_id,
                run,
                chunk,
                fact_id=fact_id,
                start=start,
                end=end,
                selection_id=selection.receipt_id,
                policy=selection.policy_hash,
                fact_kind=fact_kind,
                proposal_id=fact_id,
                revision=fact_revision_id(fact_kind, fact_id),
            ),
        ),
    )[0]


def _plant_graph(tmp_path: Path, *, cite_service: bool = True):
    store, _work_id, representation_id, run, chunk, selection = _plant_ready(
        tmp_path,
    )
    gateway = make_entity(
        "PaymentGateway", source_span=SourceSpan(start=_GATEWAY[0], end=_GATEWAY[1]),
    )
    service = make_entity(
        "DatabaseService", source_span=SourceSpan(start=_SERVICE[0], end=_SERVICE[1]),
    )
    relation = make_relation(
        gateway,
        service,
        source_span=SourceSpan(start=_GATEWAY[0], end=_SERVICE[1]),
    )
    stats = store.insert_proposed(
        [gateway, service],
        [relation],
        source_doc_id=representation_id,
        extractor_engine="mock",
    )
    gateway_id = stats["id_map"][gateway.id]
    service_id = stats["id_map"][service.id]
    edge_id = str(
        store.conn.execute(
            "SELECT id FROM edges WHERE src_node_id = ? AND dst_node_id = ?",
            (gateway_id, service_id),
        ).fetchone()["id"]
    )
    _cite(
        store, representation_id, run, chunk, selection,
        fact_kind="node", fact_id=gateway_id,
        start=_GATEWAY[0], end=_GATEWAY[1],
    )
    if cite_service:
        _cite(
            store, representation_id, run, chunk, selection,
            fact_kind="node", fact_id=service_id,
            start=_SERVICE[0], end=_SERVICE[1],
        )
    _cite(
        store, representation_id, run, chunk, selection,
        fact_kind="edge", fact_id=edge_id,
        start=_GATEWAY[0], end=_SERVICE[1],
    )
    store.conn.commit()
    return store, gateway_id, service_id, edge_id, representation_id, run, chunk, selection


def test_ordinary_approve_without_citation_writes_zero_decisions(
    tmp_path: Path,
) -> None:
    from ontologylab.grounded_review import (
        GroundedReviewRefused,
        ReviewAction,
        ReviewRequest,
        apply_review,
    )

    store, _work_id, _rep, _run, _chunk, _selection = _plant_ready(tmp_path)
    try:
        entity = make_entity(
            "PaymentGateway",
            source_span=SourceSpan(start=_GATEWAY[0], end=_GATEWAY[1]),
        )
        stats = store.insert_proposed(
            [entity], [], source_doc_id=_rep, extractor_engine="mock",
        )
        fact_id = stats["id_map"][entity.id]
        with pytest.raises(GroundedReviewRefused):
            apply_review(
                store.conn,
                ReviewRequest(
                    item_id=fact_id,
                    actor="tester",
                    reason="looks right",
                    action=ReviewAction.APPROVE,
                    require_citations=True,
                ),
            )
        assert _status(store, fact_id) == "proposed"
        assert _decision_count(store.conn) == 0
    finally:
        store.close()


def test_cascade_one_invalid_member_writes_zero(tmp_path: Path) -> None:
    from ontologylab.kgstore import KGStoreError

    store, gateway_id, service_id, edge_id, *_rest = _plant_graph(
        tmp_path, cite_service=False,
    )
    try:
        with pytest.raises(KGStoreError):
            store.approve(edge_id, cascade=True, by="tester", note="cascade")
        assert _status(store, gateway_id) == "proposed"
        assert _status(store, service_id) == "proposed"
        assert _status(store, edge_id) == "proposed"
        assert _decision_count(store.conn) == 0
    finally:
        store.close()


def test_grounded_approve_appends_receipt_with_actor_reason_revision_digest(
    tmp_path: Path,
) -> None:
    from ontologylab.grounded_review import list_review_decisions

    store, gateway_id, service_id, edge_id, *_rest = _plant_graph(tmp_path)
    try:
        result = store.approve(
            edge_id, cascade=True, by="reviewer", note="grounded",
        )
        assert edge_id in result["approved_ids"]
        assert "decision_receipt_ids" in result
        assert result["decision_receipt_ids"]
        decisions = list_review_decisions(store.conn, "edge", edge_id)
        assert len(decisions) == 1
        decision = decisions[0]
        assert decision.actor == "reviewer"
        assert decision.reason == "grounded"
        assert decision.fact_revision == fact_revision_id("edge", edge_id)
        assert decision.citation_set_digest.startswith("sha256:")
        assert decision.citation_receipt_ids
        assert _status(store, gateway_id) == "verified"
        assert _status(store, service_id) == "verified"
        assert _status(store, edge_id) == "verified"
    finally:
        store.close()


def test_reject_quarantine_retract_compensate_append_history(
    tmp_path: Path,
) -> None:
    from ontologylab.grounded_review import (
        ReviewAction,
        ReviewRequest,
        apply_review,
        decisions_as_of,
        list_review_decisions,
    )

    store, gateway_id, service_id, edge_id, *_rest = _plant_graph(tmp_path)
    try:
        first = apply_review(
            store.conn,
            ReviewRequest(
                item_id=gateway_id,
                actor="reviewer",
                reason="ok",
                action=ReviewAction.APPROVE,
                require_citations=True,
                now=100.0,
            ),
        )
        store.reopen(gateway_id, by="reviewer")
        apply_review(
            store.conn,
            ReviewRequest(
                item_id=gateway_id,
                actor="reviewer",
                reason="bad span",
                action=ReviewAction.REJECT,
                now=200.0,
            ),
        )
        history = list_review_decisions(store.conn, "node", gateway_id)
        assert len(history) == 2
        assert history[0].action is ReviewAction.APPROVE
        assert history[1].action is ReviewAction.REJECT
        assert history[1].predecessor_receipt_id == first.decisions[0].receipt_id
        as_of = decisions_as_of(store.conn, "node", gateway_id, 150.0)
        assert len(as_of) == 1
        assert as_of[0].action is ReviewAction.APPROVE
        apply_review(
            store.conn,
            ReviewRequest(
                item_id=gateway_id,
                actor="reviewer",
                reason="compensate reject",
                action=ReviewAction.COMPENSATE,
                now=300.0,
            ),
        )
        apply_review(
            store.conn,
            ReviewRequest(
                item_id=service_id,
                actor="reviewer",
                reason="hold",
                action=ReviewAction.QUARANTINE,
                now=400.0,
            ),
        )
        store.reopen(gateway_id, by="reviewer")
        apply_review(
            store.conn,
            ReviewRequest(
                item_id=gateway_id,
                actor="reviewer",
                reason="ok again",
                action=ReviewAction.APPROVE,
                require_citations=True,
                now=500.0,
            ),
        )
        apply_review(
            store.conn,
            ReviewRequest(
                item_id=gateway_id,
                actor="reviewer",
                reason="false approve",
                action=ReviewAction.RETRACT,
                now=600.0,
            ),
        )
        final = list_review_decisions(store.conn, "node", gateway_id)
        assert [item.action for item in final][-5:] == [
            ReviewAction.APPROVE,
            ReviewAction.REJECT,
            ReviewAction.COMPENSATE,
            ReviewAction.APPROVE,
            ReviewAction.RETRACT,
        ]
        assert list_review_decisions(
            store.conn, "node", service_id,
        )[0].action is ReviewAction.QUARANTINE
        assert _status(store, gateway_id) == "rejected"
        assert _status(store, service_id) == "rejected"
        assert _status(store, edge_id) == "proposed"
    finally:
        store.close()


def test_generic_approve_cannot_waive_invalid_member(tmp_path: Path) -> None:
    from ontologylab.kgstore import KGStoreError

    store, gateway_id, service_id, edge_id, *_rest = _plant_graph(
        tmp_path, cite_service=False,
    )
    try:
        with pytest.raises(KGStoreError):
            store.approve(
                edge_id,
                cascade=True,
                by="tester",
                note="waive grounding",
            )
        assert _status(store, gateway_id) == "proposed"
        assert _status(store, service_id) == "proposed"
        assert _decision_count(store.conn) == 0
    finally:
        store.close()


def test_missing_actor_and_reason_are_refused(tmp_path: Path) -> None:
    from ontologylab.grounded_review import (
        GroundedReviewRefused,
        ReviewAction,
        ReviewRequest,
        apply_review,
    )

    store, gateway_id, *_rest = _plant_graph(tmp_path)
    try:
        with pytest.raises(GroundedReviewRefused):
            apply_review(
                store.conn,
                ReviewRequest(
                    item_id=gateway_id,
                    actor="",
                    reason="ok",
                    action=ReviewAction.APPROVE,
                    require_citations=True,
                ),
            )
        with pytest.raises(GroundedReviewRefused):
            apply_review(
                store.conn,
                ReviewRequest(
                    item_id=gateway_id,
                    actor="tester",
                    reason="",
                    action=ReviewAction.APPROVE,
                    require_citations=True,
                ),
            )
        assert _status(store, gateway_id) == "proposed"
        assert _decision_count(store.conn) == 0
    finally:
        store.close()


def test_omitted_revision_or_citation_digest_cannot_persist(
    tmp_path: Path,
) -> None:
    from ontologylab.grounded_review import apply_review, ReviewAction, ReviewRequest
    from ontologylab.grounded_review_ids import citation_set_digest
    from ontologylab.grounded_review_store import persist_decision
    from ontologylab.grounded_review_types import ReviewDecision

    store, gateway_id, *_rest = _plant_graph(tmp_path)
    try:
        result = apply_review(
            store.conn,
            ReviewRequest(
                item_id=gateway_id,
                actor="tester",
                reason="ok",
                action=ReviewAction.APPROVE,
                require_citations=True,
                now=10.0,
            ),
        )
        decision = result.decisions[0]
        assert decision.fact_revision
        assert decision.citation_set_digest == citation_set_digest(
            decision.citation_receipt_ids,
        )
        with pytest.raises(Exception):
            persist_decision(
                store.conn,
                ReviewDecision(
                    receipt_id="sha256:dead",
                    fact_kind="node",
                    fact_id=gateway_id,
                    proposal_id=gateway_id,
                    fact_revision="",
                    action=ReviewAction.REJECT,
                    actor="tester",
                    reason="later",
                    decided_ts=11.0,
                    as_of_ts=11.0,
                    citation_set_digest=decision.citation_set_digest,
                    citation_receipt_ids=decision.citation_receipt_ids,
                    representation_id=decision.representation_id,
                    selection_receipt_id=decision.selection_receipt_id,
                    policy_identity=decision.policy_identity,
                    run_receipt_id=decision.run_receipt_id,
                    predecessor_receipt_id=decision.receipt_id,
                    pack_ineligible=False,
                    waived_fact_ids=(),
                    waived_citation_ids=(),
                    scoped_defects=(),
                ),
            )
        with pytest.raises(Exception):
            persist_decision(
                store.conn,
                ReviewDecision(
                    receipt_id="sha256:beef",
                    fact_kind="node",
                    fact_id=gateway_id,
                    proposal_id=gateway_id,
                    fact_revision=decision.fact_revision,
                    action=ReviewAction.REJECT,
                    actor="tester",
                    reason="later",
                    decided_ts=12.0,
                    as_of_ts=12.0,
                    citation_set_digest="",
                    citation_receipt_ids=decision.citation_receipt_ids,
                    representation_id=decision.representation_id,
                    selection_receipt_id=decision.selection_receipt_id,
                    policy_identity=decision.policy_identity,
                    run_receipt_id=decision.run_receipt_id,
                    predecessor_receipt_id=decision.receipt_id,
                    pack_ineligible=False,
                    waived_fact_ids=(),
                    waived_citation_ids=(),
                    scoped_defects=(),
                ),
            )
    finally:
        store.close()


def test_scoped_waiver_is_pack_ineligible_and_not_global(
    tmp_path: Path,
) -> None:
    from ontologylab.grounded_review import (
        GroundedReviewRefused,
        WaiverRequest,
        approve_with_grounding_waiver,
        list_review_decisions,
    )

    store, gateway_id, service_id, edge_id, *_rest = _plant_graph(
        tmp_path, cite_service=False,
    )
    try:
        with pytest.raises(GroundedReviewRefused):
            approve_with_grounding_waiver(
                store.conn,
                WaiverRequest(
                    item_id=edge_id,
                    actor="tester",
                    reason="ship it",
                    member_ids=(),
                    citation_ids=(),
                    scoped_defects=(),
                    cascade=True,
                ),
            )
        result = approve_with_grounding_waiver(
            store.conn,
            WaiverRequest(
                item_id=edge_id,
                actor="tester",
                reason="service span missing",
                member_ids=(gateway_id, service_id, edge_id),
                citation_ids=(),
                scoped_defects=(f"node:{service_id}:missing_citation",),
                cascade=True,
            ),
        )
        assert result.decisions
        assert all(item.pack_ineligible for item in result.decisions)
        assert _status(store, gateway_id) == "verified"
        assert _status(store, service_id) == "verified"
        assert _status(store, edge_id) == "verified"
        service_history = list_review_decisions(store.conn, "node", service_id)
        assert service_history[0].pack_ineligible is True
        assert service_id in service_history[0].waived_fact_ids
    finally:
        store.close()


def test_apply_review_savepoint_is_caller_owned(tmp_path: Path) -> None:
    from ontologylab.grounded_review import (
        ReviewAction,
        ReviewRequest,
        apply_review,
    )

    store, gateway_id, *_rest = _plant_graph(tmp_path)
    try:
        if not store.conn.in_transaction:
            store.conn.execute("BEGIN")
        apply_review(
            store.conn,
            ReviewRequest(
                item_id=gateway_id,
                actor="tester",
                reason="ok",
                action=ReviewAction.APPROVE,
                require_citations=True,
            ),
        )
        assert _decision_count(store.conn) == 1
        store.conn.rollback()
        assert _decision_count(store.conn) == 0
        assert _status(store, gateway_id) == "proposed"
    finally:
        store.close()


def test_cli_reject_emits_decision_receipt_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from ontologylab.grounded_review import list_review_decisions
    from ontologylab.main import main

    store, gateway_id, *_rest = _plant_graph(tmp_path)
    store.close()
    with pytest.raises(SystemExit) as exited:
        main([
            "reject",
            "--id",
            gateway_id,
            "--by",
            "tester",
            "--note",
            "cli-reject",
            "--data-dir",
            str(tmp_path),
        ])
    assert exited.value.code == 0
    out = capsys.readouterr().out
    assert f"[ontologylab] rejected node {gateway_id}" in out
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        decisions = list_review_decisions(store.conn, "node", gateway_id)
        assert len(decisions) == 1
        receipt = decisions[0].receipt_id
        assert receipt.startswith("sha256:")
        assert f"[ontologylab] decision_receipt_ids {receipt}" in out
        assert decisions[0].citation_set_digest.startswith("sha256:")
        assert decisions[0].citation_receipt_ids
    finally:
        store.close()
