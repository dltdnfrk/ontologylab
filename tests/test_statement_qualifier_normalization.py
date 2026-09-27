"""Independent expected values and real-store checks for qualified scope."""

import json
import sqlite3

import pytest

from ontologylab.kgstore import KGStore, SchemaValidationError
from ontologylab.polarity_eval import score_polarity
from ontologylab.qualified_polarity_eval import qualifiers_cover
from ontologylab.statement_qualifiers import normalize_statement_value
from tests.conftest import insert
from tests.factories import make_entity, make_relation
from tests.test_polarity_eval import _fixture_gold
from tests.test_statement_qualifier_validation import qualified_store


@pytest.mark.parametrize("key,surface,expected", [
    ("study_context", " Field experiment ", "field_trial"),
    ("study_context", "in-vitro", "in_vitro"),
    ("study_context", "glasshouse screening", "greenhouse"),
    ("study_context", "Bioassay 2", "bioassay:2"),
    ("study_context", "Crop trial 1", "crop_trial:1"),
    ("study_context", "unlisted assay", "other:unlisted assay"),
    ("object_aspect_qualifier", "fresh-weight", "fresh_weight"),
    ("subject_aspect_qualifier", "bubble development", "bubble_development"),
    ("application_timing", "early\u2010postemergence", "early_post_emergence"),
    ("application_timing", "postemergence", "post_emergence"),
    ("object_direction_qualifier", "no change", "unchanged"),
    ("subject_direction_qualifier", "decreasing", "decreased"),
    ("object_form_or_variant_qualifier", "larvae", "life_stage:larva"),
    ("object_form_or_variant_qualifier", "life stage:larvae", "life_stage:larva"),
    ("subject_form_or_variant_qualifier", "Strain Sa2-V6", "strain:sa2v6"),
    ("object_form_or_variant_qualifier", "isolate 620", "isolate:620"),
    ("subject_form_or_variant_qualifier", "QST 713", "other:qst713"),
    ("population_context_qualifier", "R Population", "rpopulation"),
    ("population_context_qualifier", "Michigan 2020 sampled isolates", "michigan2020sampledisolates"),
    ("dose", "dilute doses", "dilute"),
    ("dose", "250 g/ha", "0.25 kg/ha"),
    ("dose", "1680 g a.i. ha\u22121", "1.68 kg/ha a.i."),
    ("dose", "95 or 190 g/ha", "0.095 or 0.19 kg/ha"),
    ("dose", "0.1 mg/L", "0.1 mg/L"),
    ("dose", "01 mg/L", "1 mg/L"),
    ("dose", "1x recommended rate", "1x recommended rate"),
    ("dose", "0.1 unsupported", "0.1 unsupported"),
])
def test_explicit_synonyms_and_units_are_idempotent(key, surface, expected):
    assert normalize_statement_value(key, surface) == expected
    assert normalize_statement_value(key, expected) == expected


@pytest.mark.parametrize("key,left,right", [
    ("study_context", "bioassay 1", "bioassay 2"),
    ("study_context", "crop trial 1", "field trial 1"),
    ("study_context", "jar bioassay", "bioassay"),
    ("study_context", "field trial", "field trails"),
    ("application_timing", "early-postemergence", "postemergence"),
    ("application_timing", "preemergence and early-postemergence", "preemergence"),
    ("object_aspect_qualifier", "growth", "mortality"),
    ("object_form_or_variant_qualifier", "strain 620", "isolate 620"),
    ("population_context_qualifier", "Michigan 2020", "Michigan 2022"),
    ("dose", "0.1 mg/L", "01 mg/L"),
    ("dose", "250 g a.i./ha", "250 g a.e./ha"),
    ("dose", "250 g a.i./ha", "250 g/ha"),
    ("dose", "95 or 190 g/ha", "95 g/ha"),
    ("dose", "0.1 unsupported", "01 unsupported"),
])
def test_different_scope_never_receives_credit(key, left, right):
    assert not qualifiers_cover({key: left}, {key: right})
    assert not qualifiers_cover({}, {key: left})


def test_store_normalizes_and_keeps_original_surface(qualified_store, doc):
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    raw = {
        "polarity": "no_effect", "study_context": "field experiment",
        "dose": "250 g/ha", "population_context_qualifier": "R population",
        "object_aspect_qualifier": "fresh-weight",
    }
    relation = make_relation(a, b, "controls", qualifiers=dict(raw))
    insert(qualified_store, doc, [a, b], [relation])
    row = qualified_store.conn.execute("SELECT * FROM edges").fetchone()
    expected = {
        "polarity": "no_effect", "study_context": "field_trial",
        "dose": "0.25 kg/ha", "population_context_qualifier": "rpopulation",
        "object_aspect_qualifier": "fresh_weight",
    }
    assert json.loads(row["qualifiers_json"]) == expected
    assert json.loads(row["properties_json"]) == {"raw_qualifiers": raw}
    assert relation.qualifiers == expected  # citation binding uses this object
    assert row["id"] == relation.id


