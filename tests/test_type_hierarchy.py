"""entity_type is-a hierarchy: install validation, export, prompt rendering.

The hierarchy is data, not code: ``parent`` on an entity type names another
type in the same schema_version. Install rejects unknown parents and cycles
before anything is written; export and the extraction prompt carry the
relation so queries and the extractor can generalize upward.
"""

from __future__ import annotations

import pytest

from ontologylab.extractor import build_extraction_prompt
from ontologylab.kgstore import KGStoreError


def _schema_with_hierarchy(store):
    return store.install_schema(
        label="hierarchy-test",
        description="",
        entity_types=[
            {"name": "Component", "description": "A software artifact.",
             "attributes": {}},
            {"name": "Service", "description": "A running component.",
             "attributes": {}, "parent": "Component"},
            {"name": "Database", "description": "A storage component.",
             "attributes": {}, "parent": "Component"},
        ],
        relation_types=[
            {"name": "uses", "description": "", "domain_type": "*",
             "range_type": "*", "directed": True},
        ],
    )


def test_install_stores_and_exports_parent(store):
    _schema_with_hierarchy(store)
    schema = store.get_schema()
    by_name = {e["name"]: e for e in schema["entity_types"]}
    assert by_name["Service"]["parent"] == "Component"
    assert by_name["Database"]["parent"] == "Component"
    assert by_name["Component"]["parent"] is None


def test_unknown_parent_is_rejected(store):
    with pytest.raises(KGStoreError, match="not an entity type"):
        store.install_schema(
            label="bad-parent",
            description="",
            entity_types=[
                {"name": "Service", "description": "", "attributes": {},
                 "parent": "NoSuchType"},
            ],
            relation_types=[],
        )


def test_cyclic_parent_chain_is_rejected(store):
    with pytest.raises(KGStoreError, match="cyclic"):
        store.install_schema(
            label="cycle",
            description="",
            entity_types=[
                {"name": "A", "description": "", "attributes": {},
                 "parent": "B"},
                {"name": "B", "description": "", "attributes": {},
                 "parent": "A"},
            ],
            relation_types=[],
        )


def test_self_parent_is_a_cycle(store):
    with pytest.raises(KGStoreError, match="cyclic"):
        store.install_schema(
            label="self-cycle",
            description="",
            entity_types=[
                {"name": "A", "description": "", "attributes": {},
                 "parent": "A"},
            ],
            relation_types=[],
        )


def test_prompt_renders_is_a(store):
    _schema_with_hierarchy(store)
    schema = store.get_schema()
    prompt = build_extraction_prompt(schema, "chunk text")
    assert "Service" in prompt
    assert "is-a Component" in prompt
