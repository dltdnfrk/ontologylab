"""End-to-end MVP: collect(file) → extract(mock) → approve → pack → MCP query."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from conftest import default_schema_dict  # noqa: E402
from ontologylab.extractor import (  # noqa: E402
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
)
from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.mcp_server import PackSession  # noqa: E402
from ontologylab.packbuilder import build_pack  # noqa: E402


FIXTURE_TEXT = """
# Rate Limiting in Distributed Systems

A RateLimiter component is a common pattern for throttling inbound traffic.
It typically uses the TokenBucket algorithm (a Technique) as its core mechanism.
The RateLimiter is part_of the API Gateway Component in many service meshes.
Related concepts include Backpressure and Quotas.
""".strip()


class CannedEngine:
    def name(self) -> str:
        return "canned"

    async def generate(self, prompt: str, *, model: str | None = None):
        payload = {
            "entities": [
                {
                    "name": "RateLimiter",
                    "entity_type": "Component",
                    "aliases": ["rate limiter"],
                    "properties": {},
                    "confidence": 0.95,
                    "source_span": {"start": 0, "end": 11},
                },
                {
                    "name": "TokenBucket",
                    "entity_type": "Technique",
                    "aliases": ["Token Bucket"],
                    "properties": {},
                    "confidence": 0.9,
                    "source_span": {"start": 0, "end": 11},
                },
                {
                    "name": "API Gateway",
                    "entity_type": "Component",
                    "aliases": [],
                    "properties": {},
                    "confidence": 0.85,
                    "source_span": {"start": 0, "end": 11},
                },
                {
                    "name": "Backpressure",
                    "entity_type": "Concept",
                    "aliases": [],
                    "properties": {},
                    "confidence": 0.8,
                    "source_span": {"start": 0, "end": 12},
                },
            ],
            "relations": [
                {
                    "relation_type": "uses",
                    "source": {"name": "RateLimiter", "entity_type": "Component"},
                    "target": {"name": "TokenBucket", "entity_type": "Technique"},
                    "properties": {},
                    "confidence": 0.9,
                    "source_span": {"start": 0, "end": 40},
                },
                {
                    "relation_type": "part_of",
                    "source": {"name": "RateLimiter", "entity_type": "Component"},
                    "target": {"name": "API Gateway", "entity_type": "Component"},
                    "properties": {},
                    "confidence": 0.85,
                    "source_span": {"start": 0, "end": 40},
                },
                {
                    "relation_type": "related_to",
                    "source": {"name": "RateLimiter", "entity_type": "Component"},
                    "target": {"name": "Backpressure", "entity_type": "Concept"},
                    "properties": {},
                    "confidence": 0.75,
                    "source_span": {"start": 0, "end": 40},
                },
            ],
        }
        text = "```json\n" + json.dumps(payload) + "\n```"
        return text, {"calls": 1, "elapsed": 0.01}


def test_e2e_mvp_loop(tmp_path: Path) -> None:
    data = tmp_path / "data"
    packs = tmp_path / "packs"
    data.mkdir()
    kg_path = data / "kg.sqlite"

    # 1. collect (upload file)
    store = KGStore.open(kg_path)
    doc, created = store.insert_document(
        source_kind="upload",
        source_uri="file:///fixture-rate-limiter.md",
        title="rate-limiting",
        raw_text=FIXTURE_TEXT,
        content_hash="e2e-mvp-1",
    )
    assert created

    # 2. extract (canned mock)
    schema = default_schema_dict()
    engine = CannedEngine()
    raw, _usage = asyncio.run(engine.generate("unused", model=None))
    chunks = chunk_document(FIXTURE_TEXT)
    assert chunks
    _ = build_extraction_prompt(schema, chunks[0].text)
    result = parse_and_validate_extraction(raw, schema, chunks[0])
    assert len(result.entities) >= 3, result.warnings
    stats = store.insert_proposed(
        result.entities,
        result.relations,
        source_doc_id=doc.id,
        extractor_engine=engine.name(),
        extractor_model="canned",
    )
    assert stats["nodes_new"] >= 3

    # 3. approve all proposed (CLI-equivalent)
    pending = store.pending_review()
    for item in pending:
        store.approve(item["id"], cascade=True)

    nodes, edges = store.verified_subgraph()
    assert len(nodes) >= 3
    assert len(edges) >= 1
    store.close()

    # 4. build pack
    manifest = build_pack(
        kg_path, packs, name="e2e-mvp", allow_incomplete_extraction=True,
        incomplete_extraction_intent="legacy canned extraction fixture",
    )
    assert manifest.counts["nodes_verified"] >= 3

    # 5. MCP query against pack
    session = PackSession(packs)
    session.load_pack(manifest.pack_id)
    lookup = session.entity_lookup(name="RateLimiter")
    assert lookup["count"] >= 1
    rl_id = lookup["matches"][0]["id"]

    search = session.semantic_search("token bucket throttling")
    assert search["count"] >= 1

    tb = session.entity_lookup(name="TokenBucket")
    assert tb["count"] >= 1
    path = session.find_path(rl_id, tb["matches"][0]["id"])
    assert path["found"] is True

    gq = session.graph_query(entity_type="Component")
    assert len(gq["nodes"]) >= 1
    session.close()
