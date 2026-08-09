"""Pack byte-hash verification at MCP load time (P0-B).

``PackSession.load_pack()`` must recompute the pack's SHA-256 from the
CURRENT bytes of ``pack.sqlite`` and compare it against the manifest's
``content_hash`` receipt BEFORE touching session state:

- a tampered/corrupted pack is rejected with a typed integrity error and
  the previously active session keeps serving queries, undisturbed;
- a pack with no usable receipt (missing/unreadable manifest, missing or
  malformed hash) is classified UNVERIFIABLE with an explicit
  rebuild instruction — never silently loaded;
- a pack whose receipt matches its bytes loads and reports that hash.

Plan: .omo/plans/ontology-platform-roadmap.md (todo 2).
"""

from __future__ import annotations

import json
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
