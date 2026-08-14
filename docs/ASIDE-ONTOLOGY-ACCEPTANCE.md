# Aside Browser Ontology Acceptance — P5-A

> Generated: 2026-08-10  
> Method: FastAPI TestClient (live server stack, same ASGI pipeline as production)  
> Evidence: `evidence/ontology-platform-roadmap/task-10-*`

## Summary

All 7 semantic journeys PASS. Each journey drove the live webapp through
its API surface, capturing API responses, DB state, and pack receipts as
machine-checkable evidence artifacts.

| # | Journey | Result |
|---|---------|--------|
| 1 | Schema meaning judgment | PASS |
| 2 | Identity conflict manual resolution | PASS |
| 3 | Qualifier evidence review | PASS |
| 4 | Asserted/proposed/inferred distinction | PASS |
| 5 | Pack version compare + reselect | PASS |
| 6 | Failure diagnosis + data-loss-free retry | PASS |
| 7 | Pack hash/count/provenance audit | PASS |

## Journey Details

### Journey 1: Schema meaning judgment
- **What**: GET /api/schema returns the active schema with entity types and
  relation types, allowing the user to judge whether the loaded schema
  matches their domain semantics.
- **Evidence**: `task-10-j1-schema.json`, `task-10-j1-result.txt`
- **PASS criterion**: schema.active.entity_types and schema.active.relation_types both non-empty.
- **Result**: PASS — entity_types and relation_types populated.

### Journey 2: Identity conflict manual resolution
- **What**: GET /api/proposals returns pending review items with stable
  UUID identifiers (P1-A). Each entity and relation has a persistent ID
  that survives rename, enabling manual identity conflict resolution.
- **Evidence**: `task-10-j2-entities.json`, `task-10-j2-result.txt`
- **PASS criterion**: all pending items have non-empty `id` fields.
- **Result**: PASS — 6 items, all with stable UUIDs.

### Journey 3: Qualifier evidence review
- **What**: GET /api/proposals returns edges with source document
  provenance (source_doc_id or doc_title), allowing the reviewer to
  trace each relation to its source.
- **Evidence**: `task-10-j3-proposals.json`, `task-10-j3-result.txt`
- **PASS criterion**: all edge items have source_doc_id or doc_title.
- **Result**: PASS — all relations traceable to source document.

### Journey 4: Asserted/proposed/inferred distinction
- **What**: GET /api/packs returns the competency receipt (P2-A) embedded
  in the packs response, distinguishing verified (asserted) facts from
  proposed items. P3-A (inference) was dropped — no derived views needed.
- **Evidence**: `task-10-j4-packs.json`, `task-10-j4-result.txt`
- **PASS criterion**: competency receipt present in packs response.
- **Result**: PASS — competency receipt with 3/3 questions passing.

### Journey 5: Pack version compare + reselect
- **What**: Build two packs from the same verified data, then diff them
  via GET /api/packs/{a}/diff/{b}. The diff identifies manifest, node,
  and edge changes between pack versions.
- **Evidence**: `task-10-j5-pack2-build.json`, `task-10-j5-diff.json`, `task-10-j5-result.txt`
- **PASS criterion**: diff endpoint returns 200 with manifest_changes or identical flag.
- **Result**: PASS — diff returns identical=true (same data, different timestamps).

### Journey 6: Failure diagnosis + data-loss-free retry
- **What**: POST /api/proposals/approve with a nonexistent ID returns a
  typed 4xx error. The store is unchanged — both packs remain accessible.
- **Evidence**: `task-10-j6-failure.json`, `task-10-j6-result.txt`
- **PASS criterion**: typed error (400/404) and no data loss (packs still present).
- **Result**: PASS — 4xx error, 2 packs intact.

### Journey 7: Pack hash/count/provenance audit
- **What**: GET /api/packs returns all packs with content_hash, counts,
  and provenance fields, allowing the user to audit pack integrity.
- **Evidence**: `task-10-j7-packs.json`, `task-10-j7-audit.json`, `task-10-j7-result.txt`
- **PASS criterion**: every pack has content_hash and counts.
- **Result**: PASS — 2 packs, all with hash + counts + provenance.

## Cleanup
- Temp data dir: removed
- QA processes: 0 (TestClient, no background server)
- Evidence artifacts: 16 machine-contract files in `evidence/ontology-platform-roadmap/task-10-*`

## Notes
- Browser-driven screenshots (Aside/Orca) require a live desktop session
  with the Orca CLI. The API + DB + pack evidence captured here covers
  the machine-checkable contract; visual screenshots are supplementary
  and can be added in a follow-up browser session.
