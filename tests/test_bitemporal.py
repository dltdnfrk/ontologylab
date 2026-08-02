"""W13 bitemporal edges: invalidation instead of deletion, history preserved."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.packbuilder import build_pack
from tests.conftest import insert, make_entity, make_relation


def _seed_verified_edge(store, doc):
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    insert(store, doc, [gateway, limiter], [make_relation(gateway, limiter)])
    for name in ("ApiGateway", "RateLimiter"):
        node_id = store.conn.execute(
            "SELECT id FROM nodes WHERE name = ?", (name,)
        ).fetchone()["id"]
        store.approve(node_id, by="tester")
    edge_id = store.conn.execute("SELECT id FROM edges").fetchone()["id"]
    store.approve(edge_id, by="tester")
    return edge_id


def test_new_edges_carry_valid_from(store, doc):
    edge_id = _seed_verified_edge(store, doc)
    row = store.conn.execute(
        "SELECT valid_from, created_ts, invalidated_ts FROM edges WHERE id = ?",
        (edge_id,),
    ).fetchone()
    assert row["valid_from"] == row["created_ts"]
    assert row["invalidated_ts"] is None


def test_invalidate_excludes_from_current_truth(store, doc):
    edge_id = _seed_verified_edge(store, doc)
    node_ids = [r["id"] for r in store.conn.execute("SELECT id FROM nodes")]

    report = store.invalidate_edge(edge_id, by="tester", reason="superseded")
    assert report["invalidated_by"] == "tester"

    _nodes, edges = store.verified_subgraph()
    assert edges == []
    assert store.graph_query()["edges"] == []
    assert store.traverse_relations(node_ids, max_hops=1)["edges"] == []
    assert store.find_path(node_ids[0], node_ids[1])["found"] is False
    # ... but the row itself is preserved with full audit fields
    row = store.conn.execute(
        "SELECT * FROM edges WHERE id = ?", (edge_id,)
    ).fetchone()
    assert row["status"] == "verified"
    assert row["invalidation_reason"] == "superseded"


def test_invalidate_guards(store, doc):
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    insert(store, doc, [gateway, limiter], [make_relation(gateway, limiter)])
    edge_id = store.conn.execute("SELECT id FROM edges").fetchone()["id"]
    node_id = store.conn.execute("SELECT id FROM nodes").fetchone()["id"]

    with pytest.raises(KGStoreError, match="only verified"):
        store.invalidate_edge(edge_id, by="tester")  # still proposed
    with pytest.raises(KGStoreError, match="edges only"):
        store.invalidate_edge(node_id, by="tester")

    verified_edge = _seed_verified_edge_from_existing(store, edge_id)
    store.invalidate_edge(verified_edge, by="tester")
    with pytest.raises(KGStoreError, match="already invalidated"):
        store.invalidate_edge(verified_edge, by="tester")


def _seed_verified_edge_from_existing(store, edge_id):
    edge = store.conn.execute(
        "SELECT * FROM edges WHERE id = ?", (edge_id,)
    ).fetchone()
    for endpoint in (edge["src_node_id"], edge["dst_node_id"]):
        store.approve(endpoint, by="tester")
    store.approve(edge_id, by="tester")
    return edge_id


def test_reassertion_coexists_with_invalidated_history(store, doc):
    edge_id = _seed_verified_edge(store, doc)
    store.invalidate_edge(edge_id, by="tester", reason="contradicted")

    # Re-extracting the same triple: NOT deduped against the invalidated
    # row — it arrives as a fresh proposed edge (history coexists).
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    stats = insert(store, doc, [gateway, limiter],
                   [make_relation(gateway, limiter)])
    assert stats["edges_new"] == 1 and stats["edges_merged"] == 0

    rows = store.conn.execute(
        "SELECT id, status, invalidated_ts FROM edges ORDER BY created_ts"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["invalidated_ts"] is not None
    assert rows[1]["status"] == "proposed" and rows[1]["invalidated_ts"] is None

    # the new assertion can be verified and becomes current truth
    store.approve(rows[1]["id"], by="tester")
    _nodes, edges = store.verified_subgraph()
    assert [e["id"] for e in edges] == [rows[1]["id"]]


def test_pack_excludes_invalidated_edges(store, doc, tmp_path):
    edge_id = _seed_verified_edge(store, doc)
    store.invalidate_edge(edge_id, by="tester")
    manifest = build_pack(
        store.db_path, tmp_path / "packs", "bitemp",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="synthetic bitemporal fixture",
    )
    assert manifest.counts["edges_verified"] == 0
    assert manifest.counts["nodes_verified"] == 2


def test_migration_adds_columns_and_fixes_dedup_index(tmp_path):
    db = tmp_path / "kg.sqlite"
    store = KGStore.open(db)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///x", title="x",
        raw_text="ApiGateway RateLimiter", content_hash="sha256:mig",
    )
    edge_id = _seed_verified_edge(store, doc)
    store.close()

    # Simulate a pre-W13 database: drop the columns and restore the old
    # index (index first — its predicate references invalidated_ts).
    conn = sqlite3.connect(db)
    conn.execute("DROP INDEX IF EXISTS idx_edges_dedup")
    for column in ("valid_from", "invalidated_ts", "invalidated_by",
                   "invalidation_reason"):
        conn.execute(f"ALTER TABLE edges DROP COLUMN {column}")
    conn.execute(
        "CREATE UNIQUE INDEX idx_edges_dedup ON edges "
        "(schema_version_id, relation_type, src_node_id, dst_node_id) "
        "WHERE status IN ('proposed','verified')"
    )
    conn.commit()
    conn.close()

    store = KGStore.open(db)  # migration runs here
    try:
        row = store.conn.execute(
            "SELECT valid_from, created_ts, invalidated_ts FROM edges "
            "WHERE id = ?", (edge_id,),
        ).fetchone()
        assert row["valid_from"] == row["created_ts"]  # backfilled
        index_sql = store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_edges_dedup'"
        ).fetchone()["sql"]
        assert "invalidated_ts IS NULL" in index_sql
        # and the migrated DB supports the full invalidate/reassert cycle
        store.invalidate_edge(edge_id, by="tester")
        assert store.verified_subgraph()[1] == []
    finally:
        store.close()


def test_legacy_pack_without_bitemporal_columns_still_serves(store, doc, tmp_path):
    """Packs built before W13 lack the columns; read paths must not break."""
    edge_id = _seed_verified_edge(store, doc)
    manifest = build_pack(
        store.db_path, tmp_path / "packs", "legacy",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="synthetic legacy-pack fixture",
    )
    pack_sqlite = tmp_path / "packs" / manifest.pack_id / "pack.sqlite"

    conn = sqlite3.connect(pack_sqlite)
    conn.execute("DROP INDEX IF EXISTS idx_edges_dedup")
    for column in ("valid_from", "invalidated_ts", "invalidated_by",
                   "invalidation_reason"):
        conn.execute(f"ALTER TABLE edges DROP COLUMN {column}")
    conn.commit()
    conn.close()

    pack = KGStore.open(pack_sqlite, read_only=True)
    try:
        nodes, edges = pack.verified_subgraph()
        assert len(edges) == 1 and edges[0]["id"] == edge_id
        assert edges[0]["valid_from"] is None  # absent column -> None, no crash
        assert pack.graph_query()["edges"]
        node_ids = [n["id"] for n in nodes]
        assert pack.find_path(node_ids[0], node_ids[1])["found"] is True
    finally:
        pack.close()


def test_cli_invalidate(store, doc, capsys):
    from ontologylab.main import main

    edge_id = _seed_verified_edge(store, doc)
    with pytest.raises(SystemExit) as exc:
        main(["invalidate", "--id", edge_id, "--reason", "stale",
              "--data-dir", str(store.db_path.parent)])
    assert exc.value.code == 0
    assert "invalidated edge" in capsys.readouterr().out


@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    with TestClient(app) as tc:
        yield tc


def test_invalidate_api(client, tmp_path):
    from ontologylab.paths import kg_db_path

    store = KGStore.open(kg_db_path(tmp_path / "data"))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///x", title="x",
        raw_text="ApiGateway RateLimiter", content_hash="sha256:x",
    )
    edge_id = _seed_verified_edge(store, doc)
    store.close()

    res = client.post(f"/api/edges/{edge_id}/invalidate",
                      json={"id": edge_id, "note": "superseded"})
    assert res.status_code == 200 and res.json()["ok"] is True
    # double invalidation is a client error
    res = client.post(f"/api/edges/{edge_id}/invalidate", json={"id": edge_id})
    assert res.status_code == 400
    assert client.post("/api/edges/nope/invalidate",
                       json={"id": "nope"}).status_code == 404
