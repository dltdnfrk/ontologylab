# Task 1 product-commit boundary report

Date: 2026-08-23
Worker: omo senpi-task `st_01a02e4d`
Mode: COMMIT (product/test only). No push. No amend/rebase/reset/checkout/restore/stash.

## Verdict

`committed`

Exactly one atomic Step 6 product/test commit exists. Path list is verified. No unowned path was staged or committed. No push occurred.

## Ground truth (pre-commit)

| Fact | Value |
|---|---|
| Physical cwd | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Git top-level | `/Users/hyunjun/Documents/MUNI/ontologylab` |
| Origin | `origin` → `https://github.com/dltdnfrk/ontologylab.git` (fetch/push) |
| Branch | `main` |
| Upstream | `origin/main` |
| Pre-commit HEAD | `eab47a615cc5f309c05a48875c6e6877096783dd` |
| Pre-commit subject | `feat(migration): resumable migration core, backfill/collision executor, F6 rehearsal` |
| Ahead/behind vs `origin/main` | `0	41` before commit; `0	42` after. `origin/main` still `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| Staged diff initially | empty |
| Merge-base `origin/main` | `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| `origin/master` | missing (not a valid object) |

Dominant local subject style is conventional `type(scope): lowercase summary` (`feat`, `fix`, `test`, `docs`). Preferred integrated subject used as requested.

## Verifier gate

Re-read `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-1-verifier.md`.

- Verdict: `confirmed`
- Repair hashes required by verifier, still present on committed bytes:
  - `ontologylab/kgstore.py` `2226e9bf6b67952ccea38202203478a96fd5571bbb27b75045d53b8961eca22f`
  - `tests/test_provenance_api.py` `8eb666e387c227a9b7814c3bc3d1e73d84ae55e606fd5f30f3f5408530cf2684`
  - `tests/test_document_view.py` `7a29831a54656af1df31bc707f6eb5721e792dcb8358e2b74351fcb2cd2f6911`

No focused smoke rerun: those three files and the G007 production files (except `kgstore.py`) had not drifted. `kgstore.py` G007 hash `ae0422d7…` is the pre-repair bundle; the committed hash is the independently confirmed repair.

## Ownership derivation

Owned paths were taken from current dirty tree intersected with Step 6 evidence, not from the task sentence alone.

| Source | Owned product/test paths |
|---|---|
| G001 regression | `ontologylab/ingestion_service.py`, `tests/test_ingestion_service.py`, `ontologylab/authority_repo.py` |
| G002 regression | `ontologylab/ingestion_surfaces.py`, `ontologylab/server/ingest_routes.py`, `ontologylab/server/app.py`, `ontologylab/main.py`, `tests/test_ingestion_surfaces.py` |
| G004 regression | `tests/test_ingest_concurrency.py`, `tests/wave21/ingest_concurrency.py`, `ontologylab/ingestion_service.py`, `ontologylab/authority_repo.py` |
| G006 regression | `ontologylab/provenance_outbox.py`, `ontologylab/ingestion_service.py`, `ontologylab/server/ingest_routes.py`, `ontologylab/main.py`, `tests/test_provenance_outbox.py`, `tests/test_provenance.py` |
| G008 regression | `ontologylab/file_lifecycle.py`, `ontologylab/ingestion_service.py`, `ontologylab/kgstore.py`, `ontologylab/work_view.py`, `ontologylab/ingestion_surfaces.py`, `ontologylab/server/ingest_routes.py`, `ontologylab/main.py`, `tests/test_file_lifecycle.py`, `tests/test_document_view.py` |
| G009 regression | `ontologylab/ingestion_shadow.py`, `ontologylab/ingestion.py`, `ontologylab/server/routes.py`, `ontologylab/main.py`, `ontologylab/ingestion_service.py`, `ontologylab/ingestion_surfaces.py`, `ontologylab/authority_repo.py`, `tests/test_ingestion_shadow_entrypoints.py` |
| G007 security product table | all nine hashed production modules above; current hashes MATCH except `kgstore.py` (confirmed repair) |
| Task-1 executor/verifier | `ontologylab/kgstore.py` `document_raw_text` repair + `tests/test_provenance_api.py` focused test |

Hunk attribution (no mixed unowned hunks):

- Tracked diffs inspected in full before staging. Every hunk is Step 6 service/lifecycle/outbox/shadow/surface wiring or the confirmed legacy-read repair.
- Untracked owned files are new Step 6 modules/tests whose headers name 6A/6B/6C/6D/F2/F4/F5.

## Commit

