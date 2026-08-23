# Task 7 final goal review — rebound to committed HEAD

Date: 2026-08-24
Reviewer: omo senpi-task `st_01a030c7`
Lane: independent product/canonical goal audit on committed HEAD.
Mode: read-only except this file. No product/test/plan/canonical edits.
No commit. No push. No full-suite rerun. No network. No live Application
Support open. Port 8799 / PID 55560 observed only. Denylist unread /
unopened / unhashed / unimported.

Authority (section 0 wins on conflict):
- `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md` §§6-8
- `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md` §0 and Step 7
- Plan Todo 7 in `.omo/plans/wave21-ingestion-steps5-10.md`
- Step 7 kickoff: `.omo/ulw-loop/wave21-step6-ingestion-service-20260821/step7-kickoff.md`

Prior receipts are claims. `task-7-review-goal.md` is **not** evidence:
it binds parent `5a63789`, suite **2630 / 1 / 2**, and the 17-path
product perimeter. That parent does not contain `grounded_review_current`,
member-cite joining, citation `AMBIGUOUS`, pointer-first H1 review link,
or pack-ineligible reject/quarantine/compensate. This file re-reads
current committed sources/tests and recomputes identities.

## Verdict

**PASSED**

**Confidence:** 0.92

Committed HEAD `362b0a679483139e51d8e37748674a867d6a9b2f` satisfies the
Step 7 product goals this lane was asked to audit: C-024/F9 exact
receipt binding and ambiguity quarantine; C-032 append-only /
idempotent ReviewDecision with a current pointer and active-member
cites; tampered / non-approval / waiver pack denial; H1
existing / materialize / finalize safety; RED-before-change plus
mutation coverage bound to the freeze that is now HEAD; typing /
compatibility / protection. The SSE hang-fix is test-only supporting
suite infrastructure. Task 7 has no performance budget.

This is **not** Step 7 loop close. It does not claim rebound QA,
context review, evidence index, or Step 8 kickoff. Pack **publish**
exclusion of waived facts remains Step 8.

## Binding identity (independently recomputed)

| Fact | Required / claimed | Observed now |
|---|---|---|
| HEAD | `362b0a679483139e51d8e37748674a867d6a9b2f` | match |
| Tree | `dce1386961684e924108ded625e56dab4031384d` | match |
| Subject | `fix(extraction): preserve exact receipt identity` | match |
| Parent | `5a6378964bfc41fe2a679453a88235c548a59f4b` | match |
| Hang-fix subject | `test(server): synchronize jobs stream change` | match |
| Product commit | `4878c2f262e6909deb94ff61ef6d04a7e990edd7` | ancestor; `feat(extraction): complete representation-grounded review flow`; parent `8f0e45f` (Task 6); tree `4289084a…` |
| 21-path repair set | exact `git diff-tree` of HEAD | 21 paths; listed below |
| 21-path content SHA-256 | code-final / security-final / commit table | **21/21 MATCH** `HEAD:` and working tree |
| 21-path perimeter | `LC_ALL=C` sorted `path<TAB>content-sha256\n` | `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` (2050 bytes). Do **not** copy `1eac91b2…`. |
| Full-suite perimeter | SHA-256 of `LC_ALL=C`-sorted `git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml` | `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867` (387 paths) |
| Full-suite receipt | `2650 passed, 1 skipped, 2 xfailed` exit 0 | `task-7-final-full-suite.md`; not re-run here |
| Tracked `ontologylab` / `tests` vs HEAD | clean | `git diff --quiet HEAD -- ontologylab tests` exit 0 |
| Staged index | empty | `git diff --cached --quiet` exit 0 |
| `origin/main` | unpushed | still `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`; `origin/main...HEAD` is `0 51` |
| Hang-fix blob | `tests/test_server.py` SHA-256 `8a420db2bb95e77817afb369061dee0ba772b134e4520ea54c210393689eb3cb` | match at HEAD |
| `FULL_V2_AUTHORITY` | false | `ontologylab/ingestion_shadow.py:33` is `False` |

21-path `git diff-tree --name-status -r 362b0a6`:

