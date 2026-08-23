# Task 3 product-commit boundary report

Date: 2026-08-23
Worker: omo senpi-task `st_01a02ee7`
Mode: COMMIT (product/test only). No push. No amend/rebase/reset/checkout/restore/stash.

## Verdict

`committed`

Exactly one atomic Task 3 product/test commit exists. Path list is verified. No unowned path was staged or committed. No push occurred.

## Ground truth (pre-commit)

| Fact | Value |
|---|---|
| Physical cwd | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Git top-level | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Origin | `origin` → `https://github.com/dltdnfrk/ontologylab.git` (fetch/push) |
| Branch | `main` |
| Upstream | `origin/main` |
| Pre-commit HEAD | `49ac5249fbfaecf0e18a00d08392166ea79250d5` |
| Pre-commit subject | `feat(extraction): bind runs and chunks to representations` |
| Ahead/behind vs `origin/main` | `0	44` before commit; `0	45` after. `origin/main` still `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| Staged diff initially | empty |
| Merge-base `origin/main` | `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| `origin/master` | missing (not a valid object) |

Dominant local subject style is conventional `type(scope): lowercase summary` (`feat`, `fix`, `test`, `docs`). Requested subject used verbatim.

## Verifier gate

Re-read:

- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-verifier.md` → `needs-fix` (isolated raw-path mutant not killed)
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-repair.md` → test-only isolated raw-path repair
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-repair-verifier.md` → `confirmed` (confidence `0.93`)

HEAD at verify/repair time: `49ac5249fbfaecf0e18a00d08392166ea79250d5` (unchanged; no commit). Repair is test-only; product SHA-256 values equal the pre-repair executor/verifier table.

Required current-byte hashes, recomputed from working-tree then from staged index then from committed `HEAD:` blobs; all MATCH. No focused smoke rerun: every owned file matched the repair-verifier table on current bytes. Task instruction: do not duplicate tests when hashes match.

| Path | SHA-256 |
|---|---|
| `ontologylab/selection_types.py` | `b06e489f58a45b30f77ad4325d71f7b9fcf5c8be34daf39cd5b6cfae3f90159a` |
| `ontologylab/selection_policy.py` | `0c4c7ccfeeabccd6f846c3a629ebe02e9f853b103d2be3ef037b1e31881e556f` |
| `ontologylab/selection_ids.py` | `242d3fb56eeac0c25c465505a7f1ecc7b5bc548ea75cd6715af9f6ad36f8fdfe` |
| `ontologylab/selection_schema.py` | `017795e17b2deb70b380ad1542a23cd0bc092e165a943537cc4564370a4cf7de` |
| `ontologylab/selection_store.py` | `60f12ee19fe58eaf0cdf27bf60892f4bbffe90d916b2e3ccd6951a6bd3cc47de` |
| `ontologylab/selection.py` | `702fc8431d53422108ca82f7ec7d917039c8a832e1bcc12d86c8ae5fc25e90c9` |
| `ontologylab/research_extract.py` | `d2da049dd2c822a8ea2d9c1208d2ffec4010f104869489175b5b2c4ad33a20c3` |
| `ontologylab/work_view.py` | `c771d04559f7387ae79fb654c5959fa4ccbff0975ae318d6c90ad8e4800044bf` |
| `ontologylab/server/jobs.py` | `6fd412136a097d6cc5bea3d0766cdd65061b3bda68ebdc49165603bef0e19023` |
| `ontologylab/ingestion_shadow.py` | `dfcd1d02c43c710e913fddb0c46afc5e7cc36b7dcc33b0e3e75de0fdc81a29fc` |
| `ontologylab/connectors/base.py` | `554e095301108e683c747447d98c86145dc3092a0a6d16642956eff3dbd81fdc` |
| `tests/test_preferred_selection.py` | `0296cf4622522c0f79884c7956b85717dfaf8d0f0bbda4ee17c33c6cd6801fd2` |
| `tests/test_research_selection.py` | `0ab337b2e73376ac08669d7af27fde5331defaf50f529289f4d9b77ace57541c` |
| `tests/test_research_ready_boundary.py` | `7f037cc32caaa8cf20bb65589bf08a41b51e024c6163f9e6297feb27cb4657c3` |

Companion freeze (Task 2, not restaged): `ontologylab/extraction_receipt_store.py` `42ad7c6be247587304a5ad6fd4ef29da5d199ce4f4f27f5d7c58d3084dc64f86` MATCH, working tree clean vs HEAD.

## Ownership derivation

Owned paths were taken from the current dirty tree intersected with Task 3 executor/verifier/repair evidence, not from the task sentence alone.

| Source | Owned product/test paths |
|---|---|
| Plan Task 3 | immutable `preferred-representation-v1` receipts; F9 tuple; research extracts selected ready Representation bytes; no direct path read; no historical recompute |
| Task-3 executor | `selection_types.py`, `selection_policy.py`, `selection_ids.py`, `selection_schema.py`, `selection_store.py`, `selection.py`, `research_extract.py`, `work_view.py` (`work_candidates`), `server/jobs.py`, `ingestion_shadow.py`, `connectors/base.py`, `tests/test_preferred_selection.py`, `tests/test_research_selection.py` |
| Task-3 verifier | same product/test set; isolated raw-path coverage missing |
| Task-3 repair + repair-verifier | adds `tests/test_research_ready_boundary.py` only; product hashes frozen |

Hunk attribution (no mixed unowned hunks):

- Tracked diffs inspected in full before staging.
  - `connectors/base.py`: additive `stage` / `content_kind` on `RawDocument` only.
  - `ingestion_shadow.py`: pass through explicit stage/kind, keep default unknown/fulltext-or-metadata.
  - `server/jobs.py`: research job routes through `extract_research_documents`; `SelectionRefused` summary; capture pre-collapse `fetched_docs`. `_extract_async` still `run_extraction`.
  - `work_view.py`: new `work_candidates` projection; `work_snapshot` reuses it and still calls `preferred_representation` (D07 stage-first display).
- Untracked owned files are new Task 3 selection/receipt/research modules and the three direct/HTTP/mutation tests, including the isolated raw-path tamper test.
- No unexpected module: no Citation/review/migration/pack files; no Task 2 receipt modules restaged; staged keyword scan for `citation_receipt` / `CitationReceipt` / `review_decision` / `approve_with_grounding` / `pack_completeness` / `v2_migration` / `migration_ledger` / `ReviewDecision` was empty.

Excluded from this commit (present in worktree, never staged):

- `.omo/plans`, drafts, Boulder, start-work ledger/reports (this report included)
- Step 6 evidence
- canonical docs under `docs/`
- Task 2 committed files (`extraction_receipt_*`, `tests/test_extraction_receipts.py`)
- Task 4+ Citation/review/migration/pack files (none dirty)
- unrelated/untracked user files (`.sisyphus/`, `artifacts/`, `graphify-out/`, `uv.lock`, planning docs)

## Commit

| Field | Value |
|---|---|
| Subject | `feat(extraction): receipt preferred representation selection` |
| Commit | `1afd0f85b038475a3b0a43f477febd1b25bfce01` |
| Tree | `d60bc0ebd5961971f2809461cca842a22608d30a` |
| Parent | `49ac5249fbfaecf0e18a00d08392166ea79250d5` |
| `git log -1 --oneline` | `1afd0f8 feat(extraction): receipt preferred representation selection` |
| Files | 14 (`1604` insertions, `63` deletions) |
| Perimeter hash | `0021ce5daae3e4031e05a6ffe1c7e92e35cf1a29e55bfedda20660519a122084` |
| Perimeter recipe | SHA-256 of sorted `path<TAB>file-sha256\n` over the 14 committed paths |
| Push | none. `origin/main` unchanged. Branch now `[ahead 45]` |

## Committed path list

```
M ontologylab/connectors/base.py
M ontologylab/ingestion_shadow.py
A ontologylab/research_extract.py
A ontologylab/selection.py
A ontologylab/selection_ids.py
A ontologylab/selection_policy.py
A ontologylab/selection_schema.py
A ontologylab/selection_store.py
A ontologylab/selection_types.py
M ontologylab/server/jobs.py
M ontologylab/work_view.py
A tests/test_preferred_selection.py
A tests/test_research_ready_boundary.py
A tests/test_research_selection.py
```

Per-file SHA-256 (committed `HEAD:` blobs; same as pre-stage working tree and repair-verifier table):

```
ontologylab/connectors/base.py	554e095301108e683c747447d98c86145dc3092a0a6d16642956eff3dbd81fdc
ontologylab/ingestion_shadow.py	dfcd1d02c43c710e913fddb0c46afc5e7cc36b7dcc33b0e3e75de0fdc81a29fc
ontologylab/research_extract.py	d2da049dd2c822a8ea2d9c1208d2ffec4010f104869489175b5b2c4ad33a20c3
ontologylab/selection.py	702fc8431d53422108ca82f7ec7d917039c8a832e1bcc12d86c8ae5fc25e90c9
ontologylab/selection_ids.py	242d3fb56eeac0c25c465505a7f1ecc7b5bc548ea75cd6715af9f6ad36f8fdfe
ontologylab/selection_policy.py	0c4c7ccfeeabccd6f846c3a629ebe02e9f853b103d2be3ef037b1e31881e556f
ontologylab/selection_schema.py	017795e17b2deb70b380ad1542a23cd0bc092e165a943537cc4564370a4cf7de
ontologylab/selection_store.py	60f12ee19fe58eaf0cdf27bf60892f4bbffe90d916b2e3ccd6951a6bd3cc47de
ontologylab/selection_types.py	b06e489f58a45b30f77ad4325d71f7b9fcf5c8be34daf39cd5b6cfae3f90159a
ontologylab/server/jobs.py	6fd412136a097d6cc5bea3d0766cdd65061b3bda68ebdc49165603bef0e19023
ontologylab/work_view.py	c771d04559f7387ae79fb654c5959fa4ccbff0975ae318d6c90ad8e4800044bf
tests/test_preferred_selection.py	0296cf4622522c0f79884c7956b85717dfaf8d0f0bbda4ee17c33c6cd6801fd2
tests/test_research_ready_boundary.py	7f037cc32caaa8cf20bb65589bf08a41b51e024c6163f9e6297feb27cb4657c3
tests/test_research_selection.py	0ab337b2e73376ac08669d7af27fde5331defaf50f529289f4d9b77ace57541c
```

Staged-set proof before commit: 14/14 owned, 0 forbidden (no `.omo/`, `docs/`, live data, `uv.lock`, graphify, or unowned paths). Index empty after commit. Owned working tree clean vs HEAD.

## Residual `git status --short` (classified)

```
?? .sisyphus/                                          unrelated user/tooling
?? artifacts/                                          unrelated user artifacts
?? docs/CONANSSAM-PROMPT-2026-08-08.bak                 unrelated / not Task 3 product
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
- `git rev-parse HEAD` pre-commit `49ac5249fbfaecf0e18a00d08392166ea79250d5`
- working-tree SHA-256 vs repair-verifier table: 14/14 MATCH plus untouched Task 2 `extraction_receipt_store.py`
- staged path set == owned set; forbidden set empty
- full staged diffs of the four tracked files inspected; every hunk is Task 3
- staged blob keyword scan: no Task 4+ Citation/review/migration/pack symbols
- `git log -1 --oneline` after commit → `1afd0f8 feat(extraction): receipt preferred representation selection`
- committed-blob perimeter rehash matches pre-stage `0021ce5d…`
- `git rev-parse origin/main` unchanged (`4ee5465b…`)

Not run (out of this commit scope):

- focused smoke (bytes did not drift from confirmed repair-verifier)
- full `.venv/bin/python -m pytest` suite
- any network / live Application Support / port 8799 action

## Recovery

Parent `49ac5249fbfaecf0e18a00d08392166ea79250d5` is untouched. Residual untracked files were never added. No force, push, or history rewrite. Reflog: `1afd0f8 HEAD@{0}: commit: feat(extraction): receipt preferred representation selection`.
