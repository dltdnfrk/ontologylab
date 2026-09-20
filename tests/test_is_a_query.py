"""is-a transitive type filtering: a filter on a parent type matches
descendants, while identity resolution stays exact.

The hierarchy is real only if queries honor it — asking for ``Chemical``
must find a ``Herbicide``. Resolution is the exception: a node proposed
as ``Herbicide`` must not silently become the ``Chemical`` another
document meant, so ``_resolve_node`` and the registry-identity lookup
keep exact-type matching.
"""

from __future__ import annotations

from tests.conftest import insert
from tests.factories import make_entity


def _hierarchy(store):
    return store.install_schema(
        label="isa-test",
        description="",
        entity_types=[
            {"name": "Component", "description": "", "attributes": {}},
            {"name": "Service", "description": "", "attributes": {},
             "parent": "Component"},
            {"name": "Database", "description": "", "attributes": {},
             "parent": "Component"},
            {"name": "PostgresDb", "description": "", "attributes": {},
             "parent": "Database"},
        ],
        relation_types=[
            {"name": "uses", "description": "", "domain_type": "*",
             "range_type": "*", "directed": True},
        ],
    )


def test_type_filter_values_expands_transitively(store):
    _hierarchy(store)
    assert store.type_filter_values("Component") == [
        "Component", "Database", "PostgresDb", "Service",
    ]
    assert store.type_filter_values("Database") == ["Database", "PostgresDb"]
    assert store.type_filter_values("Service") == ["Service"]
    # A type no schema declares degrades to the exact match it always was.
    assert store.type_filter_values("NoSuchType") == ["NoSuchType"]


def test_entity_lookup_matches_descendants(store, doc):
    _hierarchy(store)
    insert(store, doc, [
        make_entity("ApiServer", entity_type="Service"),
        make_entity("MainDb", entity_type="PostgresDb"),
        make_entity("PlainThing", entity_type="Component"),
    ])
    store.bulk_approve()
    matches = store.entity_lookup(name="MainDb", entity_type="Component")
    assert [m["name"] for m in matches] == ["MainDb"]
    # The reverse does not hold: a parent instance is not a child type.
    assert store.entity_lookup(name="PlainThing", entity_type="Service") == []


def test_semantic_search_matches_descendants(store, doc):
    _hierarchy(store)
    insert(store, doc, [
        make_entity("ApiServer", entity_type="Service"),
        make_entity("MainDb", entity_type="PostgresDb"),
    ])
    store.bulk_approve()
    hits = store.semantic_search("ApiServer", entity_type="Component")
    assert any(h["name"] == "ApiServer" for h in hits)
    hits = store.semantic_search("MainDb", entity_type="Component")
    assert any(h["name"] == "MainDb" for h in hits)


def test_graph_query_matches_descendants(store, doc):
    _hierarchy(store)
    insert(store, doc, [
        make_entity("ApiServer", entity_type="Service"),
        make_entity("MainDb", entity_type="PostgresDb"),
    ])
    store.bulk_approve()
    out = store.graph_query(entity_type="Component")
    names = {n["name"] for n in out["nodes"]}
    assert {"ApiServer", "MainDb"} <= names


def test_approve_filtered_matches_descendants(store, doc):
    _hierarchy(store)
    insert(store, doc, [
        make_entity("ApiServer", entity_type="Service"),
        make_entity("MainDb", entity_type="PostgresDb"),
    ])
    result = store.bulk_approve(entity_type="Component")
    assert len(result["nodes_approved"]) == 2