```
M  ontologylab/citation.py
M  ontologylab/citation_bind.py
M  ontologylab/citation_store.py
M  ontologylab/citation_types.py
M  ontologylab/grounded_review.py
A  ontologylab/grounded_review_members.py
M  ontologylab/grounded_review_schema.py
M  ontologylab/grounded_review_store.py
M  ontologylab/h1_classify_cite.py
M  ontologylab/h1_existing.py
M  ontologylab/h1_existing_review.py
M  ontologylab/h1_finalize.py
M  ontologylab/h1_materialize.py
M  ontologylab/h1_materialize_review.py
A  tests/step7_sec2_support.py
M  tests/step7_valid_stale.py
A  tests/test_step7_citation_bind.py
A  tests/test_step7_review_repair.py
A  tests/test_step7_security_members.py
A  tests/test_step7_security_repair_2.py
A  tests/test_step7_tampered_non_approval.py
```

`5a63789` vs `4878c2f` is only `tests/test_server.py`.

## Per-requirement matrix

Independent reads of HEAD sources/tests. Suite / mutant / typing numbers
are bound to named receipts whose freeze hashes MATCH current `HEAD:`
blobs. Not re-executed here.

| ID | Criterion | Result | Evidence on `362b0a6` |
|---|---|---|---|
| C-024 | Publisher `publishedVersion` abstract + unknown-stage PMC; live research consumer selects ready PMC full text and extracts **selected only** | **HOLD** | `plant_c024` is DOI `10.1000/c024.fixture` with publisher/published/abstract beside pmc/unknown/fulltext. `extract_research_documents` (`research_extract.py:133-162`, SHA-256 `d2da049d…`) calls `put_selection_receipt(..., PolicyVersion.V1)` then `run_extraction(..., selected)`. `jobs.py:957` awaits that function. `test_c024_chain_receipts_agree_on_representation` asserts one V1 receipt on PMC, run hash = `PMC_BODY`, citations/decision bind that Representation/run/selection, publisher token absent. `test_c024_research_extracts_only_pmc_and_binds_task2_run` and `test_research_http_selects_pmc_from_publisher_and_pmc_fake` (TestClient) pin the consumer. Staged-only PMC is `NO_ELIGIBLE_READY_FULL_TEXT` with 0 nodes / 0 runs / 0 cites. |
| F9 | Tuple `ready > usable full text > grade > source > stage > length > lexical hash`; stage cannot beat full text; v2 does not retarget old receipts | **HOLD** | `selection_policy.py` (SHA-256 `0c4c7ccf…`) `policy_parts` / `sort_key` V1 are that exact order. `select_winner` V1 returns `None` unless `usable_full_text_rank == 0`. V2 ranks stage before full text and may pick the publisher abstract. `test_policy_v2_does_not_recompute_historical_v1_receipt` keeps the stored V1 row on PMC. Research hard-codes V1. `work_snapshot` / `preferred_representation` remain stage-first (D07 split; baseline tests pin this). |
| Exact bind + ambiguity quarantine | Multi-run / multi-selection persist refuses; explicit Task 2 ids bind the live run; H1 unique-or-none | **HOLD** | `CitationRefusalCode.AMBIGUOUS` in `citation_types.py`. `_resolve_chunk` / `_resolve_selection` refuse when `len(rows) > 1` (`citation_bind.py:109-116`, `131-148`). `test_persist_without_context_refuses_when_two_runs_cover_chunk` accepts `ambiguous` or `cross_bind`. `test_persist_with_explicit_run_binds_current_not_stale` binds the live run. `selection_run_receipt` returns the id only when exactly one identity-matching row exists (`h1_existing.py:56-71`); `test_selection_run_receipt_refuses_same_policy_two_configs` asserts `None` and the extra run is not the sole linked family. |
| C-032 | Spanless / invalid-member cascade writes zero; scoped waiver durable + pack-ineligible; generic approval is not a waiver | **HOLD** | `test_cascade_one_invalid_member_writes_zero`, `test_generic_waiver_refused_scoped_waiver_pack_ineligible`, `test_generic_approve_cannot_waive_invalid_member`. `_waive` refuses empty members/defects (`GENERIC_WAIVER`) and set mismatch (`UNSCOPED_WAIVER`); hard-codes `pack_ineligible=True`. Ordinary approve still `require_grounding`. Pack **publish** exclusion remains Step 8. |
| Current pointer + idempotency | Additive mutable tip; decisions append-only; same-id no-op; pointer written in the review SAVEPOINT | **HOLD** | `grounded_review_schema.py` creates `grounded_review_current (fact_kind, fact_id PK, receipt_id)` beside append-only `grounded_review_decisions` with UPDATE/DELETE abort triggers. `persist_decision` same-payload returns; different payload is `CONFLICT`. `set_current_decision` INSERT / same-id no-op / UPDATE tip only. `_write_batch` does persist → `set_current_decision` → derived status inside `grounded_review_v1`. `_current_predecessor` prefers the pointer over `ORDER BY` latest. `test_current_pointer_rolls_back_with_review_savepoint` asserts 0 decisions and NULL tip after caller `ROLLBACK`. |
| Active-member cites | Waiver / non-approval digest = current `citations` membership + revision + run/selection/policy; stale extras stay out | **HOLD** | `stored_member_citations` (`grounded_review_members.py`) joins stored receipts to current `citations` spans, `fact_revision_id`, and `_current_identity` (current run + selection + policy). `_waive` and non-approve `_apply` use that helper; approve still `require_grounding`. `test_waiver_binds_active_member_citations_when_stale_extra_exists` and `test_tampered_reject_digest_excludes_stale_citation_rows` assert live ids only. `test_compensate_predecessor_is_pointer_when_stale_row_sorts_later` binds predecessor to the pointer, not a later-sorting stale approve. |
| Tamper / non-approval / waiver pack denial | Tampered approve is typed zero-write; reject/quarantine/compensate/waiver are pack-ineligible; HTTP 409 | **HOLD** | `members_have_citations` treats `CITATION_UNGROUNDED` as present so `KGStore.approve` cannot fall through to legacy `_set_status` (`grounded_review_preflight.py:93-104`, SHA-256 `793e1332…`). Tamper → `GroundingPreflightError` / status `proposed` / 0 decisions (`test_tampered_approve_still_writes_zero`, `test_tampered_ready_bytes_block_review_with_zero_decisions`). Reject / quarantine append `pack_ineligible=True`. CLI reject prints the stored `sha256:` id. TestClient approve is 409 after tamper. Security-final independently probed library + real uvicorn `:18447` on these same 21 blobs: approve 409, reject/compensate 200, both pack 1, live cite set only. |
| H1 existing | Pointer-first exact match; else historical exact-unique; no first-tip / `ORDER BY` winner | **HOLD** | `existing_review` (`h1_existing_review.py:27-59`) prefers `current_decision_id` only when the payload is aligned (actor/reason/times/v1-or-v2 id) and `_review_matches` the current Task 4 cite set + grounding + waiver pack/defects. Else `len(found) == 1` or `None`. Waiver match requires `pack_ineligible` and nonempty `scoped_defects`. Ordinary match refuses pack-ineligible / waived / predecessor. Tests: `test_h1_links_current_waiver_not_colliding_stale_twins`, `test_h1_same_cite_different_scope_does_not_mint_eligible`, `test_h1_links_historical_unique_waiver_when_pointer_missing`. |
| H1 materialize / finalize | History-exists mint guard; missing review quarantines; chunk/cite bind the current run | **HOLD** | `materialize_review` returns existing, else `None` when any decision already exists (`h1_materialize_review.py:31-38`). `bind_family` on `H1ReviewAnchor` quarantines `UNGROUNDED` when materialize returns `None` (`h1_finalize.py:60-67`). `test_h1_quarantines_when_current_tips_are_indistinguishable` asserts no family id, `quarantined`, zero eligible pack-0 approve. `lookup_chunk_receipt` / `_citation_binding` require `current_run_receipt_id` then unique span on that run. `test_h1_chunk_family_links_live_not_smaller_stale`, `test_h1_citation_mint_uses_current_run_not_covering_stale`. |
| H1 rehearsal safety | Backup-API copy only; overlap / not-sqlite refuse; pass2 no-op; no production catch-up | **HOLD** | `prepare_h1_copy` → `prepare_backup_copy`. `run_h1_operator` header-checks SQLite, `_refuse_overlap` before copy, migrates destination only. Tests: `test_h1_on_reviewed_chain_links_family_receipts_and_is_idempotent`, `test_h1_rerun_is_idempotent_and_byte_identical`, `test_h1_operator_does_not_mutate_source`, `test_h1_interrupt_resume_does_not_duplicate`, `test_h1_out_of_range_span_is_quarantined_not_repaired`, `test_h1_malformed_source_is_typed_refusal` (`not_sqlite`), `test_cli_source_overlap_refuses_without_partial`. No 9C / Application Support path. |
| SSE teardown | Deterministic test seam only; product jobs unchanged | **HOLD (supporting)** | Diff `4878c2f..5a63789` is only `tests/test_server.py`. Replaces `threading.Timer(0.15, registry.touch)` with an Event handshake on the **second** `wait_version`, bounded `wait(2.0)` / `join(1.0)`. File SHA-256 `8a420db2…` unchanged at HEAD. Product `JobRegistry.touch` / `wait_version` / `jobs.py` research consumer were not in that commit. Final suite `2650 / 1 / 2` on this HEAD supersedes the hung `4878c2f` attempts and the 2630 parent run. |
| RED before change | Named handoff gaps failed for the named reason before the surviving production edit | **HOLD (historical, documented)** | Executor: tamper escaped as interior `GroundedReviewRefused` + `TypeError`; H1 minted a parallel `legacy-h1-v1` family. Repair-2: valid stale still linked. Security-repair-2 baseline: `2 failed, 25 passed` because H1 minted an eligible pack-0 approve instead of the live waiver. Survivors are the HEAD tests named above. |
| Mutation | Named implementation mutants die then restore | **HOLD (bound to freeze = HEAD)** | Code-final: 8 isolated mutants + prior five MAJOR re-kills, 21/21 SHA-256 restored. Security-final: 8 mutants (first-tip, skip pointer, drop mint guard, `_waive` via `citations_for`, return all stored, `ineligible=False`, `_should_require` always False, `conn.commit()` after pointer). Repair-2-verifier and executor tables remain claims for earlier seams; the killing tests are on HEAD. Not re-mutated here. Blueprint-named mutants remain as Task 2–6 tests (`test_chunk_receipt_binds_end_profile_text_hash_and_plan`, `test_cascade_one_invalid_member_writes_zero`, `test_generic_approve_cannot_waive_invalid_member`, `test_policy_v2_does_not_recompute_historical_v1_receipt`, `test_h1_out_of_range_span_is_quarantined_not_repaired`). |
| Typing | basedpyright 0/0/0 on changed Python | **HOLD (bound)** | Code-final: 21 changed files 0/0/0 on this freeze. Bytes unchanged since that run. No post-commit re-run. |
| Performance | Task 7 p95 / payload gate | **N/A** | Blueprint / plan give Step 7 no performance budget. Step 10 owns baseline comparison. No Task 7 perf claim is allowed. |
| Compatibility | Additive schema; legacy citation-less approve remains Task 5 baseline; no pack v2 / F11 / authority flip | **HOLD** | `CREATE TABLE IF NOT EXISTS` only. `FULL_V2_AUTHORITY = False`. `8f0e45f..HEAD` path names are extraction/citation/review/H1 + SSE test hang-fix + identity-preservation repair. Citation-less legacy `approve()` remains the Task 5 baseline (`test_baseline_approval_without_citation_receipt_succeeds`). |
| Protection | No live data, 8799 mutation, network, denylist, canonical writes | **HOLD** | Denylist sizes only (6279 / 1652 / 2229 / 6434 / 1928 / 5697); `git ls-files --error-unmatch` miss for all six. `rg` on committed `ontologylab`/`tests` has no `review_decision*` / `review_grounding` imports (SQL table `grounded_review_decisions` only). Observe-only: PID `55560` still `127.0.0.1:8799` DEVICE `0x1ff51c806b197195`. No leftover Task 7 listen ports (`18447` / `54489` / `57699` / `64678` / `50464`). This lane did not create or remove `/private/tmp/ontologylab-wave21-*` roots belonging to other workers. Canonical analysis/blueprint not edited. |
| Full suite | Exact `.venv/bin/python -m pytest` on committed perimeter | **HOLD (bound)** | `task-7-final-full-suite.md`: 2650 passed, 1 skipped, 2 xfailed, 1 Starlette/httpx warning, 1274.66s, exit 0, HEAD and perimeter unchanged. Supersedes `task-7-full-suite.md` (2630 on `5a63789` / `07716de5…`). |
| Surfaces | Direct / CLI / HTTP / research / review agree on machine ids | **HOLD (code + bound freeze probes)** | Committed: library + TestClient approve/research + CLI reject. Security-final real uvicorn `:18447` on the freeze that is now HEAD: approve 409, reject/compensate 200, pack 1, live cite set. Plan QA matrix (CLI `approve` + `migrate-h1`, SSE subscribed before POST) last measured on **parent** `5a63789` or earlier dirty trees; that is a gate/QA rebound item, not a missing product contract. New Step 7 tests contain no `time.sleep` / `threading.Timer`. |

