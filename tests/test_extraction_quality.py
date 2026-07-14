"""Extraction-quality regression harness: triple P/R/F1 against a gold set.

A small hand-labeled fixture document plus its gold entities/relations. The
eval functions compare an extractor's output against gold by normalized
(name, type) for entities and (relation_type, src, dst) for relation
triples, then assert floor thresholds — so an engine/prompt/parser change
that silently degrades extraction fails CI instead of shipping.

The gold set is written against the deterministic MockEngine (CamelCase
extraction) so the harness runs offline; the same functions are reusable
against live-engine output for manual quality checks.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from conftest import default_schema_dict  # noqa: E402
from ontologylab.engines import MockEngine  # noqa: E402
from ontologylab.extractor import (  # noqa: E402
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
)
from ontologylab.kgstore import normalize_name  # noqa: E402

GOLD_DOC = (
    "The ApiGateway forwards inbound requests to the RateLimiter. "
    "The RateLimiter uses the TokenBucketAlgorithm to shape traffic and "
    "stores its counters in the SessionCache. Behind the gateway, the "
    "OrderService persists orders into the OrderDatabase."
)

# Gold labels: entity (name, type) and relation (type, src, dst) triples.
# Types follow the MockEngine contract (CamelCase -> Component); relation
# triples are consecutive-mention links with the schema's compatible type.
GOLD_ENTITIES = {
    ("apigateway", "Component"),
    ("ratelimiter", "Component"),
    ("tokenbucketalgorithm", "Component"),
    ("sessioncache", "Component"),
    ("orderservice", "Component"),
    ("orderdatabase", "Component"),
}
# MockEngine picks the first schema relation compatible with Component
# endpoints — 'uses' in the default ontology.
GOLD_RELATIONS = {
    ("uses", "apigateway", "ratelimiter"),
    ("uses", "ratelimiter", "tokenbucketalgorithm"),
    ("uses", "tokenbucketalgorithm", "sessioncache"),
    ("uses", "sessioncache", "orderservice"),
    ("uses", "orderservice", "orderdatabase"),
}


def prf(predicted: set, gold: set) -> dict[str, float]:
    """Precision / recall / F1 over exact set membership."""
    true_pos = len(predicted & gold)
    precision = true_pos / len(predicted) if predicted else 0.0
    recall = true_pos / len(gold) if gold else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def extract_triples(engine, schema, text):
    """Run an engine over the doc and return (entity_set, relation_triples)."""
    entities: set[tuple[str, str]] = set()
    relations: set[tuple[str, str, str]] = set()
    for chunk in chunk_document(text):
        prompt = build_extraction_prompt(schema, chunk.text)
        raw, _usage = asyncio.run(engine.generate(prompt, model=None))
        result = parse_and_validate_extraction(raw, schema, chunk)
        by_id = {e.id: e for e in result.entities}
        for ent in result.entities:
            entities.add((normalize_name(ent.name), ent.entity_type))
        for rel in result.relations:
            src = by_id.get(rel.src_entity_id)
            dst = by_id.get(rel.dst_entity_id)
            if src and dst:
                relations.add(
                    (
                        rel.relation_type,
                        normalize_name(src.name),
                        normalize_name(dst.name),
                    )
                )
    return entities, relations


def test_gold_set_extraction_quality_floor():
    schema = default_schema_dict()
    entities, relations = extract_triples(MockEngine(), schema, GOLD_DOC)

    ent_scores = prf(entities, GOLD_ENTITIES)
    rel_scores = prf(relations, GOLD_RELATIONS)

    # Regression floors, not aspirations: the deterministic mock should hit
    # these exactly; a parser/prompt/normalization regression drops below.
    assert ent_scores["f1"] >= 0.99, f"entity F1 regressed: {ent_scores}"
    assert rel_scores["f1"] >= 0.99, f"relation F1 regressed: {rel_scores}"


def test_prf_math():
    assert prf(set(), set()) == {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    scores = prf({("a", "T")}, {("a", "T"), ("b", "T")})
    assert scores["precision"] == 1.0
    assert scores["recall"] == 0.5
    assert round(scores["f1"], 4) == round(2 / 3, 4)
