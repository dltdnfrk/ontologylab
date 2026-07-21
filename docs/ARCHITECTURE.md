# ontologylab — Architecture

A **local-first, single-user** pipeline that turns collected documents into a queryable knowledge graph and serves it to MCP clients:

```
collect  ->  extract (LLM)  ->  verify (human-in-the-loop)  ->  knowledge graph  ->  knowledge pack  ->  local MCP server
```

Inspired by opencrab.sh/mcp (ingest -> ontology + KG -> knowledge packs -> remote MCP URL), but rebuilt as a **local, offline-after-download, no-API-keys, single-user** tool. Inference runs through subscription CLIs (`claude` / `codex` / `gemini`, plus an offline `mock`), reusing the `drylab` optimization-engine infrastructure wherever it applies.

This document unifies three design perspectives — system architecture, the ontology/KG data model, and the MCP server interface — into one specification. Where the perspectives disagreed, the reconciled decision is marked **[Reconciled]** with rationale.

All examples and shipped connectors use **neutral domains only**: software, technical documentation, and general knowledge. Connectors are **deny-by-default**: only allowlisted sources and queries are permitted (see §12).

---

## 1. Design principles

1. **Local-first, single-user.** Everything runs on one machine. The dashboard binds `127.0.0.1` only, no auth; the MCP server speaks stdio to the client that spawns it. No cloud, no multi-user, no network services beyond outbound document fetching through an allowlisted connector.
2. **Human-in-the-loop is mandatory.** LLM auto-extraction is the default *first* step, never the last. Every extracted entity/relation is born `proposed` and can only become `verified` through an explicit human action — the direct descendant of drylab's `Finding.verified` invariant ("never silently treat unverified output as ground truth").
3. **Verified-only leaves the building.** A knowledge pack — the deployable unit the MCP server serves — contains *only* `verified` rows. `proposed`/`rejected` rows never leave the working database. Enforced structurally (a pack is a separate file built from a verified-only query), not just by a status filter.
4. **Easiest correct storage.** One sqlite file, reusing drylab's `memory.py` pattern (WAL, functional `open()` + OO wrapper). No external graph DB, no vector DB — at single-user scale indexed sqlite answers neighbor/path/type queries fast enough and ships zero extra services.
5. **Reuse drylab, adapt only the seams.** LLM-CLI adapters, provenance log, safety caps/kill switch, TUI, and the FastAPI + vanilla-JS local shell are reused near-verbatim. Only optimization-loop-specific pieces (coordinator, sandbox, heuristic domain) are dropped.
6. **Explicit, typed, read-only MCP surface.** All KG-query tools are exposed initially (graph query, semantic search, entity lookup, relation traversal, path finding, pack management) with typed JSON-Schema contracts. No MCP tool mutates the graph — approval is a human action outside MCP scope.

---

## 2. Component diagram

```
                              ┌──────────────────────────────────────────────┐
                              │              USER'S MACHINE (local)            │
                              └──────────────────────────────────────────────┘

 ┌────────────────────┐   spawns per job    ┌─────────────────────────────────────────────┐
 │  ontologylab CLI    │◄────subprocess─────►│   ontologylab dashboard (OPTIONAL, runs       │
 │  python -m           │                     │   only while the user has the UI open)        │
 │   ontologylab.main   │                     │                                               │
 │   collect|extract|   │                     │  FastAPI app (server/app.py, reused as-is)    │
 │   build-pack         │                     │   ├─ /api/sources      (ingest config)        │
 └─────────┬───────────┘                     │   ├─ /api/jobs         (JobManager, SSE)       │
           │                                 │   ├─ /api/proposals    (HITL approval queue)   │
           │ writes                          │   ├─ /api/graph        (graph browser)         │
           ▼                                 │   ├─ /api/packs        (build/export)          │
 ┌────────────────────────┐                  │   ├─ /api/mcp          (mcp lifecycle status)  │
 │  data/jobs/<job_id>/   │◄──tail SSE───────┤   └─ /api/settings,/cost,/engines (reused)     │
 │   status.json          │                  │  web/ vanilla JS+HTML dashboard (reused shell) │
 │   provenance.jsonl     │                  └──────────────────┬──────────────────────────────┘
 └────────────────────────┘                                    │ JobManager
                                                                │ (server/runner.py, adapted)
           ┌────────────────────────────────────────────────────────────────────┐
           │                  PIPELINE STAGES (per job, subprocess)              │
           │                                                                      │
           │  [collect] ───► [extract] ───► [verify: HITL, dashboard/CLI only]    │
           │      │              │                        │                       │
           │      ▼              ▼                        ▼                       │
           │  connectors:   engines.py adapters:      approval action            │
           │  - paper API    Claude/Codex/Gemini/       (proposed -> verified     │
           │  - web/URL      Mock (Engine Protocol,      | rejected; human only)  │
           │    (allowlist)  generate(prompt,model)                              │
           │  -> documents    -> (text, usage))         writes to KG store       │
           └────────────────────────────────┬─────────────────────────────────┘
                                             ▼
                          ┌───────────────────────────────────┐
                          │   WORKING KG STORE — data/kg.sqlite │
                          │   nodes / edges / documents tables  │
                          │   + schema_version/entity_type/     │
                          │     relation_type tables            │
                          │   status: proposed|verified|rejected│
                          │   (drylab/memory.py pattern reuse)   │
                          └────────────────┬──────────────────────┘
                                           │ build-pack (verified subset ONLY)
                                           ▼
                          ┌───────────────────────────────────┐
                          │  KNOWLEDGE PACK  packs/<pack_id>/   │
                          │   pack.sqlite  (verified KG only)   │
                          │   schema.json  (ontology export)    │
                          │   manifest.json (version,sources,   │
                          │     counts, content hash)           │
                          │   provenance.jsonl (build audit)    │
                          │   IMMUTABLE once built              │
                          └────────────────┬──────────────────────┘
                                           │ --packs-dir / --pack, read-only
                                           ▼
                          ┌───────────────────────────────────┐
                          │   ontologylab MCP SERVER            │
                          │   python -m ontologylab.mcp_server  │
                          │   FastMCP over stdio                │
                          │   tools: list_packs, load_pack,     │
                          │    get_schema, entity_lookup,       │
                          │    get_entity, semantic_search,     │
                          │    graph_query, traverse_relations, │
                          │    find_path, get_communities       │
                          └────────────────┬──────────────────────┘
                                           │ MCP (stdio)
                                           ▼
                                ┌────────────────────┐
                                │  MCP CLIENT          │
                                │  (Claude Desktop /    │
                                │   Claude Code / etc.) │
                                └────────────────────┘
```

Cross-cutting utilities threaded through every stage (all reused near-verbatim from drylab): `provenance.py` (per-job JSONL log + live `status.json`), `safety.py` (`Caps` + `KillSwitch`), `tui.py` (dependency-free CLI progress).

---

## 3. Process model

Three independent process types:

| Process | Entry point | Lifetime | Started by | drylab reuse |
|---|---|---|---|---|
| **Dashboard** | `python -m ontologylab.serve` | Long-running, **optional** | The user | `serve.py` + `server/app.py` **as-is**, 127.0.0.1-only, no auth |
| **Pipeline job** (collect / extract / build-pack) | `python -m ontologylab.main <stage> ...` | Short-lived, one subprocess per job | Dashboard JobManager, **or** the CLI directly (headless) | `server/runner.py` subprocess-per-run + status/provenance tail |
| **MCP server** | `python -m ontologylab.mcp_server` | Long-running per client session | The **MCP client** spawns it over stdio | New code; supervised like a job (PID, log, kill sentinel) when dashboard-launched |

