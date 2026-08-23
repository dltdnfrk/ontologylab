# Task 2 product-commit boundary report

Date: 2026-08-23
Worker: omo senpi-task `st_01a02eb0`
Mode: COMMIT (product/test only). No push. No amend/rebase/reset/checkout/restore/stash.

## Verdict

`committed`

Exactly one atomic Task 2 product/test commit exists. Path list is verified. No unowned path was staged or committed. No push occurred.

## Ground truth (pre-commit)

| Fact | Value |
|---|---|
| Physical cwd | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Git top-level | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Origin | `origin` → `https://github.com/dltdnfrk/ontologylab.git` (fetch/push) |
| Branch | `main` |
| Upstream | `origin/main` |
| Pre-commit HEAD | `63e326f27c60b81f8a3e3daaf27518e82564da5c` |
| Pre-commit subject | `docs(evidence): close wave21 ingestion step 6` |
| Ahead/behind vs `origin/main` | `0	43` before commit; `0	44` after. `origin/main` still `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| Staged diff initially | empty |
| Merge-base `origin/main` | `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| `origin/master` | missing (not a valid object) |

Dominant local subject style is conventional `type(scope): lowercase summary` (`feat`, `fix`, `test`, `docs`). Requested subject used verbatim.

## Verifier gate

Re-read `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-2-verifier.md`.

- Verdict: `confirmed` (confidence `0.91`)
- HEAD at verify time: `63e326f27c60b81f8a3e3daaf27518e82564da5c` (unchanged; no commit)
- Required current-byte hashes, recomputed from working-tree then from committed `HEAD:` blobs; all MATCH:

| Path | SHA-256 |
|---|---|
| `ontologylab/extraction_receipt_ids.py` | `c8c0fd4b431bfaa5ae9687fa869e0d8cffe5338557a625dc461ac110c6d9daae` |
| `ontologylab/extraction_receipt_store.py` | `42ad7c6be247587304a5ad6fd4ef29da5d199ce4f4f27f5d7c58d3084dc64f86` |
| `ontologylab/extraction_receipts.py` | `01d18f23b0c88506a3ed694eef42e33e22d29ce48e0b1cbc6042f5cfc78bd8e7` |
| `ontologylab/extraction_receipt_schema.py` | `4f68452dcbad35e3e85443751071786ac156a1c62ad3ca5e1510e2443a044ea8` |
| `ontologylab/extraction_receipt_types.py` | `bc2b07d241cd3392760035a96803ebef61f0774caecdda57a38089282e834dc3` |
| `ontologylab/extraction_state.py` | `09bd61aeb8567c22c2a2abca8717296db7089f51a2f7be77068d8fcc1bac880e` |
| `tests/test_extraction_receipts.py` | `b1a0f2b465267163c813e0c60da982e83f0ffc73da799c36296bc3a9b55be52e` |

No focused smoke rerun: every owned file matched the verifier table on current bytes. Task instruction: do not duplicate QA when bytes do not drift.

## Ownership derivation

Owned paths were taken from the current dirty tree intersected with Task 2 executor/verifier evidence, not from the task sentence alone.

| Source | Owned product/test paths |
|---|---|
| Plan Task 2 | additive schema/types/repository binding runs to `representation_id` + document hash + policy/config; chunks to start/end/profile/hash/plan; focused extraction tests |
| Task-2 executor | `extraction_state.py` hook/re-exports; new `extraction_receipts.py`, `extraction_receipt_types.py`, `extraction_receipt_ids.py`, `extraction_receipt_schema.py`, `extraction_receipt_store.py`; `tests/test_extraction_receipts.py` |
| Task-2 verifier | same seven paths; `extraction_state.py` is exactly `+10` vs HEAD (import re-exports + `ensure_receipt_schema` inside existing `ensure_schema`) |

Hunk attribution (no mixed unowned hunks):

- Tracked diff inspected in full before staging. `ontologylab/extraction_state.py` is two hunks only: public re-exports and the schema hook. `plan` / `claim` / `failed` / `succeeded` / `finish` / `recover_running_once` bodies are unchanged.
- Untracked owned files are new Task 2 receipt modules and the direct contract test. Headers name Representation-scoped run/chunk receipts only.
- No unexpected module: no `extractor.py`, `work_view.py`, citation, review, pack, or migration edits.

Excluded from this commit (present in worktree, never staged):

- `.omo/plans`, drafts, Boulder, start-work ledger/reports (this report included)
- Step 6 evidence
- canonical docs under `docs/`
- Task 3+ product/test files (none dirty)
- unrelated/untracked user files (`.sisyphus/`, `artifacts/`, `graphify-out/`, `uv.lock`, planning docs)

