"""Extraction pipeline: chunking, prompt/parse contract, span rebasing."""

import json
from pathlib import Path

import pytest

from ontologylab.engines import EngineError, MockEngine
from ontologylab.extractor import (
    TARGET_CHUNK_TOKENS,
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


def test_default_chunk_size_follows_measured_agrochem_sweep():
    # The live measurement is part of the invariant: a future default change
    # needs a new record, not an unexplained constant edit.
    record = Path(__file__).parent.parent / "docs/CHUNK-SWEEP-2026-08.md"
    assert record.is_file()
    assert TARGET_CHUNK_TOKENS == 3000


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


# --------------------------------------------------------------------------
# Grounding, including the door that was left open
# --------------------------------------------------------------------------


def test_an_entity_absent_from_the_chunk_is_rejected() -> None:
    """The grounding rule, stated directly."""
    result = parse_and_validate_extraction(
        wrap({"entities": [{"name": "GhostService", "entity_type": "Component"}]}),
        SCHEMA,
        Chunk(index=0, char_offset=0, text="The OrderService writes to disk."),
    )

    assert result.entities == []
    assert any("not found in chunk" in w for w in result.warnings)


def test_the_same_name_as_a_relation_endpoint_is_announced() -> None:
    """Found in review: the rule above had a quiet way around it.

    A name the model never emitted as an entity, and that does not occur in
    the source text, still becomes a proposal — minted as a placeholder so
    the edge is not dangling. That is defensible; doing it in silence was
    not. The direct claim is rejected loudly two hundred lines earlier,
    while the endpoint form produced no warning at all, and `synthesized`
    is counted into a statistic and then dropped — it reaches neither the
    database nor the reviewer.

    What survives is the missing span, which is why the review UI keys on
    that. This pins the announcement so the two paths stay comparable.
    """
    result = parse_and_validate_extraction(
        wrap(
            {
                "entities": [],
                "relations": [
                    {
                        "relation_type": "uses",
                        "source": {"name": "OrderService", "entity_type": "Component"},
                        "target": {"name": "GhostService", "entity_type": "Component"},
                    }
                ],
            }
        ),
        SCHEMA,
        Chunk(index=0, char_offset=0, text="The OrderService writes to disk."),
    )

    ghost = [e for e in result.entities if e.name == "GhostService"]
    assert ghost, "the placeholder is still minted — a dangling edge is worse"
    assert ghost[0].source_span is None
    assert any(
        "does not appear in the chunk" in w and "GhostService" in w
        for w in result.warnings
    ), "an ungrounded endpoint must not enter in silence"


def test_a_grounded_endpoint_keeps_its_span_and_raises_no_alarm() -> None:
    """The warning must fire on absence, not on being an endpoint."""
    result = parse_and_validate_extraction(
        wrap(
            {
                "entities": [],
                "relations": [
                    {
                        "relation_type": "uses",
                        "source": {"name": "OrderService", "entity_type": "Component"},
                        "target": {"name": "OrderDatabase", "entity_type": "Component"},
                    }
                ],
            }
        ),
        SCHEMA,
        Chunk(
            index=0,
            char_offset=0,
            text="The OrderService writes into the OrderDatabase.",
        ),
    )

    assert all(e.source_span is not None for e in result.entities)
    assert not any("does not appear" in w for w in result.warnings)


def test_a_missing_span_means_ungrounded_and_nothing_else() -> None:
    """The invariant the review UI depends on.

    The panel tells the reviewer *why* there is no excerpt, and it can only
    do that honestly if a null span has exactly one cause. The direct entity
    path guarantees a span (it rejects otherwise), so a null span is always
    an ungrounded endpoint — never a bookkeeping gap.
    """
    result = parse_and_validate_extraction(
        wrap(
            {
                "entities": [
                    {"name": "OrderService", "entity_type": "Component"},
                    {"name": "OrderDatabase", "entity_type": "Component"},
                ]
            }
        ),
        SCHEMA,
        Chunk(
            index=0,
            char_offset=0,
            text="The OrderService writes into the OrderDatabase.",
        ),
    )

    assert result.entities
    assert all(e.source_span is not None for e in result.entities)
