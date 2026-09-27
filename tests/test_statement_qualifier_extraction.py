"""Scripted engines exercise qualified proposals without any model requests."""

import json

import pytest

from ontologylab.qualified_extraction import split_grounded_variants
from ontologylab.models import SourceSpan
from tests.factories import make_entity, make_relation
from tests.test_engine_json_retry import CountingEngine, drive
from tests.test_statement_qualifier_validation import qualified_store


def test_grounded_variants_become_distinct_statements_not_species_aliases(qualified_store, tmp_path):
    text = "Agent Cedar inhibited Fungus delta isolate L and Fungus delta isolate M in vitro."
    entities = [
        {"name": "Agent Cedar", "entity_type": "ActiveIngredient"},
        {"name": "Fungus delta isolate L", "entity_type": "Pathogen"},
        {"name": "Fungus delta isolate M", "entity_type": "Pathogen"},
    ]
    relations = [
        {"source": entities[0], "target": entity, "relation_type": "inhibits",
         "qualifiers": {"polarity": "supports", "study_context": "in vitro"},
         "source_span": {"start": 0, "end": len(text)}}
        for entity in entities[1:]
    ]
    engine = CountingEngine([json.dumps({"entities": entities, "relations": relations})])
    outcome, _ = drive(qualified_store, tmp_path, engine, text=text)
    assert not outcome.chunk_failed and engine.calls == 1
    assert [r[0] for r in qualified_store.conn.execute(
        "SELECT name FROM nodes WHERE entity_type='Pathogen'"
    )] == ["Fungus delta"]
    rows = qualified_store.conn.execute("SELECT qualifiers_json FROM edges").fetchall()
    assert {json.loads(r[0])["object_form_or_variant_qualifier"] for r in rows} == {
        "isolate L", "isolate M",
    }
    assert all("isolate" not in row[0] for row in qualified_store.conn.execute(
        "SELECT surface FROM node_aliases"
    ))


@pytest.mark.parametrize("case", ["outside_span", "conflict", "implicit", "unlinked"])
def test_unsafe_variant_recovery_leaves_the_original_proposal(case):
    text = "Agent Cedar inhibited Fungus delta. Elsewhere, Fungus delta isolate L."
    a = make_entity("Agent Cedar", "ActiveIngredient")
    b = make_entity("Fungus delta isolate L", "Pathogen")
    relation = make_relation(a, b, "inhibits", source_span=SourceSpan(0, 34))
    if case == "conflict":
        relation.source_span = SourceSpan(0, len(text))
        relation.qualifiers["object_form_or_variant_qualifier"] = "isolate M"
    elif case == "implicit":
        b.name = "isolate L"
    before = b.name, dict(relation.qualifiers)
    split_grounded_variants([a, b], [] if case == "unlinked" else [relation], text)
    assert (b.name, relation.qualifiers) == before
