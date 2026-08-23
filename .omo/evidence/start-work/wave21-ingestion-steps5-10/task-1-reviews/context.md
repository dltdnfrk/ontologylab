# Task 1 context review — repository / history / authority fidelity

Review type: CONTEXT (Step 6 close / start-work Task 1)
Reviewer: omo senpi-task `st_01a02e6c`
Date: 2026-08-23
Mode: read-only inspection of committed bytes plus one focused pytest
      invocation. No product, test, plan, or canonical-doc edits. No commit,
      push, network, live Application Support read/write, or port 8799 /
      PID 55560 mutation.

Prior receipts (`task-1-executor.md`, `task-1-verifier.md`,
`task-1-product-commit.md`, `task-1-full-suite.md`, G005/G007 context
reviews, G006/G008/G009) are treated as claims. Verdicts below are bound to
current committed bytes.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` |
| Tree | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` |
| Subject | Step 6 product/test increment | `feat(ingestion): complete transactional v2 shadow service` |
| Parent | Step 5 commit | `eab47a615cc5f309c05a48875c6e6877096783dd` `feat(migration): resumable migration core, backfill/collision executor, F6 rehearsal` |
| Perimeter SHA-256 | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` | recomputed independently over the 23 committed paths; match |
| Full-suite receipt | 2521 passed / 1 skipped / 2 xfailed | claimed by `task-1-full-suite.md` on this same HEAD/tree/perimeter; this lane did not rerun the 19-minute suite |

Perimeter recipe (reproduced): SHA-256 of sorted `path<TAB>file-sha256\n`
over `git show --name-only --format= e3bca45`. Working tree of those 23
paths matches `HEAD:` blobs. Staged index empty.

## Verdict

**PASS**

Confidence: `0.93`

Committed Step 6 consumes the Step 5 parent without rewriting it, owns only
the Step 6 product/test perimeter, keeps pre-fence shadow under live v1
constraints, keeps research extraction on the current ingest `document_ids`,
discriminates legacy vs v2 reads honestly, and does not slip Step 7+ /
cutover / 9C semantics. Unrelated dirty work and the protected listener are
unchanged.

## Authority used

Joint execution authority (section 0 wins on conflict):

- `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md` §0
  and Step 6
- `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md` §6
  Step 6 (`6A`/`6B`/`6C`/`6D`)

Also read, not treated as authority when they conflict with §0:

- `.omo/plans/wave21-ingestion-steps5-10.md` Task 1
- `.omo/ulw-loop/wave21-step6-ingestion-service-20260821/brief.md`
- `.omo/ulw-loop/wave21-step5-migration-core-20260821/step6-kickoff.md`
  (still remaps 6B to citation-blob removal; §0 wins)
- Step 5 evidence index
- G006 / G008 / G009 receipts
- G005 context FAIL and G007 context PASS (pre-commit dirty tree)

Canonical docs were not edited. The analysis file remains untracked
(`?? docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md`).
The blueprint is under gitignored `.omo/`. Neither path is in `e3bca45`.

## Checklist

| Required fidelity | Result |
|---|---|
| Step 5 dependency consumed | **HOLD** |
| Step 6-only ownership held | **HOLD** |
| Old constraints respected by shadow mode | **HOLD** |
| Research extracts only current IDs | **HOLD** |
| Legacy / v2 boundaries honest | **HOLD** |
| No Step 7+ / cutover slip | **HOLD** |
| Protected / unrelated work preserved | **HOLD** |

## 1. Step 5 dependency consumed

§0.1: `S5 --> S6`. Task 1 is blocked by the Step 5 commit / current Step 6
bundle and blocks 2–20.

Evidence on current bytes:

- `git merge-base --is-ancestor eab47a6 e3bca45` → ancestor yes.
- `git diff --stat eab47a6 e3bca45 --` restricted to Step 5 product/tests
  (`migration.py`, `migration_backfill.py`, `migration_rehearsal.py`,
  `tests/test_migration*.py`, `tests/test_wave21_perf_baseline.py`,
  `tests/fixtures/wave21/{target-migration-contract-v1,perf-v1}.json`,
  `doi_backfill.py`, `identity_decisions.py`, `authority.py`,
  `alias_authority.py`) is empty.
- File-set intersection of the two commits is empty. Step 5 landed
  `ontologylab/migration{,_backfill,_rehearsal}.py` plus four tests;
  Step 6 landed a disjoint 23-path set.
- Frozen Step 5 perf manifest is byte-identical to the parent blob
  (`4ee7b1badc8c43e742b4fc5e1d23ece7678b54e0`) and still hashes to the
  plan-required
  `019a986f878bcba5b2ba8c67a1451d8fc19af021988e28bdd9f7e2287f82f0b1`.
- `ontologylab/authority.py:6-8` (unchanged vs parent) still states that
  global `UNIQUE(content_hash)` and the partial DOI index keep write
  authority until the Step 9 constraint rebuild. Step 6 writes into that
  additive schema (`works` / `work_identifiers` / `document_observations`
  / `provenance_outbox`) instead of replacing Step 5 machinery.

Step 5 evidence index
(`.omo/evidence/ulw/wave21-step5-migration-core-20260821/G005-goal-5-close-step-5-run-the-exact-fu/a1/step5-evidence-index.md`)
remains the consumed baseline: backup-copy migration core, F1/F6, no
production cutover.

## 2. Step 6-only ownership held

`git diff --name-only eab47a6 e3bca45` is exactly the 23 committed paths.
No extra path, no missing path.

```
M ontologylab/authority_repo.py
A ontologylab/file_lifecycle.py
M ontologylab/ingestion.py
A ontologylab/ingestion_service.py
A ontologylab/ingestion_shadow.py
A ontologylab/ingestion_surfaces.py
M ontologylab/kgstore.py
M ontologylab/main.py
A ontologylab/provenance_outbox.py
M ontologylab/server/app.py
A ontologylab/server/ingest_routes.py
M ontologylab/server/routes.py
M ontologylab/work_view.py
A tests/test_document_view.py
A tests/test_file_lifecycle.py
A tests/test_ingest_concurrency.py
A tests/test_ingestion_service.py
A tests/test_ingestion_shadow_entrypoints.py
A tests/test_ingestion_surfaces.py
A tests/test_provenance.py
M tests/test_provenance_api.py
A tests/test_provenance_outbox.py
A tests/wave21/ingest_concurrency.py
```

That set is the G006/G008/G009 + Task-1 repair perimeter claimed by
`task-1-product-commit.md`, independently rehashed to `abe543be…`.

Unchanged vs parent (not owned, not rewritten):

| Path | Role left to later / earlier steps |
|---|---|
| `ontologylab/server/jobs.py` | research current-ID extract (blob `f8e32cc9…` identical) |
| `ontologylab/extractor.py` | extraction loop |
| `ontologylab/preferred.py` | D07 on-read ranker, not C-024 consumer |
| `ontologylab/extraction_state.py` | pre-Step-7 run table |
| `ontologylab/migration*.py` | Step 5 |
| `ontologylab/packbuilder.py`, `pack_completeness.py` | Step 8 |
| `ontologylab/critic.py` | review, Step 7 |
| `ontologylab/authority.py` | Step 3 additive schema |

G006/G008/G009 receipts name the same new modules now in `HEAD:`
(`provenance_outbox.py`, `file_lifecycle.py`, `ingestion_shadow.py`) plus
the four production seams. Those receipts were written against the dirty
pre-commit tree; the committed blobs match the hashes recorded in
`task-1-product-commit.md`.

Plan Task 1's suggested subject `fix(ingestion): preserve safe legacy
provenance reads` would understate this tree. The landed subject names the
whole Step 6 increment. That is the honest ownership caption.

## 3. Old constraints respected by shadow mode

Canonical analysis §6 Step 6: pre-fence allows **legacy-compatible shadow
mode** only. Representable outcomes are mirrored atomically; richer /
conflicting outcomes go to a durable queue; this is not full semantic
dual-write; full v2 write authority waits for Step 9 constraint rebuild.

Committed adapter (`ontologylab/ingestion_shadow.py:1-7,32-33`):

```python
SHADOW_MODE = "legacy_compatible"
FULL_V2_AUTHORITY = False
```

`FULL_V2_AUTHORITY` is assigned in exactly one place in `ontologylab/` and
`tests/`, and the value is `False`.

Live v1 constraints still authoritative:

- `kgstore.py:251` `UNIQUE (content_hash)` — no hunk vs parent.
- `insert_document` same-DOI / new-bytes still one row
  (`tests/test_kgstore.py:416-444`;
  `tests/test_wave21_identity_characterization.py:15-20,75-88`).
- `ingest_item` still refuses a foreign hash as `InvalidIngestItem`
  (`ingestion_service.py:231-238`). Two-Work same-bytes remains Step 9.

Shadow itself does not punch through those constraints:

- same DOI + new bytes → enqueue `reason="richer"`, return the existing
  document, `created=False`, raw text stays the first bytes
  (`ingestion_shadow.py:336-358`;
  `test_richer_same_doi_new_bytes_is_queued_not_second_representation`).
- different DOI + same bytes → enqueue `reason="conflict"` and a typed
  `IdentityConflict` (`ingestion_shadow.py:360-378`;
  `test_conflicting_different_doi_same_bytes_is_queued_and_typed`).
- representable create/duplicate goes through `_mirror_create` /
  `_mirror_duplicate` (legacy document row + Observation/outbox) inside a
  SAVEPOINT; `shadow_persist` never commits or rolls back the caller
  (`ingestion_shadow.py:390-397`).

`work_view.py` now ranks **ready** representations only via the unchanged
D07 `preferred_representation` (stage-first, not the Step 7 tuple
`ready > usable full text > …`). That is F4 honesty, not C-024 selection.
Research never calls it.

## 4. Research extracts only current IDs

`ontologylab/server/jobs.py` is byte-identical to the Step 5 parent
(`f8e32cc9…`). The research worker still:

1. calls `ingest_documents` (now the shadow adapter);
2. binds `doc_ids = list(result.document_ids)`;
3. passes that list into `run_extraction`;
4. documents that it must not fall back to global `unprocessed_doc_ids`.

```894:951:ontologylab/server/jobs.py
            result = ingest_documents(store, raw_docs, provenance)
            doc_ids = list(result.document_ids)
            ...
            # `doc_ids` is passed explicitly and is never allowed to fall back
            # to `unprocessed_doc_ids(store)`.
            stopped_reason = await run_extraction(
                store, engine, provenance, caps, doc_ids, ...
            )
