"""Carry-forward preserves source truth and never grants target approval."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

import pytest

import ontologylab.carry_forward as module
from ontologylab.carry_forward import CarryForwardError, carry_forward
from ontologylab.kgstore import KGStore
from ontologylab.kgstore_base import EDGE_POLARITY_SQL, SchemaValidationError, UnknownQualifierError
from ontologylab.packbuilder import build_pack
from tests.fixtures.carry_forward.build_v1_fixture import build_fixture


@pytest.fixture
def fixture_store(tmp_path):
    source, target = build_fixture(tmp_path)
    with KGStore.open(tmp_path / "kg.sqlite") as store:
        yield store, source, target


def snapshot(store):
    return list(store.conn.iterdump())


def cli(path, source, target, *extra):
    return subprocess.run(
        [sys.executable, "-m", "ontologylab.main", "carry-forward",
         "--from-schema", str(source), "--to-schema", str(target),
         "--data-dir", str(path), *extra],
        capture_output=True, text=True, timeout=30,
    )


def test_only_verified_current_carry_and_sources_are_unchanged(fixture_store):
    store, source, target = fixture_store
    before = {
        table: [tuple(r) for r in store.conn.execute(f"SELECT * FROM {table}")]
        for table in ("nodes", "edges", "citations", "node_aliases")
    }
    assert store.conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 5
    assert store.conn.execute("SELECT count(*) FROM edges WHERE status='proposed'").fetchone()[0] == 24
    assert store.conn.execute("SELECT count(*) FROM nodes WHERE status='rejected'").fetchone()[0] == 1
    assert store.conn.execute("SELECT count(*) FROM edges WHERE invalidated_ts IS NOT NULL").fetchone()[0] == 3

    result = carry_forward(store, source, target, operator="operator-a")

    assert (result.nodes, result.edges) == (73, 106)
    assert not result.dry_run
    for table in ("nodes", "edges"):
        old = [tuple(r) for r in store.conn.execute(
            f"SELECT * FROM {table} WHERE schema_version_id=?", (source,),
        )]
        assert old == before[table]
        rows = store.conn.execute(
            f"SELECT * FROM {table} WHERE schema_version_id=?", (target,),
        ).fetchall()
        assert {r["status"] for r in rows} == {"proposed"}
        assert all(r["verified_by"] is None and r["verified_ts"] is None for r in rows)
    for table in ("citations", "node_aliases"):
        assert all(row in [tuple(r) for r in store.conn.execute(f"SELECT * FROM {table}")]
                   for row in before[table])
    assert store.conn.execute("SELECT count(*) FROM carry_forward").fetchone()[0] == 179
    assert {r[0] for r in store.conn.execute("SELECT operator FROM carry_forward")} == {"operator-a"}
    assert {r[0] for r in store.conn.execute(
        f"SELECT {EDGE_POLARITY_SQL} FROM edges WHERE schema_version_id=?", (target,),
    )} == {""}
    event = store.conn.execute(
        "SELECT payload_json FROM provenance_outbox WHERE event_id=?", (result.event_id,),
    ).fetchone()
    assert json.loads(event[0])["nodes"] == 73
    assert json.loads(event[0])["edges"] == 106


def test_copies_stream_origin_aliases_citations_and_normalizes(fixture_store):
    store, source, target = fixture_store
    store.conn.execute("UPDATE nodes SET origin='inferred', decode_params=' {\"temperature\":0} '")
    store.conn.execute("UPDATE edges SET origin='curated', extractor_model=NULL")
    store.conn.commit()

    carry_forward(store, source, target)

    for entry in store.conn.execute("SELECT * FROM carry_forward"):
        table = "nodes" if entry["kind"] == "node" else "edges"
        old = store.conn.execute(f"SELECT * FROM {table} WHERE id=?", (entry["from_id"],)).fetchone()
        new = store.conn.execute(f"SELECT * FROM {table} WHERE id=?", (entry["to_id"],)).fetchone()
        for column in ("extractor_engine", "extractor_model", "prompt_version",
                       "decode_params", "origin", "source_doc_id", "source_span"):
            assert new[column] == old[column]
        assert new["review_note"] == (
            f"carried from {old['id']}, verified by {old['verified_by']} at {old['verified_ts']}"
        )
        copies = []
        for item_id in (old["id"], new["id"]):
            copies.append([tuple(r) for r in store.conn.execute(
                "SELECT source_doc_id, source_span, created_ts, extractor_engine, "
                "extractor_model, prompt_version, decode_params FROM citations "
                "WHERE kind=? AND item_id=? ORDER BY rowid", (entry["kind"], item_id),
            )])
        assert copies[0] == copies[1]
        if entry["kind"] == "node":
            aliases = [
                [tuple(r) for r in store.conn.execute(
                    "SELECT normalized_alias, surface FROM node_aliases WHERE node_id=? "
                    "ORDER BY normalized_alias", (item_id,),
                )] for item_id in (old["id"], new["id"])
            ]
            assert aliases[0] == aliases[1]
    props = json.loads(store.conn.execute(
        "SELECT properties_json FROM nodes WHERE schema_version_id=? AND entity_type='DoseRate'",
        (target,),
    ).fetchone()[0])
    assert props["measurement"]["value"] == 0.25
    assert props["measurement"]["unit"] == "kg/ha"


def test_second_run_writes_nothing(fixture_store):
    store, source, target = fixture_store
    carry_forward(store, source, target)
    before = snapshot(store)

    result = carry_forward(store, source, target)

    assert (result.nodes, result.edges, result.skipped_nodes, result.skipped_edges) == (0, 0, 73, 106)
    assert result.event_id is None
    assert snapshot(store) == before


def test_carries_platform_raw_qualifiers_without_reinterpreting_source(fixture_store):
    store, source, target = fixture_store
    properties = json.dumps({"raw_qualifiers": {"study_context": "field experiment"}})
    store.conn.execute(
        "UPDATE edges SET properties_json=?, qualifiers_json=?, qualifiers_key=? "
        "WHERE id='v1-edge-105'",
        (properties, '{"study_context":"field_trial"}', '{"study_context":"field_trial"}'),
    )
    store.conn.commit()

    carry_forward(store, source, target)

    copied = store.conn.execute(
        "SELECT e.properties_json, e.qualifiers_json FROM edges e "
        "JOIN carry_forward c ON c.to_id=e.id WHERE c.from_id='v1-edge-105'"
    ).fetchone()
    assert json.loads(copied[0]) == json.loads(properties)
    assert json.loads(copied[1]) == {"study_context": "field_trial"}


@pytest.mark.parametrize("sql", [
    "UPDATE nodes SET properties_json='{\"value\":17}' WHERE entity_type='DoseRate'",
    "UPDATE edges SET relation_type='unknown' WHERE id='v1-edge-105'",
    "UPDATE edges SET relation_type='infects' WHERE id='v1-edge-105'",
    "UPDATE edges SET qualifiers_json='{\"evidence_strength\":\"invalid\"}' WHERE id='v1-edge-105'",
])
def test_target_validation_refuses_everything(fixture_store, sql):
    store, source, target = fixture_store
    store.conn.execute(sql)
    store.conn.commit()
    before = snapshot(store)

    with pytest.raises(SchemaValidationError):
        carry_forward(store, source, target)

    assert snapshot(store) == before


@pytest.mark.parametrize("dry_run", [False, True])
def test_unknown_qualifier_raises_typed_refusal_and_rolls_back(fixture_store, dry_run):
    store, source, target = fixture_store
    store.conn.execute(
        "UPDATE edges SET qualifiers_json=? WHERE id='v1-edge-105'",
        (json.dumps({"invented_scope": "adult"}),),
    )
    store.conn.commit()
    before = snapshot(store)

    with pytest.raises(UnknownQualifierError) as caught:
        carry_forward(store, source, target, dry_run=dry_run)

    assert caught.value.qualifier == "invented_scope"
    assert caught.value.relation_type == "controls"
    assert caught.value.schema_version_id == target
    assert caught.value.__traceback__ is not None
    assert not store.conn.in_transaction
    assert store._tx_depth == 0
    assert snapshot(store) == before


def test_edge_with_rejected_endpoint_is_refused(fixture_store):
    store, source, target = fixture_store
    store.conn.execute("UPDATE edges SET dst_node_id='v1-rejected' WHERE id='v1-edge-105'")
    store.conn.commit()
    before = snapshot(store)

    with pytest.raises(CarryForwardError, match="endpoint v1-rejected"):
        carry_forward(store, source, target)

    assert snapshot(store) == before


def test_approval_and_active_only_pack(fixture_store, tmp_path):
    store, source, target = fixture_store
    carry_forward(store, source, target)
    expected = {"nodes": set(), "edges": set()}
    for kind, table in (("node", "nodes"), ("edge", "edges")):
        for entry in store.conn.execute("SELECT * FROM carry_forward WHERE kind=?", (kind,)).fetchall():
            assert store.citations(kind, entry["to_id"])
            store.approve(entry["to_id"], by="target-reviewer")
            expected[table].add(entry["to_id"])

    manifest = build_pack(
        store.db_path, tmp_path / "packs", "carried",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="synthetic carry fixture has no extraction runs",
    )

    assert manifest.included_schema_version_ids == [target]
    with sqlite3.connect(tmp_path / "packs" / manifest.pack_id / "pack.sqlite") as pack:
        for table, ids in expected.items():
            assert {r[0] for r in pack.execute(f"SELECT id FROM {table}")} == ids
            assert {r[0] for r in pack.execute(f"SELECT schema_version_id FROM {table}")} == {target}


@pytest.mark.parametrize("sql", [
    "UPDATE nodes SET name='edited' WHERE id='v1-node-000'",
    "UPDATE edges SET invalidated_ts=1 WHERE id='v1-edge-000'",
    "UPDATE citations SET source_span=NULL WHERE item_id='v1-edge-000'",
    "UPDATE node_aliases SET surface='edited' WHERE node_id='v1-node-000'",
])
def test_stale_sources_are_reported_not_recarried(fixture_store, sql):
    store, source, target = fixture_store
    carry_forward(store, source, target)
    store.conn.execute(sql)
    store.conn.commit()
    before = snapshot(store)

    with pytest.raises(CarryForwardError, match="field_hash"):
        carry_forward(store, source, target)

    assert snapshot(store) == before


@pytest.mark.parametrize("failure", [KeyboardInterrupt, sqlite3.OperationalError])
def test_interruption_rolls_back_rows_ledger_and_provenance(fixture_store, monkeypatch, failure):
    store, source, target = fixture_store
    before = snapshot(store)

    def interrupt():
        assert store.conn.execute("SELECT count(*) FROM carry_forward").fetchone()[0] == 179
        raise failure("interrupted before audit write")

    with monkeypatch.context() as patch:
        patch.setattr(module.uuid, "uuid4", interrupt)
        with pytest.raises(failure):
            carry_forward(store, source, target)

    assert snapshot(store) == before
    resumed = carry_forward(store, source, target)
    assert (resumed.nodes, resumed.edges) == (73, 106)


@pytest.mark.parametrize("source_id,target_id", [(99999, 3), (2, 99999), (2, 2)])
def test_cli_malformed_input_has_no_success_output(fixture_store, tmp_path, source_id, target_id):
    store, _, _ = fixture_store
    before = snapshot(store)

    result = cli(tmp_path, source_id, target_id)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr
    assert snapshot(store) == before


def test_cli_preview_then_carry_then_rerun(fixture_store, tmp_path):
    store, source, target = fixture_store
    before = snapshot(store)
    result = cli(tmp_path, source, target, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "nodes": 73, "edges": 106, "skipped_nodes": 0, "skipped_edges": 0,
        "dry_run": True, "event_id": None,
    }
    assert snapshot(store) == before
    for expected in ((73, 106), (0, 0)):
        result = cli(tmp_path, source, target, "--operator", "cli-reviewer")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert (payload["nodes"], payload["edges"]) == expected
        assert payload["dry_run"] is False


def test_cli_stale_source_refuses_without_startup_rekey(fixture_store, tmp_path):
    store, source, target = fixture_store
    carry_forward(store, source, target)
    store.conn.execute("UPDATE nodes SET name='edited after carry' WHERE id='v1-node-000'")
    store.conn.commit()
    before = snapshot(store)

    result = cli(tmp_path, source, target)

    assert result.returncode == 1
    assert not result.stdout
    assert "field_hash" in result.stderr
    assert snapshot(store) == before
