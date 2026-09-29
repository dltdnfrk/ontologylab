"""Comparison and observation time stay distinct in statement identity."""

import json
import sqlite3

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.schemas import AGROCHEM_STATEMENT_QUALIFIERS
from ontologylab.statement_qualifiers import (
    canonical_qualifiers,
    normalize_statement_value,
)
from tests.conftest import insert
from tests.factories import make_entity, make_relation
from tests.test_statement_qualifier_validation import qualified_store


_PRIOR_CANONICAL_KEY = (
    '{"dose":"0.25 kg/ha","object_aspect_qualifier":"fresh_weight",'
    '"study_context":"field_trial"}'
)
_PRIOR_EDGE = {
    "polarity": "supports",
    "study_context": "field_trial",
    "dose": "0.25 kg/ha",
    "object_aspect_qualifier": "fresh_weight",
}


def test_comparison_contexts_stay_distinct():
    # Given: two comparisons that share a treatment and differ only by comparator.
    untreated = canonical_qualifiers({
        "comparison_context_qualifier": "A vs untreated",
    })
    reference = canonical_qualifiers({
        "comparison_context_qualifier": "A vs reference",
    })
    # Then: identity keeps the key, and the two comparators do not collapse.
    assert untreated == '{"comparison_context_qualifier":"a vs untreated"}'
    assert reference == '{"comparison_context_qualifier":"a vs reference"}'
    assert untreated != reference


def test_observation_times_stay_distinct():
    day_7 = canonical_qualifiers({"observation_time_qualifier": "day 7"})
    day_14 = canonical_qualifiers({"observation_time_qualifier": "day 14"})
    assert day_7 == '{"observation_time_qualifier":"day 7"}'
    assert day_14 == '{"observation_time_qualifier":"day 14"}'
    assert day_7 != day_14


def test_edge_without_new_keys_keeps_prior_canonical_key():
    assert canonical_qualifiers(dict(_PRIOR_EDGE)) == _PRIOR_CANONICAL_KEY
    assert canonical_qualifiers({
        "polarity": "supports",
        "study_context": " In Vitro ",
    }) == '{"study_context":"in vitro"}'


@pytest.mark.parametrize("key,surface,expected", [
    ("comparison_context_qualifier", "untreated control", "untreated_control"),
    ("comparison_context_qualifier", "no treatment", "untreated_control"),
    ("comparison_context_qualifier", "Untreated", "untreated_control"),
    ("comparison_context_qualifier", "reference product", "reference"),
    ("comparison_context_qualifier", "reference", "reference"),
    ("comparison_context_qualifier", "A vs untreated", "other:a vs untreated"),
    ("comparison_context_qualifier", "A vs reference", "other:a vs reference"),
    ("comparison_context_qualifier", "other:a vs untreated", "other:a vs untreated"),
    ("observation_time_qualifier", "pre-treatment", "pre_treatment"),
    ("observation_time_qualifier", "pre treatment", "pre_treatment"),
    ("observation_time_qualifier", "posttreatment", "post_treatment"),
    ("observation_time_qualifier", "day 7", "other:day 7"),
    ("observation_time_qualifier", "day 14", "other:day 14"),
    ("observation_time_qualifier", "Day  7", "other:day 7"),
    ("observation_time_qualifier", "other:day 7", "other:day 7"),
    ("study_context", "field experiment", "field_trial"),
    ("dose", "0.1 mg/L", "0.1 mg/L"),
    ("application_timing", "postemergence", "post_emergence"),
    ("object_form_or_variant_qualifier", "larvae", "life_stage:larva"),
])
def test_attested_values_normalize_and_unknowns_keep_scope(key, surface, expected):
    assert normalize_statement_value(key, surface) == expected
    assert normalize_statement_value(key, expected) == expected


def test_new_keys_are_optional_closed_vocabulary():
    for key in ("comparison_context_qualifier", "observation_time_qualifier"):
        spec = AGROCHEM_STATEMENT_QUALIFIERS[key]
        assert spec["type"] == "string"
        assert spec["required"] is False


def _controls(scope):
    agent = make_entity("Agent", "ActiveIngredient")
    pest = make_entity("Pest", "Pest")
    relation = make_relation(
        agent, pest, "controls", qualifiers={"polarity": "supports", **scope},
    )
    return agent, pest, relation


def test_store_keeps_comparison_and_time_identities_apart(qualified_store, doc):
    # Given: one installed agrochem-v2 graph and four same-endpoint claims.
    scopes = (
        {"comparison_context_qualifier": "A vs untreated"},
        {"comparison_context_qualifier": "A vs reference"},
        {"observation_time_qualifier": "day 7"},
        {"observation_time_qualifier": "day 14"},
    )
    entities = []
    relations = []
    for scope in scopes:
        agent, pest, relation = _controls(scope)
        entities.extend((agent, pest))
        relations.append(relation)
    # When: the proposal boundary writes them.
    result = insert(qualified_store, doc, entities, relations)
    # Then: none merge, and the stored identity is the attested-only form.
    assert result["edges_merged"] == 0
    assert {
        row["qualifiers_key"]
        for row in qualified_store.conn.execute("SELECT qualifiers_key FROM edges")
    } == {
        '{"comparison_context_qualifier":"other:a vs untreated"}',
        '{"comparison_context_qualifier":"other:a vs reference"}',
        '{"observation_time_qualifier":"other:day 7"}',
        '{"observation_time_qualifier":"other:day 14"}',
    }


def test_installed_v2_schema_validates_old_edges_and_store_reopens(qualified_store, doc):
    # Given: a previously installed agrochem-v2 declaration without the new keys.
    conn = qualified_store.conn
    for row in conn.execute("SELECT name, qualifiers_json FROM relation_type"):
        declared = json.loads(row["qualifiers_json"] or "{}")
        declared.pop("comparison_context_qualifier", None)
        declared.pop("observation_time_qualifier", None)
        conn.execute(
            "UPDATE relation_type SET qualifiers_json=? WHERE name=?",
            (json.dumps(declared), row["name"]),
        )
    stored = {
        row["name"]: json.loads(row["qualifiers_json"])
        for row in conn.execute("SELECT name, qualifiers_json FROM relation_type")
    }
    assert stored["controls"]
    assert "comparison_context_qualifier" not in stored["controls"]
    assert "observation_time_qualifier" not in stored["controls"]
    agent, pest, relation = _controls({})
    relation.qualifiers = dict(_PRIOR_EDGE)
    # When: an old edge is written and the store is opened again.
    insert(qualified_store, doc, [agent, pest], [relation])
    copy = qualified_store.db_path.parent / "pre-comparison.sqlite"
    with sqlite3.connect(copy) as raw:
        qualified_store.conn.backup(raw)
        before = [tuple(item) for item in raw.execute("SELECT * FROM edges ORDER BY id")]
    reopened = KGStore.open(copy)
    try:
        after = [
            tuple(item) for item in reopened.conn.execute("SELECT * FROM edges ORDER BY id")
        ]
        # Then: the old edge validated, its identity is unchanged, and open kept every byte.
        assert len(before) == 1
        assert after == before
        row = reopened.conn.execute("SELECT qualifiers_json, qualifiers_key FROM edges").fetchone()
        assert json.loads(row["qualifiers_json"]) == _PRIOR_EDGE
        assert row["qualifiers_key"] == _PRIOR_CANONICAL_KEY
        declarations = {
            item["name"]: json.loads(item["qualifiers_json"])
            for item in reopened.conn.execute("SELECT name, qualifiers_json FROM relation_type")
        }
        assert declarations == stored
    finally:
        reopened.close()
