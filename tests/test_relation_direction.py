"""Directed relation traversal semantics at the KGStore boundary."""

from __future__ import annotations

from tests.factories import make_entity, make_relation


def _verified_graph(store, doc, *, directed: bool) -> tuple[str, str]:
    store.install_schema(
        label=f"direction-{'directed' if directed else 'undirected'}",
        description="",
        entity_types=[{"name": "Thing", "attributes": {}}],
        relation_types=[
            {
                "name": "links",
                "domain_type": "Thing",
                "range_type": "Thing",
                "directed": directed,
            }
        ],
    )
    source = make_entity("A", entity_type="Thing")
    target = make_entity("B", entity_type="Thing")
    relation = make_relation(source, target, "links")
    stats = store.insert_proposed(
        [source, target],
        [relation],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    source_id = stats["id_map"][source.id]
    target_id = stats["id_map"][target.id]
    store.approve(source_id, by="tester")
    store.approve(target_id, by="tester")
    store.approve(relation.id, by="tester")
    return source_id, target_id


def test_semantic_path_does_not_walk_a_directed_relation_backward(store, doc) -> None:
    source_id, target_id = _verified_graph(store, doc, directed=True)

    assert store.find_path(target_id, source_id, mode="semantic")["found"] is False
    assert store.find_path(source_id, target_id, mode="semantic")["found"] is True


def test_structural_both_mode_still_walks_a_directed_relation_backward(store, doc) -> None:
    source_id, target_id = _verified_graph(store, doc, directed=True)

    result = store.find_path(target_id, source_id, mode="structural")

    assert result["found"] is True
    assert result["hop_count"] == 1


def test_semantic_path_walks_an_undirected_relation_both_ways(store, doc) -> None:
    source_id, target_id = _verified_graph(store, doc, directed=False)

    assert store.find_path(source_id, target_id, mode="semantic")["found"] is True
    assert store.find_path(target_id, source_id, mode="semantic")["found"] is True


def test_neighbor_traversal_exposes_the_same_explicit_modes(store, doc) -> None:
    source_id, target_id = _verified_graph(store, doc, directed=True)

    semantic = store.traverse_relations(
        [target_id], direction="both", mode="semantic", max_hops=1
    )
    structural = store.traverse_relations(
        [target_id], direction="both", mode="structural", max_hops=1
    )

    assert {node["id"] for node in semantic["nodes"]} == {target_id}
    assert {node["id"] for node in structural["nodes"]} == {source_id, target_id}
