---
name: project-ontologylab-graphrag-direction
description: ontologylab (local sqlite KG pipeline) is evaluating graph-RAG-style features post-MVP; 2026-07 research brief covered GraphRAG/LightRAG/HippoRAG2/Graphiti/Cognee/sqlite-vec landscape
metadata:
  type: project
---

ontologylab is a local-first, single-user, sqlite-based KG pipeline (LLM extraction → HITL verify → immutable packs → local MCP server, 8 read-only tools incl. FTS5 + LLM query expansion). As of 2026-07-14 it has no vector embeddings, no community detection/hierarchical summaries, no temporal/episodic edges, and updates via full pack rebuilds rather than incremental merge — current query is lexical FTS5 + BFS graph traversal only.

Delivered a research brief (2026-07-14) comparing it against Microsoft GraphRAG, LightRAG, HippoRAG 2, Graphiti/Zep, Cognee, sqlite-vec/sqlite-vector, and two directly-comparable local-first sqlite hybrid-search projects: **fidx** (github.com/williamliu-ai/fidx, FTS5+sqlite-vec+RRF, no LLM in query path, v0.1.0 as of 2026-07-04) and **vstash** (arxiv 2604.15484, sqlite-vec+FTS5+adaptive RRF with per-query IDF weighting). These two are the closest architectural peers — worth re-checking for updates in future research passes, since they're pre-1.0 and evolving fast.

**Why:** roadmap (docs/ROADMAP.md) already lists "tier-2 embedding search" post-MVP; this research is meant to inform which of the graph-RAG-world features (community summaries, global/local query modes, temporal edges, incremental entity resolution, hybrid BM25+vector fusion) are worth building next, given the tool's constraint of staying single-file-sqlite, offline, no API key required.

**How to apply:** when asked to continue/deepen this research (e.g. "check for updates on GraphRAG incremental indexing", "any new sqlite vector extensions"), start from this snapshot rather than re-deriving the whole landscape — the Microsoft GraphRAG `graphrag.append` incremental-update command was still unshipped/design-phase as of 2026-07-14 (see github.com/microsoft/graphrag/issues/741); check for status changes before citing it as available. See [[reference-local-sqlite-hybrid-search-projects]] for the peer-tool list.
