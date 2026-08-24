"""Immutable verify-copy-reverify pack snapshot contract."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.packbuilder import build_pack
from ontologylab.verified_pack_reader import (
    PackIntegrityError,
    activate_pack,
    inspect_verified_manifest,
)


def _build_pack(tmp_path: Path, name: str) -> Path:
    kg = tmp_path / f"{name}.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    document, _created = store.insert_document(
        source_kind="upload",
        source_uri="file:///doc.txt",
        title="doc",
        raw_text="RateLimiter implements TokenBucket algorithm",
        content_hash=f"{name}-hash",
    )
    store.insert_proposed(
        [
            ProposedEntity(id="n_rl", entity_type="Component", name="RateLimiter"),
            ProposedEntity(id="n_tb", entity_type="Technique", name="TokenBucket"),
        ],
        [
            ProposedRelation(
                id="e_uses",
                relation_type="uses",
                src_entity_id="n_rl",
                dst_entity_id="n_tb",
            )
        ],
        source_doc_id=document.id,
        extractor_engine="mock",
    )
    store.approve("n_rl")
    store.approve("n_tb")
    store.approve("e_uses")
    store.close()
    manifest = build_pack(
        kg,
        packs,
        name=name,
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="verified pack reader fixture",
    )
    return packs / manifest.pack_id


def test_activate_pack_serves_detached_copy_when_source_is_valid(
    tmp_path: Path,
) -> None:
    pack_dir = _build_pack(tmp_path, "reader-valid")
    snapshot = activate_pack(pack_dir)
    try:
        source = pack_dir / "pack.sqlite"
        assert snapshot.sqlite_path.resolve() != source.resolve()
        assert snapshot.sqlite_path.stat().st_ino != source.stat().st_ino
        assert snapshot.serving_root.resolve() != pack_dir.resolve()
        assert stat.S_IMODE(snapshot.sqlite_path.stat().st_mode) & 0o222 == 0
        store = snapshot.open_store()
        try:
            with pytest.raises(sqlite3.Error):
                store.conn.execute("UPDATE nodes SET name = 'mutated'")
            names = [
                row["name"]
                for row in store.conn.execute("SELECT name FROM nodes ORDER BY name")
            ]
            assert names == ["RateLimiter", "TokenBucket"]
        finally:
            store.close()
    finally:
        snapshot.close()
    assert not snapshot.serving_root.exists()
    assert pack_dir.exists()


def test_activate_pack_ignores_source_mutation_after_load(tmp_path: Path) -> None:
    pack_dir = _build_pack(tmp_path, "reader-mutate")
    snapshot = activate_pack(pack_dir)
    try:
        store = snapshot.open_store()
        try:
            before = [
                row["name"]
                for row in store.conn.execute("SELECT name FROM nodes ORDER BY name")
            ]
            (pack_dir / "pack.sqlite").write_bytes(
                (pack_dir / "pack.sqlite").read_bytes() + b"\x00"
            )
            manifest = pack_dir / "manifest.json"
            manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
            after = [
                row["name"]
                for row in store.conn.execute("SELECT name FROM nodes ORDER BY name")
            ]
            assert after == before
            assert snapshot.manifest.get("attacker") is None
        finally:
            store.close()
    finally:
        snapshot.close()


def test_activate_pack_refuses_tampered_source_when_hash_drifts(
    tmp_path: Path,
) -> None:
    pack_dir = _build_pack(tmp_path, "reader-tamper")
    sqlite_path = pack_dir / "pack.sqlite"
    blob = bytearray(sqlite_path.read_bytes())
    blob[len(blob) // 2] ^= 0xFF
    sqlite_path.write_bytes(bytes(blob))
    before = list(tmp_path.iterdir())
    with pytest.raises(PackIntegrityError):
        activate_pack(pack_dir)
    leftover = [
        path
        for path in Path(os.environ.get("TMPDIR", "/tmp")).glob(
            f"ontologylab-pack-{os.getpid()}-*"
        )
        if path.is_dir()
    ]
    assert leftover == []
    assert list(tmp_path.iterdir()) == before


def test_inspect_verified_manifest_refuses_forged_hash_when_sqlite_still_opens(
    tmp_path: Path,
) -> None:
    pack_dir = _build_pack(tmp_path, "reader-forge")
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["content_hash"] = "sha256:" + ("0" * 64)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PackIntegrityError):
        inspect_verified_manifest(pack_dir)


def test_activate_pack_preserves_v1_without_tree_hash(tmp_path: Path) -> None:
    pack_dir = _build_pack(tmp_path, "reader-legacy")
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload.pop("tree_hash", None)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = activate_pack(pack_dir)
    try:
        assert snapshot.content_hash == payload["content_hash"]
        assert snapshot.pack_id == pack_dir.name
    finally:
        snapshot.close()
