"""Pack discovery must reject malformed packs.

A directory under the packs dir is only a pack when its manifest.json is a
JSON object carrying a usable pack_id and its pack.sqlite is openable as a
pack database. Without that check the Packs screen and the Connection
(MCP status) screen disagree: one lists a phantom row, the other 500s or
offers a copyable serve command for a pack that cannot serve.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.models import ProposedEntity, ProposedRelation  # noqa: E402
from ontologylab.packbuilder import build_pack, list_packs  # noqa: E402
from ontologylab.server.app import create_app  # noqa: E402


def _good_pack(tmp_path: Path, packs_dir: Path) -> str:
    """Build one real pack and return its pack_id."""
    db = tmp_path / "kg.sqlite"
    store = KGStore.open(db)
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///x.txt",
        title="x",
        raw_text="RateLimiter uses TokenBucket",
        content_hash="disc-hash-1",
    )
    store.insert_proposed(
        [
            ProposedEntity(id="n1", entity_type="Component", name="RateLimiter"),
            ProposedEntity(id="n2", entity_type="Technique", name="TokenBucket"),
        ],
        [
            ProposedRelation(
                id="e1",
                relation_type="uses",
                src_entity_id="n1",
                dst_entity_id="n2",
            )
        ],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.approve("n1")
    store.approve("n2")
    store.approve("e1")
    store.close()
    manifest = build_pack(
        db,
        packs_dir,
        "good",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="synthetic pack discovery fixture",
    )
    return manifest.pack_id


def _write_fixture(
    packs_dir: Path,
    name: str,
    manifest: Any,
    *,
    sqlite_bytes: bytes | None = b"not a database",
) -> Path:
    """Drop a malformed pack directory into packs_dir."""
    d = packs_dir / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if sqlite_bytes is not None:
        (d / "pack.sqlite").write_bytes(sqlite_bytes)
    return d


@pytest.fixture()
def workspace(tmp_path: Path):
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    good = _good_pack(tmp_path, packs_dir)
    # 1. manifest is an object but has no pack_id
    _write_fixture(packs_dir, "no-pack-id", {"counts": {}})
    # 2. manifest is a JSON array, not an object
    _write_fixture(packs_dir, "array-manifest", [])
    # 3. plausible manifest, unusable sqlite
    _write_fixture(
        packs_dir,
        "broken-sqlite",
        {"pack_id": "broken-sqlite", "counts": {"documents": 1}},
    )
    client = TestClient(create_app(data_dir=tmp_path / "data", packs_dir=packs_dir))
    try:
        yield {"client": client, "packs_dir": packs_dir, "good": good}
    finally:
        client.close()


def test_list_packs_returns_only_valid_manifests(workspace) -> None:
    packs = list_packs(workspace["packs_dir"])
    assert [p["pack_id"] for p in packs] == [workspace["good"]]


def test_packs_and_mcp_status_agree_on_usable_packs(workspace) -> None:
    client = workspace["client"]
    packs_resp = client.get("/api/packs")
    status_resp = client.get("/api/mcp/status")

    assert packs_resp.status_code == 200
    # The malformed array manifest must not blow up MCP status with a 500.
    assert status_resp.status_code == 200

    listed = packs_resp.json()
    status = status_resp.json()
    assert [p["pack_id"] for p in listed["packs"]] == [workspace["good"]]
    assert listed["count"] == 1
    assert [p["pack_id"] for p in status["packs"]] == [workspace["good"]]
    assert status["count"] == 1


def test_no_serve_command_for_unusable_pack(workspace) -> None:
    status = workspace["client"].get("/api/mcp/status").json()
    served = {entry["pack_id"] for entry in status["packs"]}
    assert served == {workspace["good"]}
    blob = json.dumps(status)
    for bad in ("no-pack-id", "array-manifest", "broken-sqlite"):
        assert f"--pack {bad}" not in blob


def test_unusable_packs_are_reported_with_reasons(workspace) -> None:
    """Silent exclusion is a support cost: say why a directory is skipped."""
    listed = workspace["client"].get("/api/packs").json()
    unusable = {u["pack_dir"]: u for u in listed["unusable"]}
    assert set(unusable) == {"no-pack-id", "array-manifest", "broken-sqlite"}
    for entry in unusable.values():
        assert entry["reason"]
        assert "serve_command" not in entry

    status = workspace["client"].get("/api/mcp/status").json()
    assert {u["pack_dir"] for u in status["unusable"]} == set(unusable)


def test_manifest_scalar_and_traversal_pack_id_rejected(tmp_path: Path) -> None:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    _write_fixture(packs_dir, "string-manifest", "just a string")
    _write_fixture(packs_dir, "number-manifest", 7)
    _write_fixture(packs_dir, "traversal", {"pack_id": "../escape"})
    (packs_dir / "empty-dir").mkdir()

    client = TestClient(create_app(data_dir=tmp_path / "data", packs_dir=packs_dir))
    try:
        listed = client.get("/api/packs")
        status = client.get("/api/mcp/status")
        assert listed.status_code == 200
        assert status.status_code == 200
        assert listed.json()["packs"] == []
        assert status.json()["packs"] == []
        # an empty directory has no manifest at all: not a pack, not an error
        reported = {u["pack_dir"] for u in listed.json()["unusable"]}
        assert reported == {"string-manifest", "number-manifest", "traversal"}
    finally:
        client.close()


def test_removing_malformed_fixture_restores_clean_listing(workspace) -> None:
    """Stale state: discovery is a live scan, no restart or cache flush."""
    client = workspace["client"]
    assert len(client.get("/api/packs").json()["unusable"]) == 3

    import shutil

    for bad in ("no-pack-id", "array-manifest", "broken-sqlite"):
        shutil.rmtree(workspace["packs_dir"] / bad)

    listed = client.get("/api/packs").json()
    status = client.get("/api/mcp/status").json()
    assert listed["unusable"] == []
    assert status["unusable"] == []
    assert [p["pack_id"] for p in listed["packs"]] == [workspace["good"]]
    assert [p["pack_id"] for p in status["packs"]] == [workspace["good"]]


def test_truncated_but_valid_sqlite_without_pack_tables_rejected(
    tmp_path: Path,
) -> None:
    """A real sqlite file that is not a pack DB is still unusable."""
    packs_dir = tmp_path / "packs"
    d = packs_dir / "empty-db"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(
        json.dumps({"pack_id": "empty-db"}), encoding="utf-8"
    )
    conn = sqlite3.connect(str(d / "pack.sqlite"))
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()

    assert list_packs(packs_dir) == []
