"""W7 entity-merge review: scanner proposes, only a human merges/dismisses."""

from __future__ import annotations

import json

import pytest

from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.merge import scan_merge_candidates
from tests.conftest import insert, make_entity, make_relation


def _node(store: KGStore, node_id: str):
    return store.conn.execute(
        "SELECT * FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()


def _ids(store: KGStore, *names: str) -> list[str]:
    out = []
    for name in names:
        row = store.conn.execute(
            "SELECT id FROM nodes WHERE name = ?", (name,)
        ).fetchone()
        out.append(row["id"])
    return out


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def test_scan_detects_near_duplicate_names(store, doc):
    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiters"),
                        make_entity("OrderDatabase")])
    stats = scan_merge_candidates(store)
    assert stats["candidates_new"] == 1
    items = store.merge_candidates_pending()
    assert len(items) == 1
    pair = {items[0]["node_a"]["name"], items[0]["node_b"]["name"]}
    assert pair == {"RateLimiter", "RateLimiters"}
    assert any(r.startswith("name-similarity:") for r in items[0]["reasons"])


def test_scan_ignores_dissimilar_and_cross_type(store, doc):
    insert(store, doc, [
        make_entity("ApiGateway"),
        make_entity("OrderDatabase"),
        # near-identical name but different entity type: not a candidate
        make_entity("ApiGateways", entity_type="Concept"),
    ])
    stats = scan_merge_candidates(store)
    assert stats["candidates_new"] == 0
    assert store.merge_candidates_pending() == []


def test_scan_shared_alias_signal(store, doc):
    insert(store, doc, [
        make_entity("Rate Limiting Service", aliases=["throttler"]),
        make_entity("RequestThrottler", aliases=["throttler"]),
    ])
    stats = scan_merge_candidates(store)
    assert stats["candidates_new"] == 1
    items = store.merge_candidates_pending()
    assert any(r.startswith("shared-alias:") for r in items[0]["reasons"])


def test_scan_never_reproposes_dismissed_pair(store, doc):
    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiters")])
    scan_merge_candidates(store)
    candidate = store.merge_candidates_pending()[0]
    store.dismiss_merge_candidate(candidate["id"], by="tester", note="different")
    stats = scan_merge_candidates(store)
    assert stats["candidates_new"] == 0
    assert stats["candidates_existing"] == 1
    assert store.merge_candidates_pending() == []


def test_scan_embedding_cosine_signal(store, doc):
    from ontologylab.embeddings import HashingEmbedder

    insert(store, doc, [make_entity("TokenBucket"), make_entity("TokenBucketX")])
    store.embed_nodes(HashingEmbedder())
    stats = scan_merge_candidates(store, name_threshold=0.99, cosine_threshold=0.5)
    assert stats["candidates_new"] == 1
    items = store.merge_candidates_pending()
    assert any(r.startswith("embedding-cosine:") for r in items[0]["reasons"])


# ---------------------------------------------------------------------------
# merge_nodes semantics
# ---------------------------------------------------------------------------


def test_merge_unions_aliases_and_properties(store, doc):
    insert(store, doc, [
        make_entity("RateLimiter", aliases=["limiter"],
                    properties={"language": "python"}),
        make_entity("RateLimiters", aliases=["throttle-svc"],
                    properties={"language": "rust", "tier": "edge"}),
    ])
    target_id, source_id = _ids(store, "RateLimiter", "RateLimiters")
    report = store.merge_nodes(target_id, source_id, by="tester")
    assert report["target_id"] == target_id

    target = _node(store, target_id)
    aliases = json.loads(target["aliases_json"])
    assert "RateLimiters" in aliases and "throttle-svc" in aliases
    props = json.loads(target["properties_json"])
    # fill-absent only: the target's own value is never overwritten
    assert props == {"language": "python", "tier": "edge"}

    source = _node(store, source_id)
    assert source["status"] == "rejected"
    assert source["review_note"] == f"merged-into:{target_id}"


