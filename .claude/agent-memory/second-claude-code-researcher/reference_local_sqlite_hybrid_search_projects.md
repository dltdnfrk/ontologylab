---
name: reference-local-sqlite-hybrid-search-projects
description: known peer projects for local-first sqlite hybrid (BM25+vector) search — useful baseline to re-check when researching ontologylab's retrieval roadmap
metadata:
  type: reference
---

Two open-source projects are the closest architectural peers to ontologylab's local MCP query layer (single sqlite file, offline, no API key). Both fuse FTS5 (BM25) with sqlite-vec (vector) via Reciprocal Rank Fusion, and neither has graph/KG features — this is the gap ontologylab already fills that they don't.

- **fidx** — github.com/williamliu-ai/fidx. FTS5 + sqlite-vec (ONNX 768-dim embeddings) + RRF(k=60), no LLM in query path, warm queries 18-49ms p50. v0.1.0 released 2026-07-04, pre-1.0.
- **vstash** — arxiv.org/abs/2604.15484. sqlite-vec + FTS5 + *adaptive* RRF (per-query IDF-weighted fusion instead of fixed weights), fine-tuned BGE-small (33M params), reports up to +21.4% NDCG@10 on ArguAna from adaptive fusion vs static weights.

Related sqlite vector-extension landscape (as of 2026-07): `asg017/sqlite-vec` is the incumbent but original author was reportedly unavailable for a period (community fork `vlasky/sqlite-vec` exists); `sqliteai/sqlite-vector` is a newer competitor claiming ~50% faster inserts / faster quantized queries. Re-verify which is actively maintained before recommending one, since this space was in flux.

See [[project-ontologylab-graphrag-direction]] for the full research context this was gathered for.