## Independent code facts (this lane)

F9 V1 winner still refuses non-full-text:

```python
# ontologylab/selection_policy.py select_winner / PolicyVersion.V1
if winner.usable_full_text_rank != 0:
    return None
```

Research consumer still extracts `selected` only, not `collected_ids`.

H1 review link prefers `grounded_review_current` when the payload is
aligned and `_review_matches`; otherwise requires `len(found) == 1`.

`materialize_review` will not mint when history exists and lookup missed.

`members_have_citations` is still an any-member probe that treats
`CITATION_UNGROUNDED` as present so `KGStore.approve` cannot fall
through to legacy `_set_status` on the tamper path.

21-path content SHA-256 at HEAD (all MATCH the code/security-final table):

```
ontologylab/citation.py	6050d74cb87cffca1143056ae5341ab455eab7bd33bdf9cad2674ce717d4ed80
ontologylab/citation_bind.py	b045f72bfb8623c75668b81a2f936c6f0629bb1cd3753ec3bf5092782fcc9e8c
ontologylab/citation_store.py	da42b2da42205cb57c92ba87fb675cec007f97244cb081bec675b81d250e3ce4
ontologylab/citation_types.py	1b3209c242ef87e38cd0e8046ad11ac2060c3ad0b4391af9c434990bae60ae78
ontologylab/grounded_review.py	745004019c0dcbdf84a6cf86875f2d9338e1410b124cd048d1d74bbacf2e5ca0
ontologylab/grounded_review_members.py	187df60da17791aceda2a96b73e005aa08253e0cff9856bd0505ab74bd89566a
ontologylab/grounded_review_schema.py	9fc80b3b50e8391fd1dd4e9425ebf900710f5a9e91a59021c1076266902f30c5
ontologylab/grounded_review_store.py	bccd4f7d629b65af32dd36ebf748f0a313fd26f5ecdde441ce5cacc45053cd0d
ontologylab/h1_classify_cite.py	1ad78d2c47a5939f5db94c14dfba7cbf95e6c3005bf27734e2345da76f76d1c6
ontologylab/h1_existing.py	1c5f63d5aa71f3aff935a976352710a5cfe08d904ec50b6a990c513c2cea2e98
ontologylab/h1_existing_review.py	bd36a80dc55871c389fb1da8210c54a314c36acfaa4a0928536aca786820c98a
ontologylab/h1_finalize.py	b7f803229239d9e5df8674779b82d1f950b71e723146005cdf86244f85aca2ad
ontologylab/h1_materialize.py	f477b557f0896ec3f4ee3b15d2095dd9d8635b8446e78711e07a5c00491e73d0
ontologylab/h1_materialize_review.py	d23dec0f34a08b9e4a6f9c1c365b0e7428e3a002303a1b82d5b35656f2379cee
tests/step7_sec2_support.py	5463a6729acf94b051bfb724d043ce745db6fd1927c8dbd9244ef1f32f2a12de
tests/step7_valid_stale.py	10e71ed154ae6dee93263f244f7049dc8ae072cdece11e01482eaa8ffdc01d34
tests/test_step7_citation_bind.py	38f21a3ecd46f437993d735be80ef759d25945e91746bac65bc49295ddb8ffc2
tests/test_step7_review_repair.py	892fa15e8f810a78b795e09df19b206e4a74c58ffde47b6ac6f6b85f40f1a886
tests/test_step7_security_members.py	c8f7e4cc499bc36c6afeeaf1cc284332b8f09eb1e174c6171bf892650a89078c
tests/test_step7_security_repair_2.py	d64ee3a90c17f8ba22e48868113262d0b34082fa337798601c4288cd0df813af
tests/test_step7_tampered_non_approval.py	40cf516b905082769a3d9d40f154c7ece1ce172ccb85cb7270c7e596dc30a3dd
```

