# Task 1 final goal & canonical review

Review type: FINAL GOAL & CONSTRAINT VERIFICATION
Reviewer: omo senpi-task `st_01a02e68`
Date: 2026-08-23
Lane: Step 6 goal / canonical compliance only.
Mode: read-only except this file. No product/test/plan/canonical edits. No commit. No push. No network. No live Application Support. Port 8799 / PID 55560 observed only.

Authority (section 0 wins):
- `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md` §§6-8
- `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md` §0 and Step 6
- Plan Task 1 in `.omo/plans/wave21-ingestion-steps5-10.md`
- Step 6 loop: `.omo/ulw-loop/wave21-step6-ingestion-service-20260821/{brief,goals}.json`

Prior reports treated as claims, not evidence: G005 reviews (superseded), G007/a1 reviews (pre-repair / pre-commit `eab47a6`, freeze `f3aead6a…`), start-work executor/verifier/product-commit/full-suite receipts.

## Binding identity (independently recomputed)

| Fact | Required | Observed |
|---|---|---|
| HEAD | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` |
| Tree | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` |
| `git log -1` | conventional Step 6 commit | `e3bca45 feat(ingestion): complete transactional v2 shadow service` |
| Parent | Step 5 | `eab47a615cc5f309c05a48875c6e6877096783dd` |
| Perimeter SHA-256 | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` | same (23 committed paths, sorted `path<TAB>file-sha256\n`) |
| Working-tree vs `HEAD:` on those 23 | identical | identical |
| Staged index | no unowned staged paths | empty |
| Full-suite receipt | `2521 passed, 1 skipped, 2 xfailed` | `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-1-full-suite.md` claims that exact terminal line, exit 0, before/after identity unchanged |

This review does not re-run `.venv/bin/python -m pytest`. The suite number is bound to that receipt plus the unchanged perimeter, not re-observed here.

## VERDICT: PASS

**Confidence: 0.86**

Committed Step 6 product meets canonical 6A / 6B-F4 / 6C-F5 / 6D shadow-entrypoint criteria, plus the Task 1 legacy-read repair. Independent focused gate on these bytes is green. Staged/ready receipts are honest. Production collect/research/sample persist through one shadow adapter. The commit adds no Step 7 extraction/review/pack semantics.

This is **not** a claim that the ulw-loop G007 close is finished, that `05-failure-analysis.md` F2 is fully GREEN, that ingestion is lossless, or that full semantic dual-write / full v2 authority is on.

Blockers: none for this product/canonical audit.

## Per-requirement matrix

| ID | Criterion | Result | Evidence |
|---|---|---|---|
| 6A | Caller-owned SAVEPOINT service; typed receipts; no service `commit`/`rollback`; reserve → Work → Observation → assertion; same-key retry; second-DOI conflict | **PASS** | `ingestion_service.py` SAVEPOINT `ingestion_service_v2`; `RELEASE` only; item rollback is `ROLLBACK TO SAVEPOINT`. Focused `tests/test_ingestion_service.py` in the 92. |
| F2 ownership | Step 6 owns concurrent v2 writers: truth table, sentinel, outbox complete | **PASS (G004 + impl)** | 8 barrier tests green. Family writers: 1 Work / 2 Observations / 0 dangling. Sentinel survives. Independent probe: 2 observations ↔ 2 `provenance_outbox` rows. **Not** full `05` F2: threads not processes; metadata-only (`FAMILY_TRUTH` `documents: 0`); harness does not assert outbox; same/different-byte hash cases are pre-fence queued, not two Representations. Caption as G004, not blueprint F2 GREEN. |
| F4 ownership | Absent / finalizable staged / valid ready / typed quarantine; immutable final path | **PASS** | `file_lifecycle.py` classifier + `reconcile_files` (v2 `work_id IS NOT NULL` only). Writable `KGStore.open` runs it. 15 lifecycle tests + 5 document-view tests in the 92. G008 `red-green.txt` / `edge-mutation.txt` / `regression.txt` exist. |
| F5 ownership | Same-tx outbox; exactly one logical event; mark never before durable mirror | **PASS** | `insert_observation_event` inside the item SAVEPOINT; `project_outbox` after caller commit / on open. 14 outbox tests in the 92. G006 receipts exist. |
| 6D entrypoints | CLI collect, `POST /api/collect`, research persist, `/api/collect/sample` through service v2; pre-fence shadow only | **PASS** | All four call `ingest_documents` / `ingest_sample` → `shadow_persist` / `shadow_ingest_sample` → `finalize_shadow_writes`. `cmd_ingest` / `/api/ingest` share `ingestion_surfaces` → `ingest_work_items`. `FULL_V2_AUTHORITY = False`. G009 receipts exist. 16 shadow tests in the 92. `competency.py` still uses `insert_document` for gold CQ fixtures; that is not a named 6D collect entrypoint. |
| Staged/ready honesty | Raw bytes land `staged` and are unreadable until finalize; metadata-only may be `created`/`ready`; readers consume ready only | **PASS** | Service: staged file + `representation_state=staged` + receipt `staged`; no bytes → `READY` + `created`. `test_document_view_reads_ready_bytes_only` asserts `staged`, refuse, then ready after `finalize_representation`. `work_snapshot` prefers ready only. |
| Provenance legacy | Contained legacy synthetic `sha256:`+64 hex readable; v2 still hash-verifies; unsafe paths typed-refuse | **PASS** | Committed `document_raw_text`: `work_id is not None` → `read_ready_text`; NULL `work_id` + non-ready refuse; contained legacy decode **without** `content_hash` oracle; basename denylist + `is_relative_to`. `test_legacy_provenance_reads_when_hash_metadata_is_synthetic` and v2/path tests in the 92. |
| Exact suite | One exact full suite, exit 0, zero failed/error/xpass, perimeter unchanged | **PASS (bound receipt)** | `task-1-full-suite.md`: `.venv/bin/python -m pytest` once → `2521 passed, 1 skipped, 2 xfailed, 1 warning in 1166.19s`; exit 0; before/after HEAD/tree/perimeter identical. Not re-run here. |
| Commit | One conventional Step 6 product/test commit; no unowned staged paths | **PASS** | 23 owned paths only. Residual `??` paths are pre-existing/unrelated (`docs/`, `uv.lock`, graphify, artifacts). Plan subject `fix(ingestion): preserve safe legacy provenance reads` was not used; the landed subject matches the integrated Step 6 tree. |
| Evidence completeness | G006/G008/G009 machine receipts; G007 close artifacts; aggregate | **PASS with closer remainder** | G006/G008/G009 `red-green` / `edge-mutation` / `regression` present and non-empty. Start-work suite + commit receipts present. Official G007 `final-suite.txt`, `step6-evidence-index.md`, `step7-kickoff.md`, `scope-cleanup.txt`, `commit-boundary.txt` are **absent**. `goals.json` G007 is still `in_progress`; `aggregate-active.json` is `active`. G005 remains `blocked`/superseded. Those missing files block calling the **loop** closed; they do not reopen the product criteria above. |
| No Step 7 | No extraction-run/chunk/Citation/ReviewDecision/C-024/pack-v2 semantics in the increment | **PASS** | `git show --name-only e3bca45` is the 23 service/lifecycle/outbox/shadow/surface files only. No `extractor.py` / `extraction_state.py` / review / pack schema change. `preferred-representation-v1` in `work_view.py` is the existing read-time projection, not a Step 7 selection receipt. `FULL_V2_AUTHORITY` stays false. |
| G003 | Stale citation-projection product | **SUPERSEDED** | Not in the commit. Historical G003 receipts remain labeled superseded. |
| G007/a1 reviews | Reuse as current-byte close reviews | **REJECT** | Bound to `eab47a6` / freeze `f3aead6a…`. They still claim legacy `sha256:`+64 hex is an integrity oracle (`legacy raw text hash mismatch`). Committed `kgstore.py` `2226e9bf…` no longer does that. Do not cite those reviews as current truth. |

## Independent reproduction (this lane)

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Interpreter: `.venv/bin/python` (repo venv)

```
.venv/bin/python -m pytest \
  tests/test_ingestion_service.py \
  tests/test_ingestion_surfaces.py \
  tests/test_ingest_concurrency.py \
  tests/test_file_lifecycle.py \
  tests/test_document_view.py \
  tests/test_provenance_outbox.py \
  tests/test_ingestion_shadow_entrypoints.py \
  tests/test_provenance_api.py \
  --override-ini addopts= -q --tb=no
