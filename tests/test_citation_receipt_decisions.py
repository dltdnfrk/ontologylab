"""Isolated citation identity/profile/plan/selection decision tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ontologylab.citation import (
    CitationRefusalCode,
    CitationRefused,
    put_citation_receipts,
)
from ontologylab.citation_ids import citation_receipt_id
from ontologylab.file_lifecycle import content_hash_for, finalize_representation
from ontologylab.ingestion_service import IngestItem, RepresentationInput, ingest_item
from ontologylab.selection import put_selection_receipt
from ontologylab.selection_types import PolicyVersion
from tests.test_citation_receipts import (
    _SHORT,
    _binding,
    _citation_receipt_count,
    _plant_ready_fulltext,
    _task2_receipts,
)
from tests.test_extraction_receipts import _put, _two_ready_same_bytes


_FAKE_PLAN = "sha256:" + ("ee" * 32)
_FAKE_SELECTION = "sha256:" + ("00" * 32)


def _sibling_chunk(
    conn,
    run,
    chunk,
    *,
    profile: str | None = None,
    plan: str | None = None,
    index: int = 99,
) -> str:
    receipt_id = "sha256:" + (f"{index:02d}" * 32)
    conn.execute(
        "INSERT INTO extraction_chunk_receipts ("
        "receipt_id, run_receipt_id, chunk_index, start_offset, end_offset, "
        "coordinate_profile, chunk_text_hash, plan_receipt_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            receipt_id,
            run.receipt_id,
            index,
            chunk.start_offset,
            chunk.end_offset,
            profile if profile is not None else chunk.coordinate_profile,
            chunk.chunk_text_hash,
            plan if plan is not None else chunk.plan_receipt_id,
        ),
    )
    return receipt_id


def _ingest_ready(
    store, tmp_path: Path, body: str, *, doi: str,
) -> tuple[str, str]:
    receipt = ingest_item(
        store.conn,
        IngestItem(
            idempotency_key=f"cite-{doi}-pmc",
            scheme="doi",
            normalized_value=doi,
            source="pmc",
            evidence_grade="A",
            representation=RepresentationInput(
                source_kind="paper_api",
                source_uri=f"https://example.invalid/pmc/{doi}",
                title="cite",
                content_hash=content_hash_for(body.encode("utf-8")),
                raw_text=body.encode("utf-8"),
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
    return receipt.work_id, receipt.representation_id


def test_citation_identity_keeps_representation_not_content_hash(
    tmp_path: Path,
) -> None:
    digest_run = SimpleNamespace(
        receipt_id="sha256:" + ("11" * 32),
        document_content_hash=content_hash_for(_SHORT.encode("utf-8")),
        chunk_plan_receipt_id="sha256:" + ("22" * 32),
    )
    digest_chunk = SimpleNamespace(
        receipt_id="sha256:" + ("33" * 32),
        start_offset=0,
        end_offset=len(_SHORT),
        coordinate_profile="document-utf8-v1",
        chunk_text_hash=content_hash_for(_SHORT.encode("utf-8")),
        plan_receipt_id=digest_run.chunk_plan_receipt_id,
    )
    left = _binding(
        representation_id="rep-a",
        content_hash=digest_run.document_content_hash,
        run=digest_run,
        chunk=digest_chunk,
        fact_id="shared-fact",
        start=4,
        end=18,
        text=_SHORT,
    )
    right = _binding(
        representation_id="rep-b",
        content_hash=digest_run.document_content_hash,
        run=digest_run,
        chunk=digest_chunk,
        fact_id="shared-fact",
        start=4,
        end=18,
        text=_SHORT,
    )
    assert left.representation_content_hash == right.representation_content_hash
    assert citation_receipt_id(left) != citation_receipt_id(right)

    store, rep_a, rep_b = _two_ready_same_bytes(tmp_path)
    try:
        run_a = _put(store.conn, rep_a)
        run_b = _put(store.conn, rep_b)
        first = put_citation_receipts(
            store.conn,
            (
                _binding(
                    representation_id=rep_a,
                    content_hash=run_a.run.document_content_hash,
                    run=run_a.run,
                    chunk=run_a.chunks[0],
                    fact_id="shared-fact",
                    start=4,
                    end=18,
                    text=_SHORT,
                ),
            ),
        )
        second = put_citation_receipts(
            store.conn,
            (
                _binding(
                    representation_id=rep_b,
                    content_hash=run_b.run.document_content_hash,
                    run=run_b.run,
                    chunk=run_b.chunks[0],
                    fact_id="shared-fact",
                    start=4,
                    end=18,
                    text=_SHORT,
                ),
            ),
        )
        assert first[0].created is True
        assert second[0].created is True
        assert first[0].receipt_id != second[0].receipt_id
        assert first[0].representation_id == rep_a
        assert second[0].representation_id == rep_b
        assert (
            first[0].representation_content_hash
            == second[0].representation_content_hash
        )
        assert _citation_receipt_count(store.conn) == 2
        with pytest.raises(CitationRefused) as refused:
            put_citation_receipts(
                store.conn,
                (
                    _binding(
                        representation_id=rep_b,
                        content_hash=run_a.run.document_content_hash,
                        run=run_a.run,
                        chunk=run_a.chunks[0],
                        fact_id="shared-fact",
                        start=4,
                        end=18,
                        text=_SHORT,
                    ),
                ),
            )
        assert refused.value.code is CitationRefusalCode.CROSS_BIND
        assert _citation_receipt_count(store.conn) == 2
    finally:
        store.close()


def test_mismatched_chunk_profile_refuses_with_zero_rows(
    tmp_path: Path,
) -> None:
    store, _work_id, representation_id = _plant_ready_fulltext(
        tmp_path, _SHORT, doi="10.1000/cite.profile",
    )
    try:
        runs, _spans = _task2_receipts(
            store.conn, representation_id, _SHORT,
        )
        sibling = _sibling_chunk(
            store.conn, runs.run, runs.chunks[0], profile="bytes-v9",
        )
        valid = _binding(
            representation_id=representation_id,
            content_hash=runs.run.document_content_hash,
            run=runs.run,
            chunk=runs.chunks[0],
            fact_id="fact-gateway",
            start=4,
            end=18,
            text=_SHORT,
        )
        mismatched = replace(
            valid,
            chunk_receipt_id=sibling,
            coordinate_profile="document-utf8-v1",
        )
        with pytest.raises(CitationRefused) as refused:
            put_citation_receipts(store.conn, (mismatched,))
        assert refused.value.code is CitationRefusalCode.MISSING_RECEIPT
        assert _citation_receipt_count(store.conn) == 0
    finally:
        store.close()


def test_mismatched_chunk_plan_refuses_with_zero_rows(
    tmp_path: Path,
) -> None:
    store, _work_id, representation_id = _plant_ready_fulltext(
        tmp_path, _SHORT, doi="10.1000/cite.plan",
    )
    try:
        runs, _spans = _task2_receipts(
            store.conn, representation_id, _SHORT,
        )
        sibling = _sibling_chunk(
            store.conn, runs.run, runs.chunks[0], plan=_FAKE_PLAN,
        )
        valid = _binding(
            representation_id=representation_id,
            content_hash=runs.run.document_content_hash,
            run=runs.run,
            chunk=runs.chunks[0],
            fact_id="fact-gateway",
            start=4,
            end=18,
            text=_SHORT,
        )
        mismatched = replace(
            valid,
            chunk_receipt_id=sibling,
            chunk_plan_receipt_id=runs.run.chunk_plan_receipt_id,
        )
        with pytest.raises(CitationRefused) as refused:
            put_citation_receipts(store.conn, (mismatched,))
        assert refused.value.code is CitationRefusalCode.MISSING_RECEIPT
        assert _citation_receipt_count(store.conn) == 0
    finally:
        store.close()


def test_missing_or_foreign_selection_receipt_refuses_with_zero_rows(
    tmp_path: Path,
) -> None:
    store, work_id, representation_id = _plant_ready_fulltext(
        tmp_path, _SHORT, doi="10.1000/cite.selection",
    )
    try:
        selection = put_selection_receipt(
            store.conn, work_id, PolicyVersion.V1,
        )
        runs, _spans = _task2_receipts(
            store.conn,
            representation_id,
            _SHORT,
            policy_identity=selection.policy_hash,
        )
        valid = _binding(
            representation_id=representation_id,
            content_hash=runs.run.document_content_hash,
            run=runs.run,
            chunk=runs.chunks[0],
            fact_id="fact-gateway",
            start=4,
            end=18,
            text=_SHORT,
            selection_receipt_id=selection.receipt_id,
            policy_identity=selection.policy_hash,
        )
        missing = replace(valid, selection_receipt_id=_FAKE_SELECTION)
        with pytest.raises(CitationRefused) as refused:
            put_citation_receipts(store.conn, (missing,))
        assert refused.value.code is CitationRefusalCode.MISSING_RECEIPT
        assert _citation_receipt_count(store.conn) == 0

        foreign_rep = _ingest_ready(
            store,
            tmp_path,
            "OtherGateway text for a foreign selection receipt.",
            doi="10.1000/cite.selection.other",
        )
        foreign = put_selection_receipt(
            store.conn, foreign_rep[0], PolicyVersion.V1,
        )
        assert foreign.selected_representation_id == foreign_rep[1]
        mismatched = replace(valid, selection_receipt_id=foreign.receipt_id)
        with pytest.raises(CitationRefused) as foreign_refused:
            put_citation_receipts(store.conn, (mismatched,))
        assert foreign_refused.value.code is CitationRefusalCode.CROSS_BIND
        assert _citation_receipt_count(store.conn) == 0
    finally:
        store.close()
