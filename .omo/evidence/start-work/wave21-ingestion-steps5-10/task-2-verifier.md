# AdversarialVerify — wave21 steps 5–10 / task-2

Verifier: omo senpi-task `st_01a02ea6`
Date: 2026-08-23
HEAD: `63e326f27c60b81f8a3e3daaf27518e82564da5c` (unchanged; no commit)
Scope: Task 2 DoneClaim for Representation-scoped extraction run/chunk receipts only.
Constraint: no product/test/plan/Boulder/ledger/canonical-doc edits left behind; no commit/push; no Application Support read; no external network; no 8799 / PID 55560 mutation; no Task 3+ files.

## Verdict

`confirmed`

Confidence: `0.91`

The executor DoneClaim is independently true on current bytes. Runs bind immutable `representation_id` + exact document hash + policy/config identities + deterministic receipt ID. Chunks bind parent run + start/end + `document-utf8-v1` + exact chunk text hash + plan receipt. Same bytes under two Representation IDs mint distinct run/chunk IDs. Same Representation/policy/config retry converges. Conflicting retry and invalid range/hash/profile refuse typed with zero partial rows. Legacy `plan()` claim/retry/success/failure/interrupt is unchanged. New API owns a SAVEPOINT only: success does not `COMMIT`; failure does not connection-wide `ROLLBACK`. All seven named mutants killed then restored byte-identically. Focused + affected suites and basedpyright passed once. Disposable library QA, reopen, schema idempotency, and cleanup reproduced.

`confirmed` is about the **receipt DoneClaim**, not the plan-todo close-out (`Commit: Y`, attemptDir evidence name, Step 7 surfaces). Those were not claimed finished and are out of this verify scope.

## What was verified (current bytes)

Public seam: `put_extraction_receipts(conn, binding, chunks)` in
`ontologylab/extraction_receipts.py`. Identity:
`ontologylab/extraction_receipt_ids.py`. Persistence:
`ontologylab/extraction_receipt_store.py`. Additive schema:
`ontologylab/extraction_receipt_schema.py`. `extraction_state.py` only adds
the `ensure_schema` hook plus re-exports (`+10` vs HEAD).

```28:44:ontologylab/extraction_receipts.py
def put_extraction_receipts(
    conn: sqlite3.Connection,
    binding: ExtractionRunBinding,
    chunks: tuple[ChunkSpan, ...],
) -> ExtractionReceiptSet:
    """Persist immutable run/chunk receipts inside the caller transaction."""
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    try:
        ensure_receipt_schema(conn)
        result = put_once(conn, binding, chunks)
    except (ExtractionReceiptRefused, sqlite3.Error):
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
    return result
```

Observed contracts:

| Binding | Where | Authority |
|---|---|---|
| run identity | `run_receipt_id` = SHA-256(`extraction-run-v1`, representation_id, content_hash, policy, config, plan_id) | Representation, not content hash |
| plan identity | `plan_receipt_id` = SHA-256(`extraction-plan-v1`, representation_id, policy, config, per-chunk index/start/end/profile/text_hash) | computed, not caller-supplied |
| chunk identity | `chunk_receipt_id` = SHA-256(`extraction-chunk-v1`, run_id, index, start, end, profile, text_hash, plan_id) | parent run + span + plan |
| resume lookup | `WHERE representation_id=? AND policy_identity=? AND config_identity=?` | not `document_content_hash` |
| document hash | `documents.content_hash` after `read_ready_text` integrity check | integrity assertion |
| chunk text | slice `document[start:end]` must equal `chunk.text`; hash must equal `content_hash_for(utf-8)` | write-time verify; hash persisted |
| uniqueness | `UNIQUE (representation_id, policy_identity, config_identity)` + append-only UPDATE/DELETE triggers | conflict ≠ overwrite |
| legacy `plan()` | still `UNIQUE (document_content_hash, schema/engine/model/prompt/decode, chunk_plan_hash)` | unchanged |

`KGStore.open` still installs only `extraction_state._SCHEMA` (legacy run/chunk
tables). Receipt tables are created by `ensure_receipt_schema` on first
`put_extraction_receipts` / `ensure_schema`. That is additive, not a hidden
KGStore rewrite.

No `preferred` pointer, no Citation/selection work, no `executescript` /
`commit` / `rollback` in the new receipt modules. Content hash is stored and
compared on resume; it is not the lookup key.

## Diff / schema / security

`git diff HEAD -- ontologylab/extraction_state.py` is exactly 10 added lines:
import re-exports + `ensure_receipt_schema(conn)` inside existing
`ensure_schema`. `plan` / `claim` / `failed` / `succeeded` / `finish` /
`recover_running_once` bodies are unchanged.

