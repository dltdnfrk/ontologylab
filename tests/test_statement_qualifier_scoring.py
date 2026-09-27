"""Qualified recall uses independent scopes, not a triple-only proxy."""

import json

import pytest

from ontologylab.polarity_eval import score_polarity
from tests.conftest import insert
from tests.factories import make_entity, make_relation
from tests.test_polarity_eval import _fixture_gold
from tests.test_statement_qualifier_validation import qualified_store


def _gold(tmp_path):
    path = _fixture_gold(tmp_path)
    raw = json.loads(path.read_text())
    raw["relations"] = [
        dict(raw["relations"][0], polarity="no_effect",
             qualifiers={"population_context_qualifier": "R population"}),
        dict(raw["relations"][0], polarity="supports",
             qualifiers={"population_context_qualifier": "S population"}),
    ]
    path.write_text(json.dumps(raw))
    return path


def _add(store, doc, qualifiers, *, alias=False):
    a = make_entity("Other treatment" if alias else "TREATMENT-0", "ActiveIngredient",
                    aliases=["Treatment 0"] if alias else [])
    b = make_entity("target-pest", "Pest")
    return insert(store, doc, [a, b], [make_relation(a, b, "controls", qualifiers=qualifiers)])


def test_scorer_requires_gold_qualifiers(qualified_store, doc, tmp_path):
    path = _gold(tmp_path)
    _add(qualified_store, doc, {"polarity": "no_effect"})
    result = score_polarity(qualified_store.conn, path, qualified=True)
    assert result["counts"]["matched_relations"] == 0
    assert result["recall_no_effect"]["numerator"] == 0
    assert result["four_tuple_f1"] == 0


def test_extra_qualifiers_and_aliases_match_but_wrong_population_does_not(qualified_store, doc, tmp_path):
    path = _gold(tmp_path)
    _add(qualified_store, doc, {
        "polarity": "no_effect", "population_context_qualifier": " R  POPULATION ",
        "study_context": "field",
    }, alias=True)
    result = score_polarity(qualified_store.conn, path, qualified=True)
    assert result["counts"]["matched_relations"] == 1
    assert result["recall_no_effect"]["value"] == 1
    assert result["confusion_matrix"]["supports"]["no_effect"] == 0
    assert result["four_tuple_f1"] == 2 / 3


def test_wrong_polarity_is_not_a_match_and_conflicts_cannot_cherry_pick(qualified_store, doc, tmp_path):
    path = _gold(tmp_path)
    for polarity in ("no_effect", "supports"):
        _add(qualified_store, doc, {"polarity": polarity, "population_context_qualifier": "R population"})
    result = score_polarity(qualified_store.conn, path, qualified=True)
    assert result["counts"]["matched_predictions"] == 2
    assert result["polarity_accuracy"]["value"] == 0.5
    assert result["supports_when_gold_no_effect_flip_rate"]["value"] == 1
    assert result["four_tuple_f1"] == 0.5


@pytest.mark.parametrize("slot", ["dose", "object_aspect_qualifier", "object_form_or_variant_qualifier", "study_context"])
def test_every_gold_slot_constrains_the_match(qualified_store, doc, tmp_path, slot):
    path = _gold(tmp_path)
    raw = json.loads(path.read_text())
    raw["relations"] = [dict(raw["relations"][0], qualifiers={slot: "expected"})]
    path.write_text(json.dumps(raw))
    _add(qualified_store, doc, {"polarity": "no_effect", slot: "different"})
    assert score_polarity(qualified_store.conn, path, qualified=True)["four_tuple_f1"] == 0
