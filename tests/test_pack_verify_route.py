"""POST /api/packs/{pack_id}/verify: the Packs screen's integrity re-check.

Pins the contract the dashboard reads — `{ok, pack_id, integrity_level,
problems}` — and the two refusals: 404 for an id no pack directory carries,
422 for an id that is not a safe single path segment. The route is read-only
by construction (the verifier copies the pack into a temporary serving
directory and discards it), so every case also pins that the packs
directory is byte-for-byte untouched afterwards and that no serving copy is
left behind.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.pack_verifier import verify_pack
from ontologylab.paths import kg_db_path
from tests.conftest import insert, make_entity


@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    with TestClient(app) as tc:
        yield tc


def _seed_one_verified_node(client) -> None:
    store = KGStore.open(kg_db_path(client.app.state.data_dir))
    try:
        doc, _ = store.insert_document(
            source_kind="upload",
            source_uri="file:///verify.txt",
            title="verify",
            raw_text="RateLimiter",
            content_hash="sha256:verify",
        )
        insert(store, doc, [make_entity("RateLimiter")])
        node_id = store.conn.execute("SELECT id FROM nodes").fetchone()["id"]
        store.approve(node_id, by="tester")
    finally:
        store.close()


def _build_pack(client, name: str) -> str:
    res = client.post(
        "/api/packs/build",
        json={
            "name": name,
            "allow_incomplete_extraction": True,
            "override_intent": "synthetic verify-route fixture",
        },
    )
    body = res.json()
    assert body["ok"] is True, body
    return body["manifest"]["pack_id"]


def _inventory(root: Path) -> list[tuple[str, int, int, int, str]]:
    """Every path under ``root`` with the facts a write would change."""
    rows = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        digest = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
        )
        rows.append(
            (
                str(path.relative_to(root)),
                info.st_size,
                info.st_mode,
                info.st_mtime_ns,
                digest,
            )
        )
    return rows


def _serving_copies_left_behind() -> list[Path]:
    tmp_root = Path(os.environ.get("TMPDIR", "/tmp"))
    return [
        path
        for path in tmp_root.glob(f"ontologylab-pack-{os.getpid()}-*")
        if path.is_dir()
    ]


def test_an_intact_pack_verifies_ok_without_touching_it(client, tmp_path) -> None:
    _seed_one_verified_node(client)
    pack_id = _build_pack(client, "intact")
    packs_dir = tmp_path / "packs"
    expected_level = verify_pack(packs_dir / pack_id).integrity_level
    before = _inventory(packs_dir)

    res = client.post(f"/api/packs/{pack_id}/verify")

    assert res.status_code == 200, res.text
    assert res.json() == {
        "ok": True,
        "pack_id": pack_id,
        "integrity_level": expected_level,
        "problems": [],
    }
    assert _inventory(packs_dir) == before
    assert _serving_copies_left_behind() == []


def test_a_tampered_sqlite_is_reported_as_a_problem(client, tmp_path) -> None:
    _seed_one_verified_node(client)
    pack_id = _build_pack(client, "tampered")
    packs_dir = tmp_path / "packs"
    sqlite_path = packs_dir / pack_id / "pack.sqlite"
    blob = bytearray(sqlite_path.read_bytes())
    blob[len(blob) // 2] ^= 0xFF
    sqlite_path.write_bytes(bytes(blob))
    before = _inventory(packs_dir)

    res = client.post(f"/api/packs/{pack_id}/verify")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is False
    assert body["pack_id"] == pack_id
    assert body["integrity_level"] is None
    assert len(body["problems"]) == 1
    assert "tampered_artifact" in body["problems"][0]
    assert "pack.sqlite" in body["problems"][0]
    # Detecting the tamper must not "repair" or otherwise rewrite the pack.
    assert _inventory(packs_dir) == before
    assert _serving_copies_left_behind() == []


def test_an_unknown_pack_id_is_404(client, tmp_path) -> None:
    res = client.post("/api/packs/no-such-pack/verify")

    assert res.status_code == 404, res.text
    assert "no-such-pack" in res.json()["detail"]
    assert not (tmp_path / "packs" / "no-such-pack").exists()


@pytest.mark.parametrize(
    ("raw_segment", "decoded_id"),
    [
        # A raw `../x` never reaches the server: the HTTP client folds the
        # dot segment away before sending. Percent-encoded, it arrives as
        # `../x` and must be refused by the route's own check, not by
        # falling through the router.
        ("..%2Fx", "../x"),
        ("%2e%2e%2fx", "../x"),
        ("..%2F..%2Fetc", "../../etc"),
        ("%2e%2e", ".."),
        ("bad%20id", "bad id"),
        ("%20", " "),
        ("bad%09id", "bad\tid"),
        # Gate review B1: Starlette's `path` convertor (`.*`) cannot match a
        # newline, so these two used to fall through the router as 404.
        ("bad%0Aid", "bad\nid"),
        # The trailing form additionally passed `safe_pack_component` while
        # its pattern ended in `$`, which matches before a final newline.
        ("bad%0A", "bad\n"),
        ("%00", "\x00"),
        ("", ""),
    ],
)
def test_an_unsafe_pack_id_is_422_before_the_filesystem_is_read(
    client, tmp_path, monkeypatch, raw_segment: str, decoded_id: str,
) -> None:
    from ontologylab.server import routes

    validated: list[str] = []
    real_validator = routes.safe_pack_component

    def _counting_validator(value: str, **kwargs):
        validated.append(value)
        return real_validator(value, **kwargs)

    def _no_filesystem(*args, **kwargs):
        raise AssertionError(
            f"the filesystem was consulted for unsafe pack id {decoded_id!r}"
        )

    monkeypatch.setattr(routes, "safe_pack_component", _counting_validator)
    monkeypatch.setattr(routes, "Path", _no_filesystem)
    packs_dir = tmp_path / "packs"
    before = _inventory(packs_dir) if packs_dir.exists() else None

    res = client.post(f"/api/packs/{raw_segment}/verify")

    assert res.status_code == 422, res.text
    assert repr(decoded_id) in res.json()["detail"]
    assert validated == [decoded_id]
    assert (_inventory(packs_dir) if packs_dir.exists() else None) == before
    assert not (tmp_path / "x").exists()
