"""Extraction pipeline: chunking, prompt/parse contract, span rebasing."""

import json

import pytest

from ontologylab.engines import EngineError, MockEngine
from ontologylab.extractor import (
    Chunk,
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
)

SCHEMA = {
    "schema_version_id": 1,
    "schema_label": "software-docs-v1",
    "entity_types": [
        {"name": "Component", "description": "", "attributes": {
            "language": {"type": "string", "required": False},
        }},
        {"name": "Concept", "description": "", "attributes": {}},
    ],
    "relation_types": [
        {"name": "uses", "description": "", "domain_type": "*",
         "range_type": "*", "directed": True},
        {"name": "part_of", "description": "", "domain_type": "Component",
         "range_type": "Component", "directed": True},
        {"name": "related_to", "description": "", "domain_type": "*",
         "range_type": "*", "directed": False},
    ],
}


def wrap(payload: dict) -> str:
    return "```json\n" + json.dumps(payload) + "\n```"


def chunk_for(text: str, offset: int = 0, index: int = 0) -> Chunk:
    return Chunk(index=index, char_offset=offset, text=text)


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------


def test_short_document_is_single_chunk():
    chunks = chunk_document("short text")
    assert len(chunks) == 1
    assert chunks[0].char_offset == 0
    assert chunks[0].text == "short text"


def test_long_document_chunks_overlap_and_cover():
    text = " ".join(f"word{i}" for i in range(4000))
    chunks = chunk_document(text)
    assert len(chunks) > 1
    # coverage: every chunk's text really lives at its claimed offset
    for c in chunks:
        assert text[c.char_offset : c.char_offset + len(c.text)] == c.text
    # consecutive chunks overlap (offset of next < end of previous)
    for a, b in zip(chunks, chunks[1:]):
        assert b.char_offset < a.char_offset + len(a.text)
    # full coverage to the end
    last = chunks[-1]
    assert last.char_offset + len(last.text) == len(text)


# ---------------------------------------------------------------------------
# parse + validate
# ---------------------------------------------------------------------------


def test_malformed_json_raises_engine_error():
    chunk = chunk_for("RateLimiter text")
    with pytest.raises(EngineError):
        parse_and_validate_extraction("```json\n{not json\n```", SCHEMA, chunk)
    with pytest.raises(EngineError):
        parse_and_validate_extraction("no fenced block at all", SCHEMA, chunk)


def test_unknown_entity_type_rejected_with_warning():
    chunk = chunk_for("The RateLimiter is here.")
    raw = wrap({
        "entities": [
            {"name": "RateLimiter", "entity_type": "Gadget"},
        ],
        "relations": [],
    })
    result = parse_and_validate_extraction(raw, SCHEMA, chunk)
    assert result.entities == []
    assert any("unknown entity_type" in w for w in result.warnings)


def test_entity_name_not_in_chunk_rejected():
    chunk = chunk_for("Nothing relevant here.")
    raw = wrap({
        "entities": [
            {"name": "GhostService", "entity_type": "Component",
             "source_span": {"start": 0, "end": 5}},
        ],
        "relations": [],
    })
    result = parse_and_validate_extraction(raw, SCHEMA, chunk)
    assert result.entities == []
    assert any("not found in chunk" in w for w in result.warnings)


def test_span_rebased_to_document_coordinates():
    text = "prefix RateLimiter suffix"
    offset = 1000
    chunk = chunk_for(text, offset=offset)
    raw = wrap({
        "entities": [
            {"name": "RateLimiter", "entity_type": "Component",
             "source_span": {"start": 7, "end": 18}},
        ],
        "relations": [],
    })
    result = parse_and_validate_extraction(raw, SCHEMA, chunk)
    (ent,) = result.entities
    assert ent.source_span.start == offset + 7
    assert ent.source_span.end == offset + 18


def test_off_schema_property_dropped_keywise():
    chunk = chunk_for("RateLimiter")
    raw = wrap({
        "entities": [
            {"name": "RateLimiter", "entity_type": "Component",
             "properties": {"language": "go", "sneaky": "x"}},
        ],
        "relations": [],
    })
    result = parse_and_validate_extraction(raw, SCHEMA, chunk)
    (ent,) = result.entities
    assert ent.properties == {"language": "go"}
    assert any("off-schema property" in w for w in result.warnings)


def test_relation_endpoint_synthesized_when_not_emitted():
    chunk = chunk_for("ApiGateway talks to RateLimiter")
    raw = wrap({
        "entities": [
            {"name": "ApiGateway", "entity_type": "Component"},
        ],
        "relations": [
            {"relation_type": "uses",
             "source": {"name": "ApiGateway", "entity_type": "Component"},
             "target": {"name": "RateLimiter", "entity_type": "Component"}},
        ],
    })
    result = parse_and_validate_extraction(raw, SCHEMA, chunk)
    assert len(result.relations) == 1
    names = {e.name: e for e in result.entities}
    assert names["RateLimiter"].synthesized is True
    assert names["ApiGateway"].synthesized is False
    rel = result.relations[0]
    assert rel.src_entity_id == names["ApiGateway"].id
    assert rel.dst_entity_id == names["RateLimiter"].id


def test_relation_domain_range_enforced():
    chunk = chunk_for("Caching and CacheServer")
    raw = wrap({
        "entities": [
            {"name": "Caching", "entity_type": "Concept"},
            {"name": "CacheServer", "entity_type": "Component"},
        ],
        "relations": [
            # part_of is Component->Component; Concept source violates domain
            {"relation_type": "part_of",
             "source": {"name": "Caching", "entity_type": "Concept"},
             "target": {"name": "CacheServer", "entity_type": "Component"}},
        ],
    })
    result = parse_and_validate_extraction(raw, SCHEMA, chunk)
    assert result.relations == []
    assert any("violates" in w for w in result.warnings)


def test_confidence_clamped():
    chunk = chunk_for("RateLimiter")
    raw = wrap({
        "entities": [
            {"name": "RateLimiter", "entity_type": "Component", "confidence": 42},
        ],
        "relations": [],
    })
    result = parse_and_validate_extraction(raw, SCHEMA, chunk)
    assert result.entities[0].confidence == 1.0


# ---------------------------------------------------------------------------
# mock engine end-to-end against the real prompt
# ---------------------------------------------------------------------------


def test_mock_engine_output_parses_against_real_prompt():
    import asyncio

    text = "The ApiGateway forwards to the RateLimiter and OrderService."
    chunk = chunk_document(text)[0]
    prompt = build_extraction_prompt(SCHEMA, chunk.text)
    raw, usage = asyncio.run(MockEngine().generate(prompt, model=None))
    assert usage["engine"] == "mock"
    result = parse_and_validate_extraction(raw, SCHEMA, chunk)
    names = sorted(e.name for e in result.entities)
    assert names == ["ApiGateway", "OrderService", "RateLimiter"]
    assert len(result.relations) == 2
