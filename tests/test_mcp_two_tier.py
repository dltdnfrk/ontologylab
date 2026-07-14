"""W9 two-tier MCP responses + pack:// resources.

Compact-by-default list rows, full records via get_entity/detail=true, and
stable pack://{pack_id}/... resource addresses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.mcp_server import PackSession, compact_node
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.packbuilder import build_pack


@pytest.fixture()
def pack_session(tmp_path: Path):
    """A pack with alias/property-rich nodes, loaded into a session."""
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///doc.txt",
        title="doc",
        raw_text="RateLimiter implements TokenBucketAlgorithm for throttling",
        content_hash="w9-h1",
    )
    store.insert_proposed(
        [
            ProposedEntity(
                id="n_rl",
                entity_type="Component",
                name="RateLimiter",
                aliases=["limiter", "throttle-svc", "request-governor"],
                properties={
                    "language": "python",
                    "tier": "edge",
                    "purpose": "protects downstream services",
                    "notes": (
                        "Applies a token-bucket policy per client key, "
                        "refilling at a configured rate; rejects with 429 "
                        "when the bucket is empty and emits metrics for "
                        "every throttling decision so operators can tune "
                        "capacity against observed traffic patterns."
                    ),
                },
            ),
            ProposedEntity(
                id="n_tb",
                entity_type="Technique",
                name="TokenBucketAlgorithm",
                aliases=["token bucket"],
                properties={"category": "rate control"},
            ),
        ],
        [
            ProposedRelation(
                id="e_uses",
                relation_type="uses",
                src_entity_id="n_rl",
                dst_entity_id="n_tb",
            )
        ],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.approve("n_rl")
    store.approve("n_tb")
    store.approve("e_uses")
    store.close()
    manifest = build_pack(kg, packs, name="w9-demo")
    session = PackSession(packs)
    session.load_pack(manifest.pack_id)
    yield session, manifest.pack_id
    session.close()


# ---------------------------------------------------------------------------
# Compact tier
# ---------------------------------------------------------------------------


def test_search_is_compact_by_default(pack_session):
    session, _pack_id = pack_session
    result = session.semantic_search("RateLimiter")
    assert result["detail"] is False
    row = result["results"][0]
    assert set(row) <= {
        "id", "name", "entity_type", "status", "snippet",
        "match_score", "source_document_ids", "source_doc_id",
    }
    assert "properties" not in row and "aliases" not in row
    assert "aka limiter" in row["snippet"]
    # W2 invariant survives the compact tier: doc provenance + pack identity
    assert row["source_document_ids"]
    assert result["pack"]["pack_id"] is not None


def test_search_detail_true_returns_full_rows(pack_session):
    session, _pack_id = pack_session
    result = session.semantic_search("RateLimiter", detail=True)
    assert result["detail"] is True
    row = result["results"][0]
    assert row["properties"]["language"] == "python"
    assert "limiter" in row["aliases"]


def test_compact_rows_are_materially_smaller(pack_session):
    session, _pack_id = pack_session
    compact = session.semantic_search("RateLimiter")["results"]
    full = session.semantic_search("RateLimiter", detail=True)["results"]
    assert len(json.dumps(compact)) < 0.6 * len(json.dumps(full))


def test_lookup_compact_and_snippet_truncation(pack_session):
    session, _pack_id = pack_session
    result = session.entity_lookup(name="RateLimiter")
    assert result["detail"] is False
    row = result["matches"][0]
    assert row["id"] == "n_rl"
    assert len(row["snippet"]) <= 120


def test_graph_and_traverse_compact_edges(pack_session):
    session, _pack_id = pack_session
    gq = session.graph_query()
    assert gq["detail"] is False
    edge = gq["edges"][0]
    assert set(edge) == {
        "id", "relation_type", "source_id", "target_id", "status",
        "source_doc_id",
    }
    assert "properties" not in edge

    trav = session.traverse_relations(["n_rl"], max_hops=1)
    node_ids = {n["id"] for n in trav["nodes"]}
    assert node_ids == {"n_rl", "n_tb"}
    assert all("snippet" in n for n in trav["nodes"])
    hops = {n["id"]: n["hop"] for n in trav["nodes"]}
    assert hops["n_tb"] == 1  # hop survives compaction

    full = session.traverse_relations(["n_rl"], max_hops=1, detail=True)
    assert "properties" in full["edges"][0]


# ---------------------------------------------------------------------------
# Detail tier: get_entity
# ---------------------------------------------------------------------------


def test_get_entity_full_record(pack_session):
    session, pack_id = pack_session
    result = session.get_entity("n_rl")
    entity = result["entity"]
    assert entity["properties"]["tier"] == "edge"
    assert entity["citations"], "span citations must ride along"
    (edge,) = entity["edges"]
    assert edge["source_name"] == "RateLimiter"
    assert edge["target_name"] == "TokenBucketAlgorithm"
    assert result["pack"]["pack_id"] == pack_id


def test_get_entity_unknown_id(pack_session):
    session, _pack_id = pack_session
    with pytest.raises(KGStoreError):
        session.get_entity("no-such-node")


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


def test_resources_manifest_schema_entity(pack_session):
    session, pack_id = pack_session
    manifest = session.resource_manifest(pack_id)
    assert manifest["pack_id"] == pack_id and manifest["content_hash"]

    schema = session.resource_schema(pack_id)
    assert any(t["name"] == "Component" for t in schema["entity_types"])

    entity = session.resource_entity(pack_id, "n_rl")
    assert entity["name"] == "RateLimiter"
    assert entity["citations"] and entity["edges"]


def test_resources_work_without_active_pack(pack_session):
    session, pack_id = pack_session
    cold = PackSession(session.packs_dir)  # nothing loaded
    entity = cold.resource_entity(pack_id, "n_rl")
    assert entity["name"] == "RateLimiter"
    assert cold.store is None  # ephemeral open left no session state
    with pytest.raises(KGStoreError):
        cold.resource_manifest("no-such-pack")


def test_compact_node_helper_handles_bare_rows():
    row = {
        "id": "x", "name": "X", "entity_type": "Component",
        "status": "verified", "aliases": [], "properties": {},
        "source_doc_id": "d1",
    }
    out = compact_node(row)
    assert out["snippet"] == "" and out["source_doc_id"] == "d1"


def test_legacy_pack_without_w7_w8_tables_loads(pack_session, tmp_path):
    """Packs built before W7/W8 lack merge_candidates/critic_reviews and are
    immutable (read-only) — loading them must degrade, never fail."""
    import sqlite3

    session, pack_id = pack_session
    legacy_dir = tmp_path / "legacy-packs" / pack_id
    legacy_dir.mkdir(parents=True)
    src = session.packs_dir / pack_id
    for name in ("pack.sqlite", "manifest.json", "schema.json"):
        legacy_dir.joinpath(name).write_bytes((src / name).read_bytes())
    conn = sqlite3.connect(legacy_dir / "pack.sqlite")
    conn.execute("DROP TABLE merge_candidates")
    conn.execute("DROP TABLE critic_reviews")
    conn.commit()
    conn.close()

    legacy = PackSession(tmp_path / "legacy-packs")
    try:
        loaded = legacy.load_pack(pack_id)  # crashed pre-fix: counts() query
        assert loaded["counts"]["merge_candidates_pending"] == 0
        assert loaded["counts"]["nodes_verified"] == 2
        store = legacy.store
        assert store.merge_candidates_pending() == []
        assert store.pending_review(order="critic") == []  # packs: none pending
        assert legacy.semantic_search("RateLimiter")["count"] >= 1
    finally:
        legacy.close()


# ---------------------------------------------------------------------------
# FastMCP wiring (tool count, schemas, resource templates)
# ---------------------------------------------------------------------------


def test_fastmcp_exposes_two_tier_surface(pack_session):
    pytest.importorskip("mcp")
    import asyncio

    from ontologylab.mcp_server import build_mcp_app

    session, _pack_id = pack_session
    app = build_mcp_app(session)
    tools = {t.name: t for t in asyncio.run(app.list_tools())}
    assert "get_entity" in tools
    assert "get_communities" in tools
    assert len(tools) == 10  # 8 original + get_entity + get_communities
    for name in ("semantic_search", "entity_lookup", "graph_query",
                 "traverse_relations"):
        assert "detail" in tools[name].inputSchema["properties"], name
    assert "COMPACT" in tools["semantic_search"].description

    templates = asyncio.run(app.list_resource_templates())
    uris = {str(t.uriTemplate) for t in templates}
    assert uris == {
        "pack://{pack_id}/manifest",
        "pack://{pack_id}/schema",
        "pack://{pack_id}/entity/{entity_id}",
    }
