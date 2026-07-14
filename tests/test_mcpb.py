"""W10 .mcpb bundling: one pack -> one installable MCP bundle."""

from __future__ import annotations

import json
import zipfile

import pytest

from ontologylab import __version__
from ontologylab.mcpb import MCPB_MANIFEST_VERSION, build_mcpb, build_mcpb_manifest
from ontologylab.packbuilder import PackBuildError, build_pack
from tests.conftest import insert, make_entity


@pytest.fixture()
def pack(store, doc, tmp_path):
    """A minimal built pack: one verified node."""
    insert(store, doc, [make_entity("RateLimiter")])
    node_id = store.conn.execute("SELECT id FROM nodes").fetchone()["id"]
    store.approve(node_id, by="tester")
    packs_dir = tmp_path / "packs"
    manifest = build_pack(store.db_path, packs_dir, "bundle-test")
    return packs_dir, manifest


def test_build_mcpb_layout_and_manifest(pack):
    packs_dir, manifest = pack
    bundle = build_mcpb(packs_dir, manifest.pack_id)
    assert bundle == packs_dir / f"{manifest.pack_id}.mcpb"

    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "server/main.py" in names
        prefix = f"packs/{manifest.pack_id}/"
        for member in ("pack.sqlite", "manifest.json", "schema.json",
                       "provenance.jsonl"):
            assert prefix + member in names

        mcpb = json.loads(zf.read("manifest.json"))
        assert mcpb["manifest_version"] == MCPB_MANIFEST_VERSION
        assert mcpb["name"] == manifest.pack_id
        assert mcpb["version"] == __version__
        args = mcpb["server"]["mcp_config"]["args"]
        assert "${__dirname}/packs" in args
        assert manifest.pack_id in args
        assert mcpb["server"]["entry_point"] == "server/main.py"
        # the wrapped pack manifest rides along, hash intact
        assert mcpb["x_pack_manifest"]["content_hash"] == manifest.content_hash

        shim = zf.read("server/main.py").decode()
        assert "ontologylab.mcp_server" in shim

        # bundling copies bytes: the pack sqlite inside is byte-identical
        packed = zf.read(prefix + "pack.sqlite")
        original = (packs_dir / manifest.pack_id / "pack.sqlite").read_bytes()
        assert packed == original


def test_build_mcpb_manifest_is_honest_about_counts(pack):
    _packs_dir, manifest = pack
    mcpb = build_mcpb_manifest(manifest.__dict__)
    assert "1 nodes / 0 edges" in mcpb["description"]
    assert "search tier fts5" in mcpb["description"]


def test_build_mcpb_unknown_pack(tmp_path):
    with pytest.raises(PackBuildError):
        build_mcpb(tmp_path, "no-such-pack")


def test_build_mcpb_custom_out_path(pack, tmp_path):
    packs_dir, manifest = pack
    out = tmp_path / "dist" / "bundle.mcpb"
    bundle = build_mcpb(packs_dir, manifest.pack_id, out_path=out)
    assert bundle == out and out.is_file()


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


def _build_pack_via_api(client) -> str:
    from ontologylab.kgstore import KGStore
    from ontologylab.paths import kg_db_path

    data_dir = client.app.state.data_dir
    store = KGStore.open(kg_db_path(data_dir))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///x", title="x",
        raw_text="RateLimiter", content_hash="sha256:x",
    )
    insert(store, doc, [make_entity("RateLimiter")])
    node_id = store.conn.execute("SELECT id FROM nodes").fetchone()["id"]
    store.approve(node_id, by="tester")
    store.close()
    res = client.post("/api/packs/build", json={"name": "api-bundle"})
    assert res.json()["ok"] is True
    return res.json()["manifest"]["pack_id"]


def test_mcpb_api_build_and_download(client):
    pack_id = _build_pack_via_api(client)

    res = client.post(f"/api/packs/{pack_id}/mcpb")
    body = res.json()
    assert body["ok"] is True and body["size_bytes"] > 0

    res = client.get(body["download_url"])
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    # a valid zip with the mcpb manifest inside
    import io

    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert "manifest.json" in zf.namelist()


def test_mcpb_api_unknown_pack(client):
    res = client.post("/api/packs/nope/mcpb")
    assert res.json()["ok"] is False
    res = client.get("/api/packs/nope/mcpb/download")
    assert res.status_code == 404
