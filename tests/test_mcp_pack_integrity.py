"""Pack byte-hash verification across the MCP named-pack read surface.
# noqa: SIZE_OK — single SUT integrity matrix; Task 10 owns this file

Every ``PackSession`` tool entry point that accepts a ``pack_id`` must
recompute the pack's SHA-256 from the CURRENT bytes of ``pack.sqlite`` and
compare it against the manifest's ``content_hash`` receipt before reading:

- a tampered/corrupted pack is rejected with a typed integrity error and
  the previously active session keeps serving queries, undisturbed;
- a pack with no usable receipt (missing/unreadable manifest, missing or
  malformed hash) is classified UNVERIFIABLE with an explicit
  rebuild instruction — never silently loaded;
- a pack whose receipt matches its bytes loads and reports that hash.

Plan: .omo/plans/ontology-platform-roadmap.md (todo 2).
"""

from __future__ import annotations

import inspect
import json
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ontologylab import mcp_server  # noqa: E402
from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.mcp_server import PackSession  # noqa: E402
from ontologylab.models import ProposedEntity, ProposedRelation  # noqa: E402
from ontologylab.packbuilder import build_pack, pack_sqlite_path  # noqa: E402


# Public entry points that open a NAMED, non-active pack. Every one must
# recompute the pack's SHA-256 from CURRENT bytes before reading — the
# introspection guard below fails when a newly-added named-pack tool is not
# classified here. (resource_method / resource_method_trace are exempt: they
# refuse any pack but the active one, which load_pack + _method_reader
# already verify.)
_NAMED_PACK_READ_ENTRY_POINTS = (
    "load_pack",
    "get_schema",
    "resource_schema",
    "resource_manifest",
)
# Same contract, but these need a second id argument.
_NAMED_PACK_ID_ENTRY_POINTS = (
    "resource_entity",
    "resource_term",
    "resource_xref",
)


