# AdversarialVerify — wave21 steps 5–10 / task-3 repair

Verifier: omo senpi-task `st_01a02ee3` (fresh independent re-verify after `st_01a02ecf` needs-fix + `st_01a02eb5` repair)
Date: 2026-08-23
HEAD: `49ac5249fbfaecf0e18a00d08392166ea79250d5` (unchanged; no commit/push)
Scope: isolated direct raw-path bypass coverage for Task 3 only.
Constraint: no product/test/plan/Boulder/ledger/canonical-doc edits left behind; no Application Support read/write; no external network; no 8799 / PID 55560 mutation; no Task 4 Citation/review/migration/pack files.

Prior executor/verifier/repair reports treated as claims. Every hash, mutant outcome, suite count, and QA value below was re-measured on current bytes.

## Verdict

`confirmed`

Confidence: `0.93`

The sole needs-fix from `task-3-verifier.md` is now independently killed: replacing **only** `_bind_run_receipt`'s `read_ready_text` with `Path(raw_text_path).read_text()` fails `test_research_refuses_when_selected_ready_bytes_are_tampered` with `FileNotFoundError` on the contained relative store path. Current product SHA-256 values equal the pre-repair executor/verifier table (repair is test-only). After restore, SHA-256 identity holds and the same test is GREEN. Focused 34 + affected 102 passed once. Disposable library QA reproduced typed `hash_mismatch`, zero run/chunk/node rows, no leak token. PID 55560 / 8799 unchanged. Prior F9 / v1-v2 immutability / C-024 Task 2 bind / typed no-ready / no-Citation contracts still hold on current bytes.

`confirmed` is not a re-rating of the original grouped raw-path mutant. It is a toggle proof of the isolated Path reader against the new fixture.

## What the repair claimed vs what this pass measured

| Claim (repair) | Independent measurement |
|---|---|
| Product bytes unchanged vs pre-repair | All 11 Task 3 product hashes + `extraction_receipt_store.py` match the verifier pre-mutation table |
| New test only | `tests/test_research_ready_boundary.py` is the only new Task 3 file; `test_preferred_selection.py` / `test_research_selection.py` hashes unchanged |
| Isolated Path mutant dies | RED: `FileNotFoundError: 'documents/rep-4f0694ec74cc/raw.txt'` EXIT:1 |
| Restore identity + GREEN | `research_extract.py` SHA-256 `d2da049d…` BYTE-EQUAL; tamper test `.` EXIT:0 |
| Focused 34 / affected 102 | 34 dots EXIT:0; 102 dots EXIT:0; each command once |

## Product freeze (pre-repair hashes still current)

| File | SHA-256 (this pass, post-restore) | vs pre-repair |
|---|---|---|
| `selection_types.py` | `b06e489f58a45b30f77ad4325d71f7b9fcf5c8be34daf39cd5b6cfae3f90159a` | match |
| `selection_policy.py` | `0c4c7ccfeeabccd6f846c3a629ebe02e9f853b103d2be3ef037b1e31881e556f` | match |
| `selection_ids.py` | `242d3fb56eeac0c25c465505a7f1ecc7b5bc548ea75cd6715af9f6ad36f8fdfe` | match |
| `selection_schema.py` | `017795e17b2deb70b380ad1542a23cd0bc092e165a943537cc4564370a4cf7de` | match |
| `selection_store.py` | `60f12ee19fe58eaf0cdf27bf60892f4bbffe90d916b2e3ccd6951a6bd3cc47de` | match |
| `selection.py` | `702fc8431d53422108ca82f7ec7d917039c8a832e1bcc12d86c8ae5fc25e90c9` | match |
| `research_extract.py` | `d2da049dd2c822a8ea2d9c1208d2ffec4010f104869489175b5b2c4ad33a20c3` | match |
| `work_view.py` | `c771d04559f7387ae79fb654c5959fa4ccbff0975ae318d6c90ad8e4800044bf` | match |
| `server/jobs.py` | `6fd412136a097d6cc5bea3d0766cdd65061b3bda68ebdc49165603bef0e19023` | match |
| `ingestion_shadow.py` | `dfcd1d02c43c710e913fddb0c46afc5e7cc36b7dcc33b0e3e75de0fdc81a29fc` | match |
| `connectors/base.py` | `554e095301108e683c747447d98c86145dc3092a0a6d16642956eff3dbd81fdc` | match |
| `extraction_receipt_store.py` | `42ad7c6be247587304a5ad6fd4ef29da5d199ce4f4f27f5d7c58d3084dc64f86` | match (untouched) |
| `tests/test_preferred_selection.py` | `0296cf4622522c0f79884c7956b85717dfaf8d0f0bbda4ee17c33c6cd6801fd2` | match |
| `tests/test_research_selection.py` | `0ab337b2e73376ac08669d7af27fde5331defaf50f529289f4d9b77ace57541c` | match |
| `tests/test_research_ready_boundary.py` | `7f037cc32caaa8cf20bb65589bf08a41b51e024c6163f9e6297feb27cb4657c3` | match repair (new) |

