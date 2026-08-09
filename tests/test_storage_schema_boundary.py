"""Store-boundary schema validation regression tests."""

from __future__ import annotations

import json

import pytest

from ontologylab.kgstore import KGStoreError
from tests.conftest import insert
from tests.factories import make_entity, make_relation


def test_existing_merge_and_annotation_happy_paths_remain_valid(store, doc) -> None:
    first = make_entity(
        "RateLimiter", properties={"language": "python"}, aliases=["limiter"]
    )
    second = make_entity(
        "RateLimiterService", properties={"version": "1"}, aliases=["throttle"]
    )
    insert(store, doc, [first, second])
    node_ids = {
        row["name"]: row["id"]
        for row in store.conn.execute(
            "SELECT id, name FROM nodes WHERE name IN (?, ?)",
            (first.name, second.name),
        )
    }

    store.merge_nodes(node_ids[first.name], node_ids[second.name], by="tester")
    annotation_id, created = store.upsert_annotation(
        node_id=node_ids[first.name],
        resource="uniprot",
        external_id="P12345",
        record_url="https://example.test/P12345",
        matched_name="Rate limiter",
        facts={"function": "limits requests"},
    )
    assert created
    assert store.decide_annotation(annotation_id, accept=True, by="tester")

    row = store.conn.execute(
        "SELECT properties_json FROM nodes WHERE id = ?", (node_ids[first.name],)
    ).fetchone()
    assert row is not None
    properties = json.loads(row["properties_json"])
    assert properties["language"] == "python"
    assert properties["version"] == "1"
    assert properties["uniprot"]["external_id"] == "P12345"


def _row_counts(store) -> tuple[int, int, int]:
    return tuple(
        store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("nodes", "edges", "citations")
    )


def test_off_schema_entity_type_is_rejected_without_persisting(store, doc) -> None:
    before = _row_counts(store)

    with pytest.raises(KGStoreError, match="entity type") as caught:
        insert(store, doc, [make_entity("Ghost", entity_type="GhostType")])

    assert type(caught.value).__name__ == "SchemaValidationError"
    assert _row_counts(store) == before


def test_undeclared_entity_property_is_rejected_without_persisting(store, doc) -> None:
    before = _row_counts(store)

    with pytest.raises(KGStoreError, match="undeclared property") as caught:
        insert(store, doc, [make_entity("Gateway", properties={"secret": "x"})])

    assert type(caught.value).__name__ == "SchemaValidationError"
    assert _row_counts(store) == before


@pytest.mark.parametrize(
    ("source_type", "target_type", "expected"),
    [("Concept", "Component", "domain"), ("Component", "Concept", "range")],
)
def test_relation_endpoint_domain_and_range_are_rejected_without_persisting(
    store, doc, source_type: str, target_type: str, expected: str
) -> None:
    store.install_schema(
        label="directional-v1",
        description="",
        entity_types=[
            {"name": "Component", "attributes": {}},
            {"name": "Concept", "attributes": {}},
        ],
        relation_types=[
            {
                "name": "implements",
                "domain_type": "Component",
                "range_type": "Component",
                "directed": True,
            }
        ],
    )
    source = make_entity("Source", entity_type=source_type)
    target = make_entity("Target", entity_type=target_type)
    before = _row_counts(store)

    with pytest.raises(KGStoreError, match=expected) as caught:
        insert(store, doc, [source, target], [make_relation(source, target, "implements")])

    assert type(caught.value).__name__ == "SchemaValidationError"
    assert _row_counts(store) == before


def test_annotation_with_undeclared_property_block_is_not_queued(store, doc) -> None:
    entity = make_entity("RateLimiter")
    stats = insert(store, doc, [entity])
    node_id = stats["id_map"][entity.id]

    with pytest.raises(KGStoreError, match="undeclared property") as caught:
        store.upsert_annotation(
            node_id=node_id,
            resource="not_in_the_schema",
            external_id="bad-1",
            record_url="https://example.test/bad-1",
            matched_name="RateLimiter",
            facts={"value": "bad"},
        )

    assert type(caught.value).__name__ == "SchemaValidationError"
    assert store.conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0
    properties = json.loads(
        store.conn.execute(
            "SELECT properties_json FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()[0]
    )
    assert "not_in_the_schema" not in properties


@pytest.mark.parametrize("value", [None, "", 42])
def test_property_value_constraints_fail_closed(store, doc, value) -> None:
    before = _row_counts(store)

    with pytest.raises(KGStoreError, match="property.*language"):
        insert(store, doc, [make_entity("Gateway", properties={"language": value})])

    assert _row_counts(store) == before


def test_validation_uses_the_rows_schema_version_after_active_schema_switch(
    store, doc
) -> None:
    old_schema_id = store.active_schema_version()["id"]
    old_entity = make_entity("Old Component")
    stats = insert(store, doc, [old_entity])
    old_node_id = stats["id_map"][old_entity.id]
    store.install_schema(
        label="new-v1",
        description="",
        entity_types=[{"name": "Other", "attributes": {}}],
        relation_types=[],
    )

    annotation_id, created = store.upsert_annotation(
        node_id=old_node_id,
        resource="uniprot",
        external_id="P12345",
        record_url="https://example.test/P12345",
        matched_name="Old Component",
        facts={"function": "still valid under the old row schema"},
    )

    assert created
    assert annotation_id
    assert store.conn.execute(
        "SELECT schema_version_id FROM nodes WHERE id = ?", (old_node_id,)
    ).fetchone()[0] == old_schema_id