def _build_fixture_pack(tmp_path: Path, name: str = "mcp-integrity") -> tuple[Path, str]:
    """Same fixture shape as tests/test_mcp_session.py:_build_fixture_pack."""
    kg = tmp_path / f"{name}-kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///doc.txt",
        title="doc",
        raw_text="RateLimiter implements TokenBucket algorithm for request throttling",
        content_hash=f"{name}-h1",
    )
    store.insert_proposed(
        [
            ProposedEntity(id="n_rl", entity_type="Component", name="RateLimiter"),
            ProposedEntity(
                id="n_tb", entity_type="Technique", name="TokenBucketAlgorithm"
            ),
        ],
        [
            ProposedRelation(
                id="e_uses",
                relation_type="uses",
                src_entity_id="n_rl",
                dst_entity_id="n_tb",
            )
        ],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.approve("n_rl")
    store.approve("n_tb")
    store.approve("e_uses")
    store.close()
    manifest = build_pack(
        kg, packs, name=name, allow_incomplete_extraction=True,
        incomplete_extraction_intent="synthetic MCP pack integrity fixture",
    )
    return packs, manifest.pack_id


def _flip_one_byte(path: Path) -> bytes:
    """Flip one byte in the middle of ``path``; return the original bytes."""
    original = path.read_bytes()
    tampered = bytearray(original)
    tampered[len(tampered) // 2] ^= 0xFF
    path.write_bytes(bytes(tampered))
    return original


def test_named_pack_read_surface_rejects_current_tampered_bytes(
    tmp_path: Path,
) -> None:
    public_named_pack_tools = {
        name
        for name, method in inspect.getmembers(PackSession, inspect.isfunction)
        if not name.startswith("_")
        and "pack_id" in inspect.signature(method).parameters
    }
    assert (
        set(_NAMED_PACK_READ_ENTRY_POINTS)
        | set(_NAMED_PACK_ID_ENTRY_POINTS)
        | {"resource_method", "resource_method_trace"}  # active-pack only
    ) == public_named_pack_tools

    packs, good_id = _build_fixture_pack(tmp_path, name="mcp-surface-good")
    _, tampered_id = _build_fixture_pack(tmp_path, name="mcp-surface-tampered")
    session = PackSession(packs)
    session.load_pack(good_id)
    before_id = session.pack_id
    before_hash = session.pack_hash

    sqlite_path = pack_sqlite_path(packs, tampered_id)
    original = sqlite_path.read_bytes()
    schema_label = b"Component"
    tampered_label = b"Tampered!"
    assert len(schema_label) == len(tampered_label)
    assert schema_label in original
    sqlite_path.write_bytes(original.replace(schema_label, tampered_label, 1))

    try:
        for entry_point in _NAMED_PACK_READ_ENTRY_POINTS:
            with pytest.raises(
                mcp_server.PackIntegrityError,
                match="(?i)(integrity|mismatch)",
            ):
                getattr(session, entry_point)(tampered_id)
            assert session.pack_id == before_id
            assert session.pack_hash == before_hash
    finally:
        session.close()


def test_resource_reads_verify_tampered_pack(tmp_path: Path) -> None:
    """pack:// resource reads used to open pack.sqlite WITHOUT the hash
    check that load_pack enforces — a byte-flipped pack that load_pack
    rejects was still served through resource_entity."""
    packs, good_id = _build_fixture_pack(tmp_path, name="res-good")
    _, bad_id = _build_fixture_pack(tmp_path, name="res-bad")
    session = PackSession(packs)
    session.load_pack(good_id)

    _flip_one_byte(pack_sqlite_path(packs, bad_id))
    try:
        for entry_point in _NAMED_PACK_READ_ENTRY_POINTS[2:]:
            with pytest.raises(mcp_server.PackIntegrityError):
                getattr(session, entry_point)(bad_id)
        for entry_point in _NAMED_PACK_ID_ENTRY_POINTS:
            with pytest.raises(mcp_server.PackIntegrityError):
                getattr(session, entry_point)(bad_id, "n_rl")
    finally:
        session.close()


def test_tampered_pack_rejected_and_prior_session_unchanged(tmp_path: Path) -> None:
    packs, good_id = _build_fixture_pack(tmp_path, name="mcp-good")
    _, tampered_id = _build_fixture_pack(tmp_path, name="mcp-tampered")
    session = PackSession(packs)
    session.load_pack(good_id)
    before_id = session.pack_id
    before_hash = session.pack_hash

    original = _flip_one_byte(pack_sqlite_path(packs, tampered_id))
    try:
        with pytest.raises(mcp_server.PackIntegrityError):
            session.load_pack(tampered_id)

        # Misleading-success guard: the rejected load must not disturb the
        # active session — it still answers queries, not merely keeps labels.
        assert session.pack_id == before_id
        assert session.pack_hash == before_hash
        lookup = session.entity_lookup(name="RateLimiter")
        assert lookup["count"] >= 1
        assert lookup["pack"]["pack_id"] == good_id
        assert lookup["pack"]["content_hash"] == before_hash

        # Stale-state guard: restoring the exact original bytes makes the
        # pack loadable again — verification reads CURRENT bytes every load,
        # never a cached verdict.
        pack_sqlite_path(packs, tampered_id).write_bytes(original)
        loaded = session.load_pack(tampered_id)
        assert loaded["pack_id"] == tampered_id
        assert session.pack_id == tampered_id
    finally:
        session.close()


def test_valid_pack_loads_and_reports_manifest_hash(tmp_path: Path) -> None:
    packs, pack_id = _build_fixture_pack(tmp_path)
    session = PackSession(packs)
    try:
        loaded = session.load_pack(pack_id)
        manifest = json.loads(
            (packs / pack_id / "manifest.json").read_text(encoding="utf-8")
        )
        assert loaded["pack_id"] == pack_id
        assert loaded["content_hash"] == manifest["content_hash"]
        assert loaded["content_hash"].startswith("sha256:")
        assert loaded["counts"]["nodes_verified"] == 2
        assert session.pack_hash == manifest["content_hash"]
    finally:
        session.close()


@pytest.mark.parametrize(
    "receipt",
    [
        pytest.param(None, id="hash-field-missing"),
        pytest.param("", id="hash-empty"),
        pytest.param("not-a-sha256-receipt", id="no-sha256-prefix"),
        pytest.param("sha256:not-hex-at-all", id="non-hex-digest"),
        pytest.param("sha256:abcd", id="truncated-digest"),
        pytest.param(12345, id="non-string-receipt"),
    ],
)
def test_pack_without_usable_receipt_is_unverifiable(
    tmp_path: Path, receipt: object
) -> None:
    packs, pack_id = _build_fixture_pack(tmp_path)
    manifest_path = packs / pack_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if receipt is None:
        manifest.pop("content_hash", None)
    else:
        manifest["content_hash"] = receipt
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    session = PackSession(packs)
    try:
        with pytest.raises(mcp_server.PackIntegrityError) as excinfo:
            session.load_pack(pack_id)
        message = str(excinfo.value).lower()
        assert "unverifiable" in message
        assert "rebuild" in message
        assert session.pack_id is None  # rejected load published nothing
    finally:
        session.close()


def test_truncated_manifest_is_unverifiable(tmp_path: Path) -> None:
    packs, pack_id = _build_fixture_pack(tmp_path)
    manifest_path = packs / pack_id / "manifest.json"
    raw = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(raw[: len(raw) // 2], encoding="utf-8")
    session = PackSession(packs)
    try:
        with pytest.raises(mcp_server.PackIntegrityError, match="(?i)unverifiable"):
            session.load_pack(pack_id)
        assert session.pack_id is None
    finally:
        session.close()


def test_missing_manifest_is_unverifiable(tmp_path: Path) -> None:
    packs, pack_id = _build_fixture_pack(tmp_path)
    (packs / pack_id / "manifest.json").unlink()
    session = PackSession(packs)
    try:
        with pytest.raises(mcp_server.PackIntegrityError, match="(?i)unverifiable"):
            session.load_pack(pack_id)
        assert session.pack_id is None
    finally:
        session.close()


def test_zero_byte_pack_sqlite_rejected(tmp_path: Path) -> None:
    packs, pack_id = _build_fixture_pack(tmp_path)
    pack_sqlite_path(packs, pack_id).write_bytes(b"")
    session = PackSession(packs)
    try:
        with pytest.raises(mcp_server.PackIntegrityError) as excinfo:
            session.load_pack(pack_id)
        assert "mismatch" in str(excinfo.value).lower()
        assert session.pack_id is None
    finally:
        session.close()


def _forge_content_hash(packs: Path, pack_id: str) -> None:
    manifest_path = packs / pack_id / "manifest.json"
    forged = json.loads(manifest_path.read_text(encoding="utf-8"))
    forged["content_hash"] = "sha256:" + ("0" * 64)
    forged["created_ts"] = 9_999_999_999.0
    forged["counts"] = {"nodes_verified": 12345, "edges_verified": 0}
    manifest_path.write_text(json.dumps(forged), encoding="utf-8")


def test_resource_manifest_refuses_source_rewrite_after_load(tmp_path: Path) -> None:
    """Tampered resource: activation must freeze the served manifest."""
    packs, good_id = _build_fixture_pack(tmp_path, name="res-freeze")
    session = PackSession(packs)
    try:
        session.load_pack(good_id)
        original = session.resource_manifest(good_id)
        manifest_path = packs / good_id / "manifest.json"
        forged = json.loads(manifest_path.read_text(encoding="utf-8"))
        forged["attacker"] = "yes"
        forged["counts"] = {"nodes_verified": 999}
        manifest_path.write_text(json.dumps(forged), encoding="utf-8")
        served = session.resource_manifest(good_id)
        assert served.get("attacker") is None
        assert served.get("counts") == original.get("counts")
    finally:
        session.close()


def test_staleness_refuses_forged_latest_manifest(tmp_path: Path) -> None:
    """Staleness must not consume raw latest counts before verify."""
    packs, good_id = _build_fixture_pack(tmp_path, name="stale-good")
    _, bad_id = _build_fixture_pack(tmp_path, name="stale-bad")
    _forge_content_hash(packs, bad_id)
    session = PackSession(packs)
    try:
        result = session.get_staleness()
        assert result["latest_pack_id"] != bad_id
        assert result["latest_pack_id"] == good_id
        assert result["pack_verified_count"] != 12345
    finally:
        session.close()


def test_list_packs_refuses_raw_unverified_path(tmp_path: Path) -> None:
    """Discovery may list an unverified directory only as unusable."""
    packs, good_id = _build_fixture_pack(tmp_path, name="list-good")
    _, bad_id = _build_fixture_pack(tmp_path, name="list-bad")
    _forge_content_hash(packs, bad_id)
    session = PackSession(packs)
    try:
        listed = session.list_packs()
        ids = {row["pack_id"] for row in listed["packs"]}
        assert good_id in ids
        assert bad_id not in ids
    finally:
        session.close()


def test_load_pack_opens_detached_immutable_snapshot(tmp_path: Path) -> None:
    """Writable/source-path: serve a copy, not the mutable source inode."""
    packs, pack_id = _build_fixture_pack(tmp_path, name="snap-open")
    session = PackSession(packs)
    try:
        loaded = session.load_pack(pack_id)
        source = packs / pack_id / "pack.sqlite"
        serving = Path(loaded["sqlite_path"])
        assert serving.resolve() != source.resolve()
        assert serving.stat().st_ino != source.stat().st_ino
        assert stat.S_IMODE(serving.stat().st_mode) & 0o222 == 0
        assert session.store is not None
        with pytest.raises(sqlite3.Error):
            session.store.conn.execute("UPDATE nodes SET name = 'mutated'")
            session.store.conn.commit()
        before = session.entity_lookup(name="RateLimiter")
        assert before["count"] >= 1
        source.write_bytes(source.read_bytes() + b"\x00")
        after = session.entity_lookup(name="RateLimiter")
        assert after["matches"][0]["id"] == before["matches"][0]["id"]
        assert after["pack"]["content_hash"] == loaded["content_hash"]
    finally:
        session.close()


def test_failed_switch_keeps_prior_session_byte_identical(tmp_path: Path) -> None:
    """Failed replacement must leave the previous serving snapshot intact."""
    packs, good_id = _build_fixture_pack(tmp_path, name="switch-good")
    _, bad_id = _build_fixture_pack(tmp_path, name="switch-bad")
    session = PackSession(packs)
    try:
        loaded = session.load_pack(good_id)
        serving = Path(loaded["sqlite_path"])
        before_bytes = serving.read_bytes()
        before_ino = serving.stat().st_ino
        before_hash = session.pack_hash
        before_lookup = session.entity_lookup(name="RateLimiter")
        _flip_one_byte(pack_sqlite_path(packs, bad_id))
        with pytest.raises(mcp_server.PackIntegrityError):
            session.load_pack(bad_id)
        assert session.pack_id == good_id
        assert session.pack_hash == before_hash
        assert session.store is not None
        assert Path(session.store.db_path).stat().st_ino == before_ino
        assert Path(session.store.db_path).read_bytes() == before_bytes
        assert session.entity_lookup(name="RateLimiter") == before_lookup
        manifest_path = packs / good_id / "manifest.json"
        forged = json.loads(manifest_path.read_text(encoding="utf-8"))
        forged["attacker"] = "switch"
        manifest_path.write_text(json.dumps(forged), encoding="utf-8")
        assert session.resource_manifest(good_id).get("attacker") is None
    finally:
        session.close()
