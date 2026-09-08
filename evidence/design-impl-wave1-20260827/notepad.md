# Ultrawork Notepad — OntologyLab 단순화 구현 Wave 1
Started: 2026-08-27 (ulw-loop session design-impl-wave1-20260827)
Tier: HEAVY / delivery. Skills: ulw-loop (workflow), programming (Python rules), git-master NOT used (commits forbidden; draft messages only), debugging if a RED misbehaves.
Delegation: planner (deep) -> per-goal implementation workers (sequential across goals because main.py/routes.py overlap; parallel inside a goal only on disjoint files); QA executor per goal; final gate 3 lanes.

## Plan
1. create-goals (done) -> planner writes .omo/plans/design-impl-wave1.md -> revise criteria from plan -> create_goal.
2. G001 D03+D04 single ingest writer; G002 D02 engine default; G003 D01 resolve_engine; G004 D06 service functions.
3. Per goal: RED test -> worker GREEN -> self QA (CLI stdout / curl -i on 127.0.0.1:18899 tmp data-dir) -> cleanup receipt -> record -> checkpoint -> draft commit message.
4. Final: full suite >= baseline, gate lanes, checkpoint.

## Now
Waiting: planner + baseline suite (bash_402).

## Findings
- ingest_documents (ingestion.py:104) -> shadow_persist (ingestion_shadow.py:391) -> per-item _persist_one:333 = ingest_item + legacy documents mirror (_mirror_create:236/_mirror_duplicate:279); FULL_V2_AUTHORITY=False (:33) only referenced by tests/test_ingestion_shadow_entrypoints.py.
- Callers of legacy path: main.py cmd_collect:483, routes.py collect:1894, jobs.py (ingest_documents_batched), research_extract.py (finalize_shadow_writes + ingest_item). v2 path callers: main.py/ingest_routes.py via run_ingest/collect_sample.
- /collect and cmd_collect have identical call graphs (connector.fetch, ingest_documents, provenance.log) = D06 pair 1.
- D02: main.py:398 (nested `extract` parser — check which), :1999 critic, :2165 search default mock; :1868 p_extract already DEFAULT_ENGINE; competency.py:142 MockEngine(); settings.py:135.
- D06 sizes: _extract_async main 429 lines vs jobs 144; cmd_build_pack 210 vs packs_build 71; cmd_merge_scan 92 vs 11; cmd_critic 35 vs 23.
- Tests touching ingestion family: test_literature_ingestion, test_wave21_identity_characterization, test_ingestion_surfaces, test_evidence_grade, test_ingestion_shadow_entrypoints, test_wave21_surface_harness, wave21/perf.py.

## Findings (planner respawn)
- planner st_01a03ebc (category deep) errored at spawn: "Connect error resource_exhausted", 0 tools -> inconclusive, respawned as planner-wave1-b on unspecified-high.
- main.py:398 = nested `method extract` subcommand (method group), not top-level extract (:1868 already DEFAULT_ENGINE).
- _mirror_create (ingestion_shadow.py:236): SAVEPOINT -> ingest_item -> receipt.representation_id == documents.id -> `UPDATE documents SET doi` -> _register_artifact. The "legacy mirror" is a thin adapter; documents IS the representation table. Decision 1(a) shrinks to: move mapping/doi/artifact/batching into ingestion_service, delete ingestion.py + ingestion_shadow.py.
- routes.py:207-235 translate endpoint: engine "auto" -> candidate loop over claude/codex/gemini swallowing errors (D01 hidden policy).
- settings.engines() :121 hardcodes mock as first always-available EngineInfo; comment :128-137 documents the composer fall-through; need to locate the current composer default in web/app.js.
- documents-table readers: kgstore.py 9, extractor.py 3, research_extract.py 3 (unchanged by decision 1a).

## Now
Waiting: planner-wave1-b + baseline suite bash_402.

## Plan pointer
- .omo/plans/design-impl-wave1.md (planner st_01a03ebd). Criteria revised from SC1..SC4 per goal (C003 = SC3+SC4).

## Now
G001-A worker: T1-T4 (ingestion_service writer + tests)

## Findings (baseline)
- full suite baseline: 2962 passed / 1 skipped / 2 xfailed (26m15s). Floor for all goals.
- QA harness evidence/design-impl-wave1-20260827/qa-server.sh start|token|stop verified on HEAD (401 w/o token; engines lists mock first).

## Findings (G001 integration)
- worker T1-T4: green on its set, ruff/basedpyright/LSP clean, but 2 regressions: ingestion_service.py must never commit (test_file_lifecycle:461, test_provenance_outbox); file grew to 1019 LOC. Amendment A1: raw-document layer moves to ingestion.py (kept), ingestion_shadow.py deleted in T8.
## Now
worker st_01a03ec6 revived with A1 correction

## Findings (G001 QA)
- QA runner scenario fixes: fixture must sit outside --data-dir (store-directory guard REJECTS otherwise); /api/ingest needs source/evidence_grade/stage/content_kind + real content_hash; collect error detail echoes only the basename, never the directory or exception text.
- Amendment A2: sample records provenance (jobs/collect-sample); characterization test renamed.
## Now
G001 C003 waits on full suite bash_429; then checkpoint; G002 starts after (main.py edits must not race the running suite).

## G001 complete
- full suite 2972 passed; C001-C003 pass; checkpointed. Commits drafted 01-04.
## Now
G002: worker A (T1+T3+T4: main.py, settings.py, web/app.js, tests/test_engine_defaults.py) || worker B (T2: competency.py, routes._competency_receipt, test_competency_release_gate.py)

## G002 complete
- SC1-SC4 PASS, green set 88 passed, engines()=[claude,codex,gemini,mock], app.js mock tokens 0. Commits 05-07 drafted.
## Now
G003: single worker (T1 resolve_engine -> T2 14 call sites -> T3 translate auto removal), sequential on routes.py.

## G003 complete
- 16 call sites -> one resolve_engine; translate auto removed (502); Amendment A3: models.Engine protocol given the default its 5 implementations already had (fixed the only new basedpyright error). 239 passed, QA PASS. Commits 08,09 drafted.
## Now
G004: single worker T1(collect.py)->T2(run_extract_job)->T3(build_pack_release)->T4(adapter pins), sequential on main.py/routes.py/jobs.py.

## G004 complete
- collect.py shared acquire; run_extract_job; build_pack_release; adapters thin. 151 passed, QA PASS, 2 mutations KILLED (offline gate, retargeted pin). Commits 10-12 drafted.
## Now
Final gate: full suite >= 2962, then freeze + 3 review lanes.
