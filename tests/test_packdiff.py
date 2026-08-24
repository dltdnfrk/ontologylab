"""W14: pack diff + re-extraction harmony with existing verified data."""
# noqa: SIZE_OK — Task 10 adds verifier-boundary cases to the existing SUT

from __future__ import annotations

from pathlib import Path

import pytest

import json

from ontologylab.kgstore import KGStore
from ontologylab.mcp_server import PackIntegrityError
from ontologylab.packbuilder import PackBuildError, build_pack as _build_pack
from ontologylab.packdiff import diff_packs
from tests.conftest import insert, make_entity, make_relation


def build_pack(*args, **kwargs):
    kwargs.setdefault("allow_incomplete_extraction", True)
    kwargs.setdefault("incomplete_extraction_intent", "synthetic pack-diff fixture")
    return _build_pack(*args, **kwargs)


@pytest.fixture()
def evolving_workspace(tmp_path: Path):
    """A working KG + pack A, ready to evolve into pack B."""
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///doc.txt", title="doc",
        raw_text="ApiGateway uses RateLimiter", content_hash="w14-h1",
    )
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    insert(store, doc, [gateway, limiter], [make_relation(gateway, limiter)])
    store.bulk_approve(by="tester")
    manifest_a = build_pack(kg, packs, name="v1")
    return store, doc, packs, manifest_a


def test_diff_identical_rebuild(evolving_workspace):
    store, _doc, packs, manifest_a = evolving_workspace
    manifest_b = build_pack(store.db_path, packs, name="v1-rebuild")
    diff = diff_packs(packs, manifest_a.pack_id, manifest_b.pack_id)
    # a rebuild without changes: same rows, zero deltas
    assert diff["summary"] == {
        "nodes_added": 0, "nodes_removed": 0, "nodes_changed": 0,
        "edges_added": 0, "edges_removed": 0, "edges_changed": 0,
    }
    assert diff["manifest_changes"] == {}


def test_diff_reports_added_changed_removed(evolving_workspace):
    store, doc, packs, manifest_a = evolving_workspace

    # evolve: new entity + edge, alias change on an existing node,
    # and one edge invalidated (drops out of pack B)
    cache = make_entity("SessionCache")
    limiter2 = make_entity("RateLimiter", aliases=["throttler"])  # merges
    insert(store, doc, [cache, limiter2],
           [make_relation(limiter2, cache)])
    store.bulk_approve(by="tester")
    old_edge = store.conn.execute(
        "SELECT id FROM edges ORDER BY created_ts LIMIT 1"
    ).fetchone()["id"]
    store.invalidate_edge(old_edge, by="tester", reason="superseded")

    manifest_b = build_pack(store.db_path, packs, name="v2")
    diff = diff_packs(packs, manifest_a.pack_id, manifest_b.pack_id)

    assert diff["identical"] is False
    assert diff["summary"]["nodes_added"] == 1
    assert diff["nodes"]["added"][0]["label"] == "SessionCache"
    (changed,) = diff["nodes"]["changed"]
    assert changed["label"] == "RateLimiter" and "aliases" in changed["fields"]
    assert diff["summary"]["edges_added"] == 1
    assert "SessionCache" in diff["edges"]["added"][0]["label"]
    (removed_edge,) = diff["edges"]["removed"]
    assert "ApiGateway" in removed_edge["label"]  # invalidated edge dropped


def test_diff_unknown_pack(evolving_workspace):
    _store, _doc, packs, manifest_a = evolving_workspace
    with pytest.raises(PackBuildError):
        diff_packs(packs, manifest_a.pack_id, "no-such-pack")


def test_diff_refuses_a_tampered_pack(evolving_workspace):
    """C-046: a pack whose bytes no longer match its manifest receipt must
    fail typed before any comparison result exists."""
    store, _doc, packs, manifest_a = evolving_workspace
    manifest_b = build_pack(store.db_path, packs, name="v2")
    sqlite_b = packs / manifest_b.pack_id / "pack.sqlite"
    blob = bytearray(sqlite_b.read_bytes())
    blob[-1] ^= 0xFF
    sqlite_b.write_bytes(bytes(blob))
    with pytest.raises(PackIntegrityError):
        diff_packs(packs, manifest_a.pack_id, manifest_b.pack_id)


