"""Pack build: verified-only, non-WAL, FTS rebuilt into pack."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.models import ProposedEntity, ProposedRelation  # noqa: E402
from ontologylab.packbuilder import (  # noqa: E402
    PackBuildError,
    build_pack,
    list_packs,
)


def _populate(store: KGStore) -> None:
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///x.txt",
        title="x",
        raw_text="RateLimiter uses TokenBucket for throttling",
        content_hash="pack-hash-1",
    )
    store.insert_proposed(
        [
            ProposedEntity(id="n1", entity_type="Component", name="RateLimiter"),
            ProposedEntity(id="n2", entity_type="Technique", name="TokenBucket"),
            ProposedEntity(id="n3", entity_type="Concept", name="Throttling"),
        ],
        [
            ProposedRelation(
                id="e1",
                relation_type="uses",
                src_entity_id="n1",
                dst_entity_id="n2",
            ),
            ProposedRelation(
                id="e2",
                relation_type="related_to",
                src_entity_id="n1",
                dst_entity_id="n3",
            ),
        ],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.approve("n1")
    store.approve("n2")
    store.approve("e1")
    # n3 + e2 stay proposed — must not enter the pack


def test_build_pack_verified_only_and_fts(tmp_path: Path) -> None:
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    _populate(store)
    store.close()

    manifest = build_pack(
        kg, packs, name="demo", allow_incomplete_extraction=True,
        incomplete_extraction_intent="synthetic packbuilder fixture",
    )
    assert manifest.counts["nodes_verified"] == 2
    assert manifest.counts["edges_verified"] == 1

    pack_sqlite = packs / manifest.pack_id / "pack.sqlite"
    assert pack_sqlite.is_file()
    # no wal sidecar required
    assert not (packs / manifest.pack_id / "pack.sqlite-wal").exists()

    conn = sqlite3.connect(f"file:{pack_sqlite}?mode=ro", uri=True)
    try:
        n_prop = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE status != 'verified'"
        ).fetchone()[0]
        e_prop = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE status != 'verified'"
        ).fetchone()[0]
        assert n_prop == 0
        assert e_prop == 0
        # FTS works
        hits = conn.execute(
            "SELECT COUNT(*) FROM nodes_fts WHERE nodes_fts MATCH 'RateLimiter'"
        ).fetchone()[0]
        assert hits >= 1
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() in ("delete", "off", "memory", "persist")
    finally:
        conn.close()

    discovered = list_packs(packs)
    assert len(discovered) == 1
    assert discovered[0]["pack_id"] == manifest.pack_id


def test_method_selection_failure_leaves_no_visible_pack(
    tmp_path: Path,
) -> None:
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    _populate(store)
    store.close()

    with pytest.raises(PackBuildError, match="unknown Method release"):
        build_pack(
            kg,
            packs,
            name="demo",
            method_release_ids=("missing-release",),
            allow_incomplete_extraction=True,
            incomplete_extraction_intent="synthetic packbuilder fixture",
        )

    assert list_packs(packs) == []
    assert not list(tmp_path.glob(".packs-*-staging-*"))
