"""Statement identity and citation binding use the same canonical scope."""

import pytest

from ontologylab.citation_bind import _edge_id
from ontologylab.citation_types import ChunkCitationBatch
from tests.conftest import insert
from tests.factories import make_entity, make_relation
from tests.test_statement_qualifier_validation import qualified_store


def _put(store, doc, scope, *, target="Pest"):
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity(target, "Pest")
    relation = make_relation(a, b, "controls", qualifiers={"polarity": "supports", **scope})
    stats = insert(store, doc, [a, b], [relation])
    return a, b, relation, stats


def test_different_qualifiers_never_merge(qualified_store, doc):
    first = _put(qualified_store, doc, {"object_form_or_variant_qualifier": "adult"})
    second = _put(qualified_store, doc, {"object_form_or_variant_qualifier": "larva"})
    assert qualified_store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 2
    assert first[2].id != second[2].id


def test_normalized_values_and_key_order_deduplicate(qualified_store, doc):
    first = _put(qualified_store, doc, {"study_context": " In  Vitro ", "dose": "0.1 mg/L"})
    _put(qualified_store, doc, {"dose": "0.1 MG/L", "study_context": "in vitro"})
    _put(qualified_store, doc, {"dose": "01 mg/L", "study_context": "in vitro"})
    rows = qualified_store.conn.execute("SELECT id FROM edges").fetchall()
    assert len(rows) == 2
    assert len(qualified_store.citations("edge", first[2].id)) == 2


@pytest.mark.parametrize("same", [False, True])
def test_node_merge_respects_statement_scope(qualified_store, doc, same):
    first = _put(qualified_store, doc, {"study_context": "field"})
    second = _put(qualified_store, doc, {"study_context": "field" if same else "in vitro"}, target="Pest duplicate")
    report = qualified_store.merge_nodes(first[1].id, second[1].id)
    assert report["edges_deduplicated"] == int(same)
    assert qualified_store.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE status='proposed'"
    ).fetchone()[0] == (1 if same else 2)


def test_citation_binds_exact_qualifiers_and_current_edge(qualified_store, doc):
    first = _put(qualified_store, doc, {"study_context": "field"})
    second = _put(qualified_store, doc, {"study_context": "in vitro"})
    batch = ChunkCitationBatch(
        doc.id, 0, 0, (), (second[2],),
        {second[0].id: first[0].id, second[1].id: first[1].id},
    )
    assert _edge_id(qualified_store.conn, batch, second[2]) == second[2].id
    qualified_store.approve(second[2].id, cascade=True)
    qualified_store.invalidate_edge(second[2].id, by="test", reason="superseded")
    third = _put(qualified_store, doc, {"study_context": "in vitro"})
    batch = ChunkCitationBatch(
        doc.id, 0, 0, (), (third[2],),
        {third[0].id: first[0].id, third[1].id: first[1].id},
    )
    assert _edge_id(qualified_store.conn, batch, third[2]) == third[2].id
