# Task 5 product-commit boundary report

Date: 2026-08-23
Worker: omo senpi-task `st_01a02f63`
Mode: COMMIT (product/test only). No push. No amend/rebase/reset/checkout/restore/stash.

## Verdict

`committed`

Exactly one atomic Task 5 product/test commit exists. Path list is verified. No unowned path was staged or committed. No push occurred.

## Ground truth (pre-commit)

| Fact | Value |
|---|---|
| Physical cwd | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Git top-level | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Origin | `origin` → `https://github.com/dltdnfrk/ontologylab.git` (fetch/push) |
| Branch | `main` |
| Upstream | `origin/main` |
| Pre-commit HEAD | `7c159fd3efa24a5b9839e0ae32643e7f90560124` |
| Pre-commit subject | `feat(citations): seal representation grounding receipts` |
| Ahead/behind vs `origin/main` | `0	46` before commit; `0	47` after. `origin/main` still `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| Staged diff initially | empty |
| Merge-base `origin/main` | `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| `origin/master` | missing (not a valid object) |

Dominant local subject style is conventional `type(scope): lowercase summary` (`feat`, `fix`, `test`, `docs`). Requested subject used verbatim.

## Verifier gate

Re-read:

- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-verifier.md` → `confirmed` (confidence `0.93`); focused 55, affected 76, basedpyright clean, mutants a–j plus QA; HEAD `7c159fd3…`; no commit
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-repair-verifier.md` → `confirmed` (confidence `0.96`); repair-focused 21; CLI reject receipt print; same HEAD; no commit

HEAD at verify/repair time: `7c159fd3efa24a5b9839e0ae32643e7f90560124` (unchanged until this commit). Required current-byte hashes, recomputed from working-tree then from staged index then from committed `HEAD:` blobs; all MATCH the authorized 13-path table. No focused smoke rerun: every owned file matched the repair-verifier freeze on current bytes. Task instruction: do not run full suite or edit product/test bytes.

| Path | SHA-256 |
|---|---|
| `ontologylab/grounded_review.py` | `105e45da8363e8737f5b4156f8d75d4b929e88a12d0f5649e387897500e417e0` |
| `ontologylab/grounded_review_ids.py` | `4af4a46e68a9a4d62e3e040fd09d9452a3e05bfdfc7da01f41c6cb92bb19c226` |
| `ontologylab/grounded_review_payload.py` | `692b9a5a6b733cd1afda10ec5c33fea88b887c4e29f693a676b206db1cf3dc7a` |
| `ontologylab/grounded_review_preflight.py` | `b6c754bf500a9e384be4dc19fe024bca7d5efbc03dc764e588d6fd9291dc2a45` |
| `ontologylab/grounded_review_schema.py` | `cdc9ef8790d0f5ee01e4b57c214f4811d835b6fb04ec7f8457d109b9550a1771` |
| `ontologylab/grounded_review_store.py` | `c98f3a38cd8a3ec311b857fcb943acd8b173d684999001f9284dde6f9e09af5a` |
| `ontologylab/grounded_review_types.py` | `d64716d46155d66d42a958aa4b5cc6cdbeca06b34a302e985e5b6a8a0d4610ba` |
| `ontologylab/kgstore.py` | `0f37cc1d511917ff4b766c51301ec623ea02d539a1b7298bc62a0c3b1eb64013` |
| `ontologylab/extraction_state.py` | `7fba7e0f397cd81837412d4857b4c68e0886c275a2dff646774fc0da15bc993e` |
| `ontologylab/server/routes.py` | `d4905eb8b12bb820553fa1547473f345ed48dc2fba77de872f2691d907778ab9` |
| `ontologylab/server/schemas.py` | `a1993b8c25ec5781c6f6b92a4601728a19dc75a698eeb4cf780972032edaeea3` |
| `ontologylab/main.py` | `50e32fc1a1cc6a3921a2c8b481790b4c727593b3067f483d62d370ee4a0c6d36` |
| `tests/test_grounded_review.py` | `8b990e2fecd84407680ce42aac9660fd4401f9e4c95b465df3777d5428222cbc` |