Key decisions:

- **The dashboard is not required for the MCP server.** MCP clients conventionally spawn their own stdio server from a config entry, so a user who only wants the MCP endpoint never runs the dashboard. `ontologylab.mcp_server` is fully standalone.
- **Pipeline jobs stay subprocess-per-run** (like drylab optimization runs) because collect/extract are long, LLM-heavy, individually cancellable operations that must not block or crash the dashboard, and must be killable via the existing `KillSwitch` sentinel-file mechanism.
- **`data/kg.sqlite` (working graph) and `packs/<id>/pack.sqlite` (a shipped pack) are different files.** [Reconciled — the data-model perspective named the pack payload `kg.sqlite`; renamed to `pack.sqlite` so the immutable shipped copy is never confused with the mutable working graph.] CLI jobs and the review UI read/write `data/kg.sqlite`; `build-pack` is the only stage that reads it and writes an immutable verified-only copy into `packs/<id>/pack.sqlite`, the only file the MCP server ever opens. This keeps "still under review" data structurally unreachable from any MCP tool.
- **One active pack at a time, switchable at runtime.** [Reconciled — the architecture perspective said an MCP server is bound to one pack for its whole lifetime with no hot-swap; the MCP perspective offered a `load_pack` tool that swaps packs without restart. Resolution: because packs are **immutable, read-only files**, "switching" is just closing one read-only connection and opening another to a different file — there is no concurrent-writer or mid-session data-drift hazard, which was the architecture perspective's only concern. So `load_pack` is kept: the server holds exactly one active read-only connection at a time. No in-process mutation of a live pack ever occurs.]

---

## 4. End-to-end data flow

```
1. INGEST (collect)
   source spec (paper-API query | seed URL[s], domain-allowlisted)
     --[connector]--> raw documents -> rows in `documents`
   provenance: collect.start / collect.doc / collect.end

2. EXTRACT (LLM auto-extraction)
   engine = get_engine(cfg.engine, cfg.model, seed=cfg.seed)     # engines.py, UNCHANGED
   for each document chunk (see §7 for chunk size / overlap / token budget):
     stop, reason = caps.should_stop(state)                      # safety.Caps API
     if stop or kill_switch.triggered(): break                   # safety.KillSwitch API
     prompt = build_extraction_prompt(ontology_schema, chunk)
     raw_text, usage = await engine.generate(prompt, model=cfg.model)
     provenance.track_engine_call("extract", usage)
     # parse_and_validate_extraction(raw_text) calls extract_fenced_block INTERNALLY,
     # so main passes RAW model text, not a pre-extracted block. It returns typed
     # ProposedEntity/ProposedRelation objects with a minted uuid per entity and each
     # relation still referencing its endpoints by (name,type) — see §7.
     nodes, edges = parse_and_validate_extraction(raw_text, schema)
     kgstore.insert_proposed(nodes, edges, source_doc, prompt_version)
     # insert_proposed RESOLVES entities before writing (§5.5): each node is deduped by
     # (schema_version_id, entity_type, normalized_name) against existing proposed+verified
     # nodes; a hit reuses that node id, a miss mints one. Every relation endpoint is then
     # bound to the RESOLVED node id, so the KG is one connected graph, not per-chunk stars.
   -> rows written with status='proposed'; NEVER queryable by an MCP tool, NEVER in a pack.

3. VERIFY (human-in-the-loop — dashboard "/review" screen OR CLI, never automatic)
   The proposed -> verified gate is triggered by a human through exactly two surfaces:
     - dashboard "/review" screen (POST /api/proposals/{id}/approve|reject), or
     - the headless CLI: `ontologylab.main approve|reject|review` (§4a).
   Each action:
     approve -> status: proposed -> verified
     reject  -> status: proposed -> rejected   (kept for audit, excluded from packs)
     edit    -> human corrects fields, then approves (stored as human-edited)
   Bulk-approve-by-filter is allowed but is still an explicit per-batch human action, and
   an edge is never approved while either endpoint is still `proposed` (§5.3).
   There is no *automated* verify stage: no pipeline stage, engine, or scheduled job may set
   `status='verified'`. The `approve|reject|review` CLI is not such a stage — it is the
   headless embodiment of the human action, requiring an explicit invocation per batch.

4. KNOWLEDGE GRAPH (data/kg.sqlite — the single running local graph)
   Accumulates across many collect/extract runs. The status column gates visibility.
   Semantic-search index (FTS5 for MVP; embeddings post-MVP) covers proposed + verified so
   the review UI can search pending items, but MCP tools default to verified-only.

5. BUILD PACK (bundle the deployable unit)
   verified = kgstore.verified_subgraph(filter=cfg.pack_filter)
   write packs/<pack_id>/ = pack.sqlite (verified-only copy, same schema) + schema.json
     + manifest.json (version, source docs, counts, content hash) + provenance.jsonl slice
   The pack.sqlite is finalized as a NON-WAL, checkpointed, VACUUMed, read-optimized file and
   its FTS5 index is rebuilt INTO the pack (§6). Packs are IMMUTABLE and additive: a rebuild
   produces a new pack_id, never mutates one in place.

6. SERVE (MCP)
   ontologylab.mcp_server opens exactly one pack's pack.sqlite read-only (via a
   `file:...?mode=ro&immutable=1` URI, §6) and exposes typed MCP tools over stdio. All query
   tools default to verified-only (which is all a pack contains).
```

**Status-machine invariant (load-bearing).** A `nodes`/`edges` row's `status` starts `proposed`. Only a human action can move it to `verified` or `rejected`. No pipeline stage, engine, or scheduled job may write `status='verified'` directly. Enforced by splitting the write API: the extraction path calls `insert_proposed(...)`, physically incapable of writing `verified`; only the review path calls `approve(...)`, the sole caller allowed to set `verified`.

### 4a. Approval surface (headless CLI, resolves the "no verify job" tension)

The proposed→verified gate is a **human** action, but it must be operable without the dashboard (the MVP cut line ships CLI-only approval, no web UI). `ontologylab.main` therefore exposes explicit approval subcommands that are the headless embodiment of the same human action the dashboard performs — not an automated stage:

```
python -m ontologylab.main review [--status proposed] [--type Component] [--doc <doc_id>] [--limit N]
    # prints the pending_review queue (§5.3) as a table: kind, id, type, label, confidence, source_doc

python -m ontologylab.main approve --id <node_or_edge_id> [--by local-user] [--note "..."]
python -m ontologylab.main approve --filter "entity_type=Component,min_confidence=0.8"   # bulk, per-batch
python -m ontologylab.main reject  --id <node_or_edge_id> [--by local-user] [--note "..."]
```

Each invocation is a discrete, human-initiated command that calls `kgstore.approve(id)` / `kgstore.reject(id)` — the same code path the dashboard's `/api/proposals/{id}/approve` route calls. There is **no** `ontologylab.main verify` stage that runs unattended: "there is no verify *job*" means nothing in the collect/extract/build-pack pipeline and no scheduler ever flips status; `approve`/`reject` require a person to type the command. Bulk-approve-by-filter is still one explicit human command per batch, and (per §5.3) refuses to approve any edge whose endpoints are not already `verified`.

---

## 5. Ontology + KG data model (sqlite)

One sqlite file, `data/kg.sqlite`, same WAL + `open()`-with-schema pattern as `drylab/memory.py`. A knowledge pack's `pack.sqlite` uses the **identical schema**, so the MCP server reuses the exact same query code against a pack that the dashboard uses against the working graph — no separate "pack reader" format.

[Reconciled — the data-model perspective used singular table names (`node`/`edge`/`document`) and column `attrs_json`; the MCP and roadmap perspectives used plural (`nodes`/`edges`/`documents`) and `properties_json`. Canonical form below: **plural table names**, **`properties_json`**, **`status` with three values `proposed|verified|rejected`**, **`embedding` as a nullable BLOB** (the MCP perspective's `embedding_json` is an acceptable alternative; BLOB chosen for compactness), and a **single `source_doc_id` + `source_span`** per fact (multi-source node merge — one node citing several documents — is a documented post-MVP refinement, not an MVP array column).]

### 5.1 Ontology schema tables (types are data, not code)

The ontology schema — which entity/relation *types* are legal — is stored in tables so it can be edited, versioned, and shipped inside a pack. Extraction is validated against the active schema version. Tables are seeded from a default ontology definition module (`ontology_schema.py`) at first run.

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT NOT NULL,               -- e.g. "software-docs-v1"
    description   TEXT,
    created_ts    REAL NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1    -- only one active at a time
);

CREATE TABLE IF NOT EXISTS entity_type (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version_id INTEGER NOT NULL REFERENCES schema_version(id),
    name              TEXT NOT NULL,            -- e.g. "Component", "Concept", "API"
    description       TEXT,
    attributes_json   TEXT NOT NULL DEFAULT '{}',  -- minimal attr spec (below)
    UNIQUE (schema_version_id, name)
);

CREATE TABLE IF NOT EXISTS relation_type (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version_id INTEGER NOT NULL REFERENCES schema_version(id),
    name              TEXT NOT NULL,            -- e.g. "depends_on", "implements", "documents"
    description       TEXT,
    domain_type       TEXT NOT NULL,            -- allowed source entity_type.name
    range_type        TEXT NOT NULL,            -- allowed target entity_type.name
    directed          INTEGER NOT NULL DEFAULT 1,
    UNIQUE (schema_version_id, name)
);
```

`attributes_json` is a minimal attribute spec (not a full JSON-Schema engine), embedded verbatim into the extraction prompt so the model knows which attributes to fill:

```json
{
  "language":  {"type": "string", "required": false},
  "version":   {"type": "string", "required": false},
  "stability": {"type": "string", "enum": ["experimental", "stable", "deprecated"]}
}
```

`domain_type`/`range_type` on `relation_type` let the extraction validator reject a relation whose endpoints don't match declared types (e.g. `documents` must go `API -> Concept`) — the cheapest correctness check before a fact ever reaches `proposed`.

### 5.2 Documents, nodes, edges

```sql
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,             -- uuid4 hex
    source_kind   TEXT NOT NULL,                -- "paper_api" | "web_crawl" | "upload"
    source_uri    TEXT NOT NULL,                -- original URL / API record id
    title         TEXT,
    fetched_ts    REAL NOT NULL,
    content_hash  TEXT NOT NULL,                -- sha256 of raw text, for dedup
    raw_text_path TEXT NOT NULL,                -- path under data/documents/<id>/
    UNIQUE (content_hash)
);

CREATE TABLE IF NOT EXISTS nodes (
    id                TEXT PRIMARY KEY,          -- uuid4 hex
    schema_version_id INTEGER NOT NULL REFERENCES schema_version(id),
    entity_type       TEXT NOT NULL,             -- denormalized entity_type.name
    name              TEXT NOT NULL,             -- canonical display label
    aliases_json      TEXT NOT NULL DEFAULT '[]',
    properties_json   TEXT NOT NULL DEFAULT '{}',

    status            TEXT NOT NULL DEFAULT 'proposed'
                          CHECK (status IN ('proposed','verified','rejected')),
    confidence        REAL,                      -- extractor self-reported 0..1 (signal, not truth)
    source_doc_id     TEXT NOT NULL REFERENCES documents(id),
    source_span       TEXT,                      -- char offsets / chunk id, for citation
    extractor_engine  TEXT NOT NULL,             -- "claude"|"codex"|"gemini"|"mock"
    extractor_model   TEXT,
    prompt_version    TEXT,
    created_ts        REAL NOT NULL,
    verified_ts       REAL,                      -- set only on approve/reject
    verified_by       TEXT,                      -- e.g. "local-user"

    embedding         BLOB,                      -- packed float32[], nullable (post-MVP)
    embedding_model   TEXT
);
CREATE INDEX IF NOT EXISTS idx_nodes_type_status ON nodes (entity_type, status);
CREATE INDEX IF NOT EXISTS idx_nodes_source_doc  ON nodes (source_doc_id);
CREATE INDEX IF NOT EXISTS idx_nodes_name        ON nodes (name);

CREATE TABLE IF NOT EXISTS edges (
    id                TEXT PRIMARY KEY,          -- uuid4 hex
    schema_version_id INTEGER NOT NULL REFERENCES schema_version(id),
    relation_type     TEXT NOT NULL,
    src_node_id       TEXT NOT NULL REFERENCES nodes(id),
    dst_node_id       TEXT NOT NULL REFERENCES nodes(id),
    properties_json   TEXT NOT NULL DEFAULT '{}',

    status            TEXT NOT NULL DEFAULT 'proposed'
                          CHECK (status IN ('proposed','verified','rejected')),
    confidence        REAL,
    source_doc_id     TEXT NOT NULL REFERENCES documents(id),
    source_span       TEXT,
    extractor_engine  TEXT NOT NULL,
    extractor_model   TEXT,
    prompt_version    TEXT,
    created_ts        REAL NOT NULL,
    verified_ts       REAL,
    verified_by       TEXT
);
CREATE INDEX IF NOT EXISTS idx_edges_src_status ON edges (src_node_id, status);
CREATE INDEX IF NOT EXISTS idx_edges_dst_status ON edges (dst_node_id, status);
CREATE INDEX IF NOT EXISTS idx_edges_type       ON edges (relation_type, status);
```

Per-fact provenance lives inline on the row (`source_doc_id`, `source_span`, `extractor_engine`, `extractor_model`, `confidence`, `created_ts`, `verified_ts`, `verified_by`) so "why does the KG believe this?" is a single-row read. This is deliberately redundant with the job-level `provenance.jsonl` (which answers "what did build-job #7 do and cost"); the two serve different queries and both are kept.

### 5.3 Human-in-the-loop approval

Approval is a dedicated write, never a side effect of extraction:

```sql
-- approve:  UPDATE nodes SET status='verified', verified_ts=?, verified_by=? WHERE id=?;
-- reject:   UPDATE nodes SET status='rejected', verified_ts=?, verified_by=? WHERE id=?;
```

**Edge-approval dependency (both endpoints verified) — UX + enforcement.** An edge may be approved only if both endpoint nodes are already `verified`. This is enforced in the application layer (`kgstore.approve(edge_id)` reads `src_node_id`/`dst_node_id` status and raises `EndpointNotVerified` if either is still `proposed`/`rejected`), since sqlite `CHECK` can't reference other rows. The **UX** makes this non-surprising:

- In the review queue (dashboard and `ontologylab.main review`), a proposed edge whose endpoints are not both verified is shown **disabled** with the reason "approve endpoints first", and its two endpoint nodes are linked inline so the reviewer can approve them in place.
- **Bulk-approve** (by filter, dashboard or CLI) processes nodes before edges within the batch, then approves only those edges whose endpoints are verified *after* the node pass; any edge still blocked is reported as skipped with a count, never silently approved and never auto-approving its endpoints.
- An `approve --cascade` convenience may, in one explicit human command, approve an edge together with its two endpoint nodes — but it approves the nodes as real approvals (writing `verified_by`/`verified_ts`), it does not bypass the invariant.

**Acceptance test (edge dependency).** Seed nodes A (proposed), B (verified) and edge A→B (proposed). Assert: (1) `approve(edge_AB)` raises `EndpointNotVerified` and leaves the edge `proposed`; (2) a bulk-approve over the batch approves B-side work but reports edge A→B as skipped while A is proposed; (3) after `approve(A)`, `approve(edge_AB)` succeeds; (4) a pack built at any point never contains an edge whose endpoints are not both verified.

A cheap review-queue view:

```sql
CREATE VIEW IF NOT EXISTS pending_review AS
SELECT 'node' AS kind, id, entity_type AS type_name, name AS label,
       confidence, source_doc_id, created_ts
FROM nodes WHERE status = 'proposed'
UNION ALL
SELECT 'edge' AS kind, id, relation_type AS type_name,
       src_node_id || ' -> ' || dst_node_id AS label,
       confidence, source_doc_id, created_ts
FROM edges WHERE status = 'proposed'
ORDER BY created_ts ASC;
```

### 5.4 Semantic search — tiered, honest about what ships

[Reconciled — the MCP perspective described cosine similarity over an embedding column as the search mechanism; the data-model perspective recommended shipping FTS5 lexical search first and adding embeddings post-MVP. Resolution: the **tool signature is stable across both**, so ship the cheaper tier first and upgrade behind the same interface.]

- **MVP (tier 1): FTS5 lexical search**, zero new dependencies, using sqlite's built-in FTS5 over `name` / `aliases_json` / `properties_json`. The tool description and user-facing docs **must state this is lexical, not vector** — never silently claim semantic/vector search that isn't there.
- **Post-MVP (tier 2): local in-process embeddings.** A small CPU-only embedding model, loaded once per process, embeds `name + aliases + properties` at write time and the query at search time; brute-force cosine in Python over `verified` node embeddings (fine to ~tens of thousands of nodes). `embedding_model` records which embedder produced a vector, so a pack built with model A is never compared against a query embedded with model B.
- **Later, if a pack outgrows brute force:** add the `sqlite-vec` extension (still local, no external service) rather than a separate vector DB.

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    id UNINDEXED, name, aliases, properties, content=''
);  -- kept in sync via triggers on nodes insert/update, or rebuilt on pack build
```

**Score contract (stable across tiers).** The `semantic_search` MCP tool keeps its signature whether backed by tier 1 or tier 2, and its `match_score` field carries the **same documented meaning in both tiers: a 0..1 relevance score where higher is a better match, and `min_score` filters on it identically.** The raw backends differ (FTS5 returns BM25, which is unbounded and lower-is-better; tier-2 returns cosine in [-1,1]), so both are **normalized into the same 0..1 scale before leaving the tool**:

- **Tier 1 (BM25):** score is mapped with `match_score = 1 / (1 + bm25_raw)` (BM25 as returned by sqlite is a distance-like cost, so smaller cost → larger match_score, bounded in (0,1]). This is a rank-preserving normalization, not a calibrated probability — documented as such.
- **Tier 2 (cosine):** `match_score = (cosine + 1) / 2`, mapping [-1,1] → [0,1], same higher-is-better meaning.

The manifest records `search_tier` ("fts5" | "embeddings") and, for tier 2, `embedding_model`, so a caller can tell *which* normalization produced a score without the field ever silently changing meaning. If a future backend cannot honor the 0..1 higher-is-better contract, the field is **versioned** (`match_score_v2`) rather than reused with a different meaning.

### 5.5 Entity resolution (dedup at insert time — makes the KG connected)

Without resolution, each chunk's extraction is an isolated star (its own nodes + edges pointing only at those nodes), and `find_path`/`traverse_relations` have nothing to cross between chunks or documents. Resolution runs **inside `insert_proposed(...)`, at insert-proposed time**, before any row is written:

1. **Normalize** each extracted entity's name. **[Reconciled — implementation]**: the shipped key is the stricter `normalized_name = remove_non_alphanumerics(casefold(name))` (kgstore.normalize_name), because the originally-specified whitespace-collapse-only formula cannot unify this section's own acceptance-test variants ("RateLimiter" / "rate-limiter" / "Rate Limiter"). Trade-off accepted: punctuation-distinct names ("API-2" vs "API2") collapse to one node — still exact-match resolution, and a wrong merge remains reviewable via the union'd aliases. (Aliases are also normalized and indexed so a later mention matching an alias resolves to the same node.)
2. **Dedup key** = `(schema_version_id, entity_type, normalized_name)`. A unique index backs it:

   ```sql
   CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_resolve
       ON nodes (schema_version_id, entity_type, normalized_name);
   ```

   `normalized_name` is a stored column on `nodes` (added alongside `name`), populated by `insert_proposed`.
3. **Resolve:** look up the key over existing `proposed` + `verified` nodes.
   - **Hit** → reuse that node's `id`; merge the new mention's aliases/properties non-destructively (union aliases; fill only absent property keys; append the new `source_doc_id`/`source_span` as an additional citation — the multi-source-citation refinement noted in §5 is what a resolution hit produces) and keep the earliest `created_ts`.
   - **Miss** → mint a fresh `uuid4` node id and insert it `proposed`.
4. **Bind relation endpoints:** each `ProposedRelation` referenced its endpoints by `(name, entity_type)` (§7). After the entity pass, rewrite both endpoints to the **resolved node id** before inserting the edge. An endpoint that resolves to nothing (relation names an entity the model didn't emit as an entity) is created as a minted `proposed` node of the declared type so the edge is never dangling — flagged in provenance as `synthesized_endpoint` for reviewer attention.
5. **Edge dedup:** edges are deduped by `(schema_version_id, relation_type, src_node_id, dst_node_id)` after endpoint binding; a duplicate triple appends a citation rather than inserting a second edge.

Resolution intentionally spans `proposed` **and** `verified` nodes so that a second document's mention of an already-verified entity attaches to it (and the new edge can later be approved against it) instead of forking a parallel proposed twin. Resolution is deliberately conservative (exact normalized-name match only for the MVP); fuzzy/embedding-based merge of near-duplicate names is a documented post-MVP refinement, gated behind human review because a wrong merge is harder to undo than a missed one.

**Acceptance test (resolution).** Extract two chunks from different documents that both mention "Rate Limiter" / "rate-limiter" as a `Component` and each relate it to a distinct `Concept`. Assert exactly one `RateLimiter` node exists after both inserts, it carries both `source_doc_id` citations, and `find_path` between the two `Concept` nodes returns a 2-hop path through it — proving the graph is connected across chunks, not per-chunk stars.

---

## 6. Knowledge pack format

A knowledge pack is a single directory (optionally zipped for distribution) — a frozen, review-gated, immutable snapshot the MCP server serves read-only:

```
packs/<pack_id>/
├── manifest.json       # identity, versioning, counts, content hash (below)
├── pack.sqlite         # verified-only copy: status='verified' nodes/edges + their
│                       #   entity_type/relation_type/schema_version rows + cited
│                       #   documents rows. Same schema as §5; immutable after build.
├── schema.json         # active ontology (entity_type + relation_type), exported for
│                       #   human/agent readability without opening sqlite
└── provenance.jsonl    # copy of the build job's provenance log — self-auditing pack
```

`manifest.json`:

```json
{
  "pack_id": "software-docs-2026-07-12",
  "created_ts": 1752300000.0,
  "schema_version_id": 3,
  "schema_label": "software-docs-v1",
  "source_job_id": "extract-20260712-091500",
  "counts": { "documents": 42, "nodes_verified": 613, "edges_verified": 891,
              "entity_types": 3, "relation_types": 5 },
  "embedding_model": null,
  "ontologylab_version": "0.1.0",
  "content_hash": "sha256:...of pack.sqlite bytes"
}
```

**Why sqlite-as-payload, not a custom dump:** the MCP server opens `pack.sqlite` directly (read-only) and reuses the exact query code used against the working DB — no second reader format, and a pack is inspectable with any sqlite client. The only structural difference from the working DB is that a pack contains *only* `verified` rows.

**Build physics (deterministic, read-optimized, self-contained).** `packbuilder.build_pack()` produces the pack.sqlite in this exact order so the shipped file is a single, WAL-free, checkpointed, vacuumed artifact whose bytes are stable enough to content-hash:

1. Create the empty pack DB and `ATTACH` the working `data/kg.sqlite` as `live`.
2. Copy the verified subgraph and everything it cites, in dependency order:
   `INSERT INTO main.nodes  SELECT * FROM live.nodes  WHERE status='verified' AND <filter>;`
   then verified edges **whose src and dst are both in the copied node set**, then the
   `schema_version`/`entity_type`/`relation_type` rows referenced, then the `documents` rows cited. `proposed`/`rejected` rows never leave the working database — the concrete mechanism enforcing principle #3.
3. **Rebuild FTS5 into the pack**, do not row-copy it. A plain `INSERT ... SELECT` of the `nodes_fts` rows loses the virtual table and its shadow tables (`nodes_fts_data`, `_idx`, `_content`, `_docsize`, `_config`). Instead the builder issues `CREATE VIRTUAL TABLE nodes_fts USING fts5(...)` in the pack, then `INSERT INTO nodes_fts(rowid, ...) SELECT ... FROM main.nodes;` (or `INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')` when using an external-content table) so the pack owns a complete, self-contained FTS index.
4. `DETACH live;` then finalize for read-only serving:
   `PRAGMA journal_mode=DELETE;` (turn WAL **off** — a read-only immutable file must not need a `-wal`/`-shm` sidecar), `PRAGMA wal_checkpoint(TRUNCATE);` before the switch, `PRAGMA optimize;`, then `VACUUM;` into the final compact file.
5. Compute `content_hash = sha256(pack.sqlite bytes)` and write it into `manifest.json`.

The MCP server then opens it strictly read-only and never triggers WAL creation:

```python
uri = f"file:{pack_sqlite_path}?mode=ro&immutable=1"
conn = sqlite3.connect(uri, uri=True)   # immutable=1 asserts the file/its sidecars never change
```

`immutable=1` lets sqlite skip all locking/change detection (correct because packs are immutable) and `mode=ro` guarantees no write, no journal, no `-wal` file is ever created next to a pack.

**Packs registry — single source of truth is the directory + `manifest.json`.** [Reconciled — an earlier draft also kept a `packs` table inside the working `kg.sqlite`; that duplicated state and could drift from what is actually on disk. Resolution: **there is no `packs` table.** `list_packs` discovers packs by scanning `--packs-dir` for subdirectories that contain a readable `manifest.json`, and reads counts/version/hash from each manifest. The filesystem is authoritative; building a pack just writes a new `packs/<pack_id>/` directory, and deleting one is `rm -rf` of its directory.]

**Versioning / rollback:** rebuilding produces a new `pack_id` (timestamp- or hash-suffixed) rather than mutating a pack in place, mirroring drylab's per-run directories. Older packs stay on disk; "roll back" = point the MCP server at the previous `pack_id`. The server binds one pack per active connection, so no data migration is ever required.

---

## 7. Engine / CLI adapter plug-in point (extraction)

`engines.py`'s `Engine` Protocol and `get_engine()` factory are reused **unchanged**:

```python
class Engine(Protocol):
    def name(self) -> str: ...
    async def generate(self, prompt: str, *, model: str | None) -> tuple[str, dict]: ...

engine = get_engine(cfg.engine, cfg.model, seed=cfg.seed)   # "claude"|"codex"|"gemini"|"mock"
raw_text, usage = await engine.generate(extraction_prompt, model=cfg.model)
```

`ClaudeEngine`/`CodexEngine`/`GeminiEngine` still shell out via subprocess (`claude -p <prompt> --model claude-fable-5`, `codex exec <prompt>`, `gemini -p <prompt>`) with the same timeout / `EngineError` handling; `MockEngine` still runs fully offline and deterministic for tests and CI. **The only change is downstream of `generate()`:** drylab's `extract_python_code(text)` (regex for a ` ```python ` fence) is replaced by a generic `extract_fenced_block(text, lang="json")`, which is now called **internally by `parse_and_validate_extraction(raw_text, schema)`** — so `main` passes the raw model text and never handles fenced-block extraction itself (resolves the call-boundary contradiction). Extraction output is parsed, never executed — this is why `sandbox.py` is dropped.

### 7.1 Extraction contract (end-to-end)

**Chunking.** Documents are split before prompting: **target ~1,500 tokens per chunk with ~150-token (10%) overlap**, measured with a cheap heuristic tokenizer (≈ 4 chars/token; no model-specific tokenizer dependency). The prompt's total token budget is capped (schema + few-shot + chunk ≤ the engine's context minus a response reserve, default reserve 1,024 tokens); a chunk that would overflow is split again. Overlap exists so an entity/relation straddling a chunk boundary is seen whole by at least one chunk; entity resolution (§5.5) then dedups the overlap-induced duplicate mentions.

**The JSON the model must return** is a single fenced ` ```json ` block of exactly this shape:

```json
{
  "entities": [
    { "name": "RateLimiter", "entity_type": "Component",
      "aliases": ["rate-limiter"], "properties": {"language": "Go"},
      "confidence": 0.9, "source_span": {"start": 128, "end": 190} }
  ],
  "relations": [
    { "relation_type": "implements",
      "source": {"name": "RateLimiter", "entity_type": "Component"},
      "target": {"name": "TokenBucketAlgorithm", "entity_type": "Concept"},
      "confidence": 0.8, "source_span": {"start": 205, "end": 260} }
  ]
}
```

**A relation references its endpoints by `{name, entity_type}` — never by array index and never by a model-invented id.** This is deliberate: array indices are fragile across retries and models routinely hallucinate id strings. `name+type` is the same key entity resolution (§5.5) uses, so endpoints bind cleanly to resolved nodes.

**Name → minted-uuid binding rule (in `parse_and_validate_extraction`).** The parser: (1) validates each entity against the active `entity_type`/`relation_type` schema (known type, known property keys, right JSON type — off-schema items are rejected and logged, never coerced); (2) builds a per-chunk map `(normalized_name, entity_type) -> minted uuid4` for every valid entity; (3) for each relation, resolves `source`/`target` through that map to the minted uuids, and for a `{name,type}` that names no emitted entity, mints a placeholder entity of the declared type (flagged `synthesized_endpoint`) so the relation is never dangling; (4) returns typed `ProposedEntity` (carrying its minted id) and `ProposedRelation` (carrying resolved endpoint ids). These minted per-chunk uuids are provisional — `insert_proposed`/§5.5 may collapse them onto an existing node id during cross-chunk resolution; the per-chunk map only has to be internally consistent within one model response.

**`source_span` rebasing onto the original document.** The model sees chunk-local text, so it returns `{start,end}` offsets relative to the **chunk**. Each chunk is tracked with its `(char_offset_in_document, length)`, so the parser rebases every span to document coordinates: `doc_start = chunk.char_offset + span.start` (and likewise `end`). The stored `source_span` is therefore always a `{start,end}` char range into the original `documents.raw_text` file, so a citation resolves with a single substring read of the source document — no chunk bookkeeping needed at query time.

**Acceptance test (citation integrity).** After extracting a fixture document, for every stored node/edge assert that `raw_text[source_span.start:source_span.end]` is non-empty and **contains the claimed surface form** (the node `name`/an alias, or, for a relation, both endpoint names appear within the span or a small window around it). **[Reconciled — implementation]**: enforcement moved to parse time with a repair-then-reject policy instead of failing the whole run: a model span that does not contain its claimed text is **relocated** to the first case-insensitive occurrence of the surface form in the chunk (logged as a provenance warning — the citation may point at a different mention than the model intended, which the reviewer sees); an entity whose name appears nowhere in the chunk is **dropped**, never stored with a fabricated offset. The invariant that every *stored* span contains its claimed surface form still holds and is what the acceptance test asserts; live-model runs are not aborted by a single bad offset.

The extraction prompt is built by a small new module, `extractor.build_extraction_prompt(ontology_schema, chunk_text) -> str` (structurally analogous to drylab's `domain.improvement_prompt()` but new code). It embeds the active ontology schema (entity types + relation types + a few-shot example in a neutral domain, e.g. software docs) plus the document chunk, and instructs the model to return the single fenced ` ```json ` block specified above.

---

## 8. Local dashboard (reused FastAPI + vanilla frontend)

`server/app.py` + `serve.py` + `web/` are reused as-is (same `create_app()` factory, same 127.0.0.1-only uvicorn binding, same static-mount pattern). New screens:

| Screen | Route | Backend | Purpose |
|---|---|---|---|
| **Sources / Ingest** | `/sources` | `/api/sources`, `/api/jobs?stage=collect` | Configure paper-API queries / seed URLs + allowlisted domains; launch a collect job; watch SSE progress; list collected documents. |
| **Ontology Review & Approval Queue** | `/review` | `/api/proposals` (list/filter), `/approve`\|`/reject`\|`/edit` | The HITL gate: paginated `proposed` nodes/edges with source-span highlight, inline edit, bulk-approve-by-filter, per-item provenance. Nothing here writes automatically. |
| **Graph Browser** | `/graph` | `/api/graph/nodes`, `/edges`, `/search` | Explore verified (default) or proposed KG: entity lookup, neighbor expansion, path traversal, search box. Mirrors the MCP query tools 1:1 so a human can sanity-check what the MCP server will answer before shipping a pack. |
| **Pack Build / Export** | `/packs` | `/api/packs` (list/build/diff/export) | Pick a subgraph filter, trigger a `build-pack` job, view manifest diff vs. previous version, export the pack directory, see which packs are bound to a running MCP server. |
| **MCP Server Status** | `/mcp` | `/api/mcp/status`, `/start`, `/stop` | Which pack a dashboard-managed instance is bound to; lists externally-spawned stdio servers read-only (PID/lockfile convention); surfaces a copy-pasteable client config snippet. |
| **Engines / Settings / Cost** | `/settings` | `/api/engines`, `/settings`, `/cost` | Reused as-is (`shutil.which` availability, `Settings` JSON, `cost_summary()` now aggregating collect/extract/build-pack jobs). |

Frontend stays dependency-free vanilla JS/HTML/CSS, no frontend framework introduced.

**[Reconciled — as shipped.]** The table above is the original per-route design sketch. The shipped dashboard is a **single-page tabbed SPA** (`web/index.html` + one `web/app.js`), not one route per screen, and job progress is **polled** (`GET /api/jobs`) rather than SSE — SSE is noted in the ROADMAP as an optional later upgrade. Shipped tabs: **Review** (HITL queue + critic triage order + per-entity review panel, W8/W11), **Merge** (entity-merge candidate review, W7), **Sources**, **Jobs**, **Packs** (build + `.mcpb` bundle + pack diff), **MCP**, **Engines**, **Settings**. Two design-table promises were reconciled rather than built as separate pages: the **Graph Browser** (`/graph`) was **not built as a standalone screen** — per-entity graph inspection (neighbors, relations, source-span mentions) is delivered by the W11 entity-centric review panel inside Review, and the same queries are available to a human via the CLI (`ontologylab entity`, `graph_query`) and to any MCP client; a full free-navigation graph browser remains an optional future screen. The Packs row's "manifest diff vs. previous version" ships as W14 pack-diff (CLI `pack-diff` + `GET /api/packs/{a}/diff/{b}` + a Packs-tab panel). **[UX pass, 2026-07]** The SPA was later reorganized workflow-first with a Korean UI: a **Home** tab (pipeline stepper ① collect → ② extract → ③ review → ④ pack → ⑤ connect, live counts, next-action recommendation), primary tabs renumbered in pipeline order with auxiliary tabs (Merge/Communities/Engines/Settings) grouped after a separator, per-tab intro copy, and cross-tab jump links (`data-goto`). No API or element-id changes — cosmetic/navigation layer only.

---

## 9. MCP server interface

`ontologylab.mcp_server` is a standalone stdio process built with the official Python MCP SDK's high-level `FastMCP` (`mcp.server.fastmcp.FastMCP`). No network port, no auth — matching the local-first posture.

```
python -m ontologylab.mcp_server [--packs-dir PATH] [--pack PACK_ID]
```

- `--packs-dir` defaults to `<ROOT>/packs/`. Each subdirectory is one pack (`pack.sqlite` + `manifest.json` + `schema.json` + `provenance.jsonl`).
- `--pack` optionally pins one pack at startup. If omitted, the client calls `load_pack` first; if exactly one pack exists, the server auto-loads it (zero-config single-pack setup).

Client config (Claude Desktop / Claude Code):

```json
{
  "mcpServers": {
    "ontologylab": {
      "command": "python",
      "args": ["-m", "ontologylab.mcp_server", "--packs-dir", "/Users/me/ontologylab/packs"]
    }
  }
}
```

### 9.1 Safety invariant

Every read tool filters to `status='verified'` by **default**, returning `proposed` rows only when a caller explicitly passes `include_proposed=true`. `rejected` rows are never returned. Because a pack contains only verified rows, `include_proposed` is meaningful only against the working DB (dashboard), not against a shipped pack — a pack literally has no proposed rows. This is the load-bearing safety property: an MCP client never silently treats an unapproved extraction as fact.

### 9.2 Tool surface (all read-only against the KG)

The **only** tool that writes anything is `load_pack`, and it writes only in-memory server session state (which sqlite file is open) — never KG rows. There is deliberately **no** `create_entity` / `approve_relation` / `edit_node` tool: approval is a human action through the dashboard/CLI, out of MCP scope. A 100% read-only surface means any MCP client can be pointed at a pack with zero risk of corrupting the graph.

| Tool | Purpose | Key inputs | Reads KG | Writes KG | Writes server state |
|---|---|---|---|---|---|
| `list_packs` | Discover local packs + stats | — | yes | no | no |
| `load_pack` | Set/switch active pack | `pack_id` | yes (opens conn) | no | yes (active-pack pointer) |
| `get_schema` | Return ontology (entity/relation types) | `pack_id?` | yes | no | no |
| `entity_lookup` | Resolve a node by id or name (compact rows by default, W9) | `id?`, `name?`, `entity_type?`, `fuzzy`, `include_proposed`, `limit`, `detail` | yes | no | no |
| `get_entity` | Full record for one entity — aliases, properties, span citations, adjacent edges (W9 tier-2 follow-up) | `id`, `include_proposed` | yes | no | no |
| `semantic_search` | NL search over nodes (FTS5 → embeddings; optional fail-open LLM query expansion); normalized 0..1 `match_score`, same meaning across tiers (§5.4). Compact rows by default (W9) | `query`, `entity_type?`, `top_k`, `min_score`, `include_proposed`, `expand`, `detail` | yes | no | no |
| `graph_query` | Filtered subgraph query | `entity_type?`, `relation_type?`, `property_filters?`, `include_proposed`, `limit`, `offset`, `detail` | yes | no | no |
| `traverse_relations` | N-hop neighborhood from seed nodes | `start_ids`, `relation_types?`, `direction`, `max_hops`, `include_proposed`, `limit`, `detail` | yes | no | no |
| `find_path` | Shortest relation path between two nodes | `source_id`, `target_id`, `max_hops`, `relation_types?`, `include_proposed` | yes | no | no |
| `get_communities` | Build-time community summaries — corpus-level "main themes" a BFS can't answer (W12); drill into one community's members with `community_id` | `community_id?`, `limit` | yes | no | no |

All inputs/outputs are typed JSON-Schema contracts (no free-form kwargs). Traversal/path use naive BFS over `edges`, sufficient at local single-pack scale. Each tool's full input/output schema is the FastMCP type signature of its handler (Pydantic-derived JSON Schema); §9.3 gives representative worked examples, and every `semantic_search`/`entity_lookup` result carries the §5.4 normalized `match_score`. **[Shipped: 10 tools.]** The 8-tool set above the fold was the MVP surface; W9 added `get_entity` (two-tier compact→detail responses) and W12 added `get_communities`. The server also exposes read-only **resources** (`pack://{id}/manifest`, `/schema`, `/entity/{id}`) addressing the same data by URI.

### 9.3 Representative tool contracts

`entity_lookup` (name → node), abridged:

```
call:   entity_lookup { "name": "rate limiter", "entity_type": "Component" }
result: { "matches": [ {
  "id": "n_0142", "entity_type": "Component", "name": "RateLimiter",
  "aliases": ["rate-limiter", "request throttler"],
  "properties": { "language": "Go", "repo_path": "services/gateway/ratelimiter" },
  "status": "verified", "source_document_ids": ["doc_0007"], "match_score": 0.93
} ] }
```

`find_path` (how is A connected to B), abridged:

```
call:   find_path { "source_id": "n_0142", "target_id": "n_0201" }
result: { "found": true, "hop_count": 1,
  "path": [ {"node_id":"n_0142","name":"RateLimiter"}, {"node_id":"n_0201","name":"TokenBucketAlgorithm"} ],
  "path_edges": [ {"relation_type":"implements","source_id":"n_0142","target_id":"n_0201"} ] }
```

### 9.4 Implementation sketch

```python
# ontologylab/mcp_server.py
from mcp.server.fastmcp import FastMCP
from ontologylab.kgstore import KGStore   # sibling of drylab/memory.py

mcp = FastMCP("ontologylab")
_state = {"store": None, "pack_id": None}

@mcp.tool()
def load_pack(pack_id: str) -> dict:
    if _state["store"] is not None:
        _state["store"].close()             # one active read-only connection at a time
    _state["store"] = KGStore.open(pack_dir_for(pack_id) / "pack.sqlite", read_only=True)
    _state["pack_id"] = pack_id
    ...

@mcp.tool()
def entity_lookup(id: str | None = None, name: str | None = None,
                  entity_type: str | None = None, fuzzy: bool = True,
                  include_proposed: bool = False, limit: int = 5) -> dict: ...

# ... list_packs, get_schema, semantic_search, graph_query, traverse_relations, find_path

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

`KGStore` is a small sibling of `memory.py` (same schema-on-open / OO-wrapper spirit) with `nodes`/`edges`/`documents`/`schema_version`/`entity_type`/`relation_type` tables instead of `runs`/`findings`, and the same `status` invariant the reviewer pattern established. **`KGStore.open()` is a real rewrite of `memory.open()`, not a rename:** drylab's `memory.open(data_dir)` takes a *directory* and hardcodes `memory.sqlite` in WAL mode with no read-only path. `KGStore.open(file_path, *, read_only=False)` instead takes an explicit **file** path and a `read_only` flag — read-write mode enables WAL for the working DB; `read_only=True` opens the pack via the `file:...?mode=ro&immutable=1` URI from §6 (never creating a `-wal` sidecar). The same `KGStore` class serves both the working DB (read-write) and a pack (`read_only=True`).

---

## 10. Directory layout

```
ontologylab/                    # renamed package (was drylab/)
  engines.py                    # reuse-asis: Engine Protocol + adapters (+ extract_fenced_block)
  provenance.py                 # reuse-asis
  safety.py                     # reuse-asis
  tui.py                        # reuse-asis
  paths.py                      # reuse-adapt of config.py: ROOT/data, ROOT/packs derivation
  kgstore.py                    # reuse-adapt of memory.py: nodes/edges/schema/status/embedding
  extractor.py                  # NEW: prompt building, extract_fenced_block, parse+validate
  ontology_schema.py            # NEW: default ontology definition (seeds schema tables)
  connectors/                   # NEW: base.py, paper_api.py, web_crawl.py, allowlist.py
                                #   (allowlist.py is deny-by-default; guards BOTH web_crawl and paper_api)
  packbuilder.py                # NEW: verified-only pack export (non-WAL/checkpoint/VACUUM + FTS rebuild)
  main.py                       # reuse-adapt CLI (structural rewrite to subcommands):
                                #   collect | extract | build-pack | approve | reject | review
  mcp_server.py                 # NEW: FastMCP stdio server, opens pack.sqlite read-only
  serve.py                      # reuse-asis: dashboard entry point
  models.py                     # reuse-adapt: Engine Protocol kept; new ProposedEntity/Relation/PackManifest
  server/
    app.py                      # reuse-asis
    routes.py                   # reuse-adapt (+proposals, graph, packs, mcp)
    runner.py                   # reuse-adapt (JobManager)
    schemas.py                  # reuse-adapt
    settings.py                 # reuse-asis
  web/                          # reuse-asis shell + new screens (sources/review/graph/packs/mcp)
data/
  kg.sqlite                     # the single running local knowledge graph
  documents/<doc_id>/           # raw collected documents + metadata
  jobs/<job_id>/                # per-job status.json + provenance.jsonl
packs/
  <pack_id>/
    pack.sqlite                 # immutable verified-only snapshot (same schema as kg.sqlite)
    manifest.json
    schema.json
    provenance.jsonl
```

`data/` is the mutable working area; `packs/` is the immutable, MCP-servable output — the same "working directory vs. shipped artifact" split drylab draws between `runs/` and `best_artifact.py`.

---

## 11. drylab reuse map

| drylab module | Disposition | In ontologylab |
|---|---|---|
| `engines.py` | **reuse-asis** | Engine Protocol + `get_engine()` + Mock/Claude/Codex/Gemini adapters, unchanged; add `extract_fenced_block(text, lang="json")` alongside `extract_python_code`. **The single most important reused piece.** |
| `provenance.py` | **reuse-asis** | Per-job JSONL log + `status.json` for collect/extract/build-pack jobs; LLM call/cost tracking. |
| `safety.py` | **reuse-asis** | `Caps` (max documents / LLM calls / wall-clock) + `KillSwitch` bound extraction/crawl jobs. |
| `tui.py` | **reuse-asis** | CLI progress for each stage. |
| `server/app.py`, `serve.py` | **reuse-asis** | FastAPI factory + 127.0.0.1 uvicorn shell; only import paths and `web/` content change. |
| `server/settings.py` | **reuse-asis** | `engines()` availability + `cost_summary()` across job dirs. |
| `memory.py` | **reuse-adapt (with a real `open()` rewrite)** → `kgstore.py` | Schema-on-open + OO-wrapper + verified-only invariant kept; `findings` replaced by `nodes`/`edges` + schema tables + status + embedding. **`open()` is rewritten, not renamed:** `memory.open(data_dir)` takes a directory and hardcodes `memory.sqlite` with no read-only path; `KGStore.open(file, *, read_only=False)` takes an explicit file + read-only flag (WAL when read-write, `mode=ro&immutable=1` when read-only, §6). |
| `config.py` | **reuse-adapt** → `paths.py` | ROOT/data + ROOT/packs derivation; optimization fields replaced by pipeline fields. |
| `main.py` | **reuse-adapt (structural rewrite to subcommands)** | Today `main.py` is flat argparse for one optimization run; ontologylab needs real subcommands — `collect`/`extract`/`build-pack`/`approve`/`reject`/`review` — each with its own arg set and wiring of engine/kgstore/provenance/safety/tui. This is a structural change, not a rename. |
| `server/routes.py` | **reuse-adapt** | Keep SSE `/events`, settings/engines/cost routes; add proposals/graph/packs/mcp routes. |
| `server/runner.py` | **reuse-adapt → JobManager (real `create()` rewrite)** | Subprocess-per-job + tail-provenance SSE pattern kept, but `runner.create()` today hardcodes optimization args and a single `RunCreate` schema. ontologylab has **three heterogeneous stages** (collect/extract/build-pack) needing per-stage launch variants, each still replicating the `status.json` + `provenance.jsonl` protocol the SSE tailer expects — so `create()` is genuinely rewritten, not just pointed at a new entry point. |
| `server/schemas.py` | **reuse-adapt** | `EngineInfo`/`Settings`/`CostSummary` verbatim; job models get extraction/pack fields. |
| `reviewer.py` | **reference-only** | Reuse the *pattern* — a distinct verification step flips `proposed -> verified` — as human approve/reject; the rerun-reproducibility check is meaningless for LLM output and is not ported. |
| `coordinator.py` | **reference-only** | Control-flow shape (propose → record → cap-check) informs the extract orchestration; the try-candidates-pick-best loop does not exist here. |
| `domain/base.py` | **reference-only** | Clean-Protocol style informs the `Connector` Protocol; no code reused. |
| `models.py` | **reference-only** (except Engine Protocol, kept) | Engine Protocol kept verbatim; other dataclasses replaced by `Document`/`ProposedEntity`/`ProposedRelation`/`PackManifest`. |
| `sandbox.py` | **drop** | Extraction is parsed, never executed — no untrusted-code sandbox needed. |
| `domain/heuristic_evolution.py` | **drop** | Bin-packing optimization demo; zero applicability. |
| `__init__.py` | **drop**/recreate | New empty package init. |

---

## 12. Non-goals

Carried over and explicit:

- **No multi-user / cloud deploy.** Local single-user first. No auth, no remote hosting, no shared state across machines.
- **No physical hardware / instrument control.**
- **Connectors are deny-by-default (strict allowlist), on both connectors.** `connectors/allowlist.py` is a **positive** allowlist: a request is permitted only if it matches an allowlisted entry, and anything else is rejected with a clear error (never silently skipped). This is enforced at **both** ingest connectors, from day one, not a retrofit:
  - **`web_crawl`** checks each URL's host against an allowed-domain list.
  - **`paper_api`** enforces the allowlist at the same point as web crawl, with two gates matched to where risk actually lives. **Sources are a closed positive list** — each name (`arxiv`, `crossref`, `openalex`, `semanticscholar`, `europepmc`) maps to exactly one fixed keyless endpoint constant, keeping the network boundary enumerable. **Queries are validated, not enumerated** (non-empty, length-bounded, no control chars, no embedded URL): a query is only a percent-encoded search term inside a fixed endpoint and cannot redirect the request, so the original five-phrase positive list was dropped (2026-07) as an unusable training wheel. Full-text is out of scope; only title+abstract are ingested.
  Shipped example content and the default allowlist use neutral domains only: software, technical documentation, and general knowledge. The default allowlist contents are listed in §12.1.
- **No candidate-code execution.** Unlike drylab, ontologylab never runs LLM-authored code; `sandbox.py` is intentionally dropped.
- **No external graph DB or vector DB in v1.** sqlite (+ FTS5, later optional `sqlite-vec`) only.
- **The MCP surface never mutates the graph.** Approval is human-only, outside MCP scope.

### 12.1 Default allowlist (shipped contents)

`connectors/allowlist.py` ships populated so the deny-by-default posture is real out of the box. All entries are neutral (software / technical documentation / general knowledge):

```python
# deny-by-default: a request is allowed ONLY if it matches an entry below.
WEB_CRAWL_ALLOWED_HOSTS = {
    "docs.python.org",
    "developer.mozilla.org",
    "www.rfc-editor.org",
    "peps.python.org",
    "raw.githubusercontent.com",   # project READMEs / docs
}

PAPER_API_ALLOWED = {
    # allowed API sources ...
    "sources": {"arxiv", "crossref"},
    # ... and allowed query categories/terms (positive list, not an open field)
    "queries": {
        "distributed systems", "software architecture",
        "programming languages", "databases", "operating systems",
    },
}
```

Both connectors import from this one module; a URL host or a paper query not present is rejected with a clear `NotAllowlisted` error. Extending the allowlist is an explicit, reviewable edit to this file — the enforcement point is the same for both connectors.
