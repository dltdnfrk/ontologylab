# Ultrawork Notepad — OntologyLab 설계 전면 재검토 (ulw-loop)
Started: 2026-08-26T14:13Z
Loop: .omo/ulw-loop/01a03618-7958-7207-8a8a-0cf045e0edc3 (G001-G004)
Tier: HEAVY, shape research — cross-domain review, user demanded full re-review.
Skills used: ulw-loop (workflow), ast-grep (structural scan if needed), git-master not needed (no commits allowed).
Delegation: G001 self (mechanical data unit); G002/G003 fan out read-only explorers per module family (disjoint, no writes); G003 synthesis self; final gate reviewers via task.

## Plan
1. G001: evidence/.../inventory.py (AST import graph) -> inventory.json; C001 completeness, C002 unreachable grep confirm, C003 no-code-change.
2. Fan-out explorers: families = ingestion(v1/v2/shadow/surfaces/file_lifecycle/authority/h1), extraction+review(extractor/critic/proposals/grounded_review_*/citation_*/review_decision_*/selection_*/extraction_receipt_*), pack+mcp(pack_*/packbuilder/mcp_*/verified_pack_reader), method(method_*), migration+cutover(migration*/cutover*/doi_backfill/work_*), server+web+engines(server/*, engines, providers, serve, tui, web/app.js).
3. G002: stage-map.json from inventory + explorer facts; checks.
4. G003: write docs/DESIGN-REVIEW-2026-08-26.md.
5. G004: citation validator -> citation-check.txt.
6. Final gate: code reviewer + QA executor + gate reviewer; checkpoint.

## Now
G001 inventory generation

## Findings
- 183 modules, 56,875 LOC ontologylab/*.py; kgstore 5587, routes 2875, main 2309 LOC.
- ARCHITECTURE.md declares 6-stage pipeline; METHODOLOGY-COMPILER adds second pipeline; wave 2.1 adds Work/Representation/Observation; h1_* migration family (20 files); cutover_* family.
- 512 intra-package import lines; main.py has 38 lazy in-function imports, kgstore 24.
