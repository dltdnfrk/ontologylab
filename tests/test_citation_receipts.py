"""Characterization and contract tests for citation grounding receipts."""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import json
from pathlib import Path

import pytest

from ontologylab.authority_repo import create_work
from ontologylab.extraction_state import ExtractionState, ensure_schema
from ontologylab.extractor import (
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
)
from ontologylab.file_lifecycle import content_hash_for, finalize_representation
from ontologylab.ingestion_service import IngestItem, RepresentationInput, ingest_item
from ontologylab.kgstore import KGStore
from ontologylab.models import SourceSpan
from ontologylab.selection import put_selection_receipt
from ontologylab.selection_types import PolicyVersion
from tests.conftest import default_schema_dict
from tests.factories import make_entity, make_relation


_FILLER = "plain lowercase filler words repeated to pad the document body. "
LONG_DOC = (
    "The RateLimiter throttles requests using the TokenBucketAlgorithm. "
    + _FILLER * 120
    + "Meanwhile the SessionCache keeps hot entries near the edge. "
    + _FILLER * 120
    + "Under load, the RateLimiter signals the LoadShedder to drop work. "
    + _FILLER * 20
)
_SHORT = "The PaymentGateway uses the DatabaseService."


def _citation_receipt_count(conn) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'citation_receipts'"
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute("SELECT COUNT(*) FROM citation_receipts").fetchone()
    return int(row[0])


def _legacy_wrap(payload: str) -> str:
    return "```json\n" + payload + "\n```"


def test_baseline_multichunk_extraction_converges_one_node_with_legacy_citations(
    tmp_path: Path,
) -> None:
    from ontologylab.engines import MockEngine

    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        document, _created = store.insert_document(
            source_kind="upload",
            source_uri="file:///long.md",
            title="long",
            raw_text=LONG_DOC,
            content_hash=content_hash_for(LONG_DOC.encode("utf-8")),
        )
        schema = store.get_schema()
        chunks = chunk_document(LONG_DOC)
        assert len(chunks) >= 2
        assert chunks[1].char_offset > 0
        engine = MockEngine()
        for chunk in chunks:
            raw, _usage = asyncio.run(
                engine.generate(build_extraction_prompt(schema, chunk.text))
            )
            result = parse_and_validate_extraction(raw, schema, chunk)
            store.insert_proposed(
                result.entities,
                result.relations,
                source_doc_id=document.id,
                extractor_engine="mock",
            )
        raw_text = store.document_raw_text(document.id)
        rows = store.conn.execute(
            "SELECT name, source_span FROM nodes WHERE source_span IS NOT NULL"
        ).fetchall()
        assert rows
        for row in rows:
            span = json.loads(row["source_span"])
            cited = raw_text[span["start"]:span["end"]]
            assert cited
            assert row["name"].casefold() in cited.casefold()
        limiter = store.conn.execute(
            "SELECT id FROM nodes WHERE normalized_name = 'ratelimiter'"
        ).fetchall()
        assert len(limiter) == 1
        citations = store.citations("node", limiter[0]["id"])
        assert len(citations) >= 2
        assert _citation_receipt_count(store.conn) == 0
    finally:
        store.close()


