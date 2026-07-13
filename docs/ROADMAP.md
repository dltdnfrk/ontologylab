# ontologylab — Phased Development Roadmap

Perspective: sequencing milestones from `drylab` rename through to a queryable local MCP
knowledge pack, maximizing reuse of existing `drylab` infra. Each milestone lists goal,
deliverables, acceptance criterion, and reused modules (`reuse-asis` / `reuse-adapt` /
`reference-only` / `drop`, per the asset map). Examples and shipped connectors use neutral
domains only: software, technical documentation, general knowledge (a small corpus of
software/technical docs — e.g. a handful of open-source project READMEs and RFC-style text
files — stands in for "papers/documents"). Connectors are deny-by-default: only allowlisted
sources/queries are permitted.

---

## Milestone 0 — Scaffold & Rename (`drylab` → `ontologylab`)

**Goal:** Stand up the renamed package skeleton with zero behavior change, so every later
milestone lands in the right namespace from day one.

**Deliverables:**
- `git mv drylab ontologylab`; update `pyproject.toml` package name, console-script entry
  points, and all `drylab.` import paths (`engines`, `config`, `provenance`, `safety`,
  `memory`, `server/*`, `serve`, `main`).
- New `ontologylab/__init__.py` (trivial, per asset map — `drop`+recreate).
- `ontologylab/domain/` and `ontologylab/sandbox.py` **left out of the new package**
  (confirmed `drop` — no candidate-code execution in this project); `ontologylab/coordinator.py`,
  `ontologylab/reviewer.py`, `ontologylab/domain/base.py`, `ontologylab/domain/heuristic_evolution.py`
  copied into `docs/reference/drylab-snapshot/` read-only for design reference, not imported.
- `ROOT/data/kg.sqlite` and `ROOT/packs/` directory constants added to a renamed
  `ontologylab/paths.py` (successor to the ROOT/data-dir derivation in `config.py`).
- Rename `runs/` → `jobs/` (extraction/pack-build job dirs) consistently across
  `provenance.py`, `safety.py`, `tui.py`, `server/runner.py`, `server/settings.py` call sites.
- Existing test suite (`tests/test_smoke.py`, `tests/test_server.py`) ported to
  `ontologylab` imports and re-run green as a regression baseline before any new code is added.

**Acceptance criterion:** `python -m ontologylab.serve` boots the existing (unmodified-feature)
FastAPI shell on `127.0.0.1:8765`; `pytest` passes with only import-path diffs vs. the drylab
baseline; no `drylab` module is imported anywhere in `ontologylab/`.

**Reused modules:** `server/app.py`, `serve.py` (`reuse-asis`, import renames only); `config.py`
(`reuse-adapt`, becomes `paths.py`); everything else deferred to later milestones.

**Risk:** rename touches every file — do it as one mechanical PR before any logic changes, so
later diffs stay reviewable. Do not interleave renaming with new features.

---

## Milestone 1 — Engine CLI Adapters Carried Over

**Goal:** Get the LLM subprocess adapters working unchanged under the new namespace, since every
downstream milestone (extraction, verification prompts, pack summaries) calls `generate()`.

**Deliverables:**
- `ontologylab/engines.py`: literal port of `Engine` Protocol
  (`async generate(prompt, *, model) -> tuple[str, dict]`) and `MockEngine` /
  `ClaudeEngine` / `CodexEngine` / `GeminiEngine` / `get_engine(name, model, seed)`.
- Swap `extract_python_code(text)` → `extract_fenced_block(text, lang="json")` (generic fence
  extractor; used later by the extraction pipeline, not by this milestone directly — this
  milestone only needs the function to exist and be unit-tested against a few fixture strings).
- Unit tests: each engine's `generate()` mocked/stubbed at the subprocess boundary
  (`subprocess.run` monkeypatched), confirming timeout/`EngineError` behavior is unchanged from
  drylab, plus a live smoke test against `MockEngine` only (no network/CLI dependency in CI).
- `ontologylab.engines.get_engine("claude", "claude-fable-5", seed=7)` importable and callable
  from a throwaway script.

**Acceptance criterion:** `MockEngine.generate("hello")` returns deterministic `(text, usage)`
in CI; a manual local run of `ClaudeEngine` (subscription CLI present) round-trips a prompt and
returns non-empty text within the configured timeout.

