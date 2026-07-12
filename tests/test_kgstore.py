"""KG store invariants: entity resolution, the human gate, read-only packs."""

import pytest

from ontologylab.kgstore import (
    EndpointNotVerified,
    KGStore,
    KGStoreError,
    normalize_name,
)
from tests.conftest import insert, make_entity, make_relation


def test_normalize_name_folds_case_space_punct():
    assert normalize_name("Rate Limiter") == normalize_name("rate-limiter")
    assert normalize_name("RateLimiter") == normalize_name("Rate Limiter".replace(" ", ""))
    assert normalize_name("A") != normalize_name("B")


# ---------------------------------------------------------------------------
# entity resolution
# ---------------------------------------------------------------------------


def test_same_normalized_name_merges_across_inserts(store, doc):
    stats1 = insert(store, doc, [make_entity("RateLimiter")])
    assert stats1["nodes_new"] == 1
    stats2 = insert(store, doc, [make_entity("rate limiter")])
    assert stats2["nodes_new"] == 0
    assert stats2["nodes_merged"] == 1
    counts = store.counts()
    assert counts["nodes_proposed"] == 1


def test_same_name_different_type_stays_separate(store, doc):
    insert(store, doc, [make_entity("Caching", entity_type="Component")])
    stats = insert(store, doc, [make_entity("Caching", entity_type="Concept")])
    assert stats["nodes_new"] == 1
    assert store.counts()["nodes_proposed"] == 2


def test_relation_endpoints_bound_to_resolved_nodes(store, doc):
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b], [make_relation(a, b)])
    # re-insert the same surface forms with fresh chunk-minted ids
    a2, b2 = make_entity("ApiGateway"), make_entity("RateLimiter")
    stats = insert(store, doc, [a2, b2], [make_relation(a2, b2)])
    assert stats["nodes_new"] == 0
    assert stats["edges_new"] == 0  # duplicate edge merged, not duplicated
    counts = store.counts()
    assert counts["nodes_proposed"] == 2
    assert counts["edges_proposed"] == 1


# ---------------------------------------------------------------------------
# the human gate
# ---------------------------------------------------------------------------


def test_rows_are_born_proposed(store, doc):
    insert(store, doc, [make_entity("ApiGateway")])
    rows = store.pending_review()
    assert len(rows) == 1
    assert store.counts()["nodes_verified"] == 0


def test_approve_promotes_and_reject_keeps_audit_row(store, doc):
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b])
    (row_a, row_b) = store.pending_review()
    store.approve(row_a["id"], by="tester")
    store.reject(row_b["id"], by="tester", note="wrong extraction")
    counts = store.counts()
    assert counts["nodes_verified"] == 1
    assert counts["nodes_proposed"] == 0
    # rejected row still exists for audit
    (rejected,) = store.conn.execute(
        "SELECT status, verified_by FROM nodes WHERE id = ?", (row_b["id"],)
    ).fetchall()
    assert rejected["status"] == "rejected"
    assert rejected["verified_by"] == "tester"


def test_edge_approval_blocked_until_endpoints_verified(store, doc):
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    rel = make_relation(a, b)
    insert(store, doc, [a, b], [rel])
    edge_id = store.pending_review(kind="edge")[0]["id"]
    with pytest.raises(EndpointNotVerified):
        store.approve(edge_id)
    # cascade approves the endpoints together with the edge
    result = store.approve(edge_id, cascade=True)
    assert result["kind"] == "edge"
    counts = store.counts()
    assert counts["edges_verified"] == 1
    assert counts["nodes_verified"] == 2


def test_bulk_approve_skips_edges_with_unverified_endpoints(store, doc):
    a, b = make_entity("HighConf", confidence=0.95), make_entity("LowConf", confidence=0.2)
    rel = make_relation(a, b, confidence=0.9)
    insert(store, doc, [a, b], [rel])
    report = store.bulk_approve(min_confidence=0.5)
    assert len(report["nodes_approved"]) == 1  # only HighConf
    assert report["edges_approved"] == []
    assert len(report["edges_skipped"]) == 1  # LowConf endpoint not verified


def test_unknown_item_errors(store):
    with pytest.raises(KGStoreError):
        store.approve("nonexistent")
    with pytest.raises(KGStoreError):
        store.reject("nonexistent")


# ---------------------------------------------------------------------------
# queries respect the verified-only default
# ---------------------------------------------------------------------------


def test_queries_hide_proposed_by_default(store, doc):
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b])
    node_id = store.pending_review()[0]["id"]
    store.approve(node_id)

    assert len(store.entity_lookup(name="ApiGateway")) == 1
    assert store.entity_lookup(name="RateLimiter") == []
    assert (
        len(store.entity_lookup(name="RateLimiter", include_proposed=True)) == 1
    )

    store.rebuild_fts()
    assert store.semantic_search("RateLimiter") == []
    assert len(store.semantic_search("RateLimiter", include_proposed=True)) == 1


# ---------------------------------------------------------------------------
# read-only mode
# ---------------------------------------------------------------------------


def test_read_only_store_refuses_writes(tmp_path, store, doc):
    insert(store, doc, [make_entity("ApiGateway")])
    store.close()
    ro = KGStore.open(tmp_path / "kg.sqlite", read_only=True)
    try:
        node_id = ro.pending_review()[0]["id"]
        with pytest.raises(KGStoreError):
            ro.approve(node_id)
        with pytest.raises(KGStoreError):
            ro.insert_document(
                source_kind="upload",
                source_uri="file:///x",
                title=None,
                raw_text="x",
                content_hash="sha256:x",
            )
    finally:
        ro.close()
