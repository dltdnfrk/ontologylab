# DoneClaim — wave21 steps 5–10 / task-1

Executor: omo senpi-task `st_01a02e39`
Date: 2026-08-23
HEAD: `eab47a615cc5f309c05a48875c6e6877096783dd` (unchanged; no commit)
Constraint: did not touch live Application Support data, network, port 8799, or PID 55560.

## Verdict

The seven `tests/test_provenance_api.py` regressions are green. v2 ready-byte integrity and unsafe-path refusal remain typed. Disposable HTTP QA reproduced the three required surfaces. Cleanup is proven.

## Root cause

`document_raw_text` treated any `sha256:` + 64 hex string on a **legacy** row (`work_id IS NULL`) as authoritative. Historical / test rows use the placeholder `sha256:` + `"d"*64`, which matches that shape but not the file bytes. `provenance()` calls `document_raw_text` for the excerpt, so six library tests raised `KGStoreError: legacy raw text hash mismatch` and the HTTP test returned an error body without `extraction`.

Runtime probe (`/private/tmp/ontologylab-wave21-task1-probe`, now deleted):

```
work_id= None
representation_state= ready
raw_text_path= documents/91ea4a0af7b0432d9a0f497b531ca5af/raw.txt
path_exists= True
bytes_len= 106
expected= sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
actual= sha256:72134957926b22c5af07e6e1bc561370bd9ce4cf8e3fe86fbf8e56d7a1330703
has_real_sha256= True
hashes_equal= False
error= legacy raw text hash mismatch
```

Hypotheses:

1. Synthetic sha256-shaped legacy hash treated as real — **confirmed**.
2. `insert_document` now sets `work_id` so v2 `read_ready_text` always hashes — **refuted** (`work_id=None`).
3. `reconcile_files` rewrote/quarantined the seeded file — **refuted** (contained ready file still present; reconcile SQL is `work_id IS NOT NULL`).

Toggle proof:

- `if False and has_real_sha256 and ...` → focused test exit 0
- restore the condition → focused test exit 1, `legacy raw text hash mismatch`

## Fix

In `ontologylab/kgstore.py` `document_raw_text`:

- v2 (`work_id is not None`) still goes through `read_ready_text` (hash + `documents/` containment + ready-only)
- legacy contained ready rows are decoded without using `content_hash` as an integrity oracle
- absolute / out-of-root / `sources.json` / `providers.json` / `.env` still raise `KGStoreError("legacy raw_text_path escapes safe storage")`
- staged/quarantined still refused via `representation_state != READY` (and v2 `FileNotReady`)

No broad catch was added. No unsafe bytes are returned on refused paths.

## Changed files (this task)

| Path | Role |
|---|---|
| `ontologylab/kgstore.py` | Remove non-authoritative legacy hash refusal |
| `tests/test_provenance_api.py` | Focused RED test for synthetic-hash legacy rows |
| `tests/test_document_view.py` | Baseline characterizations (a)(b)(c) |

Pre-existing dirty work from other agents was left untouched (`authority_repo.py`, `ingestion.py`, `main.py`, `server/*`, `work_view.py`, untracked Step 6 modules, planning docs, `.omo/plans/`).

## Tests

### Baseline on unchanged production code (before fix)

```
.venv/bin/python -m pytest \
  tests/test_document_view.py::test_v2_ready_bytes_read_when_work_id_and_hash_match \
  tests/test_document_view.py::test_v2_ready_read_fails_typed_when_hash_mismatches \
  tests/test_document_view.py::test_legacy_read_fails_typed_when_path_leaves_store_root \
  tests/test_document_view.py::test_document_view_reads_ready_bytes_only \
  tests/test_document_view.py::test_document_view_refuses_planted_store_and_absolute_paths \
  tests/test_file_lifecycle.py::test_document_raw_text_rechecks_hash_for_ready_file -q
......
EXIT:0
```

### Existing RED gate (before focused test)

```
.venv/bin/python -m pytest tests/test_provenance_api.py -q
FFFFFF......F..
7 failed (legacy raw text hash mismatch × 6; KeyError: 'extraction' × 1)
EXIT:1
```

### Focused RED / GREEN

```
.venv/bin/python -m pytest tests/test_provenance_api.py::test_legacy_provenance_reads_when_hash_metadata_is_synthetic -q
# before fix / after toggle revert: FAILED ... legacy raw text hash mismatch  EXIT:1
# after fix: .  EXIT:0
```

### After fix (run once each)

```
.venv/bin/python -m pytest tests/test_provenance_api.py tests/test_document_view.py tests/test_file_lifecycle.py tests/test_kgstore.py -q
...............................................................
FOUR_FILE_EXIT:0
63 passed
```