def _v2_wrap(pack_dir: Path) -> None:
    """Rewrite a built v1 pack as a verifier-valid v2 inventory pack."""
    import hashlib
    import os
    import sqlite3 as sqlite
    import stat as mode

    from ontologylab.pack_verifier import verify_pack

    from ontologylab.pack_v2_derive import derive_capabilities, derive_v2_counts
    files: dict[str, bytes] = {}
    for dirpath, _dirnames, filenames in os.walk(pack_dir, followlinks=False):
        base = Path(dirpath)
        for name in filenames:
            child = base / name
            rel = child.relative_to(pack_dir).as_posix()
            if rel == "manifest.json":
                continue
            child.chmod(0o444)
            files[rel] = child.read_bytes()
    inventory = [
        {
            "file_type": "regular",
            "mode": mode.S_IMODE((pack_dir / rel).stat().st_mode),
            "path": rel,
            "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for rel, data in sorted(files.items())
    ]
    connection = sqlite.connect(f"file:{pack_dir / 'pack.sqlite'}?mode=ro", uri=True)
    try:
        counts = dict(derive_v2_counts(connection))
        capabilities = list(derive_capabilities(connection, has_evidence=False))
    finally:
        connection.close()
    original = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "pack_id": pack_dir.name,
        "pack_schema_version": 2,
        "capabilities": capabilities,
        "integrity_model": "sha256-receipt-not-signature",
        "content_hash": original["content_hash"],
        "sqlite_hash": "sha256:" + hashlib.sha256(files["pack.sqlite"]).hexdigest(),
        "artifact_inventory": inventory,
        "pack_content_hash": "sha256:" + hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "counts": counts,
    }
    manifest_path = pack_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest_path.chmod(0o444)
    verify_pack(pack_dir)


def test_diff_refuses_extra_artifact_that_legacy_opener_would_serve(
    evolving_workspace,
) -> None:
    """Independent-diff: packdiff must share the standalone verifier."""
    store, _doc, packs, manifest_a = evolving_workspace
    manifest_b = build_pack(store.db_path, packs, name="v2-extra")
    pack_b = packs / manifest_b.pack_id
    _v2_wrap(pack_b)
    extra = pack_b / "notes.txt"
    extra.write_bytes(b"not-in-inventory\n")
    extra.chmod(0o444)
    with pytest.raises(PackIntegrityError):
        diff_packs(packs, manifest_a.pack_id, manifest_b.pack_id)


def test_diff_refuses_a_forged_identical_claim(evolving_workspace):
    """C-046: a forged manifest content_hash must not control the diff's
    identical verdict; verification fails before any comparison."""
    store, _doc, packs, manifest_a = evolving_workspace
    manifest_b = build_pack(store.db_path, packs, name="v2")
    manifest_path = packs / manifest_b.pack_id / "manifest.json"
    forged = json.loads(manifest_path.read_text(encoding="utf-8"))
    forged["content_hash"] = "sha256:" + "0" * 64
    manifest_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(PackIntegrityError):
        diff_packs(packs, manifest_a.pack_id, manifest_b.pack_id)