Unchanged-from-`4878c2f` and still at HEAD (rehashed this lane):
`grounded_review_ids.py` `42426bcf…`, `grounded_review_preflight.py`
`793e1332…`, `kgstore.py` `a64e55ee…`, `research_extract.py`
`d2da049d…`, `selection_policy.py` `0c4c7ccf…`,
`tests/step7_integration_support.py` `cb5acfd3…`,
`tests/test_grounded_review_identity.py` `75058dca…`,
`tests/test_step7_h1_existing.py` `c742bdbf…`,
`tests/test_step7_integration.py` `44f2c96c…`,
`tests/test_step7_integration_h1.py` `fb40ceb3…`.

## Residuals (not goal blockers)

- `grounded_review_current.receipt_id` has no SQL `REFERENCES`. Public
  writers persist the decision first in the same SAVEPOINT; deletes abort.
- `_citation_binding` / `containing_chunk` still covering-scan **on the
  current run**.
- `selection_policy` / `selection_receipt_id` still latest-by-`created_ts`
  helpers. Live citation persist and H1 `selection_run_receipt` are
  unique-or-`AMBIGUOUS` / unique-or-`None`.
- Review SAVEPOINT still only catches `GroundedReviewRefused` and
  `sqlite3.Error`.
- Waiver `_review_matches` accepts any nonempty `scoped_defects` once
  cites/grounding/time match. Same-cite scope discrimination is the
  pointer (or unique historical fallback). Ambiguity without a pointer
  quarantines rather than minting.
