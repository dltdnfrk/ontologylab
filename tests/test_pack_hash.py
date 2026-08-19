from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from ontologylab.packbuilder import build_pack

from tests.test_method_pack import seed_method_pack_database
from tests.test_packbuilder import _populate
from ontologylab.kgstore import KGStore


def test_payload_file_tamper_is_rejected(tmp_path: Path) -> None:
    """Only pack.sqlite was receipt-hashed — schema.json / provenance.jsonl
    could be rewritten under a valid receipt. The pack tree hash closes
    that: payload files bind to the receipt too."""
    import pytest

    from ontologylab.mcp_server import PackIntegrityError, PackSession

    kg = tmp_path / "kg.sqlite"
    store = KGStore.open(kg)
    _populate(store)
    store.close()
    manifest = build_pack(
        kg, tmp_path / "packs", "demo",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="fixture",
    )
    pack_dir = tmp_path / "packs" / manifest.pack_id

    schema_path = pack_dir / "schema.json"
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    data["injected"] = {"by": "attacker"}
    schema_path.write_text(json.dumps(data), encoding="utf-8")

    session = PackSession(tmp_path / "packs")
    try:
        with pytest.raises(PackIntegrityError):
            session.load_pack(manifest.pack_id)
    finally:
        session.close()


def test_manifest_without_tree_hash_still_loads(tmp_path: Path) -> None:
    """Legacy packs whose receipt predates tree_hash keep verifying on
    content_hash alone (additive field, not a breaking change)."""
    from ontologylab.mcp_server import PackSession

    kg = tmp_path / "kg.sqlite"
    store = KGStore.open(kg)
    _populate(store)
    store.close()
    manifest = build_pack(
        kg, tmp_path / "packs", "demo",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="fixture",
    )
    mpath = tmp_path / "packs" / manifest.pack_id / "manifest.json"
    legacy = json.loads(mpath.read_text(encoding="utf-8"))
    legacy.pop("tree_hash", None)
    mpath.write_text(json.dumps(legacy, indent=2), encoding="utf-8")

    session = PackSession(tmp_path / "packs")
    try:
        out = session.load_pack(manifest.pack_id)
        assert out["content_hash"] == manifest.content_hash
    finally:
        session.close()


def test_selected_method_changes_pack_content_hash(tmp_path: Path) -> None:
    kg = tmp_path / "kg.sqlite"
    store = KGStore.open(kg)
    _populate(store)
    store.close()
    method = seed_method_pack_database(kg)
    method.close()
    graph = build_pack(
        kg, tmp_path / "graph", "demo",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="fixture",
    )
    selected = build_pack(
        kg, tmp_path / "selected", "demo",
        method_release_ids=("release-1",),
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="fixture",
    )
    assert graph.content_hash != selected.content_hash
    assert selected.methodology is not None
    pack = tmp_path / "selected" / selected.pack_id / "pack.sqlite"
    assert selected.content_hash == (
        "sha256:" + hashlib.sha256(pack.read_bytes()).hexdigest()
    )
    connection = sqlite3.connect(f"file:{pack}?mode=ro", uri=True)
    try:
        receipt_json, receipt_hash = connection.execute(
            "SELECT receipt_json,receipt_hash "
            "FROM methodology_publication_receipt"
        ).fetchone()
    finally:
        connection.close()
    assert (
        "sha256:" + hashlib.sha256(receipt_json.encode()).hexdigest()
        == receipt_hash
        == selected.methodology["publication_receipt_hash"]
    )
    assert json.loads(receipt_json)["selection"][0][
        "release_content_hash"
    ] == selected.methodology["selected_release_hashes"]["release-1"]