def test_merge_repoints_edges_and_citations(store, doc):
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    limiter_dup = make_entity("RateLimiterz")
    cache = make_entity("SessionCache")
    insert(store, doc, [gateway, limiter, limiter_dup, cache],
           [make_relation(gateway, limiter_dup), make_relation(limiter_dup, cache)])
    target_id, source_id = _ids(store, "RateLimiter", "RateLimiterz")

    citations_before = len(store.citations("node", target_id))
    report = store.merge_nodes(target_id, source_id, by="tester")
    assert report["edges_repointed"] == 2

    # citations of the source now belong to the target
    assert len(store.citations("node", target_id)) == citations_before + 1
    # edges now reference the target, none reference the tombstone
    live = store.conn.execute(
        "SELECT src_node_id, dst_node_id FROM edges "
        "WHERE status IN ('proposed','verified')"
    ).fetchall()
    endpoints = {e for row in live for e in (row["src_node_id"], row["dst_node_id"])}
    assert source_id not in endpoints
    assert target_id in endpoints


def test_merge_collapses_duplicate_edges(store, doc):
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    limiter_dup = make_entity("RateLimiterz")
    insert(store, doc, [gateway, limiter, limiter_dup],
           [make_relation(gateway, limiter), make_relation(gateway, limiter_dup)])
    target_id, source_id = _ids(store, "RateLimiter", "RateLimiterz")

    report = store.merge_nodes(target_id, source_id, by="tester")
    assert report["edges_deduplicated"] == 1
    live = store.conn.execute(
        "SELECT * FROM edges WHERE status IN ('proposed','verified')"
    ).fetchall()
    assert len(live) == 1
    # the surviving edge carries the collapsed edge's citation too
    assert len(store.citations("edge", live[0]["id"])) == 2


def test_merge_rejects_would_be_self_loops(store, doc):
    limiter = make_entity("RateLimiter")
    limiter_dup = make_entity("RateLimiterz")
    insert(store, doc, [limiter, limiter_dup],
           [make_relation(limiter, limiter_dup)])
    target_id, source_id = _ids(store, "RateLimiter", "RateLimiterz")

    report = store.merge_nodes(target_id, source_id, by="tester")
    assert report["edges_self_loop_rejected"] == 1
    assert store.conn.execute(
        "SELECT COUNT(*) AS n FROM edges WHERE status IN ('proposed','verified')"
    ).fetchone()["n"] == 0


def test_merge_direction_guard_and_type_guard(store, doc):
    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiters"),
                        make_entity("RateLimit", entity_type="Concept")])
    verified_id, proposed_id = _ids(store, "RateLimiter", "RateLimiters")
    concept_id = _ids(store, "RateLimit")[0]
    store.approve(verified_id, by="tester")

    with pytest.raises(KGStoreError, match="other direction"):
        store.merge_nodes(proposed_id, verified_id, by="tester")
    with pytest.raises(KGStoreError, match="entity types"):
        store.merge_nodes(concept_id, proposed_id, by="tester")
    with pytest.raises(KGStoreError, match="itself"):
        store.merge_nodes(verified_id, verified_id, by="tester")

    # merging INTO the verified node is fine, and never flips its status
    store.merge_nodes(verified_id, proposed_id, by="tester")
    assert _node(store, verified_id)["status"] == "verified"


def test_merged_source_is_never_served(store, doc):
    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiters")])
    target_id, source_id = _ids(store, "RateLimiter", "RateLimiters")
    store.approve(target_id, by="tester")
    store.merge_nodes(target_id, source_id, by="tester")

    nodes, _ = store.verified_subgraph()
    assert {n["id"] for n in nodes} == {target_id}
    # the tombstone is invisible to lookups even with include_proposed
    assert store.entity_lookup(id=source_id, include_proposed=True) == []


