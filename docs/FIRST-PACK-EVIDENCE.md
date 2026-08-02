# First agrochem pack evidence - 2026-08-02

<!-- product-evidence:v1:start -->
{"claims":["sourced_entity_lookup","sourced_relation_traversal","full_entity_provenance","live_staleness"],"command":".venv/bin/python -m ontologylab.mcp_server --packs-dir <throwaway>/packs --live-store <throwaway>/data/kg.sqlite","evidence_id":"AC-03-FIRST-PACK","kind":"recorded-execution","result":{"content_hash":"sha256:eb233081b580a9100f08a17a4709223a9c05649607ad2848f4b6686f1e430449","edges_verified":28,"nodes_verified":29,"pack_id":"agrochem-first-20260802-223925","pending_verified_count":1}}
<!-- product-evidence:v1:end -->

This is the AC-03 evidence run over the real MCP stdio surface. It used the five
constructed passages in `tests/gold/agrochem-mini/docs.json`, production
`run_extraction`, and `get_engine("claude", model=None)` (resolved to
`claude-fable-5`). All registry caches, documents, approvals, the working
`kg.sqlite`, and the pack lived in one throwaway macOS temporary directory.
The directory was removed after the payloads below were recorded; the live
Application Support store was never opened or written.

## Pipeline and pack

- Extraction: 5 documents, 5 Claude calls, 187.296 engine seconds; 29 new
  nodes, 2 node-resolution merges, and 28 edges.
- Human gate: `e2e-tester` approved 29 nodes first and then 28 edges. The pack
  contained 29 verified nodes, 28 verified edges, and no proposed/rejected
  rows.
- Pack: `agrochem-first-20260802-223925`
- Content hash:
  `sha256:eb233081b580a9100f08a17a4709223a9c05649607ad2848f4b6686f1e430449`
- `basis_commit`: `e37def778d3cf95b5b26b48e417f8cc31c64ee6c`
- `staleness_policy.pending_verified_count_threshold`: `0` (advisory)

The built `pack.sqlite` was inspected before cleanup. The relevant verified
rows were:

```json
{
  "Botrytis cinerea": {
    "entity_type": "Pathogen",
    "properties": {
      "eppo_code": "BOTRCI",
      "eppo_matched_surface": "Botrytis cinerea",
      "scientific_name": "Botrytis cinerea"
    },
    "source_doc_id": "ba838430d729454e8480cebf12cdf61c"
  },
  "boscalid": {
    "entity_type": "ActiveIngredient",
    "properties": {
      "cas_matched_surface": "boscalid",
      "cas_number": "188425-85-6",
      "moa_code": "7",
      "moa_scheme": "FRAC"
    },
    "source_doc_id": "ba838430d729454e8480cebf12cdf61c"
  },
  "controls": {
    "source_name": "boscalid",
    "target_name": "Botrytis cinerea",
    "source_doc_id": "ba838430d729454e8480cebf12cdf61c",
    "status": "verified"
  }
}
```

This proves the fixture EPPO and PubChem/CAS/MoA caches affected proposals
before approval and that those authoritative values reached the immutable
pack.

## Actual MCP stdio exchange

The server was the real entry point:

```text
.venv/bin/python -m ontologylab.mcp_server \
  --packs-dir <throwaway>/packs --live-store <throwaway>/data/kg.sqlite
```

Messages were newline-delimited JSON-RPC on stdin/stdout. The client also sent
`notifications/initialized` after initialization; as a notification it has no
response. Responses below are the actual `structuredContent`, with only the
large schema and unrelated `get_entity.edges` entries trimmed.

### Initialize

Request:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"ontologylab-first-pack-evidence","version":"1.0"}}}
```

Response:

```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"listChanged":false,"subscribe":false},"tools":{"listChanged":false}},"serverInfo":{"name":"ontologylab","version":"1.28.1"}}}
```

### Load the pack

Request:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"load_pack","arguments":{"pack_id":"agrochem-first-20260802-223925"}}}
```

Response (`schema` omitted here; the actual response carried the complete
`agrochem-v1` schema):

```json
{
  "pack_id": "agrochem-first-20260802-223925",
  "content_hash": "sha256:eb233081b580a9100f08a17a4709223a9c05649607ad2848f4b6686f1e430449",
  "counts": {
    "documents": 5,
    "nodes_proposed": 0,
    "nodes_verified": 29,
    "nodes_rejected": 0,
    "edges_proposed": 0,
    "edges_verified": 28,
    "edges_rejected": 0,
    "merge_candidates_pending": 0
  },
  "schema": "<trimmed: complete agrochem-v1 schema was returned>"
}
```

### Resolve the target organism

Request:

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"entity_lookup","arguments":{"name":"Botrytis cinerea","entity_type":"Pathogen","detail":true}}}
```

Response:

```json
{
  "count": 1,
  "detail": true,
  "matches": [{
    "id": "9071f2d6e31244aea50f232a25875911",
    "entity_type": "Pathogen",
    "name": "Botrytis cinerea",
    "properties": {
      "scientific_name": "Botrytis cinerea",
      "eppo_code": "BOTRCI",
      "eppo_matched_surface": "Botrytis cinerea"
    },
    "status": "verified",
    "confidence": 0.95,
    "source_doc_id": "ba838430d729454e8480cebf12cdf61c",
    "source_document_ids": ["ba838430d729454e8480cebf12cdf61c"],
    "source_span": {"start": 137, "end": 153},
    "match_score": 1.0,
    "aliases": []
  }],
  "pack": {
    "pack_id": "agrochem-first-20260802-223925",
    "content_hash": "sha256:eb233081b580a9100f08a17a4709223a9c05649607ad2848f4b6686f1e430449"
  }
}
```

### Ask what controls it through graph traversal

Request:

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"traverse_relations","arguments":{"start_ids":["9071f2d6e31244aea50f232a25875911"],"relation_types":["controls"],"direction":"in","max_hops":1,"detail":true}}}
```