**Reused modules:** `engines.py` (`reuse-adapt` — only the post-`generate()` parser changes),
`models.py`'s `Engine` Protocol (`reference-only` → copied verbatim, per `engineCliContract`).

**Dependency:** none (can start immediately after M0). **Risk:** none of the target CLIs
(`claude`/`codex`/`gemini`) may be installed in a given dev/CI environment — `MockEngine` must
stay the CI-default so this milestone doesn't block on external tooling.

---

## Milestone 2 — sqlite KG Store (nodes/edges + proposed/verified status)

**Goal:** Stand up the storage backend everything else writes into, before there's any content
to write — extraction (M4) and HITL verification (M5) both depend on this schema existing.

**Deliverables:**
- `ontologylab/kgstore.py` (successor to `memory.py`): sqlite schema per `ARCHITECTURE.md` §5 —
  the ontology-type tables (`schema_version`, `entity_type`, `relation_type`) plus
  `documents(...)`, `nodes(id, entity_type, name, aliases_json, properties_json, status,
  confidence, source_doc_id, source_span, extractor_engine, ..., embedding BLOB, embedding_model)`,
  `edges(id, relation_type, src_node_id, dst_node_id, properties_json, status, ..., source_doc_id)`.
  **No `packs` table** — [Reconciled] pack discovery is directory + `manifest.json` scanning
  (ARCHITECTURE.md §6); the filesystem is the single source of truth, so the working DB holds no
  pack registry that could drift from disk.
  `status` is an enum column `{proposed, verified, rejected}` on both `nodes` and `edges`,
  mirroring `Finding.verified` — nothing is verified except by an explicit approval call.
  A stored `normalized_name` column + a `UNIQUE(schema_version_id, entity_type, normalized_name)`
  index back entity resolution (ARCHITECTURE.md §5.5).
- An OO `KGStore` wrapper class (same spirit as `Memory`, used for both the working DB read-write
  and a pack `read_only=True`), with `insert_proposed(nodes, edges, ...)`,
  `approve(node_or_edge_id)`, `reject(...)`, `verified_subgraph(...)`, and
  `semantic_search(query, top_k)`. **`KGStore.open()` is a real rewrite of `memory.open()`, not a
  rename** (ARCHITECTURE.md §9.4/§11): `memory.open(data_dir)` takes a *directory* and hardcodes
  `memory.sqlite` in WAL with no read-only path; `KGStore.open(file, *, read_only=False)` takes an
  explicit **file** path + a `read_only` flag — WAL when read-write, `file:...?mode=ro&immutable=1`
  when read-only (so a pack never creates a `-wal` sidecar).
- **Entity resolution inside `insert_proposed`** (ARCHITECTURE.md §5.5): dedup each node by
  `(schema_version_id, entity_type, normalized_name)` over proposed+verified nodes (hit reuses the
  id and appends a citation; miss mints a uuid), then bind every relation endpoint to the resolved
  node id — so the KG is one connected graph, not per-chunk stars.
- **[Reconciled] Search ships tiered:** MVP uses sqlite **FTS5 lexical** search over
  `name`/`aliases_json`/`properties_json` (zero new deps; the tool must state it is lexical, not
  vector); the `embedding` BLOB column + in-process cosine similarity is the documented
  **post-MVP** tier-2 upgrade behind the same signature (upgrade path to `sqlite-vec` noted but not
  built). **Both tiers normalize their raw backend score into one documented 0..1
  higher-is-better `match_score`** (BM25 → `1/(1+bm25)`; cosine → `(cos+1)/2`), so the stable tool
  signature never silently changes meaning (ARCHITECTURE.md §5.4).
- Unit tests: insert-proposed → query returns `status=proposed`; `approve()` flips status;
  `verified_subgraph()` never returns a `proposed` row even if it's the only data present; two
  mentions of the same entity across two documents resolve to **one** node carrying both citations.

**Acceptance criterion:** a test seeds 5 proposed nodes + 3 proposed edges, approves 3 nodes +
1 edge, and `verified_subgraph()` returns exactly the approved 3+1 — proving the "never silently
treat unverified as ground truth" invariant holds end-to-end at the storage layer.

**Reused modules:** `memory.py` (`reuse-adapt` — table shapes are new, but WAL pragma,
open()/schema pattern, OO wrapper, and the verified-only invariant are carried over intact).

