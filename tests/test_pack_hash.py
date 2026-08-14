from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from ontologylab.packbuilder import build_pack

from tests.test_method_pack import seed_method_pack_database
from tests.test_packbuilder import _populate
from ontologylab.kgstore import KGStore


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
