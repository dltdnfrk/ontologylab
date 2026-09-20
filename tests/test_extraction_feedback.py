"""Review→extract feedback: human rejections become prompt negative examples.

The loop this pins: a rejected proposal (status='rejected', review_note set)
is read back by ``rejected_extraction_feedback`` and rendered into the next
extraction prompt, so the same artifact class is not re-proposed. Approved
items and un-decided proposals must NOT appear — feedback is only what a
human actually rejected.
"""

from __future__ import annotations

from ontologylab.extractor import build_extraction_prompt
from tests.conftest import insert, make_entity, make_relation


def _schema(store):
    return store.get_schema()


def test_rejected_items_appear_in_prompt_approved_do_not(store, doc):
    ghost = make_entity("GhostConcept")
    limiter = make_entity("RateLimiter")
    gateway = make_entity("ApiGateway")
    insert(store, doc, [ghost, limiter, gateway],
           [make_relation(gateway, limiter)])

    store.reject(ghost.id, note="hallucinated surface form")
    store.approve(limiter.id)

    rejected = store.rejected_extraction_feedback()
    prompt = build_extraction_prompt(_schema(store), "chunk text",
                                     rejected=rejected)

    assert "GhostConcept" in prompt
    assert "hallucinated surface form" in prompt
    assert "do NOT re-propose" in prompt
    feedback_section = prompt.split("do NOT re-propose")[1].split("Rules:")[0]
    assert "RateLimiter" not in feedback_section
    assert "ApiGateway" not in feedback_section


def test_no_rejections_renders_no_section(store, doc):
    insert(store, doc, [make_entity("RateLimiter")])
    rejected = store.rejected_extraction_feedback()
    assert rejected == []
    prompt = build_extraction_prompt(_schema(store), "chunk text",
                                     rejected=rejected)
    assert "do NOT re-propose" not in prompt


def test_rejected_edge_is_rendered_with_endpoints(store, doc):
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    rel = make_relation(gateway, limiter)
    insert(store, doc, [gateway, limiter], [rel])
    store.reject(rel.id, note="unsupported relation")

    rejected = store.rejected_extraction_feedback()
    edge_rows = [r for r in rejected if r["kind"] == "edge"]
    assert len(edge_rows) == 1
    assert "ApiGateway" in edge_rows[0]["label"]
    assert "RateLimiter" in edge_rows[0]["label"]
    assert edge_rows[0]["review_note"] == "unsupported relation"


def test_feedback_is_capped_and_newest_first(store, doc):
    entities = [make_entity(f"Entity{i}") for i in range(5)]
    insert(store, doc, entities, [])
    for e in entities:
        store.reject(e.id, note="n")

    rejected = store.rejected_extraction_feedback(limit=3)
    assert len(rejected) == 3