**Dependency:** M0 only. **Risk:** [Reconciled] semantic search is FTS5-lexical for the MVP —
no embeddings, no vector math — so there is no embedding-format decision on the MVP path; when
tier-2 embeddings land, the `embedding` column is a packed float32 BLOB and in-process cosine is
fine at local/single-user scale, a known scaling ceiling (not a blocker) with `sqlite-vec` as the
first upgrade beyond it.

---

## Milestone 3 — Ingest Connectors (paper API + web/URL crawl)

**Goal:** Get raw documents into the `documents` table so extraction (M4) has real input.

**Deliverables:**
- `ontologylab/connectors/base.py`: small `Connector` Protocol —
  `async fetch(source_spec) -> list[Document]` (name/id/uri/title/raw_text), intentionally
  modeled after (not copied from) `domain/base.py`'s clean-Protocol style.
- `ontologylab/connectors/allowlist.py`: a **deny-by-default** (strict positive) allowlist module
  shared by BOTH connectors — a request is permitted only if it matches an allowlisted entry,
  anything else is rejected with a clear `NotAllowlisted` error (never silently skipped). Ships
  populated with neutral defaults (ARCHITECTURE.md §12.1): `WEB_CRAWL_ALLOWED_HOSTS`
  (e.g. `docs.python.org`, `developer.mozilla.org`, `www.rfc-editor.org`) and `PAPER_API_ALLOWED`
  (allowed `sources` like `arxiv`/`crossref` + a positive `queries` list). Must exist before any
  connector code ships, not be a follow-up.
- `ontologylab/connectors/paper_api.py`: one public, keyless metadata+abstract API connector
  (e.g. arXiv Atom API or Crossref — pick one with no auth). Every query/source is checked against
  `PAPER_API_ALLOWED` **before** any network call, so the paper connector has the same real
  enforcement point as web crawl (a positive allowed-source/query list, not an open query field).
- `ontologylab/connectors/web_crawl.py`: single-URL / small-URL-list fetcher (HTML → text
  extraction, e.g. via stdlib `html.parser` or a light dependency); every URL host is checked
  against `WEB_CRAWL_ALLOWED_HOSTS` before fetch.
- CLI: `python -m ontologylab.main collect --paper-query "..." [--paper-source arxiv] [--limit 5]`
  writes rows into `documents` via `kgstore.py`, logs each fetch via `provenance.py`.
  (Shipped shape: flag-style inputs — `--paper-query`/`--url`/`--file`, composable in one run —
  were chosen over the originally sketched `--connector` subcommand shape.)

**Acceptance criterion:** `collect` run against 3-5 example documents (mixed: 2-3 from the paper
API, 1-2 from web crawl of software-docs URLs) populates `documents` with non-empty `raw_text`;
a non-allowlisted crawl host is rejected with a clear error, and a non-allowlisted paper
query/source is likewise rejected before any network call — neither is silently skipped.

**Reused modules:** `provenance.py` (`reuse-asis`); the safety-cap intent is realized by the
per-query result limit clamp (1..25) inside the paper connector (`Caps`/`KillSwitch` remain
extract-only); per-document progress is the existing print-per-document lines in `collect`
(`tui.py` is not wired into collect).

**Dependency:** M0 (paths), M2 (documents table to write into). **Risk:** paper-API rate limits
/ schema drift — keep the connector thin and swappable; web crawl HTML→text quality varies by
site, acceptable for MVP as long as extraction (M4) tolerates noisy text.

---

## Milestone 4 — LLM Extraction Pipeline (ontology auto-extraction)

**Goal:** Turn raw document text into `proposed` nodes/edges using the M1 engine adapters and
M2 store — this is the connective core of the whole project.

**Deliverables:**
- `ontologylab/ontology_schema.py`: a small, hardcoded example ontology for the MVP domain
  (entity types: `Concept`, `Component`, `Technique`; relation types: `uses`, `part_of`,
  `related_to` — generic/software-doc-shaped, not domain-specific beyond that).