```

`IngestionResult.document_ids` is only the current batch entries
(`ingestion.py:43-45`). Richer queue hits still surface the **existing**
id, so research extracts the already-stored abstract, not the queued
richer payload. That is pre-fence honesty, not C-024.

Pinned by `tests/test_research_run.py::test_older_documents_are_not_extracted_on_this_run`
(reproduced this pass): a pre-existing `insert_document` row is absent
from `extract.doc` provenance; exactly one current id is extracted.

Honest residual, not a fail: standalone HTTP extract
(`jobs.py:706` `extraction_doc_ids(store)`) is still the global
unprocessed set. The required claim is the **research** consumer.

Four production seams share the adapter (G009 claim, confirmed in
committed sources):

| Surface | Call |
|---|---|
| CLI `collect` | `main.py:587` `ingest_documents` |
| `POST /api/collect` | `routes.py:1953` `ingest_documents` |
| research worker | `jobs.py:894` `ingest_documents` |
| `POST /api/collect/sample` | `routes.py:2003` `ingest_sample` |

`finalize_shadow_writes` raises quarantine only for ids in the current
batch (`ingestion.py:69-84`), so an unrelated bad row cannot fail the
current research persist/extract unit.

## 5. Legacy / v2 boundaries honest

`document_raw_text` (`kgstore.py:2186-2221`) is a two-branch discriminator:

| Branch | Predicate | Reader | Integrity |
|---|---|---|---|
| v2 | `work_id is not None` | `read_ready_text` | ready-only, `documents/` containment, always hash |
| legacy | `work_id is None` | contained store-root decode | **does not** treat `content_hash` as an oracle; refuses escapes and `{sources,providers}.json` / `.env` |
| non-ready legacy | `representation_state != READY` | none | typed refuse before `read_bytes` |

SELECT lists `raw_text_path, representation_state, work_id` and omits
`content_hash`. That is the Task 1 repair: synthetic `sha256:`+`d*64`
legacy fixtures stay readable. v2 still hash-checks.

`reconcile_files` (`file_lifecycle.py:437-444`) selects only
`work_id IS NOT NULL` and (`staged` or `documents/%` + 71-char hash).
NULL-`work_id` legacy rows are not auto-quarantined. `KGStore.open`
runs that reconcile then `project_outbox` on writable opens only
(`kgstore.py:767-775`).

`test_document_view.py` pins ready-only view, planted-path refusal, v2
hash match, v2 hash mismatch, and legacy escape. The focused provenance
test pins the synthetic-hash legacy row.

Residual (already classed by G007, not a new fail): the legacy allowlist
is store-root + three basenames, not `documents/`-only. HTTP ingest /
collect assign `work_id` and cannot enter that branch.

## 6. No Step 7+ / cutover slip

§0.1–0.3 / analysis §6: C-024, extraction/chunk/Citation/ReviewDecision
receipts, H1, pack v2 / F11, F3/F7 cutover, constraint rebuild, and 9C
are not Step 6.

On `e3bca45` vs `eab47a6`:

- No added `citation_projection.py`, `pack_v2*`, `pack_verifier.py`,
  ReviewDecision / grounding-waiver modules, or C-024 research selector.
- `git ls-tree -r --name-only HEAD | rg citation_projection` → empty.
- New Step 6 files do not import `migration`, `post_cutover_write`,
  pack v2, or C-024.
- `preferred.py` ranking is still stage-first D07 and is unchanged vs
  parent. Step 7's required tuple is not implemented.
- `extraction_state.py` still keys runs by `document_id`, not
  `representation_id` (unchanged).
- `FULL_V2_AUTHORITY is False` is asserted in
  `test_adapter_is_legacy_compatible_shadow_not_full_v2` and the richer
  test.
- `post_cutover_write` exists only in unchanged Step 5 `migration.py`.
- Two-document same-hash materialization remains the pinned
  characterization / Step 9 xfail, not a Step 6 enablement.

G003 citation-blob 6B is not in product sources. `work_snapshot` returns
work / identifiers / observations / representations /
`preferred_representation_id` only — no `title`/`citation` projection.

Kickoff/brief still say “6B = citation blob”. Those files were not
edited (planning-doc guard). §0 file-lifecycle 6B is what the tree
implements.

## 7. Protected / unrelated work preserved

`git status --short` after this review (same 11 residual entries as
`task-1-product-commit.md` / `task-1-full-suite.md`):

```
?? .sisyphus/
?? artifacts/
?? docs/CONANSSAM-PROMPT-2026-08-08.bak
?? docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md
?? docs/OMO-INGESTION-WAVE-2.1-IMPLEMENTATION-HANDOFF-2026-08-20.md
?? docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md
?? "docs/ONTOLOGYLAB-DETAILED-SMOKE-RESULT-2026-08-08 2.md"
?? docs/WAVE-2.1-DEEP-RESEARCH-REMEDIATION-GJC-2026-08-20.md
?? graphify-out/
?? ontologylab/graphify-out/
?? uv.lock
```

`git diff --stat -- ontologylab tests` empty. Staged empty. No `.omo/`,
plan, or canonical path in the commit.

Port 8799 / PID 55560 (read-only, before and after focused tests; same
DEVICE `0x1ff51c806b197195`, same start `Thu Aug 6 13:51:44 2026`):

```
python3.1 55560  TCP 127.0.0.1:8799 (LISTEN)
.venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 8799
  --data-dir /Users/hyunjun/Library/Application Support/ontologylab/data
  --packs-dir /Users/hyunjun/Library/Application Support/ontologylab/packs
