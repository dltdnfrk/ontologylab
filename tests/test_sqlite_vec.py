"""Opt-in sqlite-vec acceleration: same results as brute force, graceful fallback.

The accelerated path is a KNN prefilter over an identical exact-cosine
rescoring, so these tests assert PARITY with brute force (not new rankings)
plus clean degradation when the extension is absent.
"""

from __future__ import annotations

import pytest

from ontologylab.embeddings import HashingEmbedder, load_sqlite_vec
from ontologylab.kgstore import KGStore
from ontologylab.packbuilder import build_pack
from tests.conftest import insert, make_entity

_HAS_VEC = load_sqlite_vec(__import__("sqlite3").connect(":memory:"))
requires_vec = pytest.mark.skipif(
    not _HAS_VEC, reason="sqlite-vec not installed in this environment"
)


def _seed(store, doc, names):
    insert(store, doc, [make_entity(n, "Component") for n in names])
    store.bulk_approve()


NAMES = [
    "RateLimiter", "OrderService", "SessionCache", "ApiGateway",
    "TokenBucket", "PaymentGateway", "UserRepository", "AuthService",
    "MessageQueue", "CircuitBreaker", "LoadBalancer", "ServiceMesh",
]


def test_load_sqlite_vec_never_raises():
    import sqlite3

    # Whatever the environment, the probe returns a bool and never raises.
    assert isinstance(load_sqlite_vec(sqlite3.connect(":memory:")), bool)


@requires_vec
def test_vec_index_built_on_embed(store, doc):
    _seed(store, doc, NAMES)
    assert store._vec_available() is True
    store.embed_nodes(HashingEmbedder())
    assert store._table_exists("vec_nodes")
    count = store.conn.execute("SELECT COUNT(*) FROM vec_nodes").fetchone()[0]
    assert count == len(NAMES)


@requires_vec
def test_accelerated_matches_bruteforce(store, doc, monkeypatch):
    _seed(store, doc, NAMES)
    emb = HashingEmbedder()
    store.embed_nodes(emb)

    for query in ("rate limiting requests", "payment auth gateway", "cache"):
        accelerated = store.vector_search(query, emb, top_k=5)
        # force brute force on the SAME store/data and compare
        monkeypatch.setattr(store, "_vec_available", lambda: False)
        brute = store.vector_search(query, emb, top_k=5)
        monkeypatch.undo()
        assert [r["id"] for r in accelerated] == [r["id"] for r in brute]
        assert [r["match_score"] for r in accelerated] == [
            r["match_score"] for r in brute
        ]


@requires_vec
def test_accelerated_respects_filters(store, doc):
    insert(store, doc, [make_entity("ApiGateway", "Component"),
                        make_entity("RateLimiter", "Technique")])
    emb = HashingEmbedder()
    store.embed_nodes(emb)  # embeds proposed rows too
    # verified-only default: nothing approved yet -> no hits via vec path
    assert store.vector_search("ApiGateway", emb, top_k=5) == []
    # entity-type filter honored through the KNN shortlist
    hits = store.vector_search(
        "gateway", emb, top_k=5, entity_type="Component", include_proposed=True
    )
    assert hits and all(h["entity_type"] == "Component" for h in hits)


@requires_vec
def test_reembed_rebuilds_vec_index(store, doc):
    _seed(store, doc, ["RateLimiter"])
    emb = HashingEmbedder()
    store.embed_nodes(emb)
    insert(store, doc, [make_entity("OrderService", "Component")])
    store.bulk_approve()
    store.embed_nodes(emb)  # second backfill -> index rebuilt with both
    count = store.conn.execute("SELECT COUNT(*) FROM vec_nodes").fetchone()[0]
    assert count == 2


@requires_vec
def test_pack_build_from_vec_indexed_db(store, doc, tmp_path):
    """A vec-indexed working DB still builds a portable pack; the pack has no
    vec index (served without the extension) and uses brute-force cosine."""
    _seed(store, doc, NAMES)
    emb = HashingEmbedder()
    store.embed_nodes(emb)
    manifest = build_pack(store.db_path, tmp_path / "packs", name="vec-pack")
    assert manifest.search_tier == "fts5+vec-rrf"

    pack = KGStore.open(
        tmp_path / "packs" / manifest.pack_id / "pack.sqlite", read_only=True
    )
    try:
        assert pack._table_exists("vec_nodes") is False  # not carried in
        hits = pack.vector_search("rate limiter", emb, top_k=1)
        assert hits and hits[0]["name"] == "RateLimiter"
    finally:
        pack.close()


def test_vector_search_works_without_extension(store, doc, monkeypatch):
    """With the extension force-disabled, embed + search still work (brute)."""
    monkeypatch.setattr(KGStore, "_vec_available", lambda self: False)
    _seed(store, doc, ["RateLimiter", "OrderService"])
    emb = HashingEmbedder()
    store.embed_nodes(emb)
    assert not store._table_exists("vec_nodes")  # never created
    hits = store.vector_search("rate limiter", emb, top_k=1)
    assert hits and hits[0]["name"] == "RateLimiter"