New untracked product/test files only:

| Path | Pure LOC | Role |
|---|---|---|
| `ontologylab/extraction_receipts.py` | 38 | SAVEPOINT facade |
| `ontologylab/extraction_receipt_types.py` | 67 | frozen receipts + refusal codes |
| `ontologylab/extraction_receipt_ids.py` | 86 | deterministic IDs |
| `ontologylab/extraction_receipt_schema.py` | 68 | additive tables + no-update/delete triggers |
| `ontologylab/extraction_receipt_store.py` | 225 | parse + persist |
| `tests/test_extraction_receipts.py` | 558 | baseline + contract |

`extraction_state.py` remains 384 pure LOC (pre-existing lifecycle module).
New modules are all ≤225. Store is in the 200–250 warning band, not the >250
defect band. No Task 3+ files (`extractor.py`, `work_view.py`, citation,
review, pack, migration) are dirty.

Security / trust:

- SQL is parameterized. SAVEPOINT name is a `Final` constant.
- Document bytes come from `read_ready_text` (contained `documents/` path +
  ready-state + hash recheck). Staged → `not_ready`. One-byte tamper →
  `invalid_hash: hash_mismatch`. Unknown id → `unknown_representation`.
- Invalid range/hash/profile refuse before insert. Failure rolls back the
  SAVEPOINT, including a first-call schema install, so a fail-only session
  leaves **no tables and no rows**.
- Append-only triggers abort `UPDATE`/`DELETE` (`extraction_run_receipts is
  append-only`).
- No secret-bearing paths, no live Application Support I/O, no network.

Not a failed invariant:

- Public API does not accept a plan receipt. “Invalid plan” is the conflict
  path (retry with a different chunk plan). Independently observed as
  `conflict` with counts unchanged.
- `digest()` joins parts with `\n`. IDs are deterministic; the encoding is
  not injective if a part itself contains a newline. Current identities are
  hashes / short tokens.
- Concurrent double-insert of the same binding would surface `sqlite3.Error`
  (UNIQUE), not `ExtractionReceiptRefused`. Single-writer SAVEPOINT is the
  shipped contract.
- Production `documents` still has global `UNIQUE(content_hash)`. Two-rep
  same-bytes materialization is proven on the established disposable v2
  layout, not the live constraint set. Receipt IDs still include
  `representation_id`, so the algorithm is correct if/when Step 9 lifts the
  global unique.

## Reproduction — tests (each command once; no retry-to-pass)

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Interpreter: `.venv/bin/python` (CPython 3.12.12)

### Collection (independent)

```
.venv/bin/python -m pytest tests/test_extraction_receipts.py \
  tests/test_extraction_lifecycle.py --collect-only -q
# test_extraction_lifecycle.py: 11
# test_extraction_receipts.py: 16
# COLLECT_FOCUSED_EXIT:0

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
  tests/test_schema_install.py \
  tests/test_extractor.py --collect-only -q
# 2+6+4+10+7+7+8+23+10+21+16 = 114
# COLLECT_AFFECTED_EXIT:0
```

Executor affected set was 98 (same list without `test_extractor.py`). This
pass added `test_extractor.py` because `extractor.py` is the live
`ExtractionState` consumer.

### Runs (once each)

```
.venv/bin/python -m pytest tests/test_extraction_receipts.py \
  tests/test_extraction_lifecycle.py -q
...........................
FOCUSED_EXIT:0
# 27 passed

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
  tests/test_schema_install.py \
  tests/test_extractor.py -q
........................................................................ [ 63%]
..........................................                               [100%]
AFFECTED_EXIT:0
# 114 passed

/Users/hyunjun/.local/bin/basedpyright \
  ontologylab/extraction_receipts.py \
  ontologylab/extraction_receipt_types.py \
  ontologylab/extraction_receipt_ids.py \
  ontologylab/extraction_receipt_store.py \
  ontologylab/extraction_receipt_schema.py \
  ontologylab/extraction_state.py \
  tests/test_extraction_receipts.py
0 errors, 0 warnings, 0 notes
BASED PYRIGHT_EXIT:0
```

No full suite. No retry-to-pass. No sleeps in product or Task 2 tests.

## Mutation / toggle

Pre-hash (also post-hash; identical):

