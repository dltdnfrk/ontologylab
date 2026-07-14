"""Tier-2 hybrid search: embedder determinism, backfill, cosine, RRF fusion."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from conftest import insert, make_entity  # noqa: E402
from ontologylab.embeddings import (  # noqa: E402
    HashingEmbedder,
    cosine,
    get_embedder,
    pack_vector,
    rrf_fuse,
    unpack_vector,
)
from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.packbuilder import build_pack  # noqa: E402


def test_hashing_embedder_deterministic_and_normalized():
    emb = HashingEmbedder()
    [a1], [a2] = emb.embed(["RateLimiter"]), emb.embed(["RateLimiter"])
    assert a1 == a2
    assert abs(sum(x * x for x in a1) - 1.0) < 1e-6  # L2-normalized
    # surface-similar strings are closer than unrelated ones
    [b] = emb.embed(["rate limiting"])
    [c] = emb.embed(["PostgresDatabase"])
    assert cosine(a1, b) > cosine(a1, c)


def test_pack_unpack_roundtrip():
    vec = [0.25, -1.5, 3.125, 0.0]
    assert unpack_vector(pack_vector(vec)) == vec


def test_rrf_fusion_normalized_and_rank_preserving():
    fused = rrf_fuse([["a", "b", "c"], ["b", "a"]])
    scores = dict(fused)
    # b: rank0+rank1 beats c: rank2-only; everything in (0, 1]
    assert fused[0][0] in ("a", "b")
    assert scores["b"] > scores["c"]
    assert all(0.0 < s <= 1.0 for _, s in fused)
    # appearing first in every list -> exactly 1.0
    assert dict(rrf_fuse([["x"], ["x"]]))["x"] == pytest.approx(1.0)


def test_get_embedder_factory():
    assert get_embedder(None) is None
    assert get_embedder("none") is None
    assert get_embedder("hash").name() == "hash-v1"


def test_embed_backfill_and_hybrid_search(store, doc):
    # "RateLimiter" with FTS-hostile query: "ratelimiting" shares no FTS
    # token with the name, but char-ngrams overlap heavily.
    insert(
        store,
        doc,
        [
            make_entity("RateLimiter", "Component"),
            make_entity("OrderService", "Component"),
            make_entity("SessionCache", "Component"),
        ],
    )
    store.bulk_approve()
    emb = HashingEmbedder()
    stats = store.embed_nodes(emb)
    assert stats["embedded"] == 3
    assert store.embedding_model() == "hash-v1"
    # idempotent
    assert store.embed_nodes(emb)["embedded"] == 0

    vec_hits = store.vector_search("ratelimiting requests", emb, top_k=3)
    assert vec_hits and vec_hits[0]["name"] == "RateLimiter"
    assert 0.0 <= vec_hits[0]["match_score"] <= 1.0

    hybrid = store.hybrid_search("ratelimiting requests", emb, top_k=3)
    assert hybrid and hybrid[0]["name"] == "RateLimiter"
    # provenance survives fusion
    assert hybrid[0]["source_document_ids"]


def test_vector_search_respects_verified_only(store, doc):
    insert(store, doc, [make_entity("ApiGateway", "Component")])
    emb = HashingEmbedder()
    store.embed_nodes(emb)  # embeds the proposed row (review search support)
    # default (verified-only) must NOT return the proposed node
    assert store.vector_search("ApiGateway", emb, top_k=5) == []
    assert store.vector_search(
        "ApiGateway", emb, top_k=5, include_proposed=True
    )


def test_pack_manifest_records_embedding_tier(tmp_path, store, doc):
    insert(store, doc, [make_entity("RateLimiter", "Component")])
    store.bulk_approve()
    store.embed_nodes(HashingEmbedder())
    manifest = build_pack(store.db_path, tmp_path / "packs", name="emb-demo")
    assert manifest.search_tier == "fts5+vec-rrf"
    assert manifest.embedding_model == "hash-v1"

    # embeddings travel into the pack and are queryable read-only
    pack = KGStore.open(
        tmp_path / "packs" / manifest.pack_id / "pack.sqlite", read_only=True
    )
    try:
        assert pack.embedding_model() == "hash-v1"
        hits = pack.vector_search("rate limiter", HashingEmbedder(), top_k=1)
        assert hits and hits[0]["name"] == "RateLimiter"
    finally:
        pack.close()


def test_pack_without_embeddings_stays_fts5(tmp_path, store, doc):
    insert(store, doc, [make_entity("OrderService", "Component")])
    store.bulk_approve()
    manifest = build_pack(store.db_path, tmp_path / "packs", name="plain")
    assert manifest.search_tier == "fts5"
    assert manifest.embedding_model is None
