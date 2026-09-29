"""Evidence-mode publication must inherit the ontology version selection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ontologylab.extraction_state import ChunkSpan, ExtractionRunBinding, put_extraction_receipts
from ontologylab.kgstore import KGStore
from ontologylab.migration import compute_source_fingerprint
from ontologylab.pack_verifier import verify_pack
from ontologylab.packbuilder import build_pack
from ontologylab.selection import put_selection_receipt
from ontologylab.selection_types import PolicyVersion
from tests.factories import make_entity
from tests.test_pack_v2_closure import (
    _GATEWAY,
    _TEXT,
    _V2Fixture,
    _cite,
    _complete_streams,
    _plant_v2,
)


def _add_second_version(fixture: _V2Fixture) -> int:
    """Approve a second-schema fact from the same retained representation."""
    store = fixture.store
    version = store.install_schema(
        label="components-v2", description="Version selection regression",
        entity_types=[{"name": "Component", "attributes": {}}],
        relation_types=[],
    )
    selection = put_selection_receipt(store.conn, fixture.work_id, PolicyVersion.V1)
    receipts = put_extraction_receipts(
        store.conn,
        ExtractionRunBinding(
            representation_id=fixture.representation_id,
            policy_identity=selection.policy_hash, config_identity="config-v2",
            schema_version_id=version, extractor_engine="mock", extractor_model="",
            prompt_version="extract-v1", decode_params_json="{}",
        ),
        (ChunkSpan(
            index=0, start_offset=0, end_offset=len(_TEXT), text=_TEXT,
            text_hash=fixture.content_hash, coordinate_profile="document-utf8-v1",
        ),),
    )
    node = make_entity("PaymentGateway")
    stats = store.insert_proposed(
        [node], [], source_doc_id=fixture.representation_id, extractor_engine="mock",
    )
    node_id = stats["id_map"][node.id]
    _cite(
        store, fixture.representation_id, receipts.run, receipts.chunks[0], selection,
        fact_kind="node", fact_id=node_id, start=_GATEWAY[0], end=_GATEWAY[1],
    )
    store.approve(node_id, by="tester", note="second schema grounded")
    _complete_streams(store.conn)
    # This failed historical stream is not a producer of any shipped fact.
    store.conn.execute(
        "INSERT INTO extraction_runs "
        "(id, document_id, document_content_hash, schema_version_id, "
        "extractor_engine, extractor_model, prompt_version, decode_params, "
        "chunk_plan_hash, status, created_ts, updated_ts) "
        "VALUES ('inactive-only-run', ?, ?, 1, 'mock', 'unused', 'unused', "
        "'null', 'unused', 'failed', 1, 1)",
        (fixture.representation_id, fixture.content_hash),
    )
    store.conn.execute(
        "INSERT INTO extraction_chunks "
        "(run_id, chunk_index, char_offset, content_hash, status) "
        "VALUES ('inactive-only-run', 0, 0, ?, 'failed')",
        (fixture.content_hash,),
    )
    store.conn.commit()
    return version


@pytest.mark.parametrize("evidence_mode", ["full", "excerpt"])
@pytest.mark.parametrize("selection", ["active", "old", "all"])
def test_evidence_pack_scopes_lifecycle_and_receipts(
    tmp_path: Path, evidence_mode: str, selection: str,
) -> None:
    fixture = _plant_v2(tmp_path, complete_stream=False)
    try:
        active = _add_second_version(fixture)
        scope = {"active": (active,), "old": (1,), "all": (1, active)}[selection]
        assert fixture.store.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # Finish normal startup projection before checking build immutability.
        KGStore.open(fixture.kg).close()
        source_before = list(fixture.store.conn.iterdump())

        manifest = build_pack(
            fixture.kg, tmp_path / "packs", "scoped", evidence_mode=evidence_mode,
            schema_version_ids=None if selection == "active" else scope,
        )

        pack = tmp_path / "packs" / manifest.pack_id
        assert manifest.included_schema_version_ids == list(scope)
        schema = json.loads((pack / "schema.json").read_text())
        assert set(schema["schemas"]) == {str(version) for version in scope}
        with sqlite3.connect(pack / "pack.sqlite") as conn:
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            # Audit all actual version columns, not just the graph helper's list.
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )]
            for table in tables:
                columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
                if "schema_version_id" in columns:
                    versions = {row[0] for row in conn.execute(
                        f'SELECT DISTINCT schema_version_id FROM "{table}"'
                    )}
                    assert versions <= set(scope), table
            for table in ("nodes", "extraction_runs", "extraction_run_receipts"):
                assert {row[0] for row in conn.execute(
                    f"SELECT DISTINCT schema_version_id FROM {table}"
                )} == set(scope), table
            for table, parent, key, parent_key in (
                ("extraction_chunks", "extraction_runs", "run_id", "id"),
                ("extraction_chunk_receipts", "extraction_run_receipts",
                 "run_receipt_id", "receipt_id"),
                ("citation_receipts", "extraction_run_receipts",
                 "run_receipt_id", "receipt_id"),
                ("grounded_review_decisions", "extraction_run_receipts",
                 "run_receipt_id", "receipt_id"),
            ):
                assert conn.execute(
                    f"SELECT COUNT(*) FROM {table} c LEFT JOIN {parent} p "
                    f"ON c.{key} = p.{parent_key} "
                    f"WHERE c.{key} IS NOT NULL AND p.{parent_key} IS NULL"
                ).fetchone()[0] == 0, table
            expected_runs = len(scope) + int(1 in scope)
            assert conn.execute("SELECT COUNT(*) FROM extraction_runs").fetchone()[0] == expected_runs
            assert conn.execute("SELECT COUNT(*) FROM extraction_chunks").fetchone()[0] == expected_runs
            assert conn.execute("SELECT COUNT(*) FROM extraction_run_receipts").fetchone()[0] == len(scope)
            assert conn.execute("SELECT COUNT(*) FROM extraction_chunk_receipts").fetchone()[0] == len(scope)
            expected_facts = (3 if 1 in scope else 0) + int(active in scope)
            assert conn.execute("SELECT COUNT(*) FROM citation_receipts").fetchone()[0] == expected_facts
            assert conn.execute("SELECT COUNT(*) FROM grounded_review_decisions").fetchone()[0] == expected_facts
            assert conn.execute("SELECT COUNT(*) FROM grounded_review_current").fetchone()[0] == expected_facts
        verify_pack(pack, working=fixture.root)
        assert list(fixture.store.conn.iterdump()) == source_before
    finally:
        fixture.store.close()


@pytest.mark.parametrize("evidence_mode", ["full", "excerpt"])
def test_evidence_closure_excludes_inactive_only_citation_documents(
    tmp_path: Path, evidence_mode: str,
) -> None:
    fixture = _plant_v2(tmp_path, complete_stream=False)
    try:
        active = _add_second_version(fixture)
        fixture.store.activate_schema(1)
        document, _ = fixture.store.insert_document(
            source_kind="upload", source_uri="file:///inactive-only.txt",
            title="inactive only", raw_text="UnusedGateway", content_hash="inactive",
        )
        fixture.store.insert_proposed(
            [make_entity("UnusedGateway")], [], source_doc_id=document.id,
            extractor_engine="mock",
        )
        fixture.store.activate_schema(active)
        # Refresh only this fixture's ledger after adding its source document.
        fixture.store.conn.execute(
            "UPDATE v2_migration_ledger SET source_fingerprint = ?",
            (compute_source_fingerprint(fixture.store.conn),),
        )
        fixture.store.conn.commit()

        manifest = build_pack(
            fixture.kg, tmp_path / "packs", "scope-docs", evidence_mode=evidence_mode,
        )

        pack = tmp_path / "packs" / manifest.pack_id
        payload = json.loads((pack / "manifest.json").read_text())
        assert payload["closure"]["representation"] == [fixture.representation_id]
        with sqlite3.connect(pack / "pack.sqlite") as conn:
            assert conn.execute("SELECT id FROM documents").fetchall() == [
                (fixture.representation_id,)
            ]
        verify_pack(pack, working=fixture.root)
    finally:
        fixture.store.close()
