"""The installed vocabulary fails closed before any graph write."""

import json

import pytest

from ontologylab.kgstore import SchemaValidationError
from ontologylab.kgstore_base import UnknownQualifierError
from ontologylab.schemas import AGROCHEM_STATEMENT_QUALIFIERS, preset
from tests.conftest import insert
from tests.factories import make_entity, make_relation


@pytest.fixture
def qualified_store(store):
    schema = preset("agrochem-v2")
    store.install_schema(
        label=schema["label"], description=schema["description"],
        entity_types=schema["entity_types"], relation_types=schema["relation_types"],
    )
    return store


def test_unknown_qualifiers_are_typed_refusals_before_writes(qualified_store, doc):
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    edge = make_relation(a, b, "controls", qualifiers={"invented_scope": "adult"})
    before = qualified_store.conn.total_changes
    with pytest.raises(UnknownQualifierError) as caught:
        insert(qualified_store, doc, [a, b], [edge])
    assert caught.value.qualifier == "invented_scope"
    assert qualified_store.conn.total_changes == before


@pytest.mark.parametrize("value", [None, "", "  ", 1, True, [], {}])
def test_qualifier_values_must_be_nonempty_strings(qualified_store, doc, value):
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    with pytest.raises(SchemaValidationError):
        insert(qualified_store, doc, [a, b], [
            make_relation(a, b, "controls", qualifiers={"study_context": value}),
        ])


def test_old_v2_declarations_gain_platform_vocabulary_without_rewrite(qualified_store, doc):
    conn = qualified_store.conn
    conn.execute("UPDATE relation_type SET qualifiers_json='{}' WHERE name='controls'")
    before = conn.execute(
        "SELECT qualifiers_json FROM relation_type WHERE name='controls'"
    ).fetchone()[0]
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    qualifiers = dict.fromkeys(AGROCHEM_STATEMENT_QUALIFIERS, "source label")
    insert(qualified_store, doc, [a, b], [
        make_relation(a, b, "controls", qualifiers=qualifiers),
    ])
    assert json.loads(conn.execute("SELECT qualifiers_json FROM edges").fetchone()[0]) == qualifiers
    assert conn.execute(
        "SELECT qualifiers_json FROM relation_type WHERE name='controls'"
    ).fetchone()[0] == before
    controls = next(r for r in qualified_store.get_schema()["relation_types"] if r["name"] == "controls")
    assert AGROCHEM_STATEMENT_QUALIFIERS.keys() <= controls["qualifiers"].keys()
