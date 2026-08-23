# Task 4 product-commit boundary report

Date: 2026-08-24
Worker: omo senpi-task `st_01a02f30`
Mode: COMMIT (product/test only). No push. No amend/rebase/reset/checkout/restore/stash.

## Verdict

`committed`

Exactly one atomic Task 4 product/test commit exists. Path list is verified. No unowned path was staged or committed. No push occurred.

## Ground truth (pre-commit)

| Fact | Value |
|---|---|
| Physical cwd | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Git top-level | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Origin | `origin` → `https://github.com/dltdnfrk/ontologylab.git` (fetch/push) |
| Branch | `main` |
| Upstream | `origin/main` |
| Pre-commit HEAD | `1afd0f85b038475a3b0a43f477febd1b25bfce01` |
| Pre-commit subject | `feat(extraction): receipt preferred representation selection` |
| Ahead/behind vs `origin/main` | `0	45` before commit; `0	46` after. `origin/main` still `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| Staged diff initially | empty |
| Merge-base `origin/main` | `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| `origin/master` | missing (not a valid object) |

Dominant local subject style is conventional `type(scope): lowercase summary` (`feat`, `fix`, `test`, `docs`). Requested subject used verbatim.

## Verifier gate

Re-read:

- `.omo/plans/wave21-ingestion-steps5-10.md` Task 4 → persist immutable Citation / selected-text grounding receipts; commit subject `feat(citations): seal representation grounding receipts`
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-executor.md` → implemented; HEAD `1afd0f85…`; no commit
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-verifier-recovery.md` → `clean-for-reverification` after failed verifier `st_01a02f06`
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-verifier-retry.md` → `needs-fix` (isolated mutants 3/5/6/7 stayed green)
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-repair.md` → coverage-only four-decision repair; product hashes frozen
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-repair-verifier.md` → `confirmed` (confidence `0.94`)

HEAD at verify/repair time: `1afd0f85b038475a3b0a43f477febd1b25bfce01` (unchanged; no commit). Repair is test-only; product SHA-256 values equal the executor + repair freeze.

Required current-byte hashes, recomputed from working-tree then from staged index then from committed `HEAD:` blobs; all MATCH. No focused smoke rerun: every owned file matched the repair-verifier table on current bytes. Task instruction: do not duplicate tests when hashes match confirmed bytes.

| Path | SHA-256 |
|---|---|
| `ontologylab/citation.py` | `37a21316babc973ccd5a790e67ac507e54c81fc37554ff647ec67a305f905b8b` |
| `ontologylab/citation_types.py` | `ad0e6c44081b8efb2a577deb57f988a9934013abe3d84f4d1aa9993e08ce8f94` |
| `ontologylab/citation_ids.py` | `e4d897578170c8060ab29f4b7a85996f2c0d323b888107e710e23041ba7a9b62` |
| `ontologylab/citation_schema.py` | `54e64614bd055c2c8433c894ce60cdd9f24213ef4bc7a9732c4e5ed4a9a74c5a` |
| `ontologylab/citation_verify.py` | `c30d0fdec2417b66c3bc208a02f0359ba9bfec715a785743968ef914ac6428db` |
| `ontologylab/citation_store.py` | `28986db331bd062f4f858d0cbc1f9bc9d09a5769ce1b4c3918af761e49b04c29` |
| `ontologylab/citation_bind.py` | `e90287d1ee8549ca27ed4718a30de6d86395b53d5e2a7646d38b0c2932e55dc7` |
| `ontologylab/extractor.py` | `f2ddc74799d1cd43de41d800d12d41c876959c198eca67bc882b3186e2be09a5` |
| `ontologylab/extraction_state.py` | `3144da3be7c002db6ba79518a66fc907d322ee62580f1b6f7784f88229914b5c` |
| `tests/test_citation_receipts.py` | `b626dc0cb63c4c90c52275134ca5c6baf2bb9db0f1341108c223b40491e586d2` |
| `tests/test_citation_receipt_decisions.py` | `b3c0f1be8741898a92e1d6b947cafc359bf7c5fb5f9013aa9d211a1a27092f7b` |

Companion freeze (Task 3 research consumer, not restaged): `ontologylab/research_extract.py` `d2da049dd2c822a8ea2d9c1208d2ffec4010f104869489175b5b2c4ad33a20c3` MATCH, working tree clean vs HEAD, no Citation symbols.

## Ownership derivation

Owned paths were taken from the current dirty tree intersected with Task 4 plan/executor/verifier/repair evidence, not from the task sentence alone.

| Source | Owned product/test paths |
|---|---|
| Plan Task 4 | immutable Citation + selected-text grounding receipts; Representation/hash/run/chunk/profile/span/text; no content-hash dedupe; no chunk-local document offsets |
| Task-4 executor | `citation_types.py`, `citation_ids.py`, `citation_schema.py`, `citation_verify.py`, `citation_store.py`, `citation_bind.py`, `citation.py`, `extractor.py` persist hook, `extraction_state.py` schema hook, `tests/test_citation_receipts.py` |
| Failed verifier + recovery | same product/test set; hashes MATCH; no restore |
| Retry verifier | same product/test set; `needs-fix` on isolated #3/#5/#6/#7 |
| Repair + repair-verifier | adds `tests/test_citation_receipt_decisions.py` only; product hashes frozen; `confirmed` |

Research hook: `extract_research_documents` → `run_extraction`. The persist call lives in `extractor.py` after `insert_proposed(..., commit=False)`. `research_extract.py` has no Task 4 hunk and was not staged.

QA tests: executor/repair/repair-verifier used disposable `/private/tmp/ontologylab-wave21-task4*.qa*` drivers that were deleted. No leftover QA test file exists in the worktree.

Hunk attribution (no mixed unowned hunks):

- Tracked diffs inspected in full before staging.
  - `extraction_state.py`: import `ensure_citation_schema` and call it after `ensure_receipt_schema` (+2).
  - `extractor.py`: import `persist_chunk_citations` / `ChunkCitationBatch` and persist after `insert_proposed(..., commit=False)` (+16).
- Untracked owned files are new Task 4 citation types/ids/schema/verify/store/bind/facade plus focused + four-decision tests.
- Staged keyword scan for `ReviewDecision` / `approve_with_grounding` / `review_decision` / `review_grounding` / `waiver` was empty.

Excluded from this commit (present in worktree, never staged):

- `.omo` active/evidence reports (this report included)
- canonical docs under `docs/`
- Task 5 ReviewDecision / waiver files (`ontologylab/review_decision*.py`, `review_grounding.py`)
- Task 2/3 committed files without a Task 4 hunk (`extraction_receipt_*`, `selection_*`, `research_extract.py`, `tests/test_extraction_receipts.py`, `tests/test_preferred_selection.py`, `tests/test_research_selection.py`, `tests/test_research_ready_boundary.py`)
- unrelated/untracked user files (`.gjc/`, `.sisyphus/`, `artifacts/`, `graphify-out/`, `uv.lock`, planning docs)

## Commit

| Field | Value |
|---|---|
| Subject | `feat(citations): seal representation grounding receipts` |
| Commit | `7c159fd3efa24a5b9839e0ae32643e7f90560124` |
| Tree | `64166739485e405086196576019f888f6ac6c426` |
| Parent | `1afd0f85b038475a3b0a43f477febd1b25bfce01` |
| `git log -1 --oneline` | `7c159fd feat(citations): seal representation grounding receipts` |
| Files | 11 (`2250` insertions) |
| Perimeter hash | `bbf7f76bf97397001a50d495cace5e94542b058c239417618cddb460ec5f8487` |
| Perimeter recipe | SHA-256 of sorted `path<TAB>file-sha256\n` over the 11 committed paths |
| Push | none. `origin/main` unchanged. Branch now `[ahead 46]` |

## Committed path list

```
A ontologylab/citation.py
A ontologylab/citation_bind.py
A ontologylab/citation_ids.py
A ontologylab/citation_schema.py
A ontologylab/citation_store.py
A ontologylab/citation_types.py
A ontologylab/citation_verify.py
M ontologylab/extraction_state.py
M ontologylab/extractor.py
A tests/test_citation_receipt_decisions.py
A tests/test_citation_receipts.py
```

Per-file SHA-256 (committed `HEAD:` blobs; same as pre-stage working tree, staged index, and repair-verifier table):

```
ontologylab/citation.py	37a21316babc973ccd5a790e67ac507e54c81fc37554ff647ec67a305f905b8b
ontologylab/citation_bind.py	e90287d1ee8549ca27ed4718a30de6d86395b53d5e2a7646d38b0c2932e55dc7
ontologylab/citation_ids.py	e4d897578170c8060ab29f4b7a85996f2c0d323b888107e710e23041ba7a9b62
ontologylab/citation_schema.py	54e64614bd055c2c8433c894ce60cdd9f24213ef4bc7a9732c4e5ed4a9a74c5a
ontologylab/citation_store.py	28986db331bd062f4f858d0cbc1f9bc9d09a5769ce1b4c3918af761e49b04c29
ontologylab/citation_types.py	ad0e6c44081b8efb2a577deb57f988a9934013abe3d84f4d1aa9993e08ce8f94
ontologylab/citation_verify.py	c30d0fdec2417b66c3bc208a02f0359ba9bfec715a785743968ef914ac6428db
ontologylab/extraction_state.py	3144da3be7c002db6ba79518a66fc907d322ee62580f1b6f7784f88229914b5c
ontologylab/extractor.py	f2ddc74799d1cd43de41d800d12d41c876959c198eca67bc882b3186e2be09a5
tests/test_citation_receipt_decisions.py	b3c0f1be8741898a92e1d6b947cafc359bf7c5fb5f9013aa9d211a1a27092f7b
tests/test_citation_receipts.py	b626dc0cb63c4c90c52275134ca5c6baf2bb9db0f1341108c223b40491e586d2
```

Staged-set proof before commit: 11/11 owned, 0 forbidden (no `.omo/`, `docs/`, live data, `uv.lock`, graphify, ReviewDecision, or unowned paths). Index empty after commit. Owned working tree clean vs HEAD.

## Residual `git status --short` (classified)

```
?? .gjc/                                               unrelated user/tooling
?? .sisyphus/                                          unrelated user/tooling
?? artifacts/                                          unrelated user artifacts
?? docs/CONANSSAM-PROMPT-2026-08-08.bak                 unrelated / not Task 4 product
?? docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md   unrelated planning
?? docs/OMO-INGESTION-WAVE-2.1-IMPLEMENTATION-HANDOFF-2026-08-20.md  unrelated planning
?? docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md  canonical authority (MUST NOT)
?? docs/ONTOLOGYLAB-DETAILED-SMOKE-RESULT-2026-08-08 2.md  unrelated
?? docs/WAVE-2.1-DEEP-RESEARCH-REMEDIATION-GJC-2026-08-20.md  unrelated
?? graphify-out/                                       unrelated generated
?? ontologylab/graphify-out/                           unrelated generated
?? ontologylab/review_decision.py                      Task 5 (excluded)
?? ontologylab/review_decision_ids.py                  Task 5 (excluded)
?? ontologylab/review_decision_schema.py               Task 5 (excluded)
?? ontologylab/review_decision_store.py                Task 5 (excluded)
?? ontologylab/review_decision_types.py                Task 5 (excluded)
?? ontologylab/review_grounding.py                     Task 5 (excluded)
?? uv.lock                                             unrelated user lockfile
```

Ignored orchestration/evidence (not shown by `git status --short`, not staged):

- `.omo/plans/`
- `.omo/drafts/`
- `.omo/boulder.json` / `.omo/start-work/ledger.jsonl`
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/` (this report)