| File | SHA-256 |
|---|---|
| `extraction_receipt_ids.py` | `c8c0fd4b431bfaa5ae9687fa869e0d8cffe5338557a625dc461ac110c6d9daae` |
| `extraction_receipt_store.py` | `42ad7c6be247587304a5ad6fd4ef29da5d199ce4f4f27f5d7c58d3084dc64f86` |
| `extraction_receipts.py` | `01d18f23b0c88506a3ed694eef42e33e22d29ce48e0b1cbc6042f5cfc78bd8e7` |
| `extraction_receipt_schema.py` | `4f68452dcbad35e3e85443751071786ac156a1c62ad3ca5e1510e2443a044ea8` |
| `extraction_receipt_types.py` | `bc2b07d241cd3392760035a96803ebef61f0774caecdda57a38089282e834dc3` |
| `extraction_state.py` | `09bd61aeb8567c22c2a2abca8717296db7089f51a2f7be77068d8fcc1bac880e` |
| `tests/test_extraction_receipts.py` | `b1a0f2b465267163c813e0c60da982e83f0ffc73da799c36296bc3a9b55be52e` |

Executor grouped chunk-end / profile / text-hash / plan into one insert
mutant. That mapping covers all seven named decisions. This pass still
killed **each** decision individually, restore-after-each, then confirmed
byte identity.

| # | Decision | Mutant | Killer | Observed failure |
|---|---|---|---|---|
| 1 | representation ID dropped/ignored | omit `representation_id` from plan+run digests | `test_same_hash_two_representations_mint_distinct_run_receipts` | `UNIQUE constraint failed: extraction_run_receipts.receipt_id` exit 1 |
| 2 | lookup by content hash | `WHERE document_content_hash=?` | same | `ExtractionReceiptRefused: conflict: retry does not match the immutable extraction receipt` exit 1 |
| 3 | chunk end omitted | insert `end_offset=0` | `test_chunk_receipt_binds_end_profile_text_hash_and_plan` | stored `(0, 0, …)` ≠ bound `(0, 22, …)` exit 1 |
| 4 | profile omitted/accepted wrong | skip `CoordinateProfile` parse | `test_invalid_range_hash_or_profile_refuses_with_zero_rows` | `DID NOT RAISE ExtractionReceiptRefused` exit 1 |
| 5 | chunk text hash omitted/accepted wrong | skip hash compare | same | `DID NOT RAISE ExtractionReceiptRefused` exit 1 |
| 6 | plan receipt omitted/accepted wrong | insert `plan_receipt_id=""` | `test_chunk_receipt_binds_end_profile_text_hash_and_plan` | stored `''` ≠ bound `sha256:d376d9cb…` exit 1 |
| 7 | conflicting overwrite allowed | `return expected` instead of `CONFLICT` | `test_conflicting_retry_refuses_and_writes_zero_rows` | `DID NOT RAISE ExtractionReceiptRefused` exit 1 |

`IDENTICAL=True` `ALL_KILLED=True` `MUTATE_EXIT:0`. Companion hashes above
unchanged after the last restore. That is toggle proof, not correlation.

## Manual QA

Disposable driver `/private/tmp/ontologylab-wave21-task2-verify.driver.py`
against `/private/tmp/ontologylab-wave21-task2-verify.store` (now deleted).
Direct public library only. No server. No 8799.

Two ready Representations, distinct Works, identical bytes
`sha256:24c97a0eefe5a9ea67059607c4e3a57779ef0f6b23673cc11f091e2a2a071263`:

```
two_reps:
  first_run  sha256:96663071b130d9d736ccc732d828d941c515f3b46445a7720195d37eea72e107
  second_run sha256:840adc45e70e9b049790022310a6b65bcb45123745440b54a02a80c5fcb8477b
  distinct_runs true  distinct_chunks true
  first_chunk_complete {start:0, end:44, profile:document-utf8-v1,
                        text_hash:sha256:24c97a0e…, plan:sha256:c2995a4f…,
                        parent:sha256:96663071…}
  counts {runs:2, chunks:2}

retry_converge: retry_same=true retry_created=false chunk_same=true counts {2,2}
baseline_before_refusals: {runs:2, chunks:2}
```

Those run IDs match the executor QA IDs on the same fixture. Deterministic.

Refusals, counts stay `{2,2}`:

| Case | code | counts |
|---|---|---|
| inverted range | `invalid_range` | `{2,2}` |
| wrong chunk hash | `invalid_hash` | `{2,2}` |
| `guessed-offsets-v0` | `invalid_profile` | `{2,2}` |
| different plan (end-1) | `conflict` | `{2,2}` |
| missing representation | `unknown_representation` | `{2,2}` |
| empty representation id | `missing_binding` | `{2,2}` |

Additional probes (after the `{2,2}` gate):

- Different policy on same Representation mints a **new** run (`created=true`,
  distinct id). Identity is the triple, not representation alone.
- `DELETE` / `UPDATE` on receipt rows → `extraction_run_receipts is append-only`.
- Reopen + `ensure_receipt_schema` twice: same `rep-a`/`policy-v1` receipt and
  chunk tuple `(0, 44, document-utf8-v1, sha256:24c97a0e…, sha256:c2995a4f…)`.
