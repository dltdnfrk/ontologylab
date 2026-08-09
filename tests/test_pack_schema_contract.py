"""P0-D: multi-schema pack consumer contract.

A pack preserves verified facts extracted under EVERY schema version the
working store has held: proposals judged against v1 stay valid (and keep
pointing at v1) when v2 is installed and activated before the pack is
built. For a consumer to interpret such a pack without guessing, the
contract is:

- the manifest names every schema version whose verified facts the pack
  ships (``included_schema_version_ids``);
- schema.json carries each included version's full definition in a
  version-keyed ``schemas`` collection, with the top-level fields retained
  as the ACTIVE-schema compatibility alias;
- every packed fact's ``schema_version_id`` resolves to that exact
  version's definition FROM PACK CONTENTS — an unknown id is a typed
  lookup error, never a silent fallback to the active schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ontologylab.kgstore import KGStore, UnknownItem
from ontologylab.mcp_server import PackSession
from ontologylab.packbuilder import build_pack, pack_sqlite_path
from tests.conftest import insert, make_entity, make_relation

# Installed AFTER v1 facts are proposed, so the pack ships facts judged
# against two different ontology versions.
V2_SCHEMA: dict[str, Any] = {
    "label": "genes-v2",
    "description": "second ontology installed after v1 facts were proposed",
    "entity_types": [
        {"name": "Gene", "description": "a gene", "attributes": {}},
    ],
    "relation_types": [
        {
            "name": "interacts_with",
            "description": "gene-gene interaction",
            "domain_type": "Gene",
            "range_type": "Gene",
            "directed": False,
        },
    ],
}


def _build_pack(kg: Path, packs: Path, name: str):
    return build_pack(
        kg,
        packs,
        name=name,
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="synthetic multi-schema fixture",
    )


def _open_pack(packs: Path, pack_id: str) -> KGStore:
    return KGStore.open(pack_sqlite_path(packs, pack_id), read_only=True)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def two_schema_pack(tmp_path: Path):
    """Pack with verified facts judged under v1 (default) AND v2 (genes)."""
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///doc.txt",
        title="doc",
        raw_text="ApiGateway uses RateLimiter; BRCA1 interacts with TP53",
        content_hash="p0d-h1",
    )
    v1 = store.active_schema_version()["id"]
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    insert(store, doc, [gateway, limiter], [make_relation(gateway, limiter)])
    v2 = store.install_schema(**V2_SCHEMA)
    brca1 = make_entity("BRCA1", entity_type="Gene")
    tp53 = make_entity("TP53", entity_type="Gene")
    insert(
        store,
        doc,
        [brca1, tp53],
        [make_relation(brca1, tp53, relation_type="interacts_with")],
    )
    store.bulk_approve(by="tester")
    store.close()
    manifest = _build_pack(kg, packs, "multi")
    return kg, packs, manifest, v1, v2


def test_manifest_names_every_included_schema_version(two_schema_pack):
    _kg, packs, manifest, v1, v2 = two_schema_pack
    on_disk = _read_json(packs / manifest.pack_id / "manifest.json")
    assert on_disk.get("included_schema_version_ids") == sorted([v1, v2])
    assert manifest.included_schema_version_ids == sorted([v1, v2])


def test_schema_json_carries_every_included_version_definition(two_schema_pack):
    _kg, packs, manifest, v1, v2 = two_schema_pack
    schema_doc = _read_json(packs / manifest.pack_id / "schema.json")
    # Compatibility alias: the top level is still the ACTIVE schema (v2).
    assert schema_doc["schema_version_id"] == v2
    assert schema_doc["schema_label"] == "genes-v2"
    schemas = schema_doc.get("schemas")
    assert schemas is not None, (
        "schema.json must carry a version-keyed schemas collection so a "
        "consumer can resolve historical versions from pack contents"
    )
    assert set(schemas) == {str(v1), str(v2)}
    v1_doc = schemas[str(v1)]
    assert v1_doc["schema_version_id"] == v1
    assert v1_doc["schema_label"] == "software-docs-v1"
    assert {e["name"] for e in v1_doc["entity_types"]} >= {"Component"}
    assert schemas[str(v2)]["schema_label"] == "genes-v2"


def test_every_packed_facts_schema_version_resolves_from_pack_contents(
    two_schema_pack,
):
    _kg, packs, manifest, v1, v2 = two_schema_pack
    store = _open_pack(packs, manifest.pack_id)
    try:
        fact_versions = {
            row[0]
            for row in store.conn.execute(
                "SELECT schema_version_id FROM nodes "
                "UNION SELECT schema_version_id FROM edges"
            )
        }
        assert fact_versions == {v1, v2}
        for version_id in fact_versions:
            resolved = store.get_schema(schema_version_id=version_id)
            assert resolved["schema_version_id"] == version_id
        # The historical version resolves to ITS definition, not whatever
        # happens to be active in the pack.
        v1_doc = store.get_schema(schema_version_id=v1)
        assert v1_doc["schema_label"] == "software-docs-v1"
        assert {e["name"] for e in v1_doc["entity_types"]} >= {"Component"}
        assert store.get_schema(schema_version_id=v2)["schema_label"] == "genes-v2"
        # No-argument lookup keeps meaning ACTIVE — the compatibility alias.
        assert store.get_schema()["schema_version_id"] == v2
    finally:
        store.close()


def test_single_schema_pack_keeps_active_alias_and_resolves(tmp_path: Path):
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///doc.txt",
        title="doc",
        raw_text="ApiGateway uses RateLimiter",
        content_hash="p0d-h2",
    )
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    insert(store, doc, [gateway, limiter], [make_relation(gateway, limiter)])
    store.bulk_approve(by="tester")
    v1 = store.active_schema_version()["id"]
    before = store.get_schema()
    store.close()

    manifest = _build_pack(kg, packs, "single")

    schema_doc = _read_json(packs / manifest.pack_id / "schema.json")
    # The pre-contract export shape is untouched: same active alias fields.
    assert schema_doc["schema_version_id"] == before["schema_version_id"]
    assert schema_doc["schema_label"] == before["schema_label"]
    assert schema_doc["entity_types"] == before["entity_types"]
    assert schema_doc["relation_types"] == before["relation_types"]
    manifest_doc = _read_json(packs / manifest.pack_id / "manifest.json")
    assert manifest_doc.get("included_schema_version_ids") == [v1]
    assert set(schema_doc.get("schemas", {})) == {str(v1)}
    pack_store = _open_pack(packs, manifest.pack_id)
    try:
        assert (
            pack_store.get_schema(schema_version_id=v1)["entity_types"]
            == before["entity_types"]
        )
    finally:
        pack_store.close()


def test_unknown_schema_version_id_is_a_typed_error_not_active_fallback(
    two_schema_pack,
):
    _kg, packs, manifest, _v1, _v2 = two_schema_pack
    store = _open_pack(packs, manifest.pack_id)
    try:
        with pytest.raises(UnknownItem):
            store.get_schema(schema_version_id=999_999)
        # A malformed (non-integer) version id is the same typed refusal,
        # never a silent fallback to the active schema.
        malformed: Any = "not-a-version"
        with pytest.raises(UnknownItem):
            store.get_schema(schema_version_id=malformed)
    finally:
        store.close()


def test_mcp_session_resolves_each_version_from_the_pack(two_schema_pack):
    kg, packs, manifest, v1, v2 = two_schema_pack
    # Prove resolution comes from PACK bytes: the working KG is gone.
    kg.unlink()
    session = PackSession(packs)
    try:
        session.load_pack(manifest.pack_id)
        assert session.get_schema()["schema_version_id"] == v2
        assert (
            session.get_schema(schema_version_id=v1)["schema_label"]
            == "software-docs-v1"
        )
        assert session.get_schema(schema_version_id=v2)["schema_label"] == "genes-v2"
        with pytest.raises(UnknownItem):
            session.get_schema(schema_version_id=999_999)
    finally:
        session.close()


def test_legacy_pack_without_contract_fields_still_loads(two_schema_pack):
    """Packs written before this contract have no included_schema_version_ids
    and no schemas collection. They must still pass hash verification and
    serve per-version lookups from pack.sqlite: the new fields are additive
    receipts, never load gates."""
    _kg, packs, manifest, v1, v2 = two_schema_pack
    pack_dir = packs / manifest.pack_id
    manifest_doc = _read_json(pack_dir / "manifest.json")
    manifest_doc.pop("included_schema_version_ids", None)
    (pack_dir / "manifest.json").write_text(
        json.dumps(manifest_doc, indent=2), encoding="utf-8"
    )
    schema_doc = _read_json(pack_dir / "schema.json")
    schema_doc.pop("schemas", None)
    (pack_dir / "schema.json").write_text(
        json.dumps(schema_doc, indent=2), encoding="utf-8"
    )

    session = PackSession(packs)
    try:
        loaded = session.load_pack(manifest.pack_id)
        assert loaded["schema"]["schema_version_id"] == v2
        assert (
            session.get_schema(schema_version_id=v1)["schema_label"]
            == "software-docs-v1"
        )
    finally:
        session.close()