## Verification commands

Passed:

- `git status --short` / `git diff --stat` / `git diff --staged --stat` (empty before commit; empty after)
- `git branch --show-current` → `main`
- `git rev-parse --abbrev-ref @{upstream}` → `origin/main`
- `git rev-parse HEAD` pre-commit `1afd0f85b038475a3b0a43f477febd1b25bfce01`
- working-tree SHA-256 vs executor+repair freeze: 11/11 MATCH plus untouched Task 3 `research_extract.py`
- staged path set == owned set; forbidden set empty
- full staged diffs of the two tracked files inspected; every hunk is Task 4
- staged blob keyword scan: no Task 5 ReviewDecision/waiver symbols
- `git log -1 --oneline` after commit → `7c159fd feat(citations): seal representation grounding receipts`
- committed-blob perimeter rehash matches pre-stage `bbf7f76b…`
- `git rev-parse origin/main` unchanged (`4ee5465b…`)

Not run (out of this commit scope):

- focused smoke (bytes did not drift from confirmed repair-verifier)
- full `.venv/bin/python -m pytest` suite
- any network / live Application Support / port 8799 action

## Recovery

Parent `1afd0f85b038475a3b0a43f477febd1b25bfce01` is untouched. Residual untracked files were never added. No force, push, or history rewrite. Reflog: `7c159fd HEAD@{0}: commit: feat(citations): seal representation grounding receipts`.
