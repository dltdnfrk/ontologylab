"""Static pitfall audit: the OOPS!-style checks the schema model supports.

Install-time validation rejects unknown parents and cycles; the audit
catches the defects that are legal but wrong — missing descriptions,
unconstrained relations, orphan types, name collisions, unused
vocabulary, and competency questions the schema cannot express.
"""

from __future__ import annotations

from ontologylab.schema_audit import audit_schema
from tests.conftest import insert
from tests.factories import make_entity


def _install(store, entities, relations):
    return store.install_schema(
        label="audit-test",
        description="",
        entity_types=entities,
        relation_types=relations,
    )


def test_clean_schema_reports_only_usage_info(store):
    _install(
        store,
        [{"name": "Gene", "description": "a gene", "attributes": {}},
         {"name": "Disease", "description": "a disease", "attributes": {}}],
        [{"name": "causes", "description": "causes", "domain_type": "Gene",
          "range_type": "Disease", "directed": True}],
    )
    out = audit_schema(store)
    assert out["warnings"] == 0
    # Fresh schema: both types unused → info, never warning.
    assert {f["pitfall"] for f in out["findings"]} == {
        "unused-type", "unused-relation"
    }


def test_missing_description_and_unconstrained_relation(store):
    _install(
        store,
        [{"name": "Gene", "description": "", "attributes": {}}],
        [{"name": "related_to", "description": "", "domain_type": "*",
          "range_type": "*", "directed": False}],
    )
    out = audit_schema(store)
    pitfalls = {(f["pitfall"], f["subject"]) for f in out["findings"]}
    assert ("missing-description", "Gene") in pitfalls
    assert ("missing-description", "related_to") in pitfalls
    assert ("unconstrained-relation", "related_to") in pitfalls
    assert ("orphan-type", "Gene") in pitfalls


def test_name_collision_detected(store):
    _install(
        store,
        [{"name": "Cell Line", "description": "x", "attributes": {}},
         {"name": "CellLine", "description": "x", "attributes": {}}],
        [{"name": "causes", "description": "x", "domain_type": "Cell Line",
          "range_type": "CellLine", "directed": True}],
    )
    out = audit_schema(store)
    collisions = [f for f in out["findings"] if f["pitfall"] == "name-collision"]
    assert len(collisions) == 1


def test_used_type_not_flagged(store, doc):
    _install(
        store,
        [{"name": "Gene", "description": "x", "attributes": {}},
         {"name": "Disease", "description": "x", "attributes": {}}],
        [{"name": "causes", "description": "x", "domain_type": "Gene",
          "range_type": "Disease", "directed": True}],
    )
    insert(store, doc, [make_entity("TP53", entity_type="Gene")])
    out = audit_schema(store)
    unused = {f["subject"] for f in out["findings"]
              if f["pitfall"] == "unused-type"}
    assert unused == {"Disease"}


def test_uncovered_and_unscoped_cqs_flagged(store):
    _install(
        store,
        [{"name": "Gene", "description": "x", "attributes": {}}],
        [{"name": "causes", "description": "x", "domain_type": "Gene",
          "range_type": "Gene", "directed": True}],
    )
    store.add_schema_cq("Which drugs treat diseases?",
                        requires=["Drug", "treats"],
                        reviewer="t", provenance="t")
    store.add_schema_cq("What is in the graph?",
                        reviewer="t", provenance="t")
    out = audit_schema(store)
    pitfalls = {f["pitfall"] for f in out["findings"]}
    assert "uncovered-cq" in pitfalls
    assert "unscoped-cq" in pitfalls