def test_baseline_span_validation_stores_document_offsets_on_legacy_citation(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        text = "prefix RateLimiter suffix"
        document, _created = store.insert_document(
            source_kind="upload",
            source_uri="file:///span.md",
            title="span",
            raw_text=text,
            content_hash=content_hash_for(text.encode("utf-8")),
        )
        offset = 40
        chunk = chunk_document(text)[0]
        chunk.char_offset = offset
        raw = _legacy_wrap(json.dumps({
            "entities": [{
                "name": "RateLimiter",
                "entity_type": "Component",
                "source_span": {"start": 7, "end": 18},
            }],
            "relations": [],
        }))
        result = parse_and_validate_extraction(raw, default_schema_dict(), chunk)
        (entity,) = result.entities
        assert entity.source_span is not None
        assert entity.source_span.start == offset + 7
        assert entity.source_span.end == offset + 18
        store.insert_proposed(
            result.entities, [], source_doc_id=document.id, extractor_engine="mock",
        )
        citation = store.citations("node", store.conn.execute(
            "SELECT id FROM nodes"
        ).fetchone()["id"])[0]
        assert citation["source_doc_id"] == document.id
        assert citation["source_span"] == {
            "start": offset + 7, "end": offset + 18,
        }
        assert _citation_receipt_count(store.conn) == 0
    finally:
        store.close()


def test_baseline_duplicate_fact_converges_without_citation_receipts(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        document, _created = store.insert_document(
            source_kind="upload",
            source_uri="file:///dup.md",
            title="dup",
            raw_text=_SHORT,
            content_hash=content_hash_for(_SHORT.encode("utf-8")),
        )
        first = make_entity(
            "PaymentGateway",
            source_span=SourceSpan(start=4, end=19),
        )
        second = make_entity(
            "PaymentGateway",
            source_span=SourceSpan(start=4, end=19),
        )
        store.insert_proposed(
            [first], [], source_doc_id=document.id, extractor_engine="mock",
        )
        store.insert_proposed(
            [second], [], source_doc_id=document.id, extractor_engine="mock",
        )
        nodes = store.conn.execute("SELECT id FROM nodes").fetchall()
        assert len(nodes) == 1
        assert len(store.citations("node", nodes[0]["id"])) == 2
        assert _citation_receipt_count(store.conn) == 0
    finally:
        store.close()


def test_baseline_task2_and_task3_receipts_do_not_write_citation_receipts(
    tmp_path: Path,
) -> None:
    from ontologylab.extraction_state import (
        ChunkSpan,
        ExtractionRunBinding,
        put_extraction_receipts,
    )

    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        body = _SHORT.encode("utf-8")
        receipt = ingest_item(
            store.conn,
            IngestItem(
                idempotency_key="cite-baseline-task23",
                scheme="doi",
                normalized_value="10.1000/cite.baseline",
                source="pmc",
                evidence_grade="A",
                representation=RepresentationInput(
                    source_kind="paper_api",
                    source_uri="https://example.invalid/pmc/cite",
                    title="cite",
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
        assert selection.selected_representation_id == receipt.representation_id
        put_extraction_receipts(
            store.conn,
            ExtractionRunBinding(
                representation_id=receipt.representation_id,
                policy_identity=selection.policy_hash,
                config_identity="config-baseline",
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
                    end_offset=len(_SHORT),
                    text=_SHORT,
                    text_hash=content_hash_for(body),
                    coordinate_profile="document-utf8-v1",
                ),
            ),
        )
        store.conn.commit()
        runs = store.conn.execute(
            "SELECT receipt_id FROM extraction_run_receipts"
        ).fetchall()
        assert len(runs) == 1
        chunks = store.conn.execute(
            "SELECT receipt_id FROM extraction_chunk_receipts"
        ).fetchall()
        assert len(chunks) == 1
        assert _citation_receipt_count(store.conn) == 0
    finally:
        store.close()


def test_baseline_insert_proposed_commit_false_is_caller_owned(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        document, _created = store.insert_document(
            source_kind="upload",
            source_uri="file:///txn.md",
            title="txn",
            raw_text=_SHORT,
            content_hash=content_hash_for(_SHORT.encode("utf-8")),
        )
        entity = make_entity(
            "PaymentGateway",
            source_span=SourceSpan(start=4, end=19),
        )
        store.insert_proposed(
            [entity],
            [],
            source_doc_id=document.id,
            extractor_engine="mock",
            commit=False,
        )
        assert store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
        store.conn.rollback()
        assert store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == 0
    finally:
        store.close()


def test_baseline_citations_api_returns_source_doc_and_span(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        document, _created = store.insert_document(
            source_kind="upload",
            source_uri="file:///api.md",
            title="api",
            raw_text=_SHORT,
            content_hash=content_hash_for(_SHORT.encode("utf-8")),
        )
        entity = make_entity(
            "PaymentGateway",
            source_span=SourceSpan(start=4, end=18),
        )
        relation_target = make_entity(
            "DatabaseService",
            source_span=SourceSpan(start=25, end=40),
        )
        relation = make_relation(
            entity,
            relation_target,
            source_span=SourceSpan(start=4, end=40),
        )
        store.insert_proposed(
            [entity, relation_target],
            [relation],
            source_doc_id=document.id,
            extractor_engine="mock",
        )
        node_id = store.conn.execute(
            "SELECT id FROM nodes WHERE name = 'PaymentGateway'"
        ).fetchone()["id"]
        citation = store.citations("node", node_id)[0]
        assert set(citation) == {"source_doc_id", "source_span"}
        assert citation["source_doc_id"] == document.id
        assert citation["source_span"] == {"start": 4, "end": 18}
        assert _citation_receipt_count(store.conn) == 0
    finally:
        store.close()


def test_baseline_legacy_ensure_schema_does_not_require_citation_module(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    state = ExtractionState(store.conn)
    try:
        create_work(store.conn, "work-cite-baseline")
        ensure_schema(store.conn)
        assert _citation_receipt_count(store.conn) == 0
    finally:
        state.close()
        store.close()


def _plant_ready_fulltext(
    tmp_path: Path,
    body: str,
    *,
    doi: str = "10.1000/cite.task4",
    source: str = "pmc",
) -> tuple[KGStore, str, str]:
    store = KGStore.open(tmp_path / "kg.sqlite")
    receipt = ingest_item(
        store.conn,
        IngestItem(
            idempotency_key=f"cite-{doi}-{source}",
            scheme="doi",
            normalized_value=doi,
            source=source,
            evidence_grade="A",
            representation=RepresentationInput(
                source_kind="paper_api",
                source_uri=f"https://example.invalid/{source}/cite",
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
    return store, receipt.work_id, receipt.representation_id


def _task2_receipts(
    conn,
    representation_id: str,
    text: str,
    *,
    policy_identity: str = "policy-cite",
    config_identity: str = "config-cite",
):
    from ontologylab.extraction_state import (
        ChunkSpan,
        ExtractionRunBinding,
        put_extraction_receipts,
    )

    chunks = chunk_document(text)
    spans = tuple(
        ChunkSpan(
            index=chunk.index,
            start_offset=chunk.char_offset,
            end_offset=chunk.char_offset + len(chunk.text),
            text=chunk.text,
            text_hash=content_hash_for(chunk.text.encode("utf-8")),
            coordinate_profile="document-utf8-v1",
        )
        for chunk in chunks
    )
    return put_extraction_receipts(
        conn,
        ExtractionRunBinding(
            representation_id=representation_id,
            policy_identity=policy_identity,
            config_identity=config_identity,
            schema_version_id=1,
            extractor_engine="mock",
            extractor_model="",
            prompt_version="extract-v1",
            decode_params_json="{}",
        ),
        spans,
    ), spans


def _binding(
    *,
    representation_id: str,
    content_hash: str,
    run,
    chunk,
    fact_id: str,
    start: int,
    end: int,
    text: str,
    selection_receipt_id: str | None = None,
    policy_identity: str | None = None,
    fact_kind: str = "node",
    proposal_id: str = "proposal-1",
    fact_revision: str = "rev-1",
):
    from ontologylab.citation import CitationBinding

    selected = text[start:end]
    return CitationBinding(
        representation_id=representation_id,
        representation_content_hash=content_hash,
        run_receipt_id=run.receipt_id,
        chunk_receipt_id=chunk.receipt_id,
        chunk_start_offset=chunk.start_offset,
        chunk_end_offset=chunk.end_offset,
        coordinate_profile=chunk.coordinate_profile,
        chunk_text_hash=chunk.chunk_text_hash,
        chunk_plan_receipt_id=chunk.plan_receipt_id,
        selection_receipt_id=selection_receipt_id,
        policy_identity=policy_identity,
        fact_kind=fact_kind,
        fact_id=fact_id,
        proposal_id=proposal_id,
        fact_revision=fact_revision,
        start_offset=start,
        end_offset=end,
        selected_text=selected,
        selected_text_hash=content_hash_for(selected.encode("utf-8")),
    )


def test_overlapping_chunks_yield_distinct_citation_receipts(
    tmp_path: Path,
) -> None:
    from ontologylab.citation import list_citation_receipts
    from ontologylab.engines import MockEngine
    from ontologylab.extractor import TOTALS_KEYS
    from ontologylab.provenance import Provenance
    from ontologylab.research_extract import (
        ResearchExtractSession,
        extract_research_documents,
    )
    from tests.test_preferred_selection import caps

    store, _work_id, representation_id = _plant_ready_fulltext(
        tmp_path, LONG_DOC,
    )
    try:
        totals = dict.fromkeys(TOTALS_KEYS, 0)

        def _stats(stats: dict[str, int]) -> None:
            for key in totals:
                totals[key] += stats.get(key, 0)

        asyncio.run(
            extract_research_documents(
                store,
                (representation_id,),
                ResearchExtractSession(
                    engine=MockEngine(),
                    provenance=Provenance(str(tmp_path / "job-overlap"), seed=0),
                    caps=caps(),
                    extractor_engine="mock",
                    extractor_model="",
                    on_progress=lambda _line: None,
                    on_stats=_stats,
                ),
            )
        )
        limiter = store.conn.execute(
            "SELECT id FROM nodes WHERE normalized_name = 'ratelimiter'"
        ).fetchall()
        assert len(limiter) == 1
        receipts = list_citation_receipts(
            store.conn, "node", str(limiter[0]["id"]),
        )
        assert len(receipts) >= 2
        assert len({item.receipt_id for item in receipts}) == len(receipts)
        assert len({item.chunk_receipt_id for item in receipts}) >= 2
        selection = store.conn.execute(
            "SELECT receipt_id FROM preferred_selection_receipts"
        ).fetchone()
        run = store.conn.execute(
            "SELECT receipt_id FROM extraction_run_receipts"
        ).fetchone()
        for item in receipts:
            assert item.representation_id == representation_id
            assert item.run_receipt_id == run["receipt_id"]
            assert item.selection_receipt_id == selection["receipt_id"]
            assert item.coordinate_profile == "document-utf8-v1"
            assert item.chunk_plan_receipt_id
            assert item.start_offset < item.end_offset
            assert LONG_DOC[item.start_offset:item.end_offset] == item.selected_text
            assert "RateLimiter" in item.selected_text
    finally:
        store.close()


def test_citation_receipt_uses_document_offsets_not_chunk_local(
    tmp_path: Path,
) -> None:
    from ontologylab.citation import put_citation_receipts

    store, _work_id, representation_id = _plant_ready_fulltext(
        tmp_path, LONG_DOC, doi="10.1000/cite.offsets",
    )
    try:
        runs, _spans = _task2_receipts(
            store.conn, representation_id, LONG_DOC,
        )
        later = runs.chunks[1]
        local_start = LONG_DOC[later.start_offset:].index("RateLimiter")
        start = later.start_offset + local_start
        end = start + len("RateLimiter")
        assert start > later.start_offset > 0
        stored = put_citation_receipts(
            store.conn,
            (
                _binding(
                    representation_id=representation_id,
                    content_hash=runs.run.document_content_hash,
                    run=runs.run,
                    chunk=later,
                    fact_id="fact-limiter",
                    start=start,
                    end=end,
                    text=LONG_DOC,
                ),
            ),
        )
        receipt = stored[0]
        row = store.conn.execute(
            "SELECT start_offset, end_offset, selected_text, "
            "representation_id FROM citation_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
        assert receipt.start_offset == start
        assert row["start_offset"] == start
        assert row["end_offset"] == end
        assert row["start_offset"] != local_start
        assert row["selected_text"] == "RateLimiter"
        assert row["representation_id"] == representation_id
        assert LONG_DOC[row["start_offset"]:row["end_offset"]] == "RateLimiter"
    finally:
        store.close()


def test_citation_receipt_binds_representation_run_chunk_profile_plan_and_text_hash(
    tmp_path: Path,
) -> None:
    from ontologylab.citation import (
        get_citation_receipt,
        put_citation_receipts,
    )

    store, work_id, representation_id = _plant_ready_fulltext(
        tmp_path, _SHORT, doi="10.1000/cite.bind",
    )
    try:
        selection = put_selection_receipt(store.conn, work_id, PolicyVersion.V1)
        runs, _spans = _task2_receipts(
            store.conn,
            representation_id,
            _SHORT,
            policy_identity=selection.policy_hash,
        )
        start, end = 4, 18
        stored = put_citation_receipts(
            store.conn,
            (
                _binding(
                    representation_id=representation_id,
                    content_hash=runs.run.document_content_hash,
                    run=runs.run,
                    chunk=runs.chunks[0],
                    fact_id="fact-gateway",
                    start=start,
                    end=end,
                    text=_SHORT,
                    selection_receipt_id=selection.receipt_id,
                    policy_identity=selection.policy_hash,
                ),
            ),
        )
        receipt = stored[0]
        assert receipt.receipt_id.startswith("sha256:")
        assert receipt.representation_id == representation_id
        assert receipt.representation_content_hash == runs.run.document_content_hash
        assert receipt.run_receipt_id == runs.run.receipt_id
        assert receipt.chunk_receipt_id == runs.chunks[0].receipt_id
        assert receipt.coordinate_profile == "document-utf8-v1"
        assert receipt.chunk_plan_receipt_id == runs.run.chunk_plan_receipt_id
        assert receipt.chunk_text_hash == runs.chunks[0].chunk_text_hash
        assert receipt.selection_receipt_id == selection.receipt_id
        assert receipt.selected_text == "PaymentGateway"
        assert receipt.selected_text_hash == content_hash_for(
            b"PaymentGateway",
        )
        loaded = get_citation_receipt(store.conn, receipt.receipt_id)
        assert loaded is not None
        assert loaded.receipt_id == receipt.receipt_id
        assert loaded.selected_text_hash == receipt.selected_text_hash
        row = store.conn.execute(
            "SELECT representation_id, run_receipt_id, chunk_receipt_id, "
            "coordinate_profile, chunk_plan_receipt_id, chunk_text_hash, "
            "selection_receipt_id, selected_text_hash FROM citation_receipts "
            "WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
        assert tuple(row) == (
            representation_id,
            runs.run.receipt_id,
            runs.chunks[0].receipt_id,
            "document-utf8-v1",
            runs.run.chunk_plan_receipt_id,
            runs.chunks[0].chunk_text_hash,
            selection.receipt_id,
            receipt.selected_text_hash,
        )
    finally:
        store.close()


def test_same_bytes_two_representations_cannot_cross_bind_citations(
    tmp_path: Path,
) -> None:
    from ontologylab.citation import (
        CitationRefusalCode,
        CitationRefused,
        put_citation_receipts,
    )
    from tests.test_extraction_receipts import _put, _two_ready_same_bytes

    store, rep_a, rep_b = _two_ready_same_bytes(tmp_path)
    try:
        run_a = _put(store.conn, rep_a)
        run_b = _put(store.conn, rep_b)
        assert run_a.run.document_content_hash == run_b.run.document_content_hash
        assert run_a.run.receipt_id != run_b.run.receipt_id
        with pytest.raises(CitationRefused) as refused:
            put_citation_receipts(
                store.conn,
                (
                    _binding(
                        representation_id=rep_b,
                        content_hash=run_a.run.document_content_hash,
                        run=run_a.run,
                        chunk=run_a.chunks[0],
                        fact_id="fact-cross",
                        start=4,
                        end=19,
                        text=_SHORT,
                    ),
                ),
            )
        assert refused.value.code is CitationRefusalCode.CROSS_BIND
        assert _citation_receipt_count(store.conn) == 0
        first = put_citation_receipts(
            store.conn,
            (
                _binding(
                    representation_id=rep_a,
                    content_hash=run_a.run.document_content_hash,
                    run=run_a.run,
                    chunk=run_a.chunks[0],
                    fact_id="fact-a",
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
                    fact_id="fact-b",
                    start=4,
                    end=18,
                    text=_SHORT,
                ),
            ),
        )
        assert first[0].receipt_id != second[0].receipt_id
        assert first[0].representation_id == rep_a
        assert second[0].representation_id == rep_b
        assert _citation_receipt_count(store.conn) == 2
    finally:
        store.close()


def test_mismatched_selected_text_or_hash_refuses_with_zero_partial_writes(
    tmp_path: Path,
) -> None:
    from ontologylab.citation import (
        CitationRefusalCode,
        CitationRefused,
        put_citation_receipts,
    )
    from dataclasses import replace

    store, _work_id, representation_id = _plant_ready_fulltext(
        tmp_path, _SHORT, doi="10.1000/cite.mismatch",
    )
    try:
        runs, _spans = _task2_receipts(
            store.conn, representation_id, _SHORT,
        )
        valid = _binding(
            representation_id=representation_id,
            content_hash=runs.run.document_content_hash,
            run=runs.run,
            chunk=runs.chunks[0],
            fact_id="fact-gateway",
            start=4,
            end=19,
            text=_SHORT,
        )
        wrong_hash = replace(
            valid,
            selected_text_hash="sha256:" + ("0" * 64),
        )
        wrong_text = replace(valid, selected_text="PaymentGatewayX")
        for binding, code in (
            (wrong_hash, CitationRefusalCode.INVALID_HASH),
            (wrong_text, CitationRefusalCode.INVALID_TEXT),
        ):
            with pytest.raises(CitationRefused) as refused:
                put_citation_receipts(store.conn, (binding,))
            assert refused.value.code is code
        assert _citation_receipt_count(store.conn) == 0
        nodes = store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert int(nodes) == 0
    finally:
        store.close()


def test_conflicting_citation_retry_does_not_overwrite(
    tmp_path: Path,
) -> None:
    from ontologylab.citation import (
        CitationRefusalCode,
        CitationRefused,
        ensure_citation_schema,
        put_citation_receipts,
    )
    from ontologylab.citation_ids import citation_receipt_id

    store, _work_id, representation_id = _plant_ready_fulltext(
        tmp_path, _SHORT, doi="10.1000/cite.conflict",
    )
    try:
        runs, _spans = _task2_receipts(
            store.conn, representation_id, _SHORT,
        )
        binding = _binding(
            representation_id=representation_id,
            content_hash=runs.run.document_content_hash,
            run=runs.run,
            chunk=runs.chunks[0],
            fact_id="fact-gateway",
            start=4,
            end=19,
            text=_SHORT,
        )
        ensure_citation_schema(store.conn)
        store.conn.execute(
            "INSERT INTO citation_receipts ("
            "receipt_id, representation_id, representation_content_hash, "
            "run_receipt_id, chunk_receipt_id, chunk_start_offset, "
            "chunk_end_offset, coordinate_profile, chunk_text_hash, "
            "chunk_plan_receipt_id, selection_receipt_id, policy_identity, "
            "fact_kind, fact_id, proposal_id, fact_revision, start_offset, "
            "end_offset, selected_text, selected_text_hash, created_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "sha256:" + ("ab" * 32),
                binding.representation_id,
                binding.representation_content_hash,
                binding.run_receipt_id,
                binding.chunk_receipt_id,
                binding.chunk_start_offset,
                binding.chunk_end_offset,
                binding.coordinate_profile,
                binding.chunk_text_hash,
                binding.chunk_plan_receipt_id,
                binding.selection_receipt_id,
                binding.policy_identity,
                binding.fact_kind,
                binding.fact_id,
                binding.proposal_id,
                binding.fact_revision,
                binding.start_offset,
                binding.end_offset,
                binding.selected_text,
                binding.selected_text_hash,
                0.0,
            ),
        )
        expected_id = citation_receipt_id(binding)
        with pytest.raises(CitationRefused) as refused:
            put_citation_receipts(store.conn, (binding,))
        assert refused.value.code is CitationRefusalCode.CONFLICT
        row = store.conn.execute(
            "SELECT receipt_id, selected_text_hash FROM citation_receipts"
        ).fetchone()
        assert row["receipt_id"] == "sha256:" + ("ab" * 32)
        assert row["receipt_id"] != expected_id
        assert row["selected_text_hash"] == binding.selected_text_hash
        assert _citation_receipt_count(store.conn) == 1
    finally:
        store.close()


def test_same_citation_retry_converges(
    tmp_path: Path,
) -> None:
    from ontologylab.citation import put_citation_receipts

    store, _work_id, representation_id = _plant_ready_fulltext(
        tmp_path, _SHORT, doi="10.1000/cite.retry",
    )
    try:
        runs, _spans = _task2_receipts(
            store.conn, representation_id, _SHORT,
        )
        binding = _binding(
            representation_id=representation_id,
            content_hash=runs.run.document_content_hash,
            run=runs.run,
            chunk=runs.chunks[0],
            fact_id="fact-gateway",
            start=4,
            end=19,
            text=_SHORT,
            proposal_id="proposal-first",
        )
        first = put_citation_receipts(store.conn, (binding,))
        second = put_citation_receipts(
            store.conn,
            (_binding(
                representation_id=representation_id,
                content_hash=runs.run.document_content_hash,
                run=runs.run,
                chunk=runs.chunks[0],
                fact_id="fact-gateway",
                start=4,
                end=19,
                text=_SHORT,
                proposal_id="proposal-retry",
            ),),
        )
        assert first[0].receipt_id == second[0].receipt_id
        assert first[0].created is True
        assert second[0].created is False
        assert _citation_receipt_count(store.conn) == 1
    finally:
        store.close()


def test_put_citation_receipts_leaves_caller_transaction_uncommitted(
    tmp_path: Path,
) -> None:
    from ontologylab.citation import put_citation_receipts

    store, _work_id, representation_id = _plant_ready_fulltext(
        tmp_path, _SHORT, doi="10.1000/cite.txn",
    )
    try:
        runs, _spans = _task2_receipts(
            store.conn, representation_id, _SHORT,
        )
        store.conn.commit()
        store.conn.execute("BEGIN IMMEDIATE")
        put_citation_receipts(
            store.conn,
            (
                _binding(
                    representation_id=representation_id,
                    content_hash=runs.run.document_content_hash,
                    run=runs.run,
                    chunk=runs.chunks[0],
                    fact_id="fact-gateway",
                    start=4,
                    end=19,
                    text=_SHORT,
                ),
            ),
        )
        assert _citation_receipt_count(store.conn) == 1
        store.conn.rollback()
        assert _citation_receipt_count(store.conn) == 0
    finally:
        store.close()


def test_get_citation_receipt_refuses_tampered_ready_bytes(
    tmp_path: Path,
) -> None:
    from ontologylab.citation import (
        CitationRefusalCode,
        CitationRefused,
        get_citation_receipt,
        put_citation_receipts,
    )
    from ontologylab.file_lifecycle import final_raw_text_path

    store, _work_id, representation_id = _plant_ready_fulltext(
        tmp_path, _SHORT, doi="10.1000/cite.tamper",
    )
    try:
        runs, _spans = _task2_receipts(
            store.conn, representation_id, _SHORT,
        )
        stored = put_citation_receipts(
            store.conn,
            (
                _binding(
                    representation_id=representation_id,
                    content_hash=runs.run.document_content_hash,
                    run=runs.run,
                    chunk=runs.chunks[0],
                    fact_id="fact-gateway",
                    start=4,
                    end=18,
                    text=_SHORT,
                ),
            ),
        )
        store.conn.commit()
        path = tmp_path / final_raw_text_path(representation_id)
        data = bytearray(path.read_bytes())
        data[0] = (data[0] ^ 0x01) & 0xFF
        path.write_bytes(bytes(data))
        with pytest.raises(CitationRefused) as refused:
            get_citation_receipt(store.conn, stored[0].receipt_id)
        assert refused.value.code is CitationRefusalCode.INVALID_HASH
    finally:
        store.close()