- Outer txn success: sentinel `7` visible mid-put; `ROLLBACK` drops sentinel
  **and** the extra receipt (`extra_survived=0`). No hidden `COMMIT`.
- Outer txn failure (`invalid_range`): sentinel `9` still present; counts
  unchanged. No connection-wide `ROLLBACK`.
- Legacy `insert_document` store: `ensure_schema` twice installs receipt
  tables; `plan` → claim → owner-lock release → `recover_running_once` →
  same `run_id`, chunk `0` retryable.
- Separate probe: staged Representation → `not_ready: representation
  rep-staged is staged`. One-byte ready tamper → `invalid_hash: hash_mismatch`.
  Fail-only session: receipt tables rolled back (`sqlite_master` empty).

## Cleanup proof

```
rm -rf /private/tmp/ontologylab-wave21-task2-verify.store \
       /private/tmp/ontologylab-wave21-task2-verify.mutation-backup
rm -f  /private/tmp/ontologylab-wave21-task2-verify.driver.py \
       /private/tmp/ontologylab-wave21-task2-verify.mutate.py
ls -ld /private/tmp/ontologylab-wave21-task2-verify*  → no prefix
pgrep -lf ontologylab-wave21-task2-verify             → none
```

8799 / PID 55560 **read-only** before and after (same start, same argv):

```
python3.1 55560  TCP 127.0.0.1:8799 (LISTEN)
STARTED Thu Aug  6 13:51:44 2026
.venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 8799 \
  --data-dir /Users/hyunjun/Library/Application Support/ontologylab/data \
  --packs-dir /Users/hyunjun/Library/Application Support/ontologylab/packs
```

No Application Support files were opened. Other pre-existing loopback
Python listeners (60654+, 8787, 8891, …) were not started by this session
and were not touched. Product hashes after QA/mutation/cleanup identical to
pre-verify. `git status --short` matches the pre-verify dirty tree plus this
report. No commit. No `.debug-journal.md` written by this verifier (the
existing excluded journal is the executor’s leftover).

## Adversarial classes

| Class | Probe | Result |
|---|---|---|
| malformed_input | inverted range, bad hash, unknown profile, empty binding, unknown id | typed `ExtractionReceiptRefused`; counts unchanged |
| stale_state | reopen after commit; same-binding retry | receipt IDs stable; `created=False` |
| dirty_worktree | compared status before/after; hashed only task files | no extra product drift; HEAD unchanged; unrelated docs/`.sisyphus`/`uv.lock` left untouched |
| misleading_success_output | overwrite mutant returns success without raise | test killed it (`DID NOT RAISE`) |
| flaky_tests | no sleeps; IDs are SHA-256 of bound fields | single-run green |
| repeated_interruptions | legacy claim → recover → same `run_id` | still green (unit + QA) |
| cancel_resume | `tests/test_extraction_lifecycle.py` (11) + `finish(cancelled=…)` | 11 passed; new API does not own cancel |

## Residual risks

1. `extractor.py` still plans document-scoped runs by content hash. Task 3+
   must consume `put_extraction_receipts`. Out of this claim.
2. Production `UNIQUE(content_hash)` still prevents two ready rows with the
   same bytes. Algorithm is Representation-scoped; live rows are not, yet.
3. `config_identity` is caller-supplied and is **not** derived from
   engine/model/prompt/decode. Same triple with a different model converges
   and keeps the first stored metadata.
4. `digest()` newline joining is deterministic but not injective.
5. First failed `put` inside an uncommitted txn rolls back schema install.
   Callers that query tables after only failures must call `ensure_schema`
   first (tests already do).
6. Store module is 225 pure LOC (warning band). `_insert_receipts` takes 6
   parameters. Neither is a contract fail.
7. Plan Task 2 close-out commit
   `feat(extraction): bind runs and chunks to representations` is **not**
   done. Out of this DoneClaim.

## Why not another verdict

- `false-positive`: two-rep IDs differ for a real reason (representation in
  the digest); mutation #1 collapses them to a UNIQUE failure. QA refusals
  are typed codes, not empty success.
- `needs-fix`: no reproduced hidden commit/rollback, no content-hash
  authority, no partial rows on refuse, no >250 new module, no Task 3
  leakage, no failed required suite. Executor mutation coverage maps to all
  seven decisions; this pass independently killed each.
- `needs-human-review`: dirty worktree is real but isolated by hashes +
  mutation + disposable library QA. It does not make the receipt contract
  unverifiable.

## Stop condition

This file is the only write. One strict verdict: `confirmed`.
