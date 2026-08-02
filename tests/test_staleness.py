"""Staleness observability: the pack says what it is based on, the live tier says what it missed.

A pack is immutable, so "how stale is this answer" cannot live inside it —
right after a manual build the embedded count would always read zero, which
is why the basis metadata ships in the manifest and the pending count is
computed at query time against the live store. These tests pin both halves,
plus the degrade paths: no git repo means basis_commit is None (never a
fabricated hash), and no live store configured means pending is None with a
note, never a silent zero.
"""

from __future__ import annotations

import json

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.mcp_server import PackSession
from ontologylab.packbuilder import build_pack as _build_pack
from tests.conftest import make_entity, make_relation


def build_pack(*args, **kwargs):
    kwargs.setdefault("allow_incomplete_extraction", True)
    kwargs.setdefault("incomplete_extraction_intent", "synthetic staleness fixture")
    return _build_pack(*args, **kwargs)


def _seed_store(tmp_path, *, extra_verified: int = 0):
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///d.txt", title="d",
        raw_text="x", content_hash="h",
    )
    a, b = make_entity("boscalid"), make_entity("Botrytis cinerea")
    stats = store.insert_proposed(
        [a, b], [make_relation(a, b, "controls")],
        source_doc_id=doc.id, extractor_engine="mock",
    )
    for node_id in stats["id_map"].values():
        store.approve(node_id, by="t")
    rel_id = stats["id_map"] and store.conn.execute(
        "SELECT id FROM edges LIMIT 1"
    ).fetchone()["id"]
    store.approve(rel_id, by="t")

    extra_ids = []
    for i in range(extra_verified):
        e = make_entity(f"Extra{i}")
        stats2 = store.insert_proposed(
            [e], [], source_doc_id=doc.id, extractor_engine="mock",
        )
        new_id = stats2["id_map"][e.id]
        store.approve(new_id, by="t")
        extra_ids.append(new_id)
    return store, doc


def test_manifest_carries_basis_and_the_default_policy(tmp_path) -> None:
    store, _ = _seed_store(tmp_path)
    store.close()

    manifest = build_pack(
        name="agrochem", kg_db_path=tmp_path / "kg.sqlite",
        packs_dir=tmp_path / "packs",
    )

    assert manifest.basis_commit is None or (
        isinstance(manifest.basis_commit, str) and len(manifest.basis_commit) == 40
    )
    policy = manifest.staleness_policy
    assert policy is not None
    assert policy["pending_verified_count_threshold"] == 0
    assert "rebuild" in policy["description"].lower()

    on_disk = json.loads(
        (tmp_path / "packs" / manifest.pack_id / "manifest.json").read_text()
    )
    assert on_disk["basis_commit"] == manifest.basis_commit
    assert on_disk["staleness_policy"] == manifest.staleness_policy
    assert "created_ts" in on_disk


def test_pending_count_is_computed_live_against_the_store(tmp_path) -> None:
    store, _ = _seed_store(tmp_path)
    store.close()
    build_pack(name="p1", kg_db_path=tmp_path / "kg.sqlite",
               packs_dir=tmp_path / "packs")

    # After the build, two more verified nodes arrive — pending is 2, and it
    # would be wrong to read this from the (immutable) pack.
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = store.conn.execute("SELECT id FROM documents LIMIT 1").fetchone()["id"]
    for i in range(2):
        e = make_entity(f"Late{i}")
        stats = store.insert_proposed(
            [e], [], source_doc_id=doc_id, extractor_engine="mock",
        )
        store.approve(stats["id_map"][e.id], by="t")
    store.close()

    session = PackSession(
        tmp_path / "packs", live_store_path=tmp_path / "kg.sqlite"
    )
    try:
        result = session.get_staleness()
    finally:
        session.close()

    assert result["latest_pack_id"] is not None
    assert result["pending_verified_count"] == 2
    assert result["store_verified_count"] == 5  # 3 in the pack + 2 late
    assert result["pack_verified_count"] == 3
    assert result["pending_verified_count"] == (
        result["store_verified_count"] - result["pack_verified_count"]
    )


def test_pending_is_none_when_no_live_store_is_configured(tmp_path) -> None:
    store, _ = _seed_store(tmp_path)
    store.close()
    build_pack(name="p1", kg_db_path=tmp_path / "kg.sqlite",
               packs_dir=tmp_path / "packs")

    session = PackSession(tmp_path / "packs")
    try:
        result = session.get_staleness()
    finally:
        session.close()

    assert result["pending_verified_count"] is None
    assert result["store_verified_count"] is None
    assert "live store" in result["note"].lower()
    assert result["latest_pack_id"] is not None
    assert "basis_commit" in result
    assert "staleness_policy" in result


def test_staleness_with_no_packs_says_so(tmp_path) -> None:
    session = PackSession(
        tmp_path / "packs", live_store_path=tmp_path / "kg.sqlite"
    )
    try:
        result = session.get_staleness()
    finally:
        session.close()

    assert result["latest_pack_id"] is None
    assert result["pending_verified_count"] is None
    assert "no packs" in result["note"].lower()


def test_pending_never_goes_negative(tmp_path) -> None:
    """A store rebuilt from an older DB can hold fewer items than the pack."""
    store, _ = _seed_store(tmp_path, extra_verified=2)
    store.close()
    build_pack(name="p1", kg_db_path=tmp_path / "kg.sqlite",
               packs_dir=tmp_path / "packs")

    small = KGStore.open(tmp_path / "small.sqlite")
    doc, _ = small.insert_document(
        source_kind="upload", source_uri="file:///d.txt", title="d",
        raw_text="x", content_hash="h2",
    )
    e = make_entity("OnlyOne")
    stats = small.insert_proposed(
        [e], [], source_doc_id=doc.id, extractor_engine="mock",
    )
    small.approve(stats["id_map"][e.id], by="t")
    small.close()

    session = PackSession(
        tmp_path / "packs", live_store_path=tmp_path / "small.sqlite"
    )
    try:
        result = session.get_staleness()
    finally:
        session.close()

    assert result["pending_verified_count"] == 0
