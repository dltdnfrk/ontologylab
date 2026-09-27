"""Pass attribution through real extraction, migration, packs, and export."""

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

import pytest

from ontologylab.carry_forward import carry_forward
from ontologylab.claims import claims_for
from ontologylab.kgstore import KGStore
from ontologylab.kgstore_base import _SCHEMA, KGStoreError
from ontologylab.mcp_server import PackSession
from ontologylab.packbuilder import build_pack
from ontologylab.schemas import preset
from tests.factories import make_entity, make_relation
from tests.test_statement_completion import NULL, TEXT, ScriptedEngine, drive, payload
from tests.test_statement_qualifier_validation import qualified_store


def test_first_and_completion_only_statements_and_nodes(qualified_store, tmp_path):
    # Given: an independent source-grounded statement only in completion.
    sentence = NULL.replace("Agent Cedar", "Agent Birch")
    text = TEXT + " " + sentence
    completion = payload(text, null=True)
    entity = completion["entities"][0]
    entity["name"] = "Agent Birch"
    entity["source_span"] = {
        "start": text.index("Agent Birch"), "end": text.index("Agent Birch") + 11,
    }
    completion["relations"][0]["source_span"] = {
        "start": text.index(sentence), "end": len(text),
    }
    engine = ScriptedEngine([payload(text), completion])
    # When
    outcome, records, status = drive(qualified_store, tmp_path, engine, text=text)
    # Then: status and request accounting still describe two real requests.
    assert outcome == "" and not outcome.chunk_failed
    assert status["engine_calls"] == len(engine.prompts) == 2
    assert sum(r["payload"].get("engine_call", False) for r in records) == 2
    expected_nodes = {
        "Agent Cedar": ["first"], "Agent Birch": ["completion"],
        "Beetle delta": ["first", "completion"],
    }
    for node in qualified_store.conn.execute("SELECT * FROM nodes"):
        assert node["status"] == "proposed"
        assert qualified_store.citations("node", node["id"])[0]["extraction_passes"] == (
            expected_nodes[node["name"]]
        )
        assert qualified_store.provenance("node", node["id"])["extraction"]["passes"] == (
            expected_nodes[node["name"]]
        )
    edges = qualified_store.conn.execute("SELECT * FROM edges").fetchall()
    assert len(edges) == 2
    for edge in edges:
        expected = ["completion"] if json.loads(edge["qualifiers_json"])["polarity"] == "no_effect" else ["first"]
        assert edge["status"] == "proposed" and edge["confidence"] == 0.7
        citations = qualified_store.citations("edge", edge["id"])
        assert len(citations) == 1 and citations[0]["extraction_passes"] == expected
        claim = claims_for(
            qualified_store.conn, subject_id=edge["src_node_id"], include_proposed=True,
        )["claims"][0]
        assert claim["extraction_passes"] == expected
        assert claim["provenance"] == "extracted"
    assert qualified_store.conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == 5


def test_duplicate_passes_union_without_changing_identity_or_counts(qualified_store, tmp_path):
    # Given: a lower-confidence completion duplicate must not rewrite the first.
    completion = payload()
    completion["relations"][0]["confidence"] = 0.1
    # When
    _, records, status = drive(
        qualified_store, tmp_path, ScriptedEngine([payload(), completion]),
    )
    # Then: both passes survive the existing duplicate filter, not extra facts.
    edges = qualified_store.conn.execute("SELECT * FROM edges").fetchall()
    assert len(edges) == 1 and edges[0]["confidence"] == 0.7
    assert edges[0]["status"] == "proposed"
    citations = qualified_store.conn.execute("SELECT * FROM citations").fetchall()
    assert len(citations) == 3
    assert all(json.loads(c["extraction_passes"]) == ["first", "completion"] for c in citations)
    assert sum(r["step"] == "extract.completion_duplicate" for r in records) == 1
    assert status["engine_calls"] == sum(r["payload"].get("engine_call", False) for r in records) == 2
    assert qualified_store.provenance("edge", edges[0]["id"])["extraction"]["passes"] == [
        "first", "completion",
    ]


def test_store_merge_keeps_each_citation_pass_and_unions_claim(qualified_store, tmp_path):
    # Given: the same null statement was already extracted by a first-only run.
    drive(qualified_store, tmp_path / "first", ScriptedEngine([payload(null=True)]), enabled=False)
    edge = qualified_store.conn.execute("SELECT * FROM edges").fetchone()
    # When: another run emits it only from completion.
    drive(qualified_store, tmp_path / "second", ScriptedEngine([payload(), payload(null=True)]))
    # Then: identity and first metadata are unchanged, both observations are read.
    after = qualified_store.conn.execute("SELECT * FROM edges WHERE id=?", (edge["id"],)).fetchone()
    assert tuple(after) == tuple(edge)
    citations = qualified_store.citations("edge", edge["id"])
    assert [c["extraction_passes"] for c in citations] == [["first"], ["completion"]]
    claim = claims_for(
        qualified_store.conn, subject_id=edge["src_node_id"],
        polarity="no_effect", include_proposed=True,
    )["claims"][0]
    assert claim["extraction_passes"] == ["first", "completion"]