```

This review did not open Application Support files. No
`/private/tmp/ontologylab-wave21-task1*` residue. No pytest left running.

## Focused reproduction (this lane, once)

CWD `/Users/hyunjun/Documents/MUNI/ontologylab`, interpreter
`.venv/bin/python` 3.12.12.

```
.venv/bin/python -m pytest \
  tests/test_ingestion_shadow_entrypoints.py::test_adapter_is_legacy_compatible_shadow_not_full_v2 \
  tests/test_ingestion_shadow_entrypoints.py::test_richer_same_doi_new_bytes_is_queued_not_second_representation \
  tests/test_ingestion_shadow_entrypoints.py::test_conflicting_different_doi_same_bytes_is_queued_and_typed \
  tests/test_research_run.py::test_older_documents_are_not_extracted_on_this_run \
  tests/test_document_view.py \
  tests/test_provenance_api.py::test_legacy_provenance_reads_when_hash_metadata_is_synthetic \
  tests/test_file_lifecycle.py::test_document_raw_text_rechecks_hash_for_ready_file \
  tests/test_kgstore.py::test_same_doi_with_changed_body_is_one_document \
  tests/test_wave21_identity_characterization.py::test_same_doi_new_bytes_is_one_row_and_keeps_the_first_bytes \
  -q