Response:

```json
{
  "nodes": [
    {
      "id": "9071f2d6e31244aea50f232a25875911",
      "entity_type": "Pathogen",
      "name": "Botrytis cinerea",
      "properties": {"scientific_name":"Botrytis cinerea","eppo_code":"BOTRCI","eppo_matched_surface":"Botrytis cinerea"},
      "status": "verified",
      "confidence": 0.95,
      "source_doc_id": "ba838430d729454e8480cebf12cdf61c",
      "source_span": {"start":137,"end":153},
      "hop": 0,
      "aliases": []
    },
    {
      "id": "c705c8cdcf704782b0b531fa0fb1f0f3",
      "entity_type": "ActiveIngredient",
      "name": "boscalid",
      "properties": {"cas_number":"188425-85-6","cas_matched_surface":"boscalid","moa_scheme":"FRAC","moa_code":"7"},
      "status": "verified",
      "confidence": 0.95,
      "source_doc_id": "ba838430d729454e8480cebf12cdf61c",
      "source_span": {"start":55,"end":63},
      "hop": 1,
      "aliases": ["Boscalid"]
    }
  ],
  "edges": [{
    "id": "0cc870e4ac424e5dbc1de09d7cccbede",
    "relation_type": "controls",
    "source_id": "c705c8cdcf704782b0b531fa0fb1f0f3",
    "target_id": "9071f2d6e31244aea50f232a25875911",
    "status": "verified",
    "confidence": 0.92,
    "source_doc_id": "ba838430d729454e8480cebf12cdf61c",
    "properties": {},
    "invalidated_ts": null,
    "valid_from": 1785677819.705952
  }],
  "detail": true,
  "pack": {
    "pack_id": "agrochem-first-20260802-223925",
    "content_hash": "sha256:eb233081b580a9100f08a17a4709223a9c05649607ad2848f4b6686f1e430449"
  }
}
```

### Fetch boscalid provenance

Request:

```json
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"get_entity","arguments":{"id":"c705c8cdcf704782b0b531fa0fb1f0f3"}}}
```

Relevant actual response fields (unrelated adjacent edges trimmed):

```json
{
  "entity": {
    "id": "c705c8cdcf704782b0b531fa0fb1f0f3",
    "entity_type": "ActiveIngredient",
    "name": "boscalid",
    "properties": {"cas_number":"188425-85-6","cas_matched_surface":"boscalid","moa_scheme":"FRAC","moa_code":"7"},
    "status": "verified",
    "source_doc_id": "ba838430d729454e8480cebf12cdf61c",
    "source_document_ids": ["798395b62f48423bb08e22d60d9e6e40","ba838430d729454e8480cebf12cdf61c"],
    "citations": [
      {"source_doc_id":"ba838430d729454e8480cebf12cdf61c","source_span":{"start":55,"end":63}},
      {"source_doc_id":"798395b62f48423bb08e22d60d9e6e40","source_span":{"start":171,"end":179}}
    ],
    "edges": [{
      "id":"0cc870e4ac424e5dbc1de09d7cccbede",
      "relation_type":"controls",
      "source_id":"c705c8cdcf704782b0b531fa0fb1f0f3",
      "source_name":"boscalid",
      "target_id":"9071f2d6e31244aea50f232a25875911",
      "target_name":"Botrytis cinerea",
      "source_doc_id":"ba838430d729454e8480cebf12cdf61c",
      "status":"verified"
    }]
  },
  "pack": {
    "pack_id": "agrochem-first-20260802-223925",
    "content_hash": "sha256:eb233081b580a9100f08a17a4709223a9c05649607ad2848f4b6686f1e430449"
  }
}
```

### Live staleness

After the pack build, `e2e-tester` approved one additional cited node in the
throwaway working store. Request:

```json
{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"get_staleness","arguments":{}}}
```

Response:

```json
{
  "latest_pack_id": "agrochem-first-20260802-223925",
  "basis_commit": "e37def778d3cf95b5b26b48e417f8cc31c64ee6c",
  "created_ts": 1785677965.576658,
  "staleness_policy": {
    "pending_verified_count_threshold": 0,
    "description": "When pending_verified_count (verified items in the live store minus items reflected in this pack) exceeds the threshold, rebuilding the pack is recommended. Advisory; consumers may set their own threshold."
  },
  "pack_verified_count": 57,
  "store_verified_count": 58,
  "pending_verified_count": 1,
  "note": null
}
```

## AC-03 answer

**Boscalid controls _Botrytis cinerea_.** The controlling fact, organism, and
active ingredient all carry source document
`ba838430d729454e8480cebf12cdf61c`; the response envelope identifies pack
`agrochem-first-20260802-223925` and its content hash. **Source publication
date: unknown.** This fixture is constructed and contains no publication date;
its `fetched_ts` is only ingestion time and was not presented as a source date.