def test_legacy_store_and_readonly_pack_keep_rows_and_unknown_pass(qualified_store, tmp_path):
    # Given: pre-pass schema with genuine populated node, edge and citation rows.
    drive(qualified_store, tmp_path, ScriptedEngine([payload()]), enabled=False)
    legacy = tmp_path / "legacy.sqlite"
    tables = (
        "schema_version", "entity_type", "relation_type", "documents",
        "nodes", "edges", "citations", "node_aliases",
    )
    before = {}
    with closing(sqlite3.connect(legacy)) as conn:
        conn.executescript(re.sub(r",\s*extraction_passes TEXT", "", _SCHEMA))
        conn.execute("ALTER TABLE documents ADD COLUMN work_id TEXT")
        conn.execute("ALTER TABLE documents ADD COLUMN representation_state TEXT NOT NULL DEFAULT 'ready'")
        assert "extraction_passes" not in {r[1] for r in conn.execute("PRAGMA table_info(citations)")}
        for table in tables:
            columns = ",".join(r[1] for r in conn.execute(f"PRAGMA table_info({table})"))
            rows = [tuple(r) for r in qualified_store.conn.execute(f"SELECT {columns} FROM {table}")]
            before[table] = columns, rows
            if rows:
                conn.executemany(
                    f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in rows[0])})",
                    rows,
                )
        conn.commit()
    edge = qualified_store.conn.execute("SELECT * FROM edges").fetchone()
    # When/Then: old immutable readers degrade, writable open adds only metadata.
    for read_only in (True, False, False):
        with closing(KGStore.open(legacy, read_only=read_only)) as store:
            for table, (columns, rows) in before.items():
                assert [tuple(r) for r in store.conn.execute(f"SELECT {columns} FROM {table}")] == rows
            assert store.citations("edge", edge["id"])[0]["extraction_passes"] is None
            assert claims_for(
                store.conn, subject_id=edge["src_node_id"], include_proposed=True,
            )["claims"][0]["extraction_passes"] is None
            assert store.provenance("edge", edge["id"])["extraction"]["passes"] is None


def test_pass_metadata_survives_pack_mcp_and_export(qualified_store, tmp_path):
    # Given: offline extraction, approved explicitly by the fixture's operator.
    drive(qualified_store, tmp_path, ScriptedEngine([payload(), payload(null=True)]))
    for table in ("nodes", "edges"):
        for row in qualified_store.conn.execute(f"SELECT id FROM {table}").fetchall():
            qualified_store.approve(row["id"])
    subject = qualified_store.conn.execute("SELECT src_node_id FROM edges LIMIT 1").fetchone()[0]
    expected = {"supports": ["first"], "no_effect": ["completion"]}
    # When: publish to the real immutable pack and query the consumer surface.
    manifest = build_pack(qualified_store.db_path, tmp_path / "packs", name="pass-provenance")
    with closing(PackSession(tmp_path / "packs")) as session:
        session.load_pack(manifest.pack_id)
        claims = session.claims_for(subject_id=subject)["claims"]
    # Then
    assert {c["polarity"]: c["extraction_passes"] for c in claims} == expected
    qualified_store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    result = subprocess.run(
        [sys.executable, "evidence/polarity6_export.py", "export", str(qualified_store.db_path.parent)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    exported = json.loads(result.stdout)["runs"][0]["tables"]["citations"]
    assert exported == [
        dict(row) for row in qualified_store.conn.execute("SELECT * FROM citations ORDER BY rowid")
    ]
    assert all(row["extraction_passes"] is not None for row in exported)


def test_carry_forward_preserves_citation_pass_sets(qualified_store, doc):
    # Given: carry-forward accepts only empty-polarity source facts.
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    relation = make_relation(a, b, "controls")
    qualified_store.insert_proposed(
        [a, b], [relation], source_doc_id=doc.id, extractor_engine="scripted",
        proposal_passes={a.id: {"first"}, b.id: {"completion"}, relation.id: {"first", "completion"}},
    )
    for item in (a, b, relation):
        qualified_store.approve(item.id)
    source = qualified_store.active_schema_version()["id"]
    qualified_store.install_schema(**preset("agrochem-v2"))
    target = qualified_store.active_schema_version()["id"]
    # When
    carried = carry_forward(qualified_store, source, target)
    # Then
    assert (carried.nodes, carried.edges) == (2, 1)
    for entry in qualified_store.conn.execute("SELECT * FROM carry_forward"):
        assert qualified_store.citations(entry["kind"], entry["from_id"]) == (
            qualified_store.citations(entry["kind"], entry["to_id"])
        )


@pytest.mark.parametrize("passes", [set(), {"other"}])
def test_invalid_pass_map_is_refused_before_writes(qualified_store, doc, passes):
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    relation = make_relation(a, b, "controls")
    before = qualified_store.conn.total_changes
    with pytest.raises(KGStoreError, match="invalid extraction passes"):
        qualified_store.insert_proposed(
            [a, b], [relation], source_doc_id=doc.id, extractor_engine="scripted",
            proposal_passes={a.id: passes, b.id: {"first"}, relation.id: {"first"}},
        )
    assert qualified_store.conn.total_changes == before