def test_future_mentions_resolve_to_merge_target(store, doc):
    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiterz")])
    target_id, source_id = _ids(store, "RateLimiter", "RateLimiterz")
    store.merge_nodes(target_id, source_id, by="tester")

    stats = insert(store, doc, [make_entity("RateLimiterz")])
    assert stats["nodes_merged"] == 1 and stats["nodes_new"] == 0
    assert stats["id_map"][next(iter(stats["id_map"]))] == target_id


def test_merge_marks_candidates_and_stales_others(store, doc):
    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiters"),
                        make_entity("RateLimiterz")])
    scan_merge_candidates(store)
    pending = store.merge_candidates_pending()
    assert len(pending) == 3  # all pairs among the three variants

    a_id, b_id = _ids(store, "RateLimiter", "RateLimiters")
    store.merge_nodes(a_id, b_id, by="tester")

    rows = {
        (r["node_a_id"], r["node_b_id"]): r["status"]
        for r in store.conn.execute("SELECT * FROM merge_candidates")
    }
    assert sorted(rows.values()) == ["merged", "proposed", "stale"]
    # the surviving pending pair is (RateLimiter, RateLimiterz)
    remaining = store.merge_candidates_pending()
    assert len(remaining) == 1
    names = {remaining[0]["node_a"]["name"], remaining[0]["node_b"]["name"]}
    assert names == {"RateLimiter", "RateLimiterz"}


def test_merge_clears_stale_embedding(store, doc):
    from ontologylab.embeddings import HashingEmbedder

    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiterz")])
    store.embed_nodes(HashingEmbedder())
    target_id, source_id = _ids(store, "RateLimiter", "RateLimiterz")
    store.merge_nodes(target_id, source_id, by="tester")
    target = _node(store, target_id)
    assert target["embedding"] is None and target["embedding_model"] is None


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    with TestClient(app) as tc:
        yield tc


def test_merge_api_roundtrip(client, tmp_path):
    from ontologylab.paths import kg_db_path

    store = KGStore.open(kg_db_path(tmp_path / "data"))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///x", title="x",
        raw_text="RateLimiter RateLimiters", content_hash="sha256:x",
    )
    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiters")])
    store.close()

    res = client.post("/api/merge/scan", json={})
    assert res.status_code == 200 and res.json()["candidates_new"] == 1

    res = client.get("/api/merge/candidates")
    items = res.json()["items"]
    assert len(items) == 1
    cand = items[0]

    # mismatched pair ids are refused
    res = client.post(
        f"/api/merge/candidates/{cand['id']}/merge",
        json={"target_id": cand["node_a"]["id"], "source_id": "bogus"},
    )
    assert res.status_code == 400

    res = client.post(
        f"/api/merge/candidates/{cand['id']}/merge",
        json={"target_id": cand["node_a"]["id"], "source_id": cand["node_b"]["id"]},
    )
    assert res.status_code == 200 and res.json()["ok"] is True

    # deciding the same candidate twice is a conflict
    res = client.post(
        f"/api/merge/candidates/{cand['id']}/merge",
        json={"target_id": cand["node_a"]["id"], "source_id": cand["node_b"]["id"]},
    )
    assert res.status_code == 409
    assert client.get("/api/merge/candidates").json()["count"] == 0


def test_merge_api_dismiss(client, tmp_path):
    from ontologylab.paths import kg_db_path

    store = KGStore.open(kg_db_path(tmp_path / "data"))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///x", title="x",
        raw_text="t", content_hash="sha256:x",
    )
    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiters")])
    store.close()

    client.post("/api/merge/scan", json={})
    cand = client.get("/api/merge/candidates").json()["items"][0]
    res = client.post(f"/api/merge/candidates/{cand['id']}/dismiss", json={})
    assert res.status_code == 200
    assert client.get("/api/merge/candidates").json()["count"] == 0
    # scan must not re-propose the dismissed pair
    res = client.post("/api/merge/scan", json={})
    assert res.json()["candidates_new"] == 0
