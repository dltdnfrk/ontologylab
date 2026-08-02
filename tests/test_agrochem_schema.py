"""The crop-protection ontology, and the one behaviour it exists for.

A preset is data, so most of it cannot be tested — whether `Pathogen` is
the right name for a thing is a question for a plant pathologist, not for
pytest. What is testable is the shape: a relation whose endpoint names a
type the schema never declares is a rule the extractor can never satisfy,
and every use of it is rejected.

The exception is `resistant_to`. Resistance is this field's central
time-varying claim — an active reported effective in 2015 is reported
failing in 2023 — and the decision was to record both and label when each
held, never to let the newer paper silently overwrite the older one. That
is behaviour, and it is pinned here.
"""

from __future__ import annotations

import pytest

from ontologylab.schemas import PRESETS, preset
from tests.conftest import make_entity, make_relation

_AXES = {
    "control": ("Crop", "Pathogen", "Pest", "Weed", "ActiveIngredient", "Product"),
    "mode_of_action": ("MoAGroup", "TargetSite", "ResistanceMutation"),
    "residue_safety": ("ResidueLimit", "ToxicityEndpoint", "NonTargetOrganism"),
    "formulation_trial": ("Formulation", "DoseRate", "Trial", "EfficacyOutcome"),
}


def _install(store):
    schema = preset("agrochem")
    return store.install_schema(
        label=schema["label"],
        description=schema["description"],
        entity_types=schema["entity_types"],
        relation_types=schema["relation_types"],
    )


def test_the_preset_is_bundled_under_a_versioned_label() -> None:
    assert "agrochem" in PRESETS
    assert preset("agrochem")["label"] == "agrochem-v1"


def test_every_relation_endpoint_is_a_type_the_schema_declares() -> None:
    """An undeclared endpoint is a rule no extraction can ever satisfy."""
    schema = preset("agrochem")
    declared = {entity["name"] for entity in schema["entity_types"]}

    for relation in schema["relation_types"]:
        for side in ("domain_type", "range_type"):
            value = relation[side]
            assert value == "*" or value in declared, (
                f"{relation['name']}.{side}={value!r} is not a declared type"
            )


@pytest.mark.parametrize("axis, types", sorted(_AXES.items()))
def test_all_four_axes_are_present(axis, types) -> None:
    declared = {entity["name"] for entity in preset("agrochem")["entity_types"]}
    assert set(types) <= declared, f"{axis} is missing {set(types) - declared}"


def test_organisms_and_actives_carry_their_registry_identifier() -> None:
    """Names do not resolve "Botrytis cinerea" to "grey mould"; codes do.

    The resolution key is string-based, so a domain with authoritative
    identifiers has to carry them or lose the only reliable join it has.
    """
    attrs = {
        entity["name"]: set(entity["attributes"])
        for entity in preset("agrochem")["entity_types"]
    }

    for organism in ("Crop", "Pathogen", "Pest", "Weed"):
        assert "eppo_code" in attrs[organism]
    assert "cas_number" in attrs["ActiveIngredient"]
    assert {"scheme", "code"} <= attrs["MoAGroup"]


def test_installing_it_makes_it_the_active_ontology(store) -> None:
    version_id = _install(store)

    active = store.active_schema_version()
    assert active["id"] == version_id
    assert active["label"] == "agrochem-v1"

    stored_types = {
        row["name"]
        for row in store.conn.execute(
            "SELECT name FROM entity_type WHERE schema_version_id = ?", (version_id,)
        )
    }
    assert {"Crop", "Pathogen", "ActiveIngredient", "MoAGroup"} <= stored_types


def test_a_resistance_report_does_not_overwrite_the_control_claim(
    store, doc
) -> None:
    """Q2'(a): both facts are recorded, each labelled with when it held.

    2015 says boscalid controls Botrytis; 2023 says that population is
    resistant. Neither is a mistake, and collapsing them into one current
    truth would make the pack answer "does this still work?" wrongly in
    whichever direction the last paper pointed.
    """
    _install(store)
    active = make_entity("boscalid", entity_type="ActiveIngredient")
    pathogen = make_entity("Botrytis cinerea", entity_type="Pathogen")
    controls = make_relation(active, pathogen, "controls")
    store.insert_proposed(
        [active, pathogen], [controls],
        source_doc_id=doc.id, extractor_engine="mock",
    )

    resistant = make_relation(pathogen, active, "resistant_to")
    # The same entities are passed again, not omitted: relation endpoints are
    # bound through this call's own resolution map, and resolution merges them
    # onto the nodes the first call created.
    store.insert_proposed([active, pathogen], [resistant], source_doc_id=doc.id,
                          extractor_engine="mock")

    rows = {
        row["relation_type"]: row["invalidated_ts"]
        for row in store.conn.execute(
            "SELECT relation_type, invalidated_ts FROM edges"
        )
    }
    assert rows == {"controls": None, "resistant_to": None}


def test_superseding_a_control_claim_keeps_it_auditable(store, doc) -> None:
    """Invalidation is not deletion: the retired claim stays queryable.

    Approval comes first because only a verified edge can be invalidated —
    a proposal that turned out wrong is rejected, never retired, so the
    bitemporal history only ever holds claims a human once accepted.
    """
    _install(store)
    active = make_entity("boscalid", entity_type="ActiveIngredient")
    pathogen = make_entity("Botrytis cinerea", entity_type="Pathogen")
    controls = make_relation(active, pathogen, "controls")
    stats = store.insert_proposed(
        [active, pathogen], [controls],
        source_doc_id=doc.id, extractor_engine="mock",
    )
    for node_id in stats["id_map"].values():
        store.approve(node_id, by="tester")
    store.approve(controls.id, by="tester")

    store.invalidate_edge(controls.id, by="tester", reason="SdhB H272R reported")

    row = store.conn.execute(
        "SELECT invalidated_ts, invalidated_by, invalidation_reason, valid_from "
        "FROM edges WHERE id = ?",
        (controls.id,),
    ).fetchone()
    assert row["invalidated_ts"] is not None
    assert row["invalidated_by"] == "tester"
    assert row["invalidation_reason"] == "SdhB H272R reported"
    assert row["valid_from"] is not None