- `ontologylab/extractor.py`:
  - **Chunking:** ~1,500-token chunks with ~150-token overlap (heuristic ≈4 chars/token, no
    model-specific tokenizer dep), tracking each chunk's `(char_offset_in_document, length)` for
    span rebasing; prompt token budget capped to context minus a response reserve.
  - `build_extraction_prompt(document_chunk, schema) -> str` (embeds schema + chunk + a
    neutral-domain few-shot).
  - `parse_and_validate_extraction(raw_text, schema) -> (list[ProposedNode], list[ProposedEdge])`
    — **calls `extract_fenced_block(text, lang="json")` internally** (so `main` passes raw model
    text, resolving the call-boundary contradiction), then `json.loads` + dataclass/Pydantic
    validation against allowed types (reject/flag off-schema items, never coerce). The model
    returns `{"entities":[...], "relations":[...]}` where **each relation references its endpoints
    by `{name, entity_type}`, never by array index or a model-invented id**; the parser mints a
    uuid per valid entity, resolves each relation's `source`/`target` `{name,type}` to those
    minted ids (synthesizing a flagged placeholder endpoint if a relation names an un-emitted
    entity), and **rebases each chunk-local `source_span` to document coordinates**
    (`doc_start = chunk.char_offset + span.start`) so the stored span indexes the original
    `documents.raw_text` (ARCHITECTURE.md §7.1).
- Orchestration `ontologylab/main.py extract --engine claude --model claude-fable-5 --doc-ids ...`:
  for each unprocessed document chunk, calls `get_engine(...).generate(prompt, model=...)`, parses
  the result, writes `proposed` nodes/edges to `kgstore` (`insert_proposed` runs entity resolution,
  §5.5), logs an `engine_call` provenance event (reusing `provenance.track_engine_call`), and
  respects safety using the **real drylab APIs**: `stop, reason = Caps.should_stop(state)` and
  `KillSwitch.triggered()` (not `caps.check()`/`kill_switch.check()`).
- Dataclasses `ProposedEntity` / `ProposedRelation` (successor to `Finding`, per asset map) in
  `ontologylab/models.py`.

**Acceptance criterion:** running `extract` against the M3 documents with `--engine mock`
deterministically produces a non-empty, schema-valid set of `proposed` nodes/edges in one pass,
with zero rows ever written as `verified`; a malformed/off-schema LLM response is rejected (not
inserted) and logged as a provenance warning rather than crashing the run. **Citation-integrity
check:** for every stored row, `raw_text[source_span.start:source_span.end]` is non-empty and
contains the claimed surface form (node name/alias, or both endpoint names for a relation) — a
span that doesn't contain its claimed text fails the run (catches off-by-one rebasing / fabricated
offsets). **Connectedness check:** two documents mentioning the same entity yield **one** resolved
node with both citations, and `find_path` crosses between their distinct related nodes through it.

**Reused modules:** `engines.py` (M1 output, `reuse-adapt`), `provenance.py` (`reuse-asis`),
`safety.py` (`reuse-asis`), `tui.py` (`reuse-asis`), `coordinator.py` (`reference-only` — the
propose→record→cap-check control-flow shape, not the code), `models.py`'s `Finding`/`EngineSpec`
patterns (`reference-only`).

**Dependency:** M1 (engines), M2 (store), M3 (documents to extract from). **Risk:** LLM JSON
adherence is imperfect — budget real iteration time on the parser/validator and its retry/
reject policy; this is the highest-uncertainty milestone in the roadmap.

---

## Milestone 5 — HITL Verification (approve/reject proposed → verified)

**Goal:** Implement the mandatory human approval gate — nothing becomes queryable via a
knowledge pack until a human has acted on it.

**Deliverables:**
- **Headless approval CLI (MVP surface): `ontologylab.main approve|reject|review`** (ARCHITECTURE.md
  §4a) — `review` prints the `pending_review` queue; `approve --id` / `reject --id` flip one row;
  `approve --filter "..."` bulk-approves a batch. Each is a discrete, human-initiated command
  calling `kgstore.approve(id)`/`reject(id)` — the same code path the dashboard route uses. This is
  the explicit proposed→verified gate for the CLI-only MVP; **there is no automated verify stage**
  (no pipeline stage/scheduler ever sets `verified` — the CLI still requires a person to run it).
