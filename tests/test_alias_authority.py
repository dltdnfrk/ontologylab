"""Wave 2.1 Step 4 (4C): registry alias authority classes.

Name is span-grounded (source_attested); parser-minted aliases are
model_unattested; registry/curator aliases are registry_supplied /
human_asserted. Only authorized surfaces may establish EPPO/CAS identity
(D11). Compatible authoritative identity collisions yield exactly one
human-decided merge candidate, never an auto-merge (C-033).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from ontologylab.alias_authority import authorized_surfaces, surface_plan
from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.normalization import normalize_proposal
from ontologylab.paths import eppo_registry_path
from ontologylab.schemas import preset
from ontologylab.registry import (
    CASRegistryCache,
    RegistryCache,
    import_eppo,
    import_pubchem,
)


def _eppo_cache(tmp_path: Path) -> RegistryCache:
    data_dir = tmp_path / "data"
    source = tmp_path / "eppo.csv"
    source.write_text(
        "code,name,type\n"
        "AYEPEX,Apera spica-venti,synonym\n"
        "AYEPEX,loose silkybent,synonym\n",
        encoding="utf-8",
    )
    import_eppo(source, data_dir)
    return RegistryCache(data_dir)


def _cas_cache(tmp_path: Path) -> CASRegistryCache:
    data_dir = tmp_path / "data"
    source = tmp_path / "pubchem.tsv"
    source.write_text(
        "14710509\tBoscalid\n14710509\t188425-85-6\n",
        encoding="utf-8",
    )
    import_pubchem(source, data_dir)
    return CASRegistryCache(data_dir)


def _entity(
    name: str,
    *,
    entity_type: str = "ActiveIngredient",
    aliases: list[str] | None = None,
    properties: dict | None = None,
) -> ProposedEntity:
    return ProposedEntity(
        id=uuid.uuid4().hex,
        entity_type=entity_type,
        name=name,
        aliases=aliases or [],
        properties=properties or {},
    )


def test_surface_plan_classifies_authority() -> None:
    plan = surface_plan(
        name="Apera spica-venti",
        aliases=["loose silkybent", "wind grass"],
        alias_authority={
            "loose silkybent": "human_asserted",
            "wind grass": "model_unattested",
        },
    )
    assert plan.authorized == ("Apera spica-venti", "loose silkybent")
    assert plan.unattested == ("wind grass",)
    # No classification map at all: legacy compatibility - everything passes.
    legacy = surface_plan(
        name="Apera spica-venti", aliases=["loose silkybent"],
        alias_authority=None,
    )
    assert legacy.authorized == ("Apera spica-venti", "loose silkybent")
    assert legacy.unattested == ()


def test_unattested_alias_cannot_establish_eppo_identity(tmp_path: Path) -> None:
    cache = _eppo_cache(tmp_path)
    proposal = _entity(
        "Apera",
        entity_type="Crop",
        aliases=["loose silkybent"],
        properties={"alias_authority": {"loose silkybent": "model_unattested"}},
    )
    result = normalize_proposal(proposal, cache)
    assert "eppo_code" not in result.properties
    assert result.properties["normalization"] == "no_eppo_match"
    assert result.properties["eppo_unattested_match_refused"] == "loose silkybent"


def test_human_asserted_alias_establishes_eppo_identity(tmp_path: Path) -> None:
    cache = _eppo_cache(tmp_path)
    proposal = _entity(
        "Apera",
        entity_type="Crop",
        aliases=["loose silkybent"],
        properties={"alias_authority": {"loose silkybent": "human_asserted"}},
    )
    result = normalize_proposal(proposal, cache)
    assert result.properties["eppo_code"] == "AYEPEX"
    assert "eppo_unattested_match_refused" not in result.properties


def test_unattested_alias_cannot_establish_cas_identity(tmp_path: Path) -> None:
    cache = _cas_cache(tmp_path)
    proposal = _entity(
        "Boscalid-ish",
        aliases=["Boscalid"],
        properties={"alias_authority": {"Boscalid": "model_unattested"}},
    )
    result = normalize_proposal(proposal, cache)
    assert "cas_number" not in result.properties
    assert result.properties["normalization"] == "no_cas_match"
    assert result.properties["cas_unattested_match_refused"] == "Boscalid"


def test_unclassified_legacy_proposal_resolves_via_alias(tmp_path: Path) -> None:
    """Compatibility: without a classification map the pre-4C behavior is
    byte-for-byte identical (digest-pinned AC-02 evidence relies on it)."""
    cache = _eppo_cache(tmp_path)
    proposal = _entity(
        "Apera", entity_type="Crop", aliases=["loose silkybent"],
    )
    result = normalize_proposal(proposal, cache)
    assert result.properties["eppo_code"] == "AYEPEX"


def test_same_cas_identity_yields_one_review_candidate_no_merge(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        schema = preset("agrochem")
        store.install_schema(
            label=schema["label"],
            description=schema["description"],
            entity_types=schema["entity_types"],
            relation_types=schema["relation_types"],
        )
        doc, _ = store.insert_document(
            source_kind="upload", source_uri="file:///cas.txt", title="cas",
            raw_text="two aliases one cas", content_hash="sha256:cas-doc",
        )
        first = _entity(
            "Boscalid", properties={"cas_number": "188425-85-6"},
        )
        second = _entity(
            "188425-85-6 product", properties={"cas_number": "188425-85-6"},
        )
        stats = store.insert_proposed(
            [first], [], source_doc_id=doc.id, extractor_engine="mock",
        )
        assert stats["nodes_new"] == 1
        stats2 = store.insert_proposed(
            [second], [], source_doc_id=doc.id, extractor_engine="mock",
        )
        assert stats2["nodes_new"] == 1  # second node materialized, not merged
        nodes = store.conn.execute(
            "SELECT id, status FROM nodes WHERE entity_type = 'ActiveIngredient'"
        ).fetchall()
        assert len(nodes) == 2
        candidates = store.conn.execute(
            "SELECT reasons_json FROM merge_candidates"
        ).fetchall()
        assert len(candidates) == 1
        assert "same-cas_number:188425-85-6" in candidates[0]["reasons_json"]
        # Rerun is idempotent: still exactly one candidate, never an auto-merge.
        store.insert_proposed(
            [_entity("188425-85-6 product", properties={"cas_number": "188425-85-6"})],
            [], source_doc_id=doc.id, extractor_engine="mock",
        )
        assert store.conn.execute(
            "SELECT COUNT(*) FROM merge_candidates"
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE entity_type = 'ActiveIngredient'"
        ).fetchone()[0] == 2
    finally:
        store.close()


def test_extractor_stamps_parser_aliases_model_unattested() -> None:
    """The extraction boundary stamps authority without needing the engine:
    the stamp function marks every parser-minted alias model_unattested and
    never overrides an existing classification."""
    from ontologylab.extractor import stamp_alias_authority

    proposal = _entity("X", aliases=["y", "z"])
    stamped = stamp_alias_authority(proposal)
    assert stamped.properties["alias_authority"] == {
        "y": "model_unattested", "z": "model_unattested",
    }
    existing = _entity(
        "X", aliases=["y"],
        properties={"alias_authority": {"y": "registry_supplied"}},
    )
    restamped = stamp_alias_authority(existing)
    assert restamped.properties["alias_authority"] == {"y": "registry_supplied"}
