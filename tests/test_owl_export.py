"""OWL/RDFS export: the bridge to tools that need a description logic.

The store's schema model is a typed property graph; the export maps the
RDFS/OWL-lite fragment it actually carries — Class/subClassOf for the
is-a hierarchy, ObjectProperty (+ SymmetricProperty when undirected) for
relations, DatatypeProperty for attributes. '*' domain/range omits the
constraint rather than claiming owl:Thing.
"""

from __future__ import annotations

from ontologylab.owl_export import export_owl


def _install(store):
    return store.install_schema(
        label="owl-test",
        description="",
        entity_types=[
            {"name": "Chemical", "description": "a chemical",
             "attributes": {"cas_number": {"type": "string",
                                          "required": False}}},
            {"name": "Herbicide", "description": "kills weeds",
             "attributes": {}, "parent": "Chemical"},
        ],
        relation_types=[
            {"name": "controls", "description": "controls",
             "domain_type": "Herbicide", "range_type": "Chemical",
             "directed": True},
            {"name": "related_to", "description": "vague",
             "domain_type": "*", "range_type": "*", "directed": False},
        ],
    )


def test_classes_and_subclass(store):
    _install(store)
    ttl = export_owl(store)
    assert "ol:Chemical a owl:Class" in ttl
    assert "ol:Herbicide a owl:Class" in ttl
    assert "rdfs:subClassOf ol:Chemical" in ttl
    assert 'rdfs:label "Herbicide"' in ttl


def test_relations_domain_range_symmetry(store):
    _install(store)
    ttl = export_owl(store)
    assert "olp:controls a owl:ObjectProperty" in ttl
    assert "rdfs:domain ol:Herbicide" in ttl
    assert "rdfs:range ol:Chemical" in ttl
    # Undirected → SymmetricProperty; '*' sides state no constraint.
    assert "olp:related_to a owl:ObjectProperty , owl:SymmetricProperty" in ttl
    related_block = ttl.split("olp:related_to")[1].split(".")[0]
    assert "rdfs:domain" not in related_block
    assert "rdfs:range" not in related_block


def test_attributes_become_datatype_properties(store):
    _install(store)
    ttl = export_owl(store)
    assert "olp:Chemical__cas_number a owl:DatatypeProperty" in ttl
    assert "rdfs:domain ol:Chemical" in ttl
    assert "rdfs:range xsd:string" in ttl


def test_ontology_header(store):
    _install(store)
    ttl = export_owl(store)
    assert "a owl:Ontology" in ttl
    assert 'rdfs:label "owl-test"' in ttl
