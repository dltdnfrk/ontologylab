# DoneClaim — wave21 steps 5–10 / task-2

Executor: omo senpi-task `st_01a02e93`
Date: 2026-08-23
HEAD: `63e326f27c60b81f8a3e3daaf27518e82564da5c` (unchanged; no commit)
Constraint: did not touch live Application Support data, network, port 8799, or PID 55560.

## Verdict

Additive Representation-scoped extraction run and chunk receipts are implemented and evidenced. Same bytes on two Works/Representations mint distinct deterministic receipts. Same Representation+policy/config retry converges. Invalid range/hash/profile and conflicting retry are typed refusals with zero partial rows. Legacy `ExtractionState.plan` claim/retry/success/failure/interrupt behavior is unchanged. Caller-owned SAVEPOINT only on the new API.

## Contract implemented

Each new run receipt binds immutable `representation_id`, exact document content hash, `policy_identity`, `config_identity`, and a deterministic `receipt_id`. Each chunk receipt binds start/end document offsets, `document-utf8-v1` coordinate profile, chunk text hash, plan receipt, and parent run. Content hash is an integrity assertion, not identity.

New tables `extraction_run_receipts` / `extraction_chunk_receipts` are additive and append-only. Legacy `extraction_runs` / `extraction_chunks` and `plan()` stay in place.

## Changed files (this task)

| Path | Role |
| --- | --- |
| `ontologylab/extraction_state.py` | `ensure_schema` hook + public re-exports (`+10`) |
| `ontologylab/extraction_receipts.py` | Public `put_extraction_receipts` SAVEPOINT API |
| `ontologylab/extraction_receipt_types.py` | Typed receipts and refusal codes |
| `ontologylab/extraction_receipt_ids.py` | Deterministic run/chunk/plan receipt IDs |
| `ontologylab/extraction_receipt_schema.py` | Additive tables + no-update/delete triggers |
| `ontologylab/extraction_receipt_store.py` | Parse/persist inside caller transaction |
| `tests/test_extraction_receipts.py` | Baseline + contract tests |

Did not edit `extractor.py`, selection/preferred/work_view, citation/review/migration/pack, canonical docs, `.omo/plans/`, Boulder, start-work ledger, or Step 8+ files. Did not commit.

Pure LOC after split: receipts 38, types 67, ids 86, schema 68, store 225. `extraction_state.py` remains a pre-existing 384-LOC lifecycle module; this task added only the hook/re-exports.

## Baseline (production unchanged)

```
.venv/bin/python -m pytest tests/test_extraction_receipts.py -q
......
EXIT:0
```

Pinned current claim/succeed/fail/interrupt and caller transaction ownership:

- `plan`/`ensure_schema` issue connection-wide commit; caller `ROLLBACK` cannot undo a planned run
- `failed()` rolls back the caller transaction
- interrupt via owner-lock release + `recover_running_once` resumes the same run

## RED

Same-hash two-Representation identity against current `plan()` (disposable v2 layout):

```
tests/test_extraction_receipts.py::test_legacy_plan_reuses_one_run_for_same_hash_two_representations
AssertionError: assert '61c6152aba7d41b69c09b3ebd2765c3a' != '61c6152aba7d41b69c09b3ebd2765c3a'
EXIT:1
```

Contract suite before implementation (6 baseline still green):

```
......FFFFFFFFFF
EXIT:1
```

Named reasons:

- missing run Representation/policy/config binding: `assert {receipt_id, representation_id, ...} <= set()`
- missing API: `ImportError: cannot import name 'put_extraction_receipts' from 'ontologylab.extraction_state'`
- missing chunk end/profile/text hash/plan types: `ImportError: cannot import name 'ChunkSpan'`
- conflicting retry / invalid input: `ImportError: cannot import name 'ExtractionReceiptRefusalCode'`

## GREEN

```
.venv/bin/python -m pytest tests/test_extraction_receipts.py -q
................
EXIT:0
```

Root cause of first GREEN miss: `sqlite3.Connection.executescript` implicit `COMMIT` dropped `SAVEPOINT extraction_receipts_v1`. Schema install now uses per-statement `execute`.

## Mutation (kill then byte-identical restore)

Pre/post SHA-256 (unchanged after restore):

| File | SHA-256 |
| --- | --- |
| `extraction_receipt_ids.py` | `c8c0fd4b431bfaa5ae9687fa869e0d8cffe5338557a625dc461ac110c6d9daae` |
| `extraction_receipt_store.py` | `42ad7c6be247587304a5ad6fd4ef29da5d199ce4f4f27f5d7c58d3084dc64f86` |