def test_synonymous_writes_deduplicate_without_changing_edge_id(qualified_store, doc):
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    first = make_relation(a, b, "controls", qualifiers={
        "study_context": "field experiment", "dose": "250 g/ha",
    })
    second = make_relation(a, b, "controls", qualifiers={
        "study_context": "field trial", "dose": "0.25 kg/ha",
    })
    insert(qualified_store, doc, [a, b], [first])
    result = insert(qualified_store, doc, [a, b], [second])
    assert result["edges_merged"] == 1
    assert [r[0] for r in qualified_store.conn.execute("SELECT id FROM edges")] == [first.id]
    assert len(qualified_store.citations("edge", first.id)) == 2


def test_model_cannot_supply_platform_raw_qualifier_properties(qualified_store, doc):
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    edge = make_relation(a, b, "controls")
    edge.properties = {"raw_qualifiers": {"study_context": "invented"}}
    with pytest.raises(SchemaValidationError, match="undeclared properties"):
        insert(qualified_store, doc, [a, b], [edge])
    assert qualified_store.conn.execute("SELECT count(*) FROM edges").fetchone()[0] == 0


def test_scorer_normalizes_both_raw_sides_without_store_help(qualified_store, doc, tmp_path):
    path = _fixture_gold(tmp_path)
    raw = json.loads(path.read_text())
    raw["relations"] = [dict(raw["relations"][0], polarity="no_effect", qualifiers={
        "study_context": "field trial", "dose": "0.25 kg/ha",
    })]
    path.write_text(json.dumps(raw))
    a, b = make_entity("Treatment 0", "ActiveIngredient"), make_entity("target-pest", "Pest")
    edge = make_relation(a, b, "controls", qualifiers={"polarity": "no_effect"})
    insert(qualified_store, doc, [a, b], [edge])
    # Simulate a frozen pre-normalization export: bypass the new writer.
    predicted = json.dumps({
        "polarity": "no_effect", "study_context": "field experiment",
        "dose": "250 g/ha", "object_aspect_qualifier": "growth",
    })
    qualified_store.conn.execute("UPDATE edges SET qualifiers_json=?", (predicted,))
    result = score_polarity(qualified_store.conn, path, qualified=True)
    assert result["counts"]["matched_relations"] == 1
    assert result["recall_no_effect"]["numerator"] == 1
    assert result["four_tuple_f1"] == 1
    assert qualified_store.conn.execute("SELECT qualifiers_json FROM edges").fetchone()[0] == predicted
    assert qualifiers_cover({"study_context": "field trial"}, {"study_context": "field experiment"})
    assert qualifiers_cover({"study_context": "field experiment"}, {"study_context": "field trial"})


def test_existing_store_open_preserves_all_edge_bytes_and_legacy_ids(qualified_store, doc):
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    legacy = make_relation(a, b, "controls")
    scoped = make_relation(a, b, "controls", qualifiers={"study_context": "field"})
    insert(qualified_store, doc, [a, b], [legacy, scoped])
    copy = qualified_store.db_path.parent / "existing-normalization.sqlite"
    with sqlite3.connect(copy) as conn:
        qualified_store.conn.backup(conn)
        conn.execute(
            "UPDATE edges SET qualifiers_json=?, qualifiers_key=? WHERE id=?",
            ('{"study_context":"field experiment"}', '{"study_context":"field experiment"}', scoped.id),
        )
        before = conn.execute("SELECT * FROM edges ORDER BY id").fetchall()
    reopened = KGStore.open(copy)
    try:
        assert [tuple(r) for r in reopened.conn.execute("SELECT * FROM edges ORDER BY id")] == before
        result = insert(reopened, doc, [a, b], [make_relation(a, b, "controls")])
        assert result["edges_merged"] == 1
        assert len(reopened.citations("edge", legacy.id)) == 2
    finally:
        reopened.close()


def test_non_agrochem_qualifiers_keep_their_original_values(store, doc):
    store.install_schema(
        label="custom", description="Unrelated vocabulary",
        entity_types=[{"name": "Thing", "description": "", "attributes": {}}],
        relation_types=[{
            "name": "links", "description": "", "domain_type": "Thing", "range_type": "Thing",
            "directed": True, "qualifiers": {"study_context": {"type": "string"}},
        }],
    )
    a, b = make_entity("Alpha", "Thing"), make_entity("Beta", "Thing")
    insert(store, doc, [a, b], [make_relation(
        a, b, "links", qualifiers={"study_context": "field experiment"},
    )])
    assert json.loads(store.conn.execute("SELECT qualifiers_json FROM edges").fetchone()[0]) == {
        "study_context": "field experiment",
    }
