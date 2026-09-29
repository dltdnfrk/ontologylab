"""A no_effect finding is its own claim, never a citation of a supports one."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from tests.conftest import insert
from tests.factories import make_entity, make_relation


@pytest.fixture(autouse=True)
def _polarity_schema(store):
    store.install_schema(
        label="polarity-fixture",
        description="uses with a polarity qualifier",
        entity_types=[{"name": "Component", "description": "", "attributes": {}}],
        relation_types=[{
            "name": "uses", "description": "", "domain_type": "Component",
            "range_type": "Component", "directed": True,
            "qualifiers": {"polarity": {
                "type": "string", "enum": ["supports", "refutes", "no_effect"],
                "required": False,
            }},
        }],
    )


def _edges(store) -> list[tuple[str, str]]:
    return sorted(
        (row["relation_type"], row["qualifiers_json"])
        for row in store.conn.execute(
            "SELECT relation_type, qualifiers_json FROM edges "
            "WHERE status IN ('proposed','verified')"
        )
    )


def test_opposite_polarities_on_one_triple_stay_separate(store, doc) -> None:
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b], [make_relation(a, b, qualifiers={})])
    a2, b2 = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a2, b2], [make_relation(a2, b2, qualifiers={"polarity": "no_effect"})])
    a3, b3 = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a3, b3], [make_relation(a3, b3, qualifiers={"polarity": "no_effect"})])

    assert len(_edges(store)) == 2


def test_same_polarity_still_merges_as_citation(store, doc) -> None:
    for _ in range(2):
        a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
        insert(store, doc, [a, b], [make_relation(a, b)])
    assert len(_edges(store)) == 1
    edge_id = store.conn.execute("SELECT id FROM edges").fetchone()[0]
    citations = store.conn.execute(
        "SELECT COUNT(*) FROM citations WHERE kind='edge' AND item_id=?", (edge_id,)
    ).fetchone()[0]
    assert citations == 2


def test_node_merge_keeps_opposite_polarity_edges(store, doc) -> None:
    a, b, c = make_entity("ApiGateway"), make_entity("RateLimiter"), make_entity("RateGuard")
    insert(
        store, doc, [a, b, c],
        [make_relation(a, b), make_relation(a, c, qualifiers={"polarity": "no_effect"})],
    )
    store.merge_nodes(b.id, c.id)
    assert len(_edges(store)) == 2


def test_pre_polarity_index_is_rebuilt_on_open(tmp_path: Path) -> None:
    db_path = tmp_path / "old.sqlite"
    KGStore.open(db_path).close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX idx_edges_dedup")
        conn.execute(
            "CREATE UNIQUE INDEX idx_edges_dedup ON edges (schema_version_id, "
            "relation_type, src_node_id, dst_node_id) "
            "WHERE status IN ('proposed','verified') AND invalidated_ts IS NULL"
        )
    store = KGStore.open(db_path)
    try:
        sql = store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='idx_edges_dedup'"
        ).fetchone()[0]
        assert "polarity" in sql
    finally:
        store.close()