## Commit

| Field | Value |
|---|---|
| Subject | `feat(extraction): bind runs and chunks to representations` |
| Commit | `49ac5249fbfaecf0e18a00d08392166ea79250d5` |
| Tree | `2023a1bbf0e851c8bcb24b16ea072bcbc2953dc7` |
| Parent | `63e326f27c60b81f8a3e3daaf27518e82564da5c` |
| `git log -1 --oneline` | `49ac524 feat(extraction): bind runs and chunks to representations` |
| Files | 7 (`1184` insertions) |
| Perimeter hash | `1287ca36f8f7062cf5de44140d7fe2ac4fa4494bc359f802bf2d39ce736494c8` |
| Perimeter recipe | SHA-256 of sorted `path<TAB>file-sha256\n` over the 7 committed paths |
| Push | none. `origin/main` unchanged. Branch now `[ahead 44]` |

## Committed path list

```
A ontologylab/extraction_receipt_ids.py
A ontologylab/extraction_receipt_schema.py
A ontologylab/extraction_receipt_store.py
A ontologylab/extraction_receipt_types.py
A ontologylab/extraction_receipts.py
M ontologylab/extraction_state.py
A tests/test_extraction_receipts.py
```

Per-file SHA-256 (committed `HEAD:` blobs; same as pre-stage working tree and verifier table):

```
ontologylab/extraction_receipt_ids.py	c8c0fd4b431bfaa5ae9687fa869e0d8cffe5338557a625dc461ac110c6d9daae
ontologylab/extraction_receipt_schema.py	4f68452dcbad35e3e85443751071786ac156a1c62ad3ca5e1510e2443a044ea8
ontologylab/extraction_receipt_store.py	42ad7c6be247587304a5ad6fd4ef29da5d199ce4f4f27f5d7c58d3084dc64f86
ontologylab/extraction_receipt_types.py	bc2b07d241cd3392760035a96803ebef61f0774caecdda57a38089282e834dc3
ontologylab/extraction_receipts.py	01d18f23b0c88506a3ed694eef42e33e22d29ce48e0b1cbc6042f5cfc78bd8e7
ontologylab/extraction_state.py	09bd61aeb8567c22c2a2abca8717296db7089f51a2f7be77068d8fcc1bac880e
tests/test_extraction_receipts.py	b1a0f2b465267163c813e0c60da982e83f0ffc73da799c36296bc3a9b55be52e
```

Staged-set proof before commit: 7/7 owned, 0 forbidden (no `.omo/`, `docs/`, live data, `uv.lock`, graphify, or unowned paths). Index empty after commit. Owned working tree clean vs HEAD.

## Residual `git status --short` (classified)

```
?? .sisyphus/                                          unrelated user/tooling
?? artifacts/                                          unrelated user artifacts
?? docs/CONANSSAM-PROMPT-2026-08-08.bak                 unrelated / not Task 2 product
?? docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md   unrelated planning
?? docs/OMO-INGESTION-WAVE-2.1-IMPLEMENTATION-HANDOFF-2026-08-20.md  unrelated planning
?? docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md  canonical authority (MUST NOT)
?? docs/ONTOLOGYLAB-DETAILED-SMOKE-RESULT-2026-08-08 2.md  unrelated
?? docs/WAVE-2.1-DEEP-RESEARCH-REMEDIATION-GJC-2026-08-20.md  unrelated
?? graphify-out/                                       unrelated generated
?? ontologylab/graphify-out/                           unrelated generated
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
- `git rev-parse HEAD` pre-commit `63e326f27c60b81f8a3e3daaf27518e82564da5c`
- working-tree SHA-256 vs verifier table: 7/7 MATCH
- staged path set == owned set; forbidden set empty
- full staged diff inspected; every hunk is Task 2
- `git log -1 --oneline` after commit → `49ac524 feat(extraction): bind runs and chunks to representations`
- committed-blob perimeter rehash matches pre-stage `1287ca36…`
- `git rev-parse origin/main` unchanged (`4ee5465b…`)

Not run (out of this commit scope):

- focused smoke (bytes did not drift from confirmed verifier)
- full `.venv/bin/python -m pytest` suite
- any network / live Application Support / port 8799 action

## Recovery

Parent `63e326f27c60b81f8a3e3daaf27518e82564da5c` is untouched. Residual untracked files were never added. No force, push, or history rewrite. Reflog: `49ac524 HEAD@{0}: commit: feat(extraction): bind runs and chunks to representations`.