G008 affected Step 6 suite from current evidence:

```
.venv/bin/python -m pytest tests/test_file_lifecycle.py tests/test_ingestion_service.py tests/test_ingest_concurrency.py tests/test_reconciliation.py tests/test_document_view.py tests/test_extractor.py -q
..............................................................
G008_EXIT:0
62 passed
```

```
/Users/hyunjun/.local/bin/basedpyright \
  ontologylab/kgstore.py tests/test_provenance_api.py tests/test_document_view.py
0 errors, 0 warnings, 0 notes
BASED PYRIGHT:0
```

Full suite was not run (closure owns that).

## Manual QA

Disposable roots: `/private/tmp/ontologylab-wave21-task1.data`, `.packs`, `.hashqa`, `.qa.py`, `.secret.txt`, `-probe`.
Server: `python -m ontologylab.serve --host 127.0.0.1 --port 18871 --data-dir /private/tmp/ontologylab-wave21-task1.data`.

1. **Safe contained legacy provenance, synthetic hash** — HTTP 200, `extraction.engine=claude`, excerpt contains `PaymentGateway`. DB counts: documents=5, nodes=6, edges=1, works=1.
2. **One-byte v2 ready tamper** — library `KGStoreError` / HTTP 400. After reopen, reconcile quarantined the v2-linked row (`representation ... is quarantined`). Live-open tamper without reopen: `hash_mismatch`. Neither body contained `ELS-must-never-surface-9f3a` / `SECRET-xyz`.
3. **Absolute / traversal / `sources.json`** — library + HTTP 400 `legacy raw_text_path escapes safe storage`; secret not in any body.

Post-QA counts unchanged: documents=5, nodes=6, edges=1, works=1.

## Cleanup receipt

```
rm -rf /private/tmp/ontologylab-wave21-task1.data \
       /private/tmp/ontologylab-wave21-task1.packs \
       /private/tmp/ontologylab-wave21-task1-probe \
       /private/tmp/ontologylab-wave21-task1.hashqa
rm -f  /private/tmp/ontologylab-wave21-task1.qa.py \
       /private/tmp/ontologylab-wave21-task1.secret.txt
ls -d /private/tmp/ontologylab-wave21-task1*  → no task1 temps
lsof -nP -iTCP:18871 -sTCP:LISTEN            → 18871 empty
lsof -nP -iTCP:8799 -sTCP:LISTEN             → python3.1 55560 ... 127.0.0.1:8799
ps -p 55560                                  → same command: ontologylab.serve --port 8799 --data-dir Application Support/ontologylab/data
```

Debug journal removed after this claim was written.

## Adversarial classes

| Class | Status |
|---|---|
| malformed_input | Exercised: absolute, `../`, sensitive filename all typed-refuse |
| stale_state | Exercised: on-disk v2 tamper → hash_mismatch / quarantine |
| dirty_worktree | Other agents' dirty files preserved; no commit |
| misleading_success_output | QA1 is HTTP 200 with `extraction`; refusals are HTTP 400, not 200-without-extraction |
| long_commands | Recorded verbatim above |
| flaky_tests | No sleeps in product/tests; QA wait is bounded socket connect |
| repeated_interruptions | Not observed |
| prompt_injection | N/A — no untrusted prompt/LLM surface in this change |
| cancel_resume | N/A — single continuous session, no cancelled in-flight write |

## Risks

- Legacy `content_hash` is no longer an integrity oracle. That is the intended contract: those values are historically non-authoritative. v2-linked rows still hash-check via `read_ready_text`.
- `kgstore.py` remains far above the 250 pure-LOC ceiling (pre-existing; this task removed lines from the reader and did not split the module).
- A v2 row that lost `work_id` would be classified as legacy and would not hash-check. Startup reconcile stays scoped to `work_id IS NOT NULL`.

## Post-write review

1. Single responsibility: `document_raw_text` owns ready/legacy byte reads. Yes.
2. Boundary purity: untrusted paths resolved and contained at the read boundary. Yes.
3. Variant discrimination: `work_id is not None` and `state != READY` are boolean predicates, not tagged-variant `if/elif`. Yes.
4. Escape hatches: none added. Yes.
5. Defensive layer: no extra null-check; existing FileLifecycleError→KGStoreError boundary kept. Yes.
6. One-off helpers: none in production. Yes.
7. Tests lock the behavior and fail if the hash check is restored. Yes.
8. Parameter bloat: none. Yes.
9. Redundant post-delete verification: none. Yes.
10. Negative naming: none. Yes.
11. Logging: untouched. Yes.
