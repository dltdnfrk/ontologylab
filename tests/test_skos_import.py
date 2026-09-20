"""SKOS import: Turtle subset → schema_version with hierarchy, aliases, xrefs."""

from __future__ import annotations

import pytest

from ontologylab.kgstore import KGStoreError
from ontologylab.skos_import import (
    SkosParseError,
    import_skos,
    parse_skos_turtle,
)

SAMPLE = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/agro#> .

ex:Component a skos:Concept ;
    skos:prefLabel "Component" ;
    skos:definition "A software artifact." .

ex:Service a skos:Concept ;
    skos:prefLabel "Service" ;
    skos:altLabel "Microservice"@en ;
    skos:hiddenLabel "svc" ;
    skos:broader ex:Component ;
    skos:exactMatch <http://external.org/types/Service> ;
    skos:definition "A running component." .

ex:Database a skos:Concept ;
    skos:prefLabel "Database" ;
    skos:broader ex:Component .
"""


def test_parse_concepts_with_labels_and_broader():
    concepts = parse_skos_turtle(SAMPLE)
    assert len(concepts) == 3
    svc = concepts["http://example.org/agro#Service"]
    assert svc.pref_label == "Service"
    assert svc.broader == ["http://example.org/agro#Component"]
    assert svc.alt_labels == [("Microservice", "en")]
    assert svc.hidden_labels == [("svc", "en")]
    assert svc.matches == [("exact", "http://external.org/types/Service")]


def test_parse_rejects_malformed_statement():
    with pytest.raises(SkosParseError):
        parse_skos_turtle("just some words")


def test_import_installs_schema_with_hierarchy(store):
    result = import_skos(store, SAMPLE, label="agro-skos")
    assert result["concepts"] == 3
    assert result["aliases"] == 2
    assert result["xrefs"] == 1

    schema = store.get_schema()
    by_name = {e["name"]: e for e in schema["entity_types"]}
    assert by_name["Service"]["parent"] == "Component"
    assert by_name["Database"]["parent"] == "Component"
    assert by_name["Component"]["parent"] is None


def test_import_attaches_aliases_and_xrefs_to_terms(store):
    result = import_skos(store, SAMPLE, label="agro-skos")
    term_rows = store.conn.execute(
        "SELECT t.id, t.preferred_label FROM ontology_term t "
        "WHERE t.schema_version_id = ? AND t.legacy_kind = 'entity_type'",
        (result["schema_version_id"],),
    ).fetchall()
    term_by_label = {r["preferred_label"]: r["id"] for r in term_rows}
    svc_term = term_by_label["Service"]

    aliases = store.list_term_aliases(svc_term)
    labels = {(a["label"], a["alias_kind"]) for a in aliases}
    assert ("Microservice", "alternative") in labels
    assert ("svc", "hidden") in labels

    xrefs = store.list_term_xrefs(svc_term)
    assert len(xrefs) == 1
    assert xrefs[0]["mapping_predicate"] == "exact"
    assert xrefs[0]["external_id"] == "http://external.org/types/Service"
    assert xrefs[0]["license_gate"] == "identifier-only"


def test_import_rejects_empty_input(store):
    with pytest.raises(KGStoreError, match="no skos:Concept"):
        import_skos(store, "@prefix skos: <http://x#> .", label="empty")


def test_concept_scheme_is_not_an_entity_type(store):
    """A skos:ConceptScheme subject is vocabulary metadata, not a concept."""
    text = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/#> .
ex:Scheme a skos:ConceptScheme ; skos:prefLabel "Scheme" .
ex:C a skos:Concept ; skos:prefLabel "C" .
"""
    result = import_skos(store, text, label="scheme-test")
    schema = store.get_schema()
    names = {e["name"] for e in schema["entity_types"]}
    assert names == {"C"}
    assert result["concepts"] == 1


def test_untyped_subject_with_no_skos_properties_is_not_a_type(store):
    """A bare resource the file mentions is not a concept in it."""
    text = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/#> .
@prefix dct: <http://purl.org/dc/terms/> .
ex:Doc dct:title "A document about the vocabulary" .
ex:C a skos:Concept ; skos:prefLabel "C" .
"""
    result = import_skos(store, text, label="untyped-test")
    schema = store.get_schema()
    names = {e["name"] for e in schema["entity_types"]}
    assert names == {"C"}
    assert result["concepts"] == 1


def test_escaped_quote_and_hash_in_literal_survives(store):
    """An escaped quote inside a literal must not truncate the statement."""
    text = r'''
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/#> .
ex:C a skos:Concept ; skos:prefLabel "C" ; skos:altLabel "A\"#B" .
'''
    result = import_skos(store, text, label="escape-test")
    term_rows = store.conn.execute(
        "SELECT t.id FROM ontology_term t WHERE t.schema_version_id=? "
        "AND t.legacy_kind='entity_type'",
        (result["schema_version_id"],),
    ).fetchall()
    aliases = store.list_term_aliases(term_rows[0]["id"])
    assert any(a["label"] == 'A"#B' for a in aliases)


def test_nonliteral_object_on_recognized_property_fails_loudly():
    """A blank-node object on a literal property is malformed, not ignored."""
    text = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/#> .
ex:C a skos:Concept ; skos:prefLabel [ skos:prefLabel "Nested" ] .
"""
    with pytest.raises(SkosParseError):
        parse_skos_turtle(text)


def test_broader_to_external_iri_is_dropped_not_fatal(store):
    text = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/#> .
ex:A a skos:Concept ; skos:prefLabel "A" ;
    skos:broader <http://other.org/NotInFile> .
"""
    result = import_skos(store, text, label="ext-parent")
    schema = store.get_schema()
    a = [e for e in schema["entity_types"] if e["name"] == "A"][0]
    assert a["parent"] is None
    assert result["concepts"] == 1