| Mutant | Change | Behavioral failure | Restored |
| --- | --- | --- | --- |
| drop representation ID | omit `representation_id` from plan+run receipt digests | `UNIQUE constraint failed: extraction_run_receipts.receipt_id` on two same-hash Representations | yes, hash match |
| content-hash lookup | `WHERE document_content_hash = ?` instead of `representation_id` | second Representation refused as `conflict` | yes, hash match |
| omit chunk end/profile/text hash/plan | insert `0/""` for those columns | stored row `(0, 0, '', '', '')` != bound `(0, 22, document-utf8-v1, sha256:..., sha256:...)` | yes, hash match |
| allow conflicting overwrite | return expected set instead of `CONFLICT` | `Failed: DID NOT RAISE ExtractionReceiptRefused` | yes, hash match |

## Verify (each command once)

Focused new + extraction-state:

```
.venv/bin/python -m pytest tests/test_extraction_receipts.py tests/test_extraction_lifecycle.py -q
...........................
EXIT:0
27 passed
```

Affected extraction/method/ingestion/authority/schema:

```
.venv/bin/python -m pytest \
  tests/test_extraction_quality.py \
  tests/test_methodology_foundation_baseline.py \
  tests/test_app_isolation.py \
  tests/test_ingestion_service.py \
  tests/test_v2_truth_table.py \
  tests/test_authority_schema.py \
  tests/test_authority_repo.py \
  tests/test_method_extract_lifecycle.py \
  tests/test_storage_schema_boundary.py \
  tests/test_schema_install.py -q
........................................................................ [ 73%]
..........................                                               [100%]
EXIT:0
```

Static:

```
/Users/hyunjun/.local/bin/basedpyright \
  ontologylab/extraction_receipts.py \
  ontologylab/extraction_receipt_types.py \
  ontologylab/extraction_receipt_ids.py \
  ontologylab/extraction_receipt_store.py \
  ontologylab/extraction_receipt_schema.py \
  ontologylab/extraction_state.py \
  tests/test_extraction_receipts.py
0 errors, 0 warnings, 0 notes
```

No full suite. No retry-to-pass.

## Manual QA

Disposable driver `/private/tmp/ontologylab-wave21-task2-driver.py` against `/private/tmp/ontologylab-wave21-task2.store` (now deleted).

Observed JSON:

- two ready Representations, identical bytes `sha256:24c97a0eefe5a9ea67059607c4e3a57779ef0f6b23673cc11f091e2a2a071263`
- distinct run receipts `sha256:96663071…` vs `sha256:840adc45…`
- complete chunk: start 0, end 44, profile `document-utf8-v1`, text hash + plan receipt present
- retry same Representation: `retry_same=true`, `retry_created=false`
- counts after success: `{runs: 2, chunks: 2}`
- refusals: `invalid_range`, `invalid_hash`, `invalid_profile`, `conflict`; after-count stayed 2

PID 55560 / 127.0.0.1:8799 unchanged before and after (`ELAPSED 17-07:51:15`). QA root and driver removed. No leftover process or extra listener.

## Adversarial classes

| Class | Observable |
| --- | --- |
| malformed_input | inverted range / bad hash / unknown profile / conflicting plan → typed `ExtractionReceiptRefused`; row counts unchanged |
| stale_state | retry of same Representation+policy/config returns the same receipt IDs (`created=False`) |
| dirty_worktree | unrelated untracked docs/`.sisyphus` left untouched; only owned product/test paths dirty |
| misleading_success_output | overwrite mutant returned success without raise; test killed it |
| flaky_tests | no sleeps; receipt IDs are SHA-256 of bound fields |
| repeated_interruptions | baseline interrupt → `recover_running_once` → same `run_id` still green |
| cancel_resume | legacy `finish(cancelled=…)` / lifecycle suite unchanged (11 passed) |

## Risks / out of scope

- `extractor.py` still plans document-scoped runs by content hash. Task 3+ must consume `put_extraction_receipts`.
- Production `documents` still has global `UNIQUE(content_hash)` until Step 9. Same-hash two-Representation materialization is proven on the established disposable v2 layout, not the live constraint set.
- New API never `COMMIT`/`ROLLBACK`s the caller transaction; callers must commit. `executescript` is banned on this path.
- Historical receipt migration (Task 6 / H1) is not implemented; legacy rows remain readable as-is.

## Post-write review

1. Single responsibility: types / ids / schema / store / facade each name one noun.
2. Boundary purity: untrusted fields parsed into `ExtractionRunBinding` / `ChunkSpan`.
3. Variant discrimination: `match` on `FileLifecycleError`; profile via `CoordinateProfile(...)`.
4. Escape hatches: none.
5. Defensive layer: empty identity strings are boundary parse, not interior null checks.
6. Helpers: no one-off left in the facade.
7. Tests: contract tests fail if representation identity, chunk fields, or conflict refusal regress.
8. Parameter bloat: `put_extraction_receipts(conn, binding, chunks)` — 3 params.
9. Redundant verification: inserts are not re-selected; resume is a lookup.
10. Negative naming: refusal codes are positive conditions (`invalid_*`, `missing_binding`, `conflict`).
11. Logging: none added; `extraction_state` does not log.
