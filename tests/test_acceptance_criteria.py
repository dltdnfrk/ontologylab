"""Milestone acceptance criteria not covered by the module test files:

- M1: MockEngine determinism (same chunk -> byte-identical output).
- M4: citation integrity + span rebasing across MULTIPLE chunks — every
  stored span, read against the ORIGINAL document text, contains the claimed
  surface form; overlap-induced duplicate mentions resolve to one node.
- M5: bulk-approve processes nodes before edges and reports (never approves)
  edges whose endpoints are not verified.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from conftest import make_entity, make_relation  # noqa: E402
from ontologylab.engines import MockEngine  # noqa: E402
from ontologylab.extractor import (  # noqa: E402
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
)
from ontologylab.kgstore import KGStore  # noqa: E402

# A document long enough to force multiple chunks (target ~6000 chars/chunk),
# mentioning RateLimiter in two different chunks so cross-chunk resolution
# has something to merge.
_FILLER = "plain lowercase filler words repeated to pad the document body. "
LONG_DOC = (
    "The RateLimiter throttles requests using the TokenBucketAlgorithm. "
    + _FILLER * 120
    + "Meanwhile the SessionCache keeps hot entries near the edge. "
    + _FILLER * 120
    + "Under load, the RateLimiter signals the LoadShedder to drop work. "
    + _FILLER * 20
)


def test_prompt_format_contract_with_mock_engine() -> None:
    """The prompt<->mock coupling is by shared symbols, and must not drift:
    the chunk markers wrap the chunk text, and the rendered relation-type
    lines parse back out of the prompt with correct domain/range."""
    from ontologylab.engines import (
        _CHUNK_SECTION_RE,
        _RELATION_LINE_RE,
        CHUNK_MARKER_CLOSE,
        CHUNK_MARKER_OPEN,
    )
    from conftest import default_schema_dict

    schema = default_schema_dict()
    chunk_text = "The RateLimiter uses the TokenBucketAlgorithm."
    prompt = build_extraction_prompt(schema, chunk_text)

    assert CHUNK_MARKER_OPEN in prompt and CHUNK_MARKER_CLOSE in prompt
    section = _CHUNK_SECTION_RE.search(prompt)
    assert section is not None, "mock cannot recover the chunk from the prompt"
    assert section.group(1) == chunk_text

    parsed = {name: (dom, rng) for name, dom, rng in _RELATION_LINE_RE.findall(prompt)}
    for rt in schema["relation_types"]:
        assert rt["name"] in parsed, f"relation line for {rt['name']} unparseable"
        assert parsed[rt["name"]] == (rt["domain_type"], rt["range_type"])


def test_mock_engine_deterministic() -> None:
    schema_stub = {"entity_types": [], "relation_types": []}
    prompt = build_extraction_prompt(
        schema_stub, "The RateLimiter uses the TokenBucketAlgorithm."
    )
    engine_a, engine_b = MockEngine(seed=7), MockEngine(seed=7)
    text_a, _ = asyncio.run(engine_a.generate(prompt))
    text_b, _ = asyncio.run(engine_b.generate(prompt))
    assert text_a == text_b
    assert "```json" in text_a


def test_multichunk_citation_integrity_and_resolution(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        doc, _ = store.insert_document(
            source_kind="upload",
            source_uri="file:///long.md",
            title="long",
            raw_text=LONG_DOC,
            content_hash="sha256:longdoc",
        )
        schema = store.get_schema()
        chunks = chunk_document(LONG_DOC)
        assert len(chunks) >= 2, "fixture must span multiple chunks"
        assert chunks[1].char_offset > 0

        engine = MockEngine()
        for chunk in chunks:
            prompt = build_extraction_prompt(schema, chunk.text)
            raw, _usage = asyncio.run(engine.generate(prompt))
            result = parse_and_validate_extraction(raw, schema, chunk)
            store.insert_proposed(
                result.entities,
                result.relations,
                source_doc_id=doc.id,
                extractor_engine="mock",
            )

        raw_text = store.document_raw_text(doc.id)
        rows = store.conn.execute(
            "SELECT name, source_span FROM nodes WHERE source_span IS NOT NULL"
        ).fetchall()
        assert rows, "extraction must store spanned nodes"
        import json as _json

        for row in rows:
            span = _json.loads(row["source_span"])
            cited = raw_text[span["start"] : span["end"]]
            assert cited, f"empty span for {row['name']}"
            assert row["name"].casefold() in cited.casefold(), (
                f"span for {row['name']!r} cites {cited!r}"
            )

        # RateLimiter appears in two distinct chunks -> exactly ONE node,
        # carrying (at least) two citations.
        rl = store.conn.execute(
            "SELECT id FROM nodes WHERE normalized_name = 'ratelimiter'"
        ).fetchall()
        assert len(rl) == 1
        citations = store.citations("node", rl[0]["id"])
        assert len(citations) >= 2
    finally:
        store.close()


def test_bulk_approve_nodes_first_edges_skipped(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        doc, _ = store.insert_document(
            source_kind="upload",
            source_uri="file:///bulk.md",
            title="bulk",
            raw_text="AlphaService relates to BetaConcept",
            content_hash="sha256:bulk",
        )
        alpha = make_entity("AlphaService", "Component")
        beta = make_entity("BetaConcept", "Concept")
        edge = make_relation(alpha, beta, relation_type="related_to")
        store.insert_proposed(
            [alpha, beta], [edge], source_doc_id=doc.id, extractor_engine="mock"
        )

        # Filtered pass covers only Component data: the Component->Concept
        # edge is OUTSIDE the batch scope entirely (never approved, never
        # counted as skipped), and must remain proposed.
        report = store.bulk_approve(entity_type="Component")
        assert len(report["nodes_approved"]) == 1
        assert report["edges_approved"] == []
        assert report["edges_skipped"] == []

        edge_status = store.conn.execute(
            "SELECT status FROM edges"
        ).fetchone()["status"]
        assert edge_status == "proposed"

        # Unfiltered pass approves the remaining node FIRST, then the edge
        # qualifies within the same batch (nodes-before-edges ordering).
        report2 = store.bulk_approve()
        assert len(report2["nodes_approved"]) == 1
        assert len(report2["edges_approved"]) == 1
        assert report2["edges_skipped"] == []

        nodes, edges = store.verified_subgraph()
        assert len(nodes) == 2 and len(edges) == 1
    finally:
        store.close()