Measured on those bytes (from authoritative receipts, not re-run here): focused 55 passed, affected 76 passed, repair-focused 21 passed, basedpyright 0/0/0, 11 semantic mutants killed (a–j plus CLI reject-print suppress), direct/CLI/HTTP QA confirmed.

## Ownership derivation

Owned paths were the independently hashed 13-path perimeter authorized by the commit task and both verifier receipts. Denylist paths were never opened, imported, staged, or hashed-changed in this turn.

Hunk attribution (no mixed unowned hunks):

- Tracked diffs inspected in full before staging.
  - `extraction_state.py`: import `ensure_grounded_review_schema` and call it after `ensure_citation_schema` (+2).
  - `kgstore.py`: `GroundingPreflightError`; schema ensure; approve/reject dispatch; quarantine/retract/compensate/waiver; `_grounded_review` / `_require_grounded_review` / `_raise_grounded` (+175).
  - `main.py`: approve receipt print; reject `_print_review_receipts`; quarantine/retract/compensate/waiver commands and parsers (+136).
  - `server/routes.py`: 409 on `GroundingPreflightError`; quarantine/retract/compensate/waiver routes (+82 / −2).
  - `server/schemas.py`: `GroundingWaiverAction` (+12).
- Untracked owned files are the disjoint `grounded_review*` modules plus `tests/test_grounded_review.py`.
- Owned-path `rg` for `from ontologylab.review_decision` / `review_grounding` was empty. Remaining `review_decision` hits are local function/table names inside the new namespace.

Excluded from this commit (present in worktree, never staged):

- `.omo` active/evidence reports (this report included)
- canonical docs under `docs/`
- denylist Task 5 drafts (`ontologylab/review_decision*.py`, `review_grounding.py`)
- unrelated/untracked user files (`.gjc/`, `.sisyphus/`, `artifacts/`, `graphify-out/`, `uv.lock`, planning docs)

## Commit

| Field | Value |
|---|---|
| Subject | `feat(review): require append-only grounding decisions` |
| Commit | `0a3c7a21d5ee8fbcfb7aa7bf521921e0e333ea29` |
| Tree | `be6cc43cf4fad81a6f81179e57438af2bdd46ef2` |
| Parent | `7c159fd3efa24a5b9839e0ae32643e7f90560124` |
| `git log -1 --oneline` | `0a3c7a2 feat(review): require append-only grounding decisions` |
| Files | 13 (`2146` insertions, `2` deletions) |
| Perimeter hash | `82ba0621f5e3a312973e9df4d0df412ae4c992d6ff9047a797b258efdab6835c` |
| Perimeter recipe | SHA-256 of sorted `path<TAB>blob-sha256\n` over the 13 committed paths |
| Push | none. `origin/main` unchanged. Branch now `[ahead 47]` |

## Committed path list

```
M ontologylab/extraction_state.py
A ontologylab/grounded_review.py
A ontologylab/grounded_review_ids.py
A ontologylab/grounded_review_payload.py
A ontologylab/grounded_review_preflight.py
A ontologylab/grounded_review_schema.py
A ontologylab/grounded_review_store.py
A ontologylab/grounded_review_types.py
M ontologylab/kgstore.py
M ontologylab/main.py
M ontologylab/server/routes.py
M ontologylab/server/schemas.py
A tests/test_grounded_review.py
```

Per-file SHA-256 (committed `HEAD:` blobs; same as pre-stage working tree, staged index, and authorized freeze):

