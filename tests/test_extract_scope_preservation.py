"""Offline extraction contracts, not a measurement of model recall.

The scripted engine supplies source-grounded findings independently of the
prompt. These tests exercise parsing, normalization, lifecycle and real store
identity; the preregistered live trial must measure whether a model follows
the guidance.
"""

from __future__ import annotations

import json

import pytest

from ontologylab import extractor
from ontologylab.extractor import Chunk, build_extraction_prompt, parse_and_validate_extraction
from ontologylab.schemas import preset
from tests.test_engine_json_retry import CountingEngine, drive


@pytest.fixture
def agrochem_store(store):
    schema = preset("agrochem-v2")
    store.install_schema(
        label=schema["label"], description=schema["description"],
        entity_types=schema["entity_types"], relation_types=schema["relation_types"],
    )
    return store


def test_prompt_ships_active_relation_definitions(agrochem_store):
    # Shipped-copy equality, not a pin on explanatory prose.
    schema = agrochem_store.get_schema()
    prompt = build_extraction_prompt(schema, "No findings.")
    relation_lines = {
        line.split(":", 1)[0][2:]: line
        for line in prompt.splitlines()
        if line.startswith("- ") and "(source type:" in line
    }
    expected = {
        relation["name"]: relation
        for relation in schema["relation_types"]
        if relation.get("extractable", True)
    }
    assert relation_lines.keys() == expected.keys()
    for name, relation in expected.items():
        assert relation_lines[name].split(": ", 1)[1].split(" (source type:", 1)[0] == (
            relation["description"]
        )
    assert "reduces" not in relation_lines


def test_scope_guidance_is_shipped_for_preset_and_installed_schema(agrochem_store):
    for schema in (preset("agrochem-v2"), agrochem_store.get_schema()):
        prompt = build_extraction_prompt(schema, "No findings.")
        assert prompt.count(extractor._AGROCHEM_GUIDANCE) == 1
    assert extractor._AGROCHEM_GUIDANCE not in build_extraction_prompt(
        preset("software-docs"), "No findings."
    )
    assert extractor.PROMPT_VERSION == "extract-v9"