.............                                                            [100%]
```

13 passed. Only warning is the third-party Starlette/FastAPI
`httpx`/`TestClient` deprecation. No retry. After the run: HEAD, tree,
and the 23-path working tree still match the bound identity.

Full `.venv/bin/python -m pytest` was not rerun. This review binds the
suite claim to `task-1-full-suite.md` on the same HEAD/tree/perimeter:
`2521 passed, 1 skipped, 2 xfailed`, exit 0.

## Findings (non-blocking)

1. **F2 caption residual (unchanged).** G004 is still thread-barrier
   identifier-family concurrency, not the full `05-failure-analysis.md`
   process-writer / hash-case / outbox table. Cite G004, not “F2 GREEN”.
2. **Standalone extract is still global.** Only the research worker is
   pinned to current `document_ids`.
3. **`insert_document` leftover.** Competency helpers and historical
   tests still use the internal-commit writer. The four production
   collect seams do not.
4. **Kickoff/brief 6B wording is stale.** Section 0 wins; do not edit
   those planning files in this close.
5. **Legacy store-root residual.** SQL-planted NULL-`work_id` UTF-8
   files outside the three-name denylist can still be read. Not reachable
   from `/api/ingest` or collect.

None of these reopen a section-0 Step 6 context fail.

## Blockers

None for repository / history / context fidelity on
`e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` /
tree `47e5964457c46f6a769ff074ed20f3619e1b9c0c` /
perimeter `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e`.

## Honest caption

**`e3bca45`:** Step 6 is a child of the untouched Step 5 commit. The
23-path increment is the production-equivalent legacy-compatible shadow
writer (6A/6B/6C/6D) plus the confirmed synthetic-hash legacy-read
repair. Old global-hash / same-DOI constraints still govern writes;
richer and second-DOI outcomes queue. Research extracts only the current
batch ids. v2 ready bytes hash-verify; contained legacy rows do not use
`content_hash` as an oracle. Full v2 authority, C-024 selection, pack v2,
and cutover remain off. Unrelated dirty paths and PID 55560 / :8799 are
untouched.

## Protected-boundary cleanup

- This file is the only write.
- No product/test/plan/canonical bytes changed.
- No Git ref mutation.
- PID 55560 / 127.0.0.1:8799 unchanged (same DEVICE, same start time).
- No live Application Support access.
- No leftover focused-test processes or `ontologylab-wave21-task1*` temps.