def test_api_pack_diff_refuses_a_tampered_pack(evolving_workspace, tmp_path):
    """The HTTP diff surface must report tamper as a typed error status,
    never a 200 comparison."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    store, _doc, packs, manifest_a = evolving_workspace
    manifest_b = build_pack(store.db_path, packs, name="v2")
    sqlite_b = packs / manifest_b.pack_id / "pack.sqlite"
    blob = bytearray(sqlite_b.read_bytes())
    blob[-1] ^= 0xFF
    sqlite_b.write_bytes(bytes(blob))
    app = create_app(data_dir=tmp_path / "data", packs_dir=packs)
    with TestClient(app) as client:
        res = client.get(
            f"/api/packs/{manifest_a.pack_id}/diff/{manifest_b.pack_id}"
        )
        assert res.status_code == 409
        assert manifest_b.pack_id in res.json()["detail"]


def test_cli_pack_diff(evolving_workspace, capsys):
    from ontologylab.main import main

    store, doc, packs, manifest_a = evolving_workspace
    insert(store, doc, [make_entity("SessionCache")])
    store.bulk_approve(by="tester")
    manifest_b = build_pack(store.db_path, packs, name="v2")

    with pytest.raises(SystemExit) as exc:
        main(["pack-diff", "--a", manifest_a.pack_id,
              "--b", manifest_b.pack_id, "--packs-dir", str(packs)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "added node: SessionCache" in out
    assert "nodes +1 -0 ~0" in out


def test_api_pack_diff(evolving_workspace, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    store, _doc, packs, manifest_a = evolving_workspace
    manifest_b = build_pack(store.db_path, packs, name="v1-rebuild")
    app = create_app(data_dir=tmp_path / "data", packs_dir=packs)
    with TestClient(app) as client:
        res = client.get(
            f"/api/packs/{manifest_a.pack_id}/diff/{manifest_b.pack_id}"
        )
        assert res.status_code == 200
        assert res.json()["summary"]["nodes_added"] == 0
        assert client.get(
            f"/api/packs/{manifest_a.pack_id}/diff/nope"
        ).status_code == 404


# ---------------------------------------------------------------------------
# Re-extraction harmony (the other half of W14): running extraction again
# over the same/updated content must reconcile with verified data instead
# of duplicating it.
# ---------------------------------------------------------------------------


def test_reextraction_merges_into_verified_graph(evolving_workspace):
    store, doc, _packs, _manifest_a = evolving_workspace

    gateway = make_entity("ApiGateway", aliases=["edge-proxy"])
    limiter = make_entity("RateLimiter")
    stats = insert(store, doc, [gateway, limiter],
                   [make_relation(gateway, limiter)])

    # same entities -> merged into the existing VERIFIED nodes (new alias
    # unions in); same triple -> a citation on the verified edge, no dupe
    assert stats["nodes_new"] == 0 and stats["nodes_merged"] == 2
    assert stats["edges_new"] == 0 and stats["edges_merged"] == 1
    counts = store.counts()
    assert counts["nodes_proposed"] == 0 and counts["nodes_verified"] == 2
    row = store.conn.execute(
        "SELECT aliases_json FROM nodes WHERE name = 'ApiGateway'"
    ).fetchone()
    assert "edge-proxy" in row["aliases_json"]


def test_reextraction_of_updated_document_adds_only_new_facts(
    evolving_workspace,
):
    store, _doc, _packs, _manifest_a = evolving_workspace
    # the "updated" document arrives as a new row (content-hash identity)
    doc2, created = store.insert_document(
        source_kind="upload", source_uri="file:///doc.txt", title="doc",
        raw_text="ApiGateway uses RateLimiter and SessionCache",
        content_hash="w14-h2",
    )
    assert created
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    cache = make_entity("SessionCache")
    stats = insert(store, doc2, [gateway, limiter, cache],
                   [make_relation(gateway, limiter),
                    make_relation(limiter, cache)])

    # only the genuinely new fact lands as proposed; the rest reconciled
    assert stats["nodes_new"] == 1 and stats["edges_new"] == 1
    counts = store.counts()
    assert counts["nodes_proposed"] == 1 and counts["edges_proposed"] == 1
    assert counts["nodes_verified"] == 2 and counts["edges_verified"] == 1
    # the verified edge gained a second-citation from the new document
    edge_id = store.conn.execute(
        "SELECT id FROM edges WHERE status = 'verified'"
    ).fetchone()["id"]
    assert len(store.citations("edge", edge_id)) == 2
