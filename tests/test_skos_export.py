"""SKOS export: the symmetric counterpart of import_skos.

The mapping mirrors the importer — entity_type → skos:Concept,
parent_name → skos:broader, term_alias → altLabel/hiddenLabel, term_xref
→ a SKOS mapping property when the external id is an IRI and
skos:notation when it is not. A round trip preserves what the model can
express.
"""

from __future__ import annotations

from ontologylab.skos_export import export_skos
from ontologylab.skos_import import import_skos


def test_export_emits_concepts_with_hierarchy(store):
    store.install_schema(
        label="exp",
        description="",
        entity_types=[
            {"name": "Chemical", "description": "a chemical",
             "attributes": {}},
            {"name": "Herbicide", "description": "kills weeds",
             "attributes": {}, "parent": "Chemical"},
        ],
        relation_types=[],
    )
    ttl = export_skos(store)
    assert "a skos:Concept" in ttl
    assert 'skos:prefLabel "Herbicide"' in ttl
    assert "skos:broader" in ttl
    assert 'skos:definition "kills weeds"' in ttl


def test_export_carries_aliases_and_xrefs(store):
    sv = store.install_schema(
        label="exp",
        description="",
        entity_types=[
            {"name": "Gene", "description": "a gene", "attributes": {}},
        ],
        relation_types=[],
    )
    term_rows = store.conn.execute(
        "SELECT t.id FROM ontology_term t WHERE t.schema_version_id=? "
        "AND t.legacy_kind='entity_type'",
        (sv,),
    ).fetchall()
    tid = term_rows[0]["id"]
    store.add_term_alias(term_id=tid, label="cistron", language="en",
                         reviewer="t", provenance="t",
                         alias_kind="alternative")
    store.add_term_alias(term_id=tid, label="secret gene", language="en",
                         reviewer="t", provenance="t",
                         alias_kind="hidden")
    store.add_term_xref(
        term_id=tid, authority="mesh", external_id="https://meshb.nlm.nih.gov/record/ui?ui=D014",
        mapping_predicate="exact", source_uri="https://meshb.nlm.nih.gov/",
        source_version="2026", retrieved_at=1.0, confidence=1.0,
        reviewer="t", license_gate="identifier-only",
    )
    store.add_term_xref(
        term_id=tid, authority="internal", external_id="GENE-0042",
        mapping_predicate="close", source_uri="internal://registry",
        source_version="1", retrieved_at=1.0, confidence=1.0,
        reviewer="t", license_gate="identifier-only",
    )
    ttl = export_skos(store)
    assert 'skos:altLabel "cistron"@en' in ttl
    assert 'skos:hiddenLabel "secret gene"@en' in ttl
    assert "skos:exactMatch <https://meshb.nlm.nih.gov/record/ui?ui=D014>" in ttl
    # A non-IRI external id is a notation, never a fake mapping IRI.
    assert 'skos:notation "GENE-0042"' in ttl


def test_round_trip_preserves_hierarchy(store, tmp_path):
    source = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/#> .
ex:Chemical a skos:Concept ; skos:prefLabel "Chemical" .
ex:Herbicide a skos:Concept ; skos:prefLabel "Herbicide" ;
    skos:broader ex:Chemical ; skos:altLabel "weed killer"@en .
"""
    import_skos(store, source, label="rt")
    ttl = export_skos(store)
    store2 = store.__class__.open(tmp_path / "rt2.sqlite")
    try:
        result = import_skos(store2, ttl, label="rt2")
        schema = store2.get_schema()
        parents = {e["name"]: e["parent"] for e in schema["entity_types"]}
        assert parents["Herbicide"] == "Chemical"
        assert result["concepts"] == 2
    finally:
        store2.close()