# Constructed passages; none are taken from the frozen polarity gold corpus.
# Each pair deliberately differs in scope or relation despite shared tokens.
@pytest.mark.parametrize("text, claims", [
    (
        "Agent Cedar inhibited growth of Fungus delta isolate L in vitro. "
        "Agent Cedar controlled leaf blotch disease in the crop trial.",
        [
            ("Agent Cedar", "ActiveIngredient", "inhibits",
             "Fungus delta isolate L", "Pathogen", "supports"),
            ("Agent Cedar", "ActiveIngredient", "controls",
             "leaf blotch disease", "Disease", "supports"),
        ],
    ),
    (
        "Agent Cedar controlled R meadowgrass population. "
        "Agent Cedar had no significant effect on S meadowgrass population.",
        [
            ("Agent Cedar", "ActiveIngredient", "controls",
             "R meadowgrass population", "Weed", "supports"),
            ("Agent Cedar", "ActiveIngredient", "controls",
             "S meadowgrass population", "Weed", "no_effect"),
        ],
    ),
    (
        "Agent Cedar controlled Beetle delta larvae. "
        "Agent Cedar was ineffective against Beetle delta adults.",
        [
            ("Agent Cedar", "ActiveIngredient", "controls",
             "Beetle delta larvae", "Pest", "supports"),
            ("Agent Cedar", "ActiveIngredient", "controls",
             "Beetle delta adults", "Pest", "refutes"),
        ],
    ),
    (
        "Agent Cedar did not significantly reduce Beetle delta oviposition. "
        "Agent Cedar controlled Beetle delta.",
        [
            ("Agent Cedar", "ActiveIngredient", "inhibits",
             "Beetle delta oviposition", "Pathway", "no_effect"),
            ("Agent Cedar", "ActiveIngredient", "controls",
             "Beetle delta", "Pest", "supports"),
        ],
    ),
    (
        "Agent Cedar inhibited Fungus delta isolate L. "
        "Agent Cedar did not significantly inhibit Fungus delta isolate M.",
        [
            ("Agent Cedar", "ActiveIngredient", "inhibits",
             "Fungus delta isolate L", "Pathogen", "supports"),
            ("Agent Cedar", "ActiveIngredient", "inhibits",
             "Fungus delta isolate M", "Pathogen", "no_effect"),
        ],
    ),
    (
        "Bacterium delta strain J controlled leaf blotch disease. "
        "Bacterium delta strain K did not significantly control leaf blotch disease.",
        [
            ("Bacterium delta strain J", "Pathogen", "controls",
             "leaf blotch disease", "Disease", "supports"),
            ("Bacterium delta strain K", "Pathogen", "controls",
             "leaf blotch disease", "Disease", "no_effect"),
        ],
    ),
    (
        "Agent Cedar + Adjuvant Elm controlled R meadowgrass population. "
        "Agent Cedar alone was ineffective against R meadowgrass population.",
        [
            ("Agent Cedar + Adjuvant Elm", "Product", "controls",
             "R meadowgrass population", "Weed", "supports"),
            ("Agent Cedar", "ActiveIngredient", "controls",
             "R meadowgrass population", "Weed", "refutes"),
        ],
    ),
])
def test_scripted_findings_keep_relation_and_endpoint_identity(
    agrochem_store, tmp_path, text, claims,
):
    entities = {}
    relations = []
    expected = set()
    # Reviewed fixture annotations, independent of production post-processing.
    scopes = {
        "Fungus delta isolate L": ("Fungus delta", "Pathogen", "form_or_variant", "isolate L"),
        "Fungus delta isolate M": ("Fungus delta", "Pathogen", "form_or_variant", "isolate M"),
        "Bacterium delta strain J": ("Bacterium delta", "Pathogen", "form_or_variant", "strain J"),
        "Bacterium delta strain K": ("Bacterium delta", "Pathogen", "form_or_variant", "strain K"),
        "R meadowgrass population": ("meadowgrass", "Weed", "population_context", "R population"),
        "S meadowgrass population": ("meadowgrass", "Weed", "population_context", "S population"),
        "Beetle delta larvae": ("Beetle delta", "Pest", "form_or_variant", "larvae"),
        "Beetle delta adults": ("Beetle delta", "Pest", "form_or_variant", "adults"),
        "Beetle delta oviposition": ("Beetle delta", "Pest", "aspect", "oviposition"),
    }
    # Raw scripted inputs above still exercise normalization. Expectations are
    # reviewed literals, not a call back into the implementation being tested.
    normalized_values = {
        "isolate L": "isolate:l", "isolate M": "isolate:m",
        "strain J": "strain:j", "strain K": "strain:k",
        "R population": "rpopulation", "S population": "spopulation",
        "larvae": "life_stage:larva", "adults": "life_stage:adult",
    }
    for source, source_type, relation, target, target_type, polarity in claims:
        qualifiers = {"polarity": polarity}
        endpoints = []
        for side, name, entity_type in (
            ("subject", source, source_type), ("object", target, target_type),
        ):
            if name in scopes:
                name, entity_type, slot, value = scopes[name]
                key = f"{slot}_qualifier" if slot == "population_context" else f"{side}_{slot}_qualifier"
                qualifiers[key] = value
            endpoints.extend((name, entity_type))
        source, source_type, target, target_type = endpoints
        for name, entity_type in ((source, source_type), (target, target_type)):
            start = text.index(name)
            entities[name, entity_type] = {
                "name": name, "entity_type": entity_type, "aliases": [],
                "source_span": {"start": start, "end": start + len(name)},
            }
        relations.append({
            "source": {"name": source, "entity_type": source_type},
            "target": {"name": target, "entity_type": target_type},
            "relation_type": relation, "qualifiers": qualifiers,
        })
        expected.add((source, source_type, relation, target, target_type,
                      json.dumps({
                          key: normalized_values.get(value, value)
                          for key, value in qualifiers.items()
                      }, sort_keys=True)))
    engine = CountingEngine([json.dumps({
        "entities": list(entities.values()), "relations": relations,
    })])

    outcome, _ = drive(agrochem_store, tmp_path, engine, text=text)

    assert outcome == "" and not outcome.chunk_failed
    assert engine.calls == 2
    nodes = agrochem_store.conn.execute("SELECT * FROM nodes").fetchall()
    assert len(nodes) == len(entities)
    assert {(node["name"], node["entity_type"]) for node in nodes} == entities.keys()
    assert len({node["id"] for node in nodes}) == len(entities)
    for node in nodes:
        span = json.loads(node["source_span"])
        assert text[span["start"]:span["end"]] == node["name"]
        assert node["status"] == "proposed"
        assert node["prompt_version"] == "extract-v9"
    rows = agrochem_store.conn.execute(
        "SELECT s.name, s.entity_type, e.relation_type, t.name, t.entity_type, "
        "e.qualifiers_json FROM edges e "
        "JOIN nodes s ON s.id=e.src_node_id JOIN nodes t ON t.id=e.dst_node_id"
    ).fetchall()
    assert len(rows) == len(relations)
    assert {
        (*tuple(row)[:5], json.dumps(json.loads(row[5]), sort_keys=True)) for row in rows
    } == expected
    assert agrochem_store.conn.execute("SELECT COUNT(*) FROM node_aliases").fetchone()[0] == 0


def test_undeclared_reduces_is_rejected_not_silently_remapped():
    text = "Agent Cedar reduced Beetle delta oviposition."
    raw = json.dumps({"relations": [{
        "source": {"name": "Agent Cedar", "entity_type": "ActiveIngredient"},
        "target": {"name": "Beetle delta oviposition", "entity_type": "Pathway"},
        "relation_type": "reduces",
    }]})

    result = parse_and_validate_extraction(raw, preset("agrochem-v2"), Chunk(0, 0, text))

    assert result.relations == []
    assert any("unknown relation_type" in warning for warning in result.warnings)


def test_absent_population_qualifier_is_not_fabricated():
    raw = json.dumps({"entities": [{
        "name": "R meadowgrass population", "entity_type": "Weed",
    }]})

    result = parse_and_validate_extraction(
        raw, preset("agrochem-v2"), Chunk(0, 0, "Only meadowgrass was mentioned."),
    )

    assert result.entities == []
    assert any("name not found" in warning for warning in result.warnings)
