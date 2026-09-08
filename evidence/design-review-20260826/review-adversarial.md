# Adversarial review — DESIGN-REVIEW-2026-08-26
Verdict: APPROVE
## Blockers (each must cite the success criterion G00x it fails and the path:line evidence)
- none
## Notes (non-blocking: overclaims, missed deviations, misassignments, wording)
- Citation checker re-run (`cd /Users/hyunjun/Documents/MUNI/ontologylab && .venv/bin/python -P evidence/design-review-20260826/check_citations.py . docs/DESIGN-REVIEW-2026-08-26.md evidence/design-review-20260826/stage-map.json | tail -2`):
  cited=456 unresolved=0
  CITATIONS_OK unresolved=0
- G001/G002/G003/G004 hold mechanically: 183 modules, LOC sum 56,875 matches `wc -l`/`splitlines`, unreachable set is the 14 modules outside `{main, server.app, mcp_server}` closures, stage-map covers each module once with vocab `{source,acquire,normalize,resolve,extract,synthesize,verify,publish,consume,infra,cross_cutting,orphan}`, report has the seven required headings, 18 deviation rows each have `{HIGH,MED,LOW}` + a `path:line` + a proposal, cited lines exist and are non-blank.
- G002 quality hole (not a blocker: the written bar is ">=2 existing path:line refs", not unique refs): 24 `multi_stage` modules pad the list by repeating the same line (e.g. `ontologylab.alias_authority` evidence `ontologylab/alias_authority.py:49` twice; `ontologylab.method_store` repeats `ontologylab/method_store.py:631` four times; `ontologylab.doi_backfill` repeats `:57`). Those rows do not independently evidence two stages. `secondary_stages[].stage` also uses a parallel vocabulary (`Verify`, `cross-cutting`) outside `stage_vocab`.
- G001 wording trap: `inventory-unreachable-check.txt` prints `importers=0` while `inventory.json` `fan_in` is 1–4 for the cutover/review_decision cluster. Intra-orphan edges exist (`cutover_rollback` imports `cutover_rehearsal`). Zero *reachable-graph* importers is true; zero importers absolutely is not.
- Overclaim — "정준 8단계(2026-08-26 확정)" (`docs/DESIGN-REVIEW-2026-08-26.md:32`): the user froze a simplicity principle, not this 8-stage split. `docs/ARCHITECTURE.md:6` still declares 6 stages. §7 correctly calls the doc a proposal; §2's "확정" contradicts it.
- Overclaim — §0 "HIGH 7건은 모두 같은 일을 하는 경로가 둘 이상": D04 is swallowed exceptions (`ontologylab/ingestion_shadow.py:414`), D05 is a god-object (`ontologylab/kgstore.py:603`), D02 is disagreeing defaults. Those are not dual canonical flows.
- Overclaim — D02 "CLI mock, paths claude, HTTP 금지" and "감사 1번 미해소": `ontologylab extract` already defaults to `paths.DEFAULT_ENGINE` (`ontologylab/main.py:1868`). `:398` is `method extract`, not the main extract command. HTTP `ExtractRequest.engine` is `DEFAULT_ENGINE` with a comment forbidding mock-as-default (`ontologylab/server/schemas.py:80-83`), not "HTTP 금지". Prior audit #1 (`ExtractRequest.engine` mock default) is resolved.
- Overclaim — D07 "G8 게이트는 항상 통과": `:212` plants an empty provisional G8 on preview, but `validate_final_artifacts` can still fail when `selection is not None` (`ontologylab/method_compiler.py:224-232`). Citing `ontologylab/method_compiler_gates.py:497` undercuts the claim: `g8()` has real failure reasons.
- Overclaim — engine-slot row "설정 부재 시 mock으로 fall-through (`ontologylab/server/settings.py:135`)": that line is a comment about a *fixed* launchd PATH bug. Current code sets `available=resolve_available(cli_name)` (`:138`).
- Overclaim — "`serve.py`·`tui.py`는 콘솔 스크립트 진입점" (`docs/DESIGN-REVIEW-2026-08-26.md:48`, `:154`): `pyproject.toml:34` has `ontologylab-serve = ontologylab.serve:main` only. `ontologylab/tui.py` is an unused job-status helper (`fan_in=0`). Real inventory orphans excluding the console-script exception are 13, not 12. D08's "12개" inherits the error.
- Overclaim — D06 "같은 단계 로직을 각자 인라인 구현" for all five pairs: critic and merge-scan are already thin wrappers over `critic_review` / `scan_merge_candidates` (`ontologylab/main.py:1048-1056` vs `ontologylab/server/routes.py:1296-1304`; `ontologylab/main.py:1195-1201` vs `ontologylab/server/routes.py:1378-1383`). Collect and extract *are* inlined duplicates; pack build shares `build_pack()` with duplicated orchestration.
- Overclaim — D14 citations: three ledgers exist (`v2_migration_ledger` `ontologylab/authority.py:160`, `h1_migration_ledger` `ontologylab/h1_schema.py:11`, `cutover_state` `ontologylab/cutover_rehearsal.py:189`), but D14 cites `cutover_rehearsal.py:20` (enum `SHADOW_WRITE`) and `authority.py:24` (`CREATE TABLE works`), and never cites the H1 ledger. Publish reads only the v2 ledger (`ontologylab/pack_readiness.py:196-218`).
- Severity stretch: D02 as HIGH does not match the report's own HIGH rule ("정준 흐름이 둘 이상이거나 단계 경계가 없음"). Disagreeing defaults are MED.
- Missed overlapping flow — research job is a third Acquire surface that then extracts in the same function: `ontologylab/server/jobs.py:801` (`job.set_phase("collect")`) through `:861` (`query_engine = None` fail-open) then extract. D03 lists `/collect`, `/ingest`, CLI `collect` only — not CLI `ingest` (`ontologylab/main.py:447`, `:1850`) and not research.
- Missed duplicated routing — chat `_run_intent` calls sibling route handlers (`ontologylab/server/routes.py:2390` comment, `:2411` `def _run_intent`, `:2415+` `start_research` / enrich / `packs_build`). Prior audit #8; absent from the deviation table.
- Missed hidden fallback — translation `engine=="auto"` failovers claude→codex→gemini (`ontologylab/server/routes.py:207-213`). D12's 94-count bucket would absorb it, but the listed examples omit this chain.
- Missed mega-modules the report's "세 개" list ignores: `ontologylab/connectors/paper_api.py` 2155 LOC (4th largest, just under `main.py` 2309), `ontologylab/mcp_server.py` 1411, `ontologylab/proposals.py` 1229, `ontologylab/server/jobs.py` 1153. `paper_api.py` is the serious omission under the simplicity principle.
- Missed mega-module / dual dialect already half-covered by D07: `ontologylab/method_ir.py` (437, live typed IR, fan_in=13) vs `ontologylab/method_ir_codec.py` (1002, import-only). D07 cites codec `:863` but not `method_ir.py`.
- Stage misassignment — `ontologylab.doi_backfill` primary `normalize`: only importer is `ontologylab.migration_backfill` (`doi_backfill.py:57` / `migration_backfill.py:30`). Should be `cross_cutting`.
- Stage misassignment — `ontologylab.competency` primary `verify`: Q1/Q2/Q3 whole-pipeline harness (`competency.py:132` extract, `:41` pack). `cross_cutting` (or consume test gate) fits better.
- Stage misassignment (secondary) — `ontologylab.alias_authority` `extract` and `ontologylab.literature` `synthesize` rest on a duplicated single line (`alias_authority.py:49` `authorized_surfaces`; `literature.py:146` `formulate_scholarly_queries`). Primary `resolve` / `acquire` are fine.
- `ontologylab.tui` as `orphan` is correct given the inventory rule; the report's prose that it is a console-script entrypoint is what is wrong.
- 결정 목록: all eight are real forks (location, timing, default, delete/archive, v1 retirement, auto policy, split order, service layer), not rhetorical questions. Item 8 "도입 / 현행" is the thinnest but still a binary.
- 목표 구조 vs 정준 파이프라인: eight transforming stages match §2, with Consume pulled out as `consume/` adapters and store/engines/migrations as non-stage packages. Consistent. Tension is only the §2 table counting Consume as a pipeline stage (14 modules) while §5 says consume adapters have no pipeline logic — that is a placement choice, not a contradiction.
- §7 cites `no-code-change-final.txt`, which is not in `evidence/design-review-20260826/` (only `no-code-change-G001.txt` exists). Filename-only, so not a G004 miss.
## Verified samples (claim -> path:line -> supports? yes/no)
- D01 engine resolved at CLI extract, not at the Extract stage -> `ontologylab/main.py:644` (`engine = get_engine(`) -> yes
- D01 same at HTTP job extract -> `ontologylab/server/jobs.py:731` -> yes
- D01 same at HTTP route -> `ontologylab/server/routes.py:2345` -> yes
- D01 same at MCP -> `ontologylab/mcp_server.py:821` -> yes
- D02 CLI default engine is mock -> `ontologylab/main.py:398` (`method extract` `--engine` default `"mock"`) -> yes for that subparser; no as "the CLI extract default" (`ontologylab/main.py:1868` uses `DEFAULT_ENGINE`)
- D02 paths default is claude -> `ontologylab/paths.py:20` (`DEFAULT_ENGINE: str = "claude"`) -> yes
- D02 HTTP forbids engines / mock -> `ontologylab/server/schemas.py:80` (comment: never default mock; field defaults to `DEFAULT_ENGINE`) -> no as "HTTP 금지"; yes as "HTTP extract default is not mock"
- D03 legacy collect persist is hardcoded shadow import -> `ontologylab/ingestion.py:110` -> yes
- D03 second Acquire HTTP surface `POST /ingest` -> `ontologylab/server/ingest_routes.py:24` -> yes
- D03 `FULL_V2_AUTHORITY` is a flag not a slot -> `ontologylab/ingestion_shadow.py:33` (`FULL_V2_AUTHORITY = False`) -> yes
- D04 shadow persist swallows item failures with no receipt -> `ontologylab/ingestion_shadow.py:414` (`except Exception:` / `continue`) -> yes
- D05 KGStore owns many stages (class + approve + verified_subgraph + name_search) -> `ontologylab/kgstore.py:603`, `:2937`, `:4751`, `:4926` -> yes
- D06 CLI/HTTP collect inlined in parallel -> `ontologylab/main.py:483` vs `ontologylab/server/routes.py:1894` -> yes
- D06 CLI/HTTP critic inlined in parallel -> `ontologylab/main.py:1048` vs `ontologylab/server/routes.py:1296` -> no (both call `critic_review`; adapters only)
- D07 preview G8 always empty-pass -> `ontologylab/method_compiler.py:212` (`provisional_g8 = gate_result(GateId.G8, ())`) -> yes for preview; no for "G8 always passes"
- D07 duplicate `MethodPackSql` types -> `ontologylab/method_pack_sql.py:16` and `ontologylab/method_mcp_sql.py:15` -> yes
- D08 cutover family is unreachable -> `ontologylab/cutover_rehearsal.py:20` (`SHADOW_WRITE = "shadow_write"`) -> no (line does not speak to reachability)
- D09 live Verify imports H1 migration -> `ontologylab/grounded_review_members.py:11` (`from ontologylab.h1_existing import`) -> yes
- D10 Publish forks v1/v2 on `evidence_mode` -> `ontologylab/packbuilder.py:365` -> yes
- D10 regular CLI/HTTP build-pack never pass `evidence_mode`; v2 comes from pack_readiness `main` -> `ontologylab/main.py:1287`/`ontologylab/server/routes.py:2715` vs `ontologylab/pack_readiness.py:176` -> yes
- D11 `registry_lookup` outbound HTTP skips `check_url` -> `ontologylab/connectors/registry_lookup.py:66` (`urllib.request.urlopen`) vs `ontologylab/connectors/allowlist.py:112` (`def check_url`) -> yes
- D12 engine-absent query fail-open to raw topic -> `ontologylab/literature.py:154` and `ontologylab/searchquery.py:184` -> yes
- D12 `auto` embedder/reranker and MCP `"auto"` wiring -> `ontologylab/embeddings.py:233`, `ontologylab/rerankers.py:103`, `ontologylab/mcp_server.py:715` -> yes
- D12 settings fall through to mock -> `ontologylab/server/settings.py:135` -> no (historical comment, not current fall-through)
- D13 Extract persist writes Verify citations -> `ontologylab/extractor.py:898` (`persist_chunk_citations`) -> yes
- D13 `extract_research_documents` folds Acquire+Normalize+Extract -> `ontologylab/research_extract.py:133` (calls `attach_explicit_completeness_variants` / `put_selection_receipt` / `run_extraction`) -> yes
- D14 third ledger is `cutover_state` at cited line -> `ontologylab/cutover_rehearsal.py:20` -> no (table is `:189`)
- D16 critic is advisory-only -> `ontologylab/critic.py:11` -> yes
- D17 unverified manifest load remains -> `ontologylab/mcpb.py:55` and `ontologylab/packbuilder.py:904` (`json.loads` of `manifest.json`) -> yes
- §0 declared pipeline is six stages -> `docs/ARCHITECTURE.md:6` -> yes
- §3 Engine Protocol + five implementations + `get_engine` -> `ontologylab/models.py:285`, `ontologylab/engines.py:483`/`:534`/`:566`/`:594`/`:706`/`:890` -> yes
- §3 "get_engine 호출 14곳" list -> 14 call sites, all listed lines exist -> yes
