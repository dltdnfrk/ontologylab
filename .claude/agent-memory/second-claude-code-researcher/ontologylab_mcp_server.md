---
name: ontologylab-mcp-server
description: ontologylab's local stdio MCP server serves an immutable sqlite knowledge pack via 8 read-only tools; tracks feature-planning research direction
metadata:
  type: project
---

The ontologylab project runs a local stdio MCP server exposing an immutable sqlite "knowledge pack" through 8 read-only tools: `list_packs`, `load_pack`, `get_schema`, `entity_lookup`, `semantic_search`, `graph_query`, `traverse_relations`, `find_path`. As of 2026-07-14 the server uses tools only — no MCP resources, prompts, sampling, elicitation, or structured tool-output schemas are implemented yet.

**Why:** The team is planning next features and wanted a 2025-2026 landscape scan of MCP design patterns for knowledge/memory servers (comparing to Graphiti, Cognee, basic-memory, mcp-obsidian, the official `@modelcontextprotocol/server-memory`) before deciding what to add.

**How to apply:** When asked about this server's roadmap, check current tool/resource implementation first (do not assume the research-brief recommendations were acted on — verify against the actual server code before recommending "next steps" as if already done). Key candidate improvements identified in the 2026-07-14 research brief, ranked by expected value: (1) tool output schemas (`outputSchema`) on existing tools — S effort; (2) expose entities/packs as MCP `resources` (`pack://{id}/entity/{id}`) for app-controlled context loading — M effort; (3) response size budgeting / two-tier responses (compact default + detail drill-down tool) for `semantic_search` and `graph_query` — M effort; (4) citation/provenance fields (source row id, pack version) in every response — S effort; (5) ResourceLink pattern for `traverse_relations`/`find_path` when result graphs are large — M effort; (6) ship as `.mcpb` bundle for one-click distribution of server+pack — M effort; (7) ~~MCP prompts~~ deprioritized — spec discussion (modelcontextprotocol/modelcontextprotocol#1779) proposes deprecating prompts in favor of agent-invokable Skills, and prompts are user-triggered only (not agent-discoverable), so low payoff for an agent-facing knowledge server.