Pure LOC (this pass): types 98, policy 182, ids 103, schema 35, store 116, facade 42, research_extract 218 (warning band), work_view 163, jobs 762, shadow 448, base 134, tests 241 / 223 / 48.

## Isolated mutant (the only decision this repair exists to cover)

Current reader (`ontologylab/research_extract.py:198-201`):

```198:201:ontologylab/research_extract.py
    text = read_ready_text(
        store.conn, store_root_from_conn(store.conn), representation_id,
    )
```

GREEN on current bytes (before mutant):

```
.venv/bin/python -m pytest \
  tests/test_research_ready_boundary.py::test_research_refuses_when_selected_ready_bytes_are_tampered -q --tb=short
.
EXIT:0
```

Temporary isolated mutant — **only** `_bind_run_receipt` ready reader. Ranking, `not_ready`, fallback, and `put_extraction_receipts` untouched. Local `from pathlib import Path` added so `Path` could execute.

```
    raw_text_path = store.conn.execute(
        "SELECT raw_text_path FROM documents WHERE id = ?",
        (representation_id,),
    ).fetchone()["raw_text_path"]
    from pathlib import Path
    text = Path(raw_text_path).read_text()
```

Mutant SHA-256: `5085ff124e3cc62a73fe3fa3fedbe77731287f36ca1c0cee22f1d884132b3ec6` (≠ product).

RED (verbatim):

```
.venv/bin/python -m pytest \
  tests/test_research_ready_boundary.py::test_research_refuses_when_selected_ready_bytes_are_tampered -q --tb=short
F
ontologylab/research_extract.py:203: in _bind_run_receipt
    text = Path(raw_text_path).read_text()
E   FileNotFoundError: [Errno 2] No such file or directory: 'documents/rep-4f0694ec74cc/raw.txt'
FAILED tests/test_research_ready_boundary.py::test_research_refuses_when_selected_ready_bytes_are_tampered
EXIT:1
```

This distinguishes the direct read: the consumer never called `read_ready_text`, so it never produced typed `hash_mismatch`. It opened the relative `documents/…/raw.txt` from CWD. CWD had no `documents/` tree (`NO_CWD_DOCUMENTS` before and after).

Restore: `cp` of the pre-mutant byte snapshot over `research_extract.py`.

```
BYTES_EQUAL True LEN 7980
SHA d2da049dd2c822a8ea2d9c1208d2ffec4010f104869489175b5b2c4ad33a20c3
NO_PATH_MUTANT
. EXIT:0
```

`rg` after restore: `text = read_ready_text(` at line 198; no `Path(raw_text_path)`.

## Prior contracts re-checked (code + this pass's runtime)

Plan Task 3 (`.omo/plans/wave21-ingestion-steps5-10.md` todo 3): immutable `preferred-representation-v1` receipts; F9 tuple `ready > usable full text > grade > source > stage > length > lexical hash`; research extracts selected ready Representation bytes; stage may never beat usable full text; no direct path read; no historical recompute.