| Field | Value |
|---|---|
| Subject | `feat(ingestion): complete transactional v2 shadow service` |
| Commit | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` |
| Tree | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` |
| Parent | `eab47a615cc5f309c05a48875c6e6877096783dd` |
| `git log -1 --oneline` | `e3bca45 feat(ingestion): complete transactional v2 shadow service` |
| Files | 23 (`5556` insertions, `102` deletions) |
| Perimeter hash | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` |
| Perimeter recipe | SHA-256 of sorted `path<TAB>file-sha256\n` over the 23 committed paths |
| Push | none. `origin/main` unchanged. Branch now `[ahead 42]` |

Subject choice: history and G006–G009 are the complete Step 6 increment, not a repair-only close. Plan Task 1 subject `fix(ingestion): preserve safe legacy provenance reads` would understate the landed tree. Preferred integrated subject used.

## Committed path list

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

Per-file SHA-256 (committed `HEAD:` blobs; same as pre-stage working tree):

```
ontologylab/authority_repo.py	85315f3bc47f7b8845527f78d3707849c5012c28f3ab18ae730c9b68e049a4b1
ontologylab/file_lifecycle.py	f8085f9030d8b5c9fa05635a4ae7504ad7e63e58c9c6b4b7999f24b7201dbd20
ontologylab/ingestion.py	869c1f8856866afcb2ce3a16ab7d66136137d2df9a6c92c87ba850a7bc2aec23
ontologylab/ingestion_service.py	058b28de163b96c8164a35ac7afd76256b0b4f3495915bc21111660ef3237241
ontologylab/ingestion_shadow.py	4910bf10204194323896be63b4233dc3469d0fd92a98fe0df284ea73aa024002
ontologylab/ingestion_surfaces.py	882631cc44c7aedf2459cf73c6b926830ec8b683b94777fcb95c69bb97d10fdf
ontologylab/kgstore.py	2226e9bf6b67952ccea38202203478a96fd5571bbb27b75045d53b8961eca22f
ontologylab/main.py	0453beaf98113c7371d2121e5b66ada3aa2b9116c95de61979ce8f126eb0b837
ontologylab/provenance_outbox.py	b642f41a20bf5254e3c556605797cbeb28a1f5a7e16cf18c92ea62a2ee06fdb7
ontologylab/server/app.py	cb3df6c0a8c2d4789fb7287035f9b5b38f2c8c41fb2c1edb19014d6a212db57a
ontologylab/server/ingest_routes.py	7cea959f455c4f2c7bd000eb5869c85590905bc69cb553ce77d372e3b4cfd048
ontologylab/server/routes.py	e7528af60efb5bf9f58165022de5ee995ff8c2cb817c27336a389ce7ad68d0b4
ontologylab/work_view.py	3314802674bab3819468912c00961b163b3858f01c59bb932abaed2263bad6e0
tests/test_document_view.py	7a29831a54656af1df31bc707f6eb5721e792dcb8358e2b74351fcb2cd2f6911
tests/test_file_lifecycle.py	84549f4d59ca55483a5010553a8f1e4d0642ef14e0e37960899aebdfca891cae
tests/test_ingest_concurrency.py	a04e2b09352a1b89ae22fdd102bb52bc2cc66e517d7b1d8bfd74d66a596e2667
tests/test_ingestion_service.py	04f8e0f5cb78df29f3250ddcf1e0d81d6815eff296edd182da27725addf0d902
tests/test_ingestion_shadow_entrypoints.py	40b0db051e8b184fe405186ea68a8a312dd7ebc57255ec64cebcb50fb1642a5d
tests/test_ingestion_surfaces.py	0b8005562af4081abf4d5f65dd8db76685b37ded0a99444b1bc55a60354f602b
tests/test_provenance.py	0b65f4e48e37eaa589970419f4a306f5a9770322676839d5b1aaa4fa3dd3ee60
tests/test_provenance_api.py	8eb666e387c227a9b7814c3bc3d1e73d84ae55e606fd5f30f3f5408530cf2684
tests/test_provenance_outbox.py	a824be4d7bdd3ed0398b14d1e92d571b20074aba30912e7dc2f30c7b99acd741
tests/wave21/ingest_concurrency.py	e81477fd5a26e685f2d8be9af12920d17c134471af8b1d90ae47502ea08d8c96
```

Staged-set proof before commit: 23/23 owned, 0 forbidden (no `.omo/`, `docs/`, live data, `uv.lock`, graphify, or unowned paths). Index empty after commit. Owned working tree clean vs HEAD.

## Residual `git status --short` (classified)

```
?? .sisyphus/                                          unrelated user/tooling
?? artifacts/                                          unrelated user artifacts
?? docs/CONANSSAM-PROMPT-2026-08-08.bak                 unrelated / not Step 6 product
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
- `.omo/ulw-loop/wave21-step6-ingestion-service-20260821/`
- `.omo/evidence/ulw/wave21-step6-ingestion-service-20260821/`
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/` (this report)

## Verification commands

Passed:

- `git status --short` / `git diff --stat` / `git diff --staged --stat` (empty before commit)
- `git branch --show-current` → `main`
- `git rev-parse --abbrev-ref @{upstream}` → `origin/main`
- `git log -1 --oneline` after commit
- committed-blob perimeter rehash matches pre-stage `abe543be…`
- `git rev-parse origin/main` unchanged (`4ee5465b…`)

Not run (out of this commit scope):

- full `.venv/bin/python -m pytest` suite
- any network / live Application Support / port 8799 action

## Recovery

Parent `eab47a615cc5f309c05a48875c6e6877096783dd` is untouched. Residual untracked files were never added. No force, push, or history rewrite.
