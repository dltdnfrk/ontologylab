"""agrochem-v2 bundles polarity, diagnostics and the overlay into one install."""

from __future__ import annotations

import json

from ontologylab.extractor import build_extraction_prompt, chunk_document, parse_and_validate_extraction
from ontologylab.schemas import PRESETS, preset
from tests.conftest import insert
from tests.factories import make_entity, make_relation


def _install(store):
    schema = preset("agrochem-v2")
    return store.install_schema(
        label=schema["label"], description=schema["description"],
        entity_types=schema["entity_types"], relation_types=schema["relation_types"],
    )


def test_v1_preset_is_unchanged() -> None:
    v1 = PRESETS["agrochem"]
    assert v1["label"] == "agrochem-v1"
    assert all(not rt["qualifiers"] for rt in v1["relation_types"])
    assert "Question" not in {et["name"] for et in v1["entity_types"]}


def test_one_install_carries_every_claim_layer_change(store) -> None:
    before = store.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    _install(store)
    after = store.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert after == before + 1

    schema = store.get_schema()
    entities = {et["name"]: et for et in schema["entity_types"]}
    relations = {rt["name"]: rt for rt in schema["relation_types"]}
    assert {"Probe", "PerformanceMetric", "SampleMatrix"} <= set(entities)
    assert entities["Scenario"]["extractable"] is False
    assert relations["evidenced_by"]["extractable"] is False
    assert relations["controls"]["qualifiers"]["polarity"]["enum"] == [
        "supports", "refutes", "no_effect",
    ]
    assert relations["detects"]["qualifiers"]["polarity"]["required"] is False
    assert "polarity" not in relations["contains"]["qualifiers"]


def test_prompt_offers_polarity_but_no_overlay(store) -> None:
    _install(store)
    prompt = build_extraction_prompt(store.get_schema(), "Fluopyram controls Botrytis")
    assert "no_effect" in prompt
    for curated in ("Scenario", "Checklist", "evidenced_by", "predicts", "follows"):
        assert curated not in prompt


def test_v2_edges_keep_supports_and_no_effect_apart(store, doc) -> None:
    _install(store)
    for polarity in ("supports", "no_effect"):
        a = make_entity("Fluopyram", "ActiveIngredient")
        b = make_entity("Botrytis", "Pathogen")
        insert(store, doc, [a, b], [make_relation(a, b, "controls",
                                                  qualifiers={"polarity": polarity})])
    count = store.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE relation_type='controls'"
    ).fetchone()[0]
    assert count == 2


def test_prompt_tells_the_model_to_keep_null_results(store) -> None:
    _install(store)
    prompt = build_extraction_prompt(store.get_schema(), "text")
    assert '"no_effect" when it reports testing it and finding' in prompt


def test_parsed_null_result_carries_no_effect_polarity(store) -> None:
    _install(store)
    text = "Fluopyram had no significant effect on Botrytis."
    raw = "```json\n" + json.dumps({
        "entities": [
            {"name": "Fluopyram", "entity_type": "ActiveIngredient",
             "source_span": {"start": 0, "end": 9}},
            {"name": "Botrytis", "entity_type": "Pathogen",
             "source_span": {"start": 39, "end": 47}},
        ],
        "relations": [{
            "relation_type": "controls",
            "source": {"name": "Fluopyram", "entity_type": "ActiveIngredient"},
            "target": {"name": "Botrytis", "entity_type": "Pathogen"},
            "qualifiers": {"polarity": "no_effect"},
            "source_span": {"start": 0, "end": 48},
        }],
    }) + "\n```"
    result = parse_and_validate_extraction(
        raw, store.get_schema(), chunk_document(text)[0]
    )
    assert [r.qualifiers for r in result.relations] == [{"polarity": "no_effect"}]