| Contract | Evidence this pass |
|---|---|
| Exact F9 V1 tuple | `selection_policy.py:155-164` returns `(ready_rank, usable_full_text_rank, grade_rank, source_rank, stage_rank, -byte_length, content_hash)`. V1 then requires `usable_full_text_rank == 0` (`:206-209`). `test_c024_selection_receipt_selects_pmc_and_binds_inventory` + `test_selection_tie_is_stable_under_insertion_order` GREEN in focused 34. |
| Immutable v1 under explicit v2 | `get_once` / `_existing` read stored columns only; `select_winner` is imported for `put_once` only. `test_policy_v2_does_not_recompute_historical_v1_receipt` GREEN. |
| C-024 PMC + Task 2 run bind | `test_c024_research_extracts_only_pmc_and_binds_task2_run` + HTTP `test_research_http_selects_pmc_from_publisher_and_pmc_fake` GREEN. Display `work_snapshot` still uses `preferred_representation` (`work_view.py:149`); `test_baseline_work_view_prefers_published_abstract_on_c024` GREEN (D07 split). |
| Typed no-ready | `test_no_ready_full_text_is_typed_unavailable_without_fallback` GREEN: `SelectionRefused.NO_ELIGIBLE_READY_FULL_TEXT`, empty nodes. |
| No Citation scope | `rg citation` on all Task 3 selection/research modules + three Task 3 tests: `NONE`. No citation modules added. HTTP/job research still `extract_research_documents` (`jobs.py:957`); `_extract_async` still `run_extraction`. |
| Ready-byte authority | `read_ready_text` (`file_lifecycle.py:472-491`) joins `contained_documents_path`, rechecks `content_hash`, raises `FileIntegrityError("hash_mismatch")`. New tamper test + QA both observed that reason. |
| Append-only receipts | UPDATE/DELETE triggers abort with `preferred_selection_receipts is append-only` (`selection_schema.py:24-33`). |

## Reproduction — tests (each command once; no retry-to-pass)

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Interpreter: `.venv/bin/python` (CPython 3.12.12)

```
.venv/bin/python -m pytest tests/test_preferred_selection.py \
  tests/test_research_selection.py tests/test_research_ready_boundary.py \
  tests/test_document_view.py tests/test_extraction_receipts.py -q
..................................
FOCUSED_EXIT:0
# 34 passed (8+4+1+5+16)
```

```
.venv/bin/python -m pytest \
  tests/test_research_run.py tests/test_research_source_surface.py \
  tests/test_extractor.py tests/test_run_extraction.py \
  tests/test_work_view.py tests/test_ingestion_service.py \
  tests/test_file_lifecycle.py tests/test_v2_truth_table.py -q
........................................................................ [ 70%]
..............................                                           [100%]
AFFECTED_EXIT:0
# 102 passed
```

```
/Users/hyunjun/.local/bin/basedpyright \
  ontologylab/selection_types.py ontologylab/selection_policy.py \
  ontologylab/selection_ids.py ontologylab/selection_schema.py \
  ontologylab/selection_store.py ontologylab/selection.py \
  ontologylab/research_extract.py ontologylab/work_view.py \
  ontologylab/server/jobs.py ontologylab/ingestion_shadow.py \
  ontologylab/connectors/base.py \
  tests/test_preferred_selection.py tests/test_research_selection.py \
  tests/test_research_ready_boundary.py
# jobs.py:325:28 - error: Argument of type "Any | None" cannot be assigned
#   to parameter "engine" of type "str" (reportArgumentType)
# 1 error, 0 warnings, 0 notes
# PYRIGHT_EXIT:1
```

`jobs.py:325` `engine=row.get("engine")` is `git blame` `c07727e3` (2026-08-05). Not introduced by Task 3 or this repair. No diagnostics on Task 3-new modules, `work_view.py`, `ingestion_shadow.py`, `connectors/base.py`, or the three Task 3 tests.

No full suite. No retry-to-pass. No sleeps in Task 3 tests (`rg time.sleep|asyncio.sleep` → `NO_SLEEP`). HTTP test joins the job thread.

## Manual QA

Disposable driver `/private/tmp/ontologylab-wave21-task3-repair-verify.qa.py` against `/private/tmp/ontologylab-wave21-task3-repair-verify.qa` (deleted after). Direct public library only (`plant_c024` + `put_selection_receipt` + `extract_research_documents`). No HTTP, no network, no 8799. No sleeps.

First invocation without `PYTHONPATH` failed at import (`ModuleNotFoundError: tests`) before `main()`; no store created. Successful invocation:

