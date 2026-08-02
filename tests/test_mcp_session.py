"""MCP PackSession tool logic — no mcp SDK required."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.mcp_server import NoActivePack, PackSession  # noqa: E402
from ontologylab.models import ProposedEntity, ProposedRelation  # noqa: E402
from ontologylab.packbuilder import build_pack  # noqa: E402


def _build_fixture_pack(tmp_path: Path) -> tuple[Path, str, str, str]:
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///doc.txt",
        title="doc",
        raw_text="RateLimiter implements TokenBucket algorithm for request throttling",
        content_hash="mcp-h1",
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
        kg, packs, name="mcp-demo", allow_incomplete_extraction=True,
        incomplete_extraction_intent="synthetic MCP session fixture",
    )
    return packs, manifest.pack_id, "n_rl", "n_tb"


def test_list_and_load_pack(tmp_path: Path) -> None:
    packs, pack_id, _, _ = _build_fixture_pack(tmp_path)
    session = PackSession(packs)
    listed = session.list_packs()
    assert listed["count"] == 1
    assert listed["packs"][0]["pack_id"] == pack_id

    with pytest.raises(NoActivePack):
        session.entity_lookup(name="RateLimiter")

    loaded = session.load_pack(pack_id)
    assert loaded["pack_id"] == pack_id
    assert loaded["counts"]["nodes_verified"] == 2
    session.close()


def test_query_tools_against_pack(tmp_path: Path) -> None:
    packs, pack_id, n_rl, n_tb = _build_fixture_pack(tmp_path)
    session = PackSession(packs)
    session.load_pack(pack_id)

    schema = session.get_schema()
    assert "entity_types" in schema or "schema_version_id" in schema

    lookup = session.entity_lookup(name="rate limiter", entity_type="Component")
    assert lookup["count"] >= 1
    assert lookup["matches"][0]["id"] == n_rl
    assert lookup["matches"][0]["status"] == "verified"
    assert "match_score" in lookup["matches"][0]

    search = session.semantic_search("TokenBucketAlgorithm")
    assert search["search_tier"] == "fts5"
    assert search["count"] >= 1

    gq = session.graph_query(entity_type="Component")
    assert any(n["id"] == n_rl for n in gq["nodes"])

    trav = session.traverse_relations([n_rl], max_hops=1)
    assert any(n["id"] == n_tb for n in trav["nodes"])

    path = session.find_path(n_rl, n_tb)
    assert path["found"] is True
    assert path["hop_count"] == 1

    session.close()


def test_autoload_single_pack(tmp_path: Path) -> None:
    packs, pack_id, _, _ = _build_fixture_pack(tmp_path)
    session = PackSession(packs)
    auto = session.try_autoload()
    assert auto == pack_id
    assert session.pack_id == pack_id
    session.close()