- API endpoints (new, on the reused FastAPI shell): `GET /api/proposals` (paginated list of
  `status=proposed` nodes/edges, filterable by document/type), `POST /api/proposals/{id}/approve`,
  `POST /api/proposals/{id}/reject` (optional reviewer note stored alongside — mirrors
  `reviewer.py`'s "distinct verification step", redesigned as human action).
- Minimal review screen in the reused vanilla-JS dashboard (`server/`'s static frontend):
  a queue view listing proposed entities/relations with source-document context, approve/reject
  buttons, and a running count of proposed vs. verified.
- **Edge-approval dependency (ARCHITECTURE.md §5.3):** `kgstore.approve(edge_id)` raises
  `EndpointNotVerified` unless both endpoints are already `verified`. In the queue, an edge whose
  endpoints aren't both verified renders **disabled** ("approve endpoints first") with its
  endpoints linked inline. **Bulk-approve processes nodes before edges and approves only edges
  whose endpoints are verified after the node pass, reporting the rest as skipped — it never
  approves an edge whose nodes are still proposed, and never auto-approves endpoints.**
- Bulk-approve-by-confidence-threshold as a convenience (still per-item auditable — every approval,
  bulk or not, writes an individual `approved_by`/`approved_at` record).

**Acceptance criterion:** a reviewer (via dashboard **or** the `approve|reject|review` CLI) sees
the M4 proposed set, approves a subset and rejects others, and `kgstore.verified_subgraph()`
immediately reflects exactly the approved subset — no proposed row is ever exposed through the
"ground truth" query path. **Edge-dependency test:** with node A proposed, node B verified, edge
A→B proposed — `approve(edge_AB)` raises `EndpointNotVerified` and leaves it proposed; a
bulk-approve reports A→B as skipped while A is proposed; after `approve(A)` the edge approves; and
a pack built at any point contains no edge whose endpoints aren't both verified.

**Reused modules:** `server/app.py`/`serve.py` (`reuse-asis`), `server/routes.py`
(`reuse-adapt` — new `/api/proposals` routes alongside the reused settings/engines/cost
routes), `server/schemas.py` (`reuse-adapt`), `reviewer.py`'s verified-only invariant
(`reference-only`, pattern reused not code).

**Dependency:** M4 (needs proposed data to review). **Risk:** UI is the one genuinely new
surface with no drylab precedent beyond the static-shell mount point — keep it minimal (a table
+ two buttons) for MVP; richer review UX (diff view, confidence scores, batch filters) is
explicitly post-MVP polish.

---

## Milestone 6 — Knowledge Pack Build & Export

**Goal:** Bundle the verified subgraph + ontology schema + provenance into the single
deployable artifact the MCP server will serve.

**Deliverables:**
- `ontologylab/packbuilder.py`: `build_pack(name) -> PackManifest` — snapshots
  `verified_subgraph()` (nodes+edges only, `status=verified`, edges only where both endpoints are
  in the copied node set), the ontology schema (M4), and a provenance summary into
  `packs/<pack_id>/` as a self-contained directory: `pack.sqlite` (verified-only copy),
  `schema.json`, `manifest.json`, `provenance.jsonl` excerpt. **Pack finalization physics
  (ARCHITECTURE.md §6):** copy verified rows across an `ATTACH`ed pair, **rebuild FTS5 INTO the
  pack** (`CREATE VIRTUAL TABLE` + populate — a row-copy of `nodes_fts` loses the virtual table +
  shadow tables), then `PRAGMA journal_mode=DELETE` (WAL **off**), `wal_checkpoint(TRUNCATE)`,
  `PRAGMA optimize`, `VACUUM` into the final compact file, and write `content_hash` into the
  manifest. The MCP server later opens it via `file:...?mode=ro&immutable=1` so no `-wal` sidecar
  is ever created.
- CLI: `python -m ontologylab.main build-pack --name my-pack`. **No `packs` table is written** —
  pack discovery is directory + `manifest.json` scanning (single source of truth on disk).
- `GET /api/packs`, `POST /api/packs` (build), `GET /api/packs/{id}/manifest` dashboard
  endpoints, reusing the SSE job-streaming pattern from `server/runner.py` for long builds.

**Acceptance criterion:** `build-pack` on the M5-approved subgraph produces a `packs/<id>/`
directory containing only verified nodes/edges (spot-checked: any `proposed`/`rejected` row is
absent from `pack.sqlite`), with a manifest listing node/edge counts, schema version, source
provenance, and `content_hash`. The finalized `pack.sqlite` is **not** in WAL mode and needs no
`-wal`/`-shm` sidecar; an `FTS5 MATCH` query against `nodes_fts` inside the pack returns rows
(proving the index was rebuilt into the pack, not lost). `list_packs` discovers the pack by
directory scan + `manifest.json` with no `packs` table involved.

**Reused modules:** `provenance.py` (`reuse-asis`), `server/runner.py` (`reuse-adapt` with a real
`create()` rewrite — the subprocess-per-job + SSE-tail pattern is kept, but `create()` today
hardcodes optimization args + one `RunCreate` schema; the three heterogeneous stages
collect/extract/build-pack need per-stage launch variants each replicating the
`status.json`/`provenance.jsonl` protocol the SSE tailer expects), `server/settings.py`
(`reuse-asis` — `cost_summary()` extended to scan pack-build provenance too).

**Dependency:** M2 (store), M5 (verified data must exist). **Risk:** deciding pack immutability
(rebuild-in-place vs. versioned packs) — recommend versioned (`pack_id` includes a build
timestamp/hash) so an MCP client's pinned pack never silently changes underfoot.

---

## Milestone 7 — Local MCP Server (graph query, semantic search, entity lookup, path traversal, pack management)

**Goal:** Expose a built pack as MCP tools an MCP client (e.g. Claude) can connect to locally.

**Deliverables:**
- `ontologylab/mcp_server.py`: `FastMCP` stdio server (`mcp.server.fastmcp.FastMCP`), launched
  with `--packs-dir PATH` and optional `--pack PACK_ID`; holds exactly one active read-only
  connection to a pack's `pack.sqlite` opened `file:...?mode=ro&immutable=1` (§6), switchable at
  runtime via `load_pack` (safe because packs are immutable). `list_packs` discovers packs by
  scanning `--packs-dir` for subdirectories with a readable `manifest.json` (no `packs` table).
  Exposes the 8 typed tools finalized in `ARCHITECTURE.md` §9.2 (each tool's full schema is its
  FastMCP handler signature; §9.3 gives worked examples):
  - `list_packs`, `load_pack`, `get_schema` — pack discovery / activation / ontology metadata.
  - `entity_lookup(id|name, entity_type?, fuzzy, include_proposed, limit)` — resolve a node.
  - `semantic_search(query, top_k, ...)` — **[Reconciled]** backed by M2's search tier: FTS5
    lexical for the MVP (tool description states lexical, not vector), cosine over embeddings
    post-MVP behind the same signature; both tiers return the same normalized 0..1
    higher-is-better `match_score` (ARCHITECTURE.md §5.4), so the field never changes meaning.
  - `graph_query(entity_type?, relation_type?, property_filters?, ...)` — filtered subgraph query
    over `pack.sqlite` (no Cypher engine; a small typed filter DSL is enough).
  - `traverse_relations(start_ids, relation_types?, direction, max_hops, ...)` and
    `find_path(source_id, target_id, max_hops, ...)` — naive BFS over `edges` (sufficient at scale).
- Every read tool defaults `include_proposed=false`; the MCP surface is 100% read-only (no
  create/edit/approve tool) — approval stays a human dashboard/CLI action, out of MCP scope.
- Entry point documented for MCP client config (Claude Desktop / Claude Code `mcpServers` stdio
  entry: `python -m ontologylab.mcp_server --packs-dir <path>`).
- Tool schemas kept explicit and typed (expose all categories initially, prune later) — every
  tool has a JSON-Schema/Pydantic input/output contract, no free-form kwargs.

**Acceptance criterion:** an MCP client connects to the local stdio server pointed at the M6
pack, calls `entity_lookup` for a known verified entity and gets back correct data, calls
`semantic_search` with a natural-language query relevant to the example corpus and gets
plausibly-ranked results, and `path_traversal` between two connected entities returns a valid
path — all read-only against the immutable pack, no mutation tools exposed.

**Reused modules:** none directly executed at runtime (this is new code), but `kgstore.py`'s
query helpers (M2) are called against `pack.sqlite` with the same query functions used
elsewhere, avoiding a second query implementation.

**Dependency:** M6 (needs a built pack to serve). **Risk:** MCP stdio server lifecycle/process
management with an MCP client is the least precedented piece (drylab has no analog) — budget
extra time for protocol conformance testing against at least one real client.

---

## Milestone 8 — Dashboard Screens (polish pass)

**Goal:** Round out the local web UI so the whole pipeline (collect → extract → review → build
→ serve status) is operable without the CLI, reusing the existing FastAPI+vanilla shell.

**Deliverables:**
- Screens: **Sources** (connectors run history, trigger new collect jobs), **Extraction Jobs**
  (polling-based job status via `GET /api/jobs`, mirroring `tui.py`'s status-polling pattern;
  SSE streaming is an optional later upgrade), **Review Queue** (M5, promoted
  to a first-class nav item), **Packs** (M6 list/build/export/download), **MCP Status** (which
  pack is currently active for the MCP server, a "copy stdio config" helper for MCP clients).
- `server/settings.py`'s `engines()` availability check surfaced in a Settings screen (already
  reusable as-is).
- `cost_summary()` extended (M6) surfaced as a simple cost/usage panel.

**Acceptance criterion:** a user can go from zero (no documents) to a queryable MCP pack
entirely through the dashboard, with no manual CLI invocation, in one sitting.

**Reused modules:** `server/app.py`, `serve.py`, `server/settings.py` (`reuse-asis`);
`server/routes.py`, `server/schemas.py`, `server/runner.py` (`reuse-adapt`, cumulative from
M5/M6); `tui.py` pattern mirrored in the frontend's own status polling.

**Dependency:** M5, M6, M7 all feed screens here — this is an integration/polish milestone, not
new backend capability. **Risk:** low — mostly frontend work on an already-reused shell.

---

## MVP Cut Line

The smallest end-to-end slice that proves the whole concept — **ingest 1 source → extract →
approve → build pack → query via MCP** — is:

**M0 (scaffold) → M1 (engines, Mock+Claude only) → M2 (kgstore) → M3 (single connector: web
crawl of one URL, skip the paper API for MVP) → M4 (extraction, `mock` engine acceptable for
automated tests, `claude` engine for the real demo) → M5 (approval — the headless
`ontologylab.main approve|reject|review` CLI is the MVP gate; the dashboard review screen can
follow) → M6 (pack build) → M7 (MCP server, read-only tools only, no dashboard).**

M8 (dashboard screens) and the paper-API connector, bulk-approve UX, richer review UI, and any
pack versioning UX are explicitly **post-MVP**. This MVP path touches every reused drylab module
that matters (`engines.py`, `provenance.py`, `safety.py`, `tui.py`, `server/app.py`+`serve.py`)
while deferring the two purely-new, highest-uncertainty surfaces (MCP protocol conformance in M7,
dashboard polish in M8) to be validated/iterated after the core loop is proven.

**Cross-cutting dependency chain:** M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7, with M8 fanning out
from M5/M6/M7. Nothing after M2 can start before M2 lands (every later milestone writes to or
reads from `kgstore`), and M4 is the pipeline's critical-path bottleneck (highest technical
uncertainty: LLM JSON-schema adherence) — prototype the extraction prompt/parser in isolation
(against `MockEngine` fixtures and one real `claude` call) before wiring the full CLI/dashboard
around it, so a redesign there doesn't cascade into M5–M8 rework.

**Top risks flagged across the roadmap:**
1. LLM extraction JSON adherence (M4) — the single highest-uncertainty step; budget iteration
   time on the parse/validate/reject loop.
2. MCP stdio protocol conformance with a real client (M7) — no drylab precedent to lean on.
3. Connector allowlist (M3) is deny-by-default and must ship with BOTH connectors (web_crawl host
   list + paper_api source/query list) from day one, not as a retrofit — only allowlisted
   sources/queries are ever permitted.
4. Semantic search honesty (M2/M7): tier-1 is **FTS5 lexical** (BM25) search, labeled as
   lexical (not vector) in the tool description and docs — never silently claim
   semantic/vector search that isn't there. Tier-2 SHIPPED as **fail-open LLM query
   expansion** (`expansion.py`): an engine proposes lexical query variants OR-composed
   into the same FTS5 MATCH, labeled `fts5+llm-expansion` only when variants were
   actually used; any expansion failure falls back to plain lexical, still labeled
   `fts5`. Embeddings remain an explicitly deferred, **opt-in external backend** —
   `sqlite-vec` is still the named eventual scaling step, not to be silently assumed.