```
cd /Users/hyunjun/Documents/MUNI/ontologylab
PYTHONPATH=. .venv/bin/python /private/tmp/ontologylab-wave21-task3-repair-verify.qa.py
```

Observed JSON (verbatim fields):

```
selected_is_pmc=true
policy_version=preferred-representation-v1
raised=true
err_type=FileIntegrityError
reason=hash_mismatch
leaked=false
names=[]
run_count=0
chunk_count=0
node_count=0
empty_work=missing_binding
unknown_work=unknown_work
QA_EXIT:0
```

Selected id `rep-1d9b7687a4ee` == planted PMC. Tamper path `documents/rep-1d9b7687a4ee/raw.txt`. Sentinel `TamperedRawPathLeak` did not appear in node names.

## PID 55560 / 8799 (read-only)

| When | PID 55560 | 127.0.0.1:8799 |
|---|---|---|
| Phase 0 | ELAPSED `17-08:59:54` `python -m ontologylab.serve --host 127.0.0.1 --port 8799` + Application Support data/packs | LISTEN on 55560 |
| After QA | ELAPSED `17-09:01:33` same command | LISTEN on 55560 |
| Cleanup | ELAPSED `17-09:02:34` same command | LISTEN on 55560; no other listener |

Same process, clock only. This verifier did not bind, kill, or retarget 8799 and did not read/write Application Support.

## Adversarial classes

| Class | Observable |
|---|---|
| malformed_input | QA: empty work → `missing_binding`; unknown work → `unknown_work`. Matches `put_once` guards. |
| stale_state | `put_once` returns `_existing` on same receipt id; `get_once` does not call `select_winner`. `test_policy_v2_does_not_recompute_historical_v1_receipt` GREEN after v2 insert. |
| dirty_worktree | Unrelated untracked `docs/`, `.sisyphus/`, `graphify-out/`, `uv.lock`, `artifacts/` left untouched. This pass wrote only this report. Temporary mutant restored to byte identity. |
| misleading_success_output | Isolated Path mutant is no longer a silent green: FileNotFoundError vs expected `FileIntegrityError("hash_mismatch")`. basedpyright EXIT:1 is the pre-existing `jobs.py:325` error, not a Task 3 type regression. |
| flaky_tests | No sleeps in Task 3 tests; HTTP waits on thread join; receipt IDs / hashes are SHA-256; tamper test does not poll. |
| repeated_interruptions | Affected 102 includes `tests/test_research_run.py`; EXIT:0. Research cancel path not edited by the repair. |
| un-restored mutation | Post-restore SHA-256 == pre-repair `d2da049d…`; `NO_PATH_MUTANT`; no CWD `documents/` leftover. |

## Cleanup

- QA root and driver removed (`QA_GONE`, `DRIVER_GONE`)
- Pre-mutant snapshot `/private/tmp/research_extract.py.pre-mutant` removed
- Session `.debug-journal.md` removed
- `research_extract.py` hash identical to Task 3 GREEN product
- No product/test/plan/Boulder/ledger edits from this verifier
- No commit / push

Not this session (left in place; prior verifier claimed cleanup):

- `/private/tmp/ontologylab-wave21-task3-verify.qa.py`
- `/private/tmp/ontologylab-wave21-task3-verify.journal/`
- `/private/tmp/ontologylab-wave21-task3-verify.mutants/`

These do not affect product bytes or this verdict.

## Residuals / not needs-fix

- `research_extract.py` remains 218 pure LOC (warning band). Repair did not add product lines.
- Production connectors still leave `stage` / `content_kind` empty; C-024 HTTP/QA fakes set them. Unchanged.
- Display preferred projection remains stage-first. Task 4 must not treat `work_snapshot.preferred_representation_id` as extraction authority.
- Citation receipts are still Task 4.
- basedpyright on `jobs.py:325` is pre-existing (`c07727e3`).

## Scope

Read: plan Task 3, `task-3-executor.md`, `task-3-verifier.md`, `task-3-repair.md`, current Task 3 product/tests, `research_extract.py`, new boundary test, `file_lifecycle.read_ready_text`, jobs research call site.

Did not edit plan, Boulder, start-work ledger, Task 4+ files, live data, or 8799. Did not run the full suite.

This report is the only write from `st_01a02ee3`.