# 92 passed, 1 warning in 1.61s
# EXIT:0
```

The warning is the pre-existing Starlette/httpx TestClient deprecation, not a product file.

F2 outbox probe (disposable `tempfile.mkdtemp(prefix="ol-task1-goal-f2-")`, then deleted):

```
receipts ['created', 'created']
obs 2 outbox 2 obs_without_outbox_payload 0
F2_OUTBOX_COMPLETE True
CLEANED True
```

Perimeter rehash after the run still `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e`.

## Findings (not blockers)

1. **F2 caption residual.** G004 is identifier-family / thread / metadata-only. Different-DOI / same-bytes remains a durable queue / `IdentityConflict` under the live global hash constraint. Do not write “F2 GREEN” against `05-failure-analysis.md`.
2. **`shadow_persist` `except Exception: continue`.** An unexpected item can vanish without a typed receipt. Pre-existing G007 flag. Collect still redacts unexpected exceptions as `internal_error`.
3. **Research still `collapse_duplicates` before persist.** Canonical allows collapse only if every fetched Observation is recorded; this path still de-duplicates first. Not a Step 6 write-seam bypass (`ingest_documents` is still the persist).
4. **G007 close artifacts are not written yet.** Index, kickoff, and loop completion are closer-owned. A later close that cites stale G007/a1 hash-oracle language is an overclaim.
5. **G008 historical regression count is 55; current lifecycle+adjacent set is larger.** Count drift is later characterization tests, not a missing module.

## Prohibited captions (still forbidden)

- Lossless ingestion
- Every entrypoint converged in the Wave 2.1/R10-complete sense
- Full semantic dual-write / full v2 write authority
- Full `05` F2 GREEN
- Step 7+ / pack v2 / production cutover
- Reusing G007/a1 as a current-byte security/legacy-hash review

## Protected-boundary / cleanup

- Did not read or write `~/Library/Application Support/ontologylab/`.
- Did not use external network.
- Did not bind, kill, or retarget port 8799 or PID 55560.
- Observe-only `lsof` before/after focused run: PID `55560` still `127.0.0.1:8799` (`DEVICE 0x1ff51c806b197195`), started `Thu Aug 6 13:51:44 2026`, same argv (`ontologylab.serve --port 8799 --data-dir …/Application Support/ontologylab/data`).
- Probe root `/private/tmp/ol-task1-goal-f2-*` removed. No `/private/tmp/ontologylab-wave21-task1*` residue.
- This file is the only write. No product/test/plan/canonical mutation. `git diff --staged` empty.

## Why not FAIL

Product contracts, F4/F5/6D receipts, staged/ready honesty, the legacy-read repair, suite/commit/perimeter binding, and the no-Step-7 increment all hold on `e3bca45`. Missing G007 index/kickoff is closer work after these reviews, not an unmet 6A–6D criterion. Full `05` F2 is a caption residual already owned as G004.

## Stop condition

This file is the only write. One strict verdict: `PASS`.
