# Step 7 kickoff prompt

Use this prompt verbatim to start Wave 2.1 Step 7.

```text
Continue OntologyLab Wave 2.1 from Step 6's completed transactional v2 shadow service. Read these first and treat them as execution authority (section 0 of the blueprint wins on conflict):

- docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md
- .omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md
- .omo/evidence/ulw/wave21-step6-ingestion-service-20260821/G007/a1/step6-evidence-index.md

Baseline: commit e3bca459c27f6d2cbcabb1a0a9bc37230d38316f
(tree 47e5964457c46f6a769ff074ed20f3619e1b9c0c, perimeter
abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e,
suite 2521 passed / 1 skipped / 2 xfailed, exit 0). Do not rewrite Step 5
or Step 6 product bytes except where a Step 7 seam must call them.

Implement Step 7 only: Representation-scoped extraction, citation receipts,
review grounding, and policy receipts (analysis 7A run/chunk, 7B historical
Citation migration, 7C review/grounding). Do not implement Step 8+ (no pack
v2, no F11, no MCP snapshot, no standalone verifier). Do not implement 9A
cutover rehearsal beyond what 7B needs on backup copies, and do not start
9C or any production cutover. Do not enable FULL_V2_AUTHORITY. Do not claim
lossless ingestion, full semantic dual-write, or full 05-failure-analysis.md
F2 GREEN.

Required scope:
1. Make run identity Representation-scoped. Add chunk end/profile/hash plan
   receipts. Add Citation receipts that bind ID, window, text, hash, profile,
   run, and chunk, and verify them at write and at review. Add append-only
   ReviewDecision over fact revision plus citation-set digest.
2. Keep the F9 extraction-selection tuple fixed:
   ready > usable full text > grade > source > stage > length > lexical hash.
   Separate that tuple from version/stage projection (preferred-representation-v1).
   A policy v2 change must bind only future explicit selection. Old runs and
   citations stay on their original receipt.
3. C-024 GREEN requires an actual research consumer, not a helper that
   pretends to be one. Fixture: publisher publishedVersion abstract beside
   unknown-stage PMC full text. The live research extract path must select
   the PMC richer ready Representation. Kill the mutant where stage beats
   usable full text.
4. Ordinary cascade preflights every member. Any ungrounded member writes
   zero. Explicit approve_with_grounding_waiver(actor, reason, exact IDs) is
   durable, working-graph only, and excluded by the default publication
   predicate. A generic approval must not act as a waiver. Root-only
   validation must fail.
5. H1 historical extraction/chunk/citation/review migration: assign
   deterministic legacy receipt IDs and a raw-byte seal, and rehearse only
   on SQLite backup-API copies in caller-owned directories. Unverifiable
   spans are quarantined, never guessed. Every document/node/edge/citation
   anchor is preserved and classified. Production Application Support data
   is out of scope.

Named mutants that must die, then restore byte-identical:
- content-hash run lookup restored
- chunk end/profile omitted
- selected text altered after hash
- generic approval used as a waiver
- cascade validated at the root only
- old run's preferred doc recomputed after a policy change
- stage wins over usable full text (C-024)
- hash-run lookup / unverifiable span "fixed" by guess

Evidence requirements:
- RED before each production change; GREEN after; mutation proof per
  decision point; real-surface proof on disposable stores (installed CLI,
  HTTP, and the actual research consumer).
- Tests assert machine-consumed receipts (run/chunk/Citation/ReviewDecision
  ids, hashes, windows, waiver flags), not prose.
- No fixed sleeps, polling, or retry-to-pass.
- Disposable fixtures and backup-API copies only. No live Application
  Support data. No port 8799 / PID 55560. No external network. No planning
  doc edits.
- Do not commit unless the user explicitly authorizes a commit.

Completion:
- report exact RED/GREEN commands, changed files, mutation receipts, C-024
  research-consumer receipt, H1 backup-copy rehearsal receipt, waiver
  preflight receipt, cleanup, and the Step 7 evidence index;
- produce a verbatim Step 8 kickoff prompt;
- leave Step 6 commit e3bca45 as the product baseline unless a new Step 7
  commit is explicitly authorized.
```