```
ontologylab/extraction_state.py	7fba7e0f397cd81837412d4857b4c68e0886c275a2dff646774fc0da15bc993e
ontologylab/grounded_review.py	105e45da8363e8737f5b4156f8d75d4b929e88a12d0f5649e387897500e417e0
ontologylab/grounded_review_ids.py	4af4a46e68a9a4d62e3e040fd09d9452a3e05bfdfc7da01f41c6cb92bb19c226
ontologylab/grounded_review_payload.py	692b9a5a6b733cd1afda10ec5c33fea88b887c4e29f693a676b206db1cf3dc7a
ontologylab/grounded_review_preflight.py	b6c754bf500a9e384be4dc19fe024bca7d5efbc03dc764e588d6fd9291dc2a45
ontologylab/grounded_review_schema.py	cdc9ef8790d0f5ee01e4b57c214f4811d835b6fb04ec7f8457d109b9550a1771
ontologylab/grounded_review_store.py	c98f3a38cd8a3ec311b857fcb943acd8b173d684999001f9284dde6f9e09af5a
ontologylab/grounded_review_types.py	d64716d46155d66d42a958aa4b5cc6cdbeca06b34a302e985e5b6a8a0d4610ba
ontologylab/kgstore.py	0f37cc1d511917ff4b766c51301ec623ea02d539a1b7298bc62a0c3b1eb64013
ontologylab/main.py	50e32fc1a1cc6a3921a2c8b481790b4c727593b3067f483d62d370ee4a0c6d36
ontologylab/server/routes.py	d4905eb8b12bb820553fa1547473f345ed48dc2fba77de872f2691d907778ab9
ontologylab/server/schemas.py	a1993b8c25ec5781c6f6b92a4601728a19dc75a698eeb4cf780972032edaeea3
tests/test_grounded_review.py	8b990e2fecd84407680ce42aac9660fd4401f9e4c95b465df3777d5428222cbc
```

Staged-set proof before commit: 13/13 owned, 0 forbidden (no `.omo/`, `docs/`, live data, `uv.lock`, graphify, denylist, or unowned paths). Index empty after commit. Owned working tree clean vs HEAD.

## Residual `git status --short` (classified)

```
?? .gjc/                                               unrelated user/tooling
?? .sisyphus/                                          unrelated user/tooling
?? artifacts/                                          unrelated user artifacts
?? docs/CONANSSAM-PROMPT-2026-08-08.bak                 unrelated / not Task 5 product
?? docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md   unrelated planning
?? docs/OMO-INGESTION-WAVE-2.1-IMPLEMENTATION-HANDOFF-2026-08-20.md  unrelated planning
?? docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md  unrelated planning
?? docs/ONTOLOGYLAB-DETAILED-SMOKE-RESULT-2026-08-08 2.md  unrelated
?? docs/WAVE-2.1-DEEP-RESEARCH-REMEDIATION-GJC-2026-08-20.md  unrelated
?? graphify-out/                                       unrelated generated
?? ontologylab/graphify-out/                           unrelated generated
?? ontologylab/review_decision.py                      denylist (excluded)
?? ontologylab/review_decision_ids.py                  denylist (excluded)
?? ontologylab/review_decision_schema.py               denylist (excluded)
?? ontologylab/review_decision_store.py                denylist (excluded)
?? ontologylab/review_decision_types.py                denylist (excluded)
?? ontologylab/review_grounding.py                     denylist (excluded)
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
- `git rev-parse HEAD` pre-commit `7c159fd3efa24a5b9839e0ae32643e7f90560124`
- working-tree SHA-256 vs authorized freeze: 13/13 MATCH
- staged path set == owned set; forbidden set empty
- full staged diffs of the five tracked files inspected; every hunk is Task 5
- owned-path import scan: no denylist module imports
- `git log -1 --oneline` after commit → `0a3c7a2 feat(review): require append-only grounding decisions`
- committed-blob perimeter rehash `82ba0621f5e3a312973e9df4d0df412ae4c992d6ff9047a797b258efdab6835c`
- `git rev-parse origin/main` unchanged (`4ee5465b…`)
- denylist still unknown to git (`git ls-files --error-unmatch` failed for all six)

Not run (out of this commit scope):

- focused / affected / repair pytest (bytes did not drift from confirmed verifier freeze)
- full `.venv/bin/python -m pytest` suite
- any network / live Application Support / port 8799 action

## Recovery

Parent `7c159fd3efa24a5b9839e0ae32643e7f90560124` is untouched. Residual untracked files were never added. No force, push, or history rewrite. Reflog: `0a3c7a2 HEAD@{0}: commit: feat(review): require append-only grounding decisions`.