- Citation-less legacy `approve()` remains the Task 5 baseline.

## What this review is not

- Not a rebound QA review. Plan disposable ingest → select → extract →
  cite → review/waive → H1, installed CLI `approve` + `migrate-h1`, and
  SSE-before-POST on **this** HEAD are still a separate lane.
- Not a context review. `task-7-review-context.md` is still absent.
- Not Step 7 loop close, evidence index, Step 8 kickoff, or plan
  checkbox flip (`- [ ] 7.` remains).
- Not permission to treat `task-7-review-goal.md` as HEAD-bound.
- Not a claim that waived facts are already excluded from publication.
- Not pack v2 / F11 / `FULL_V2_AUTHORITY` / 9C / Wave 2.1 complete.

## Prohibited captions (still forbidden)

- Wave 2.1 / R10 complete
- Lossless ingestion
- Full semantic dual-write / `FULL_V2_AUTHORITY`
- Pack v2 / F11 / evidence-self-contained publish
- Step 9C / production cutover
- “All independent reviews confirmed on committed HEAD”
- Citing `1eac91b2…` as the 21-path perimeter
- Citing suite 2630 as the final committed-state receipt

## Protected-boundary / cleanup

- Did not read or write `~/Library/Application Support/ontologylab/`.
- Did not use external network.
- Did not bind, kill, or retarget port 8799 or PID 55560.
- Observe-only `lsof`: PID `55560` `127.0.0.1:8799` DEVICE
  `0x1ff51c806b197195`.
- Did not open, hash, import, or stage the six denylist files.
- Did not run pytest or basedpyright.
- Did not edit planning documents or product/test bytes.
- This file is the only write.

## Stop

Strict verdict: **PASSED**.

Product goals C-024 / F9 / C-032 / H1 rehearsal, exact-bind / ambiguity
quarantine, current-pointer + member-cite integrity, tamper /
non-approval / waiver pack denial, and H1 existing/materialize/finalize
safety hold on commit `362b0a679483139e51d8e37748674a867d6a9b2f` / tree
`dce1386961684e924108ded625e56dab4031384d` / suite **2650 + 1 + 2** /
full-suite perimeter `9d3f5790…` / 21-path perimeter
`1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b`.
A later gate may still require rebound QA and a context review before
an evidence index or Step 8 kickoff.
