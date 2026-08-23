"""Live citation persist binds explicit Task 2 ids, not latest created_ts."""

from __future__ import annotations

from pathlib import Path

import pytest

from ontologylab.citation import persist_chunk_citations
from ontologylab.citation_types import ChunkCitationBatch, CitationRefused
from ontologylab.file_lifecycle import (
    content_hash_for,
    read_ready_text,
    store_root_from_conn,
)
from ontologylab.models import ProposedEntity, SourceSpan
from tests.step7_integration_support import plant_and_extract, probe_node_id
from tests.step7_valid_stale import plant_valid_stale_run


def test_persist_without_context_refuses_when_two_runs_cover_chunk(
    tmp_path: Path,
) -> None:
    store, _work, _pub, pmc_id = plant_and_extract(tmp_path / "live")
    try:
        fact_id = probe_node_id(store)
        plant_valid_stale_run(store, pmc_id)
        text = read_ready_text(
            store.conn, store_root_from_conn(store.conn), pmc_id,
        )
        start = text.index("PmcFulltextProbe")
        end = start + len("PmcFulltextProbe")
        with pytest.raises(CitationRefused) as refused:
            persist_chunk_citations(
                store.conn,
                ChunkCitationBatch(
                    representation_id=pmc_id,
                    chunk_index=0,
                    chunk_start_offset=0,
                    entities=(
                        ProposedEntity(
                            id="e1",
                            name="PmcFulltextProbe",
                            entity_type="Component",
                            source_span=SourceSpan(start=start, end=end),
                        ),
                    ),
                    relations=(),
                    id_map={"e1": fact_id},
                ),
            )
        assert refused.value.code.value in {"ambiguous", "cross_bind"}
    finally:
        store.close()


def test_persist_with_explicit_run_binds_current_not_stale(tmp_path: Path) -> None:
    store, _work, _pub, pmc_id = plant_and_extract(tmp_path / "live")
    try:
        live_run = str(
            store.conn.execute(
                "SELECT receipt_id FROM extraction_run_receipts "
                "WHERE representation_id = ? AND policy_identity != ?",
                (pmc_id, "wrong-policy-v0"),
            ).fetchone()[0]
        )
        live_chunk = str(
            store.conn.execute(
                "SELECT receipt_id FROM extraction_chunk_receipts "
                "WHERE run_receipt_id = ?",
                (live_run,),
            ).fetchone()[0]
        )
        plant_valid_stale_run(store, pmc_id)
        text = read_ready_text(
            store.conn, store_root_from_conn(store.conn), pmc_id,
        )
        start = text.index("PmcFulltextProbe")
        end = start + len("PmcFulltextProbe")
        written = persist_chunk_citations(
            store.conn,
            ChunkCitationBatch(
                representation_id=pmc_id,
                chunk_index=0,
                chunk_start_offset=0,
                entities=(
                    ProposedEntity(
                        id="e1",
                        name="PmcFulltextProbe",
                        entity_type="Component",
                        source_span=SourceSpan(start=start, end=end),
                    ),
                ),
                relations=(),
                id_map={"e1": probe_node_id(store)},
                run_receipt_id=live_run,
                chunk_receipt_id=live_chunk,
            ),
        )
        assert written
        assert all(item.run_receipt_id == live_run for item in written)
        assert content_hash_for(text[start:end].encode("utf-8"))
    finally:
        store.close()
