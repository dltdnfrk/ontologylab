"""W12 communities: build-time detection + summaries, global query surface."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ontologylab.communities import (
    build_communities,
    build_summary_prompt,
    detect_communities,
    extractive_summary,
    llm_summarizer,
)
from ontologylab.engines import MockEngine
from ontologylab.kgstore import KGStore, UnknownItem
from ontologylab.mcp_server import PackSession
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.packbuilder import build_pack


# ---------------------------------------------------------------------------
# Detection (pure)
# ---------------------------------------------------------------------------


def test_detect_two_clusters_and_singleton():
    nodes = ["a1", "a2", "a3", "b1", "b2", "lone"]
    edges = [("a1", "a2"), ("a2", "a3"), ("a1", "a3"), ("b1", "b2")]
    communities = detect_communities(nodes, edges)
    as_sets = [set(c) for c in communities]
    assert {"a1", "a2", "a3"} in as_sets
    assert {"b1", "b2"} in as_sets
    assert {"lone"} in as_sets
    # largest first, then smallest member id
    assert communities[0] == ["a1", "a2", "a3"]


def test_detect_is_deterministic():
    nodes = [f"n{i}" for i in range(30)]
    edges = [(f"n{i}", f"n{(i + 1) % 10}") for i in range(10)]
    edges += [(f"n{i}", f"n{i + 1}") for i in range(15, 25)]
    first = detect_communities(nodes, edges)
    for _ in range(3):
        assert detect_communities(nodes, edges) == first


def test_extractive_summary_mentions_anchors_and_relations():
    text = extractive_summary(["RateLimiter", "ApiGateway"], {"uses": 2})
    assert "RateLimiter" in text and "uses ×2" in text


def test_build_communities_orders_members_by_degree():
    nodes = [{"id": i, "name": i.upper()} for i in ("hub", "x", "y")]
    edges = [
        {"source_id": "hub", "target_id": "x", "relation_type": "uses"},
        {"source_id": "hub", "target_id": "y", "relation_type": "uses"},
    ]
    (row,) = build_communities(nodes, edges)
    assert row["top_members"][0] == "HUB"
    assert row["summary_method"] == "extractive"
    assert row["id"] == "community-000"


def test_build_communities_llm_summarizer_and_failure_fallback():
    nodes = [{"id": "a", "name": "RateLimiter"}, {"id": "b", "name": "Cache"}]
    edges = [{"source_id": "a", "target_id": "b", "relation_type": "uses"}]

    (row,) = build_communities(
        nodes, edges,
        summarizer=llm_summarizer(MockEngine()),
        summary_method="llm:mock",
    )
    assert row["summary"].startswith("Mock summary:")
    # degree tie: names sort alphabetically, so "Cache" anchors the summary
    assert "Cache" in row["summary"]
    assert row["summary_method"] == "llm:mock"

    def broken(_names, _counts):
        raise RuntimeError("boom")

    (row,) = build_communities(
        nodes, edges, summarizer=broken, summary_method="llm:broken"
    )
    assert row["summary_method"] == "extractive"  # failed open


def test_summary_prompt_embeds_context():
    prompt = build_summary_prompt(["A", "B"], {"uses": 1})
    assert "<community-summary>" in prompt and '"members": ["A", "B"]' in prompt


# ---------------------------------------------------------------------------
# Pack build + MCP surface
# ---------------------------------------------------------------------------


@pytest.fixture()
def community_pack(tmp_path: Path):
    """Pack with two clusters: (gateway-limiter-cache) and (parser-lexer)."""
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///doc.txt", title="doc",
        raw_text="cluster text", content_hash="w12-h1",
    )
    ents = {
        name: ProposedEntity(id=f"n_{name}", entity_type="Component", name=name)
        for name in ("Gateway", "Limiter", "Cache", "Parser", "Lexer")
    }
    rels = [
        ProposedRelation(id="e1", relation_type="uses",
                         src_entity_id="n_Gateway", dst_entity_id="n_Limiter"),
        ProposedRelation(id="e2", relation_type="uses",
                         src_entity_id="n_Limiter", dst_entity_id="n_Cache"),
        ProposedRelation(id="e3", relation_type="uses",
                         src_entity_id="n_Parser", dst_entity_id="n_Lexer"),
    ]
    store.insert_proposed(list(ents.values()), rels,
                          source_doc_id=doc.id, extractor_engine="mock")
    report = store.bulk_approve(by="tester")
    assert len(report["nodes_approved"]) == 5
    assert len(report["edges_approved"]) == 3
    store.close()
    manifest = build_pack(kg, packs, name="w12-demo")
    return packs, manifest


def test_pack_build_writes_communities(community_pack):
    packs, manifest = community_pack
    assert manifest.counts["communities"] == 2

    store = KGStore.open(
        packs / manifest.pack_id / "pack.sqlite", read_only=True
    )
    try:
        communities = store.list_communities()
        assert [c["member_count"] for c in communities] == [3, 2]
        big = communities[0]
        assert set(big["top_members"]) <= {"Gateway", "Limiter", "Cache"}
        assert "uses ×2" in big["summary"]
        members = store.community_members(big["id"])
        assert {m["name"] for m in members} == {"Gateway", "Limiter", "Cache"}
        with pytest.raises(UnknownItem):
            store.community_members("community-999")
    finally:
        store.close()


def test_mcp_get_communities(community_pack):
    packs, manifest = community_pack
    session = PackSession(packs)
    session.load_pack(manifest.pack_id)
    try:
        result = session.get_communities()
        assert result["count"] == 2 and result["members"] == []
        assert result["pack"]["pack_id"] == manifest.pack_id

        top = result["communities"][0]
        detail = session.get_communities(community_id=top["id"])
        assert detail["count"] == 1
        assert len(detail["members"]) == 3
    finally:
        session.close()


def test_legacy_pack_without_communities_degrades(community_pack, tmp_path):
    import sqlite3

    packs, manifest = community_pack
    legacy_dir = tmp_path / "legacy" / manifest.pack_id
    legacy_dir.mkdir(parents=True)
    for name in ("pack.sqlite", "manifest.json"):
        legacy_dir.joinpath(name).write_bytes(
            (packs / manifest.pack_id / name).read_bytes()
        )
    conn = sqlite3.connect(legacy_dir / "pack.sqlite")
    conn.execute("DROP TABLE community_members")
    conn.execute("DROP TABLE communities")
    conn.commit()
    conn.close()

    session = PackSession(tmp_path / "legacy")
    session.load_pack(manifest.pack_id)
    try:
        assert session.get_communities() == {
            "communities": [], "members": [], "count": 0,
            "pack": {"pack_id": manifest.pack_id,
                     "content_hash": manifest.content_hash},
        }
    finally:
        session.close()


def test_cli_build_pack_with_mock_summaries(community_pack, tmp_path, capsys):
    from ontologylab.main import main

    packs, manifest = community_pack
    # rebuild from the same working DB with LLM (mock) summaries
    kg_dir = str((packs / "..").resolve())
    with pytest.raises(SystemExit) as exc:
        main([
            "build-pack", "--name", "w12-llm",
            "--packs-dir", str(tmp_path / "packs2"),
            "--summarize-engine", "mock",
            "--data-dir", kg_dir,
        ])
    assert exc.value.code == 0
    import json as json_mod

    pack_dirs = list((tmp_path / "packs2").iterdir())
    assert len(pack_dirs) == 1
    store = KGStore.open(pack_dirs[0] / "pack.sqlite", read_only=True)
    try:
        communities = store.list_communities()
        assert all(c["summary_method"] == "llm:mock" for c in communities)
        assert all(c["summary"].startswith("Mock summary:")
                   for c in communities)
    finally:
        store.close()
    manifest_json = json_mod.loads(
        (pack_dirs[0] / "manifest.json").read_text()
    )
    assert manifest_json["counts"]["communities"] == 2


# ---------------------------------------------------------------------------
# Dashboard API surface (/api/communities reads the working store)
# ---------------------------------------------------------------------------


def _community_client(tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    return TestClient(create_app(data_dir=tmp_path / "data",
                                 packs_dir=tmp_path / "packs"))


def _seed_working_store_community(tmp_path: Path) -> None:
    """Write two verified nodes + one community into the dashboard's working
    DB. Communities normally live only inside built packs, but the dashboard
    reads the working store, so we populate it directly here."""
    from ontologylab.paths import kg_db_path

    store = KGStore.open(kg_db_path(tmp_path / "data"))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///c.txt", title="c",
        raw_text="community text", content_hash="w12-api-h1",
    )
    ents = [
        ProposedEntity(id="n_A", entity_type="Component", name="Alpha"),
        ProposedEntity(id="n_B", entity_type="Component", name="Beta"),
    ]
    store.insert_proposed(ents, [], source_doc_id=doc.id,
                          extractor_engine="mock")
    store.bulk_approve(by="tester")
    store.write_communities([
        {
            "id": "c1",
            "members": ["n_A", "n_B"],
            "top_members": ["Alpha"],
            "summary": "Alpha and Beta cluster",
            "summary_method": "extractive",
        }
    ])
    store.close()


def test_api_communities_empty_on_working_store(tmp_path):
    client = _community_client(tmp_path)
    res = client.get("/api/communities")
    assert res.status_code == 200
    assert res.json() == {"communities": [], "count": 0}


def test_api_communities_list_detail_and_404(tmp_path):
    _seed_working_store_community(tmp_path)
    client = _community_client(tmp_path)

    listing = client.get("/api/communities")
    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 1
    community = body["communities"][0]
    assert community["id"] == "c1"
    assert community["member_count"] == 2
    assert community["summary_method"] == "extractive"

    detail = client.get(f"/api/communities/{community['id']}")
    assert detail.status_code == 200
    dbody = detail.json()
    assert dbody["community"]["id"] == "c1"
    assert {m["name"] for m in dbody["members"]} == {"Alpha", "Beta"}

    missing = client.get("/api/communities/nope")
    assert missing.status_code == 404
