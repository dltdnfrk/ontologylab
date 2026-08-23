# AdversarialVerify — wave21 steps 5–10 / task-1

Verifier: omo senpi-task `st_01a02e43`
Date: 2026-08-23
HEAD: `eab47a615cc5f309c05a48875c6e6877096783dd` (unchanged; no commit)
Scope: Task 1 DoneClaim for the Step 6 legacy provenance compatibility repair only.
Constraint: no product/test edits left behind; no commit; no Application Support read; no external network; no 8799 / PID 55560 mutation; no Step 7+ files.

## Verdict

`confirmed`

Confidence: `0.92`

The executor DoneClaim is independently true: contained legacy rows with synthetic `sha256:` + 64 hex now return provenance/extraction; v2 ready reads still hash-verify via `read_ready_text`; unsafe legacy paths and non-ready states refuse typed without leaking secrets; startup reconcile stays `work_id IS NOT NULL`. Focused, four-file, G008, G009, basedpyright, mutation toggle, disposable HTTP QA, and cleanup all reproduced on this pass.

`confirmed` is about the **repair DoneClaim**, not the whole plan-todo (Step 6 commit, evidence index, reviews, `git log -1`). Those remaining Task 1 close-out items were not claimed finished by the executor and were not in this verify scope.

## What was verified (current bytes)

`ontologylab/kgstore.py` `document_raw_text` (lines 2186–2221):

```2186:2221:ontologylab/kgstore.py
    def document_raw_text(self, doc_id: str) -> str:
        ...
            if row["work_id"] is not None:
                return read_ready_text(self.conn, self.db_path.parent, doc_id)
            if row["representation_state"] != READY:
                raise KGStoreError(...)
            ...
            if (
                not resolved.is_relative_to(root)
                or resolved.name in {"sources.json", "providers.json", ".env"}
            ):
                raise KGStoreError("legacy raw_text_path escapes safe storage")
            data = resolved.read_bytes()
            return data.decode("utf-8")
        except (FileLifecycleError, OSError, UnicodeDecodeError) as exc:
            raise KGStoreError(str(exc)) from exc
```

Observed contracts:

| Branch | Discriminator | Reader | Integrity | Path |
|---|---|---|---|---|
| v2 | `work_id is not None` | `read_ready_text` | `content_hash_for(data) != row["content_hash"]` → `FileIntegrityError("hash_mismatch")` (`file_lifecycle.py:472-491`) | `contained_documents_path` (`documents/` only) |
| legacy | `work_id is None` | local decode | **does not** treat `content_hash` as oracle (SELECT omits `content_hash`) | store-root `resolve()` + `is_relative_to` + basename denylist |
| non-ready legacy | `representation_state != READY` | none | n/a | raise before `read_bytes` |

`insert_document` still writes `work_id` NULL and relies on `representation_state TEXT NOT NULL DEFAULT 'ready'` (`kgstore.py:807-814`, `2094-2101`). Provenance still calls `document_raw_text` for the excerpt (`kgstore.py:4733-4735`). HTTP `/api/provenance/{kind}/{item_id}` maps `KGStoreError` → 400 (`routes.py:602-618`).

Startup reconcile remains v2-scoped (`file_lifecycle.py:437-444`):

```sql
WHERE work_id IS NOT NULL AND (
  representation_state = 'staged'
  OR (raw_text_path LIKE 'documents/%' AND length(content_hash) = 71)
)
```

`KGStore.open` still calls that `reconcile_files` (`kgstore.py:767-770`). Independent QA: after HTTP v2 tamper, only the v2 row became `quarantined`; the NULL-`work_id` synthetic-hash legacy row stayed `ready` and still readable; the planted `staged` row stayed `staged`.

No broad `except Exception` / empty fallback was added on the read path. The only catch is `(FileLifecycleError, OSError, UnicodeDecodeError)` → `KGStoreError(str(exc))`. That converts errors; it never returns file bytes. `KGStoreError` raised for escape / non-ready is not swallowed by that except.

## Diff / security analysis

`git diff ontologylab/kgstore.py` vs HEAD still contains **pre-existing dirty Step 6 work** (`KGStore.open` reconcile/outbox) plus this repair. Task-1-owned reader delta vs the broken intermediate is: remove the “real-looking sha256” compare on the legacy branch.

Does the current reader weaken v2 / path invariants?

- **v2 hash / ready / `documents/`**: no. `work_id is not None` is the first branch and always calls `read_ready_text`. Live-open one-byte tamper → `KGStoreError: hash_mismatch`. HTTP reopen after tamper → reconcile quarantines → `representation … is quarantined`. Both typed; neither body contained planted secrets.
- **Staged / quarantined**: legacy checks `representation_state != READY` before read. HTTP staged plant → 400 `representation rep-staged is staged`. Bytes `staged-must-not-surface` never appeared.
- **Absolute / traversal / sensitive names**: refuse before `read_bytes`. HTTP abs, `../secret`, `sources.json` → 400 `legacy raw_text_path escapes safe storage`. Extra library probe: `providers.json` and `.env` same typed refuse. No `ELS-must-never-surface-9f3a` / `SECRET-xyz-must-never-surface` in any body.
- **Symlink escape**: `Path.resolve()` then `is_relative_to(root)` (legacy) / `contained_documents_path` (v2). Not re-exploited here; G008 mutant m1 already pins write-side containment.
- **Catch-as-exfil**: `str(exc)` for `UnicodeDecodeError`/`OSError`/`FileLifecycleError` does not include file contents. Confirmed: no secret substrings in 400 bodies.

Residual (not a failed invariant for this claim):

- Legacy reader is store-root + three basenames, not `documents/`-only. A SQL-planted NULL-`work_id` ready row pointing at some other UTF-8 file under the data dir can be read. HTTP ingest/collect always assign `work_id` and cannot enter that branch. Same residual G007 already classed non-H1.
- A v2 row that **lost** `work_id` would be classified legacy and would not hash-check. Reconcile would also skip it.
- `document_review_context` (`kgstore.py:4258-4265`) still swallows `KGStoreError` and returns `text=""`. HTTP `/api/document/{id}/review` therefore returns **200 with empty text** on v2 quarantine and unsafe legacy plants. That is a pre-existing silent panel fallback, not a secret leak, and not the provenance surface named by the DoneClaim.

## Reproduction — tests (each command once; no retry-to-pass)

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Interpreter: `.venv/bin/python` (CPython 3.12.12)

### Collection (independent)

```
.venv/bin/python -m pytest \
  tests/test_document_view.py::test_v2_ready_bytes_read_when_work_id_and_hash_match \
  tests/test_document_view.py::test_v2_ready_read_fails_typed_when_hash_mismatches \
  tests/test_document_view.py::test_legacy_read_fails_typed_when_path_leaves_store_root \
  tests/test_document_view.py::test_document_view_reads_ready_bytes_only \
  tests/test_document_view.py::test_document_view_refuses_planted_store_and_absolute_paths \
  tests/test_file_lifecycle.py::test_document_raw_text_rechecks_hash_for_ready_file \
  tests/test_provenance_api.py::test_legacy_provenance_reads_when_hash_metadata_is_synthetic \
  --collect-only -q
# 5 + 1 + 1 = 7 collected; COLLECT_FOCUSED_EXIT:0

.venv/bin/python -m pytest tests/test_provenance_api.py tests/test_document_view.py \
  tests/test_file_lifecycle.py tests/test_kgstore.py --collect-only -q
# document_view 5, file_lifecycle 15, kgstore 27, provenance_api 16 = 63
# COLLECT_FOUR_EXIT:0

.venv/bin/python -m pytest tests/test_file_lifecycle.py tests/test_ingestion_service.py \
  tests/test_ingest_concurrency.py tests/test_reconciliation.py \
  tests/test_document_view.py tests/test_extractor.py --collect-only -q
# 15+10+8+8+5+16 = 62; COLLECT_G008_EXIT:0
# G008 evidence originally recorded 55; current tree added characterization tests.
# Executor also reported 62. Independent count matches executor, not the older G008 receipt.

.venv/bin/python -m pytest tests/test_ingestion_shadow_entrypoints.py \
  tests/test_ingestion_surfaces.py tests/test_collect_sample.py \
  tests/test_research_run.py tests/test_research_source_surface.py \
  tests/test_server.py tests/test_wave21_surface_harness.py --collect-only -q
# 16+8+2+35+5+20+11 = 97; COLLECT_G009_EXIT:0  (matches G009/a1/regression.txt)
```

### Runs (once each)

```
# focused baseline + RED-isolation
.venv/bin/python -m pytest <7 nodeids above> -q
.......
FOCUSED_EXIT:0

.venv/bin/python -m pytest tests/test_provenance_api.py tests/test_document_view.py \
  tests/test_file_lifecycle.py tests/test_kgstore.py -q
...............................................................
FOUR_FILE_EXIT:0
# 63 passed

# exact G008 affected Step 6 suite from evidence
.venv/bin/python -m pytest tests/test_file_lifecycle.py tests/test_ingestion_service.py \
  tests/test_ingest_concurrency.py tests/test_reconciliation.py \
  tests/test_document_view.py tests/test_extractor.py -q
..............................................................
G008_EXIT:0
# 62 passed

# exact G009 affected Step 6 suite from evidence (executor omitted this; run once here)
.venv/bin/python -m pytest tests/test_ingestion_shadow_entrypoints.py \
  tests/test_ingestion_surfaces.py tests/test_collect_sample.py \
  tests/test_research_run.py tests/test_research_source_surface.py \
  tests/test_server.py tests/test_wave21_surface_harness.py -q
........................................................................ [ 74%]
.........................
G009_EXIT:0
# 97 passed

/Users/hyunjun/.local/bin/basedpyright \
  ontologylab/kgstore.py tests/test_provenance_api.py tests/test_document_view.py \
  tests/test_file_lifecycle.py tests/test_kgstore.py
0 errors, 0 warnings, 0 notes
BASED PYRIGHT_EXIT:0
```

Full suite was not run.

## Mutation / toggle

Pre-hash `ontologylab/kgstore.py`:
`2226e9bf6b67952ccea38202203478a96fd5571bbb27b75045d53b8961eca22f`

Temporary restore of the removed legacy hash oracle (SELECT `content_hash`; if `sha256:`+64 lowercase hex and digest ≠ stored, raise `legacy raw text hash mismatch`). No other files touched.

```
.venv/bin/python -m pytest \
  tests/test_provenance_api.py::test_legacy_provenance_reads_when_hash_metadata_is_synthetic -q
# FAILED ... KGStoreError: legacy raw text hash mismatch
# MUTATION_RED_EXIT:1
```

Restore current bytes (inverse edit). Post-hash:
`2226e9bf6b67952ccea38202203478a96fd5571bbb27b75045d53b8961eca22f` (identical)

```
.venv/bin/python -m pytest \
  tests/test_provenance_api.py::test_legacy_provenance_reads_when_hash_metadata_is_synthetic -q
.
MUTATION_GREEN_EXIT:0
```

Companion hashes unchanged:
- `tests/test_provenance_api.py` `8eb666e387c227a9b7814c3bc3d1e73d84ae55e606fd5f30f3f5408530cf2684`
- `tests/test_document_view.py` `7a29831a54656af1df31bc707f6eb5721e792dcb8358e2b74351fcb2cd2f6911`

The isolated test fails for the named reason when the oracle is restored and passes when it is absent. That is toggle proof, not correlation.

## Manual QA

Disposable root: `/private/tmp/ontologylab-wave21-task1-verify.data`
Packs: `/private/tmp/ontologylab-wave21-task1-verify.packs`
Secret file: `/private/tmp/ontologylab-wave21-task1-verify.secret.txt` (`SECRET-xyz-must-never-surface`)
Store `sources.json`: `ELS-must-never-surface-9f3a`
Server (not 8799):

```
.venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 18917 \
  --data-dir /private/tmp/ontologylab-wave21-task1-verify.data \
  --packs-dir /private/tmp/ontologylab-wave21-task1-verify.packs
# listener PID 8534; socket connect → PORT_READY
```

Seed facts (library against that data-dir only):

- legacy `insert_document` `work_id=None`, `content_hash=sha256:`+`d*64`, path `documents/c0fd4713f5cb42408984c111f6da1431/raw.txt`, state `ready`
- v2 `ingest_item` + `finalize` `work_id=work-1ac8b68b4642`, `id=rep-ece93ad62120`
- plants: absolute secret, `../…secret.txt`, `sources.json`, staged contained file
- counts before HTTP: documents=6, nodes=12, edges=6, works=1

### QA1 — contained legacy synthetic hash

`GET http://127.0.0.1:18917/api/provenance/node/44a9d85b69204d07b5e5238283bc9951`

```
HTTP 200
{"kind":"node",...,"extraction":{"engine":"claude","model":"haiku",...},
 "excerpt":"The >>>PaymentGateway<<< validates cards through the FraudDetector. ..."}
SECRET_LEAK=[]
```

### QA2 — one-byte v2 ready tamper

Before tamper: same node `756ed02c2ba2413583bea2842defcf25` HTTP 200, excerpt from `v2 ready body…`.
Tamper: `documents/rep-ece93ad62120/raw.txt` last byte `\n` → `X` (len 35 unchanged).

```
HTTP 400
{"detail":"representation rep-ece93ad62120 is quarantined"}
SECRET_LEAK=[]
```

Live-open (same sqlite connection, no reopen) on a fresh v2 row:

```
LIVE_TAMPER_TYPED KGStoreError hash_mismatch
LIVE_TAMPER_LEAK False
```

### QA3 — absolute / traversal / sensitive / staged

```
GET .../node/1ee4521f927f41f69a21e14dd69aabc7  → 400 legacy raw_text_path escapes safe storage
GET .../node/6526bff8d15e49e1b4df534198809ab1  → 400 legacy raw_text_path escapes safe storage
GET .../node/2071e59e2fd842dbbd4f38f00079f0e8  → 400 legacy raw_text_path escapes safe storage
GET .../node/fad4cd54266242a7a1785dda5d9fc29e  → 400 representation rep-staged is staged
SECRET_LEAK=[] on every body
```

Library extras: `providers.json` / `.env` → same escape error, no sentinel.

### DB state after HTTP (before extra live ingest)

```
COUNTS {"documents": 6, "nodes": 12, "edges": 6, "works": 1}
legacy: work_id=None, representation_state=ready, still reads PaymentGateway prefix
v2:     work_id=work-1ac8b68b4642, representation_state=quarantined
staged: representation_state=staged (not auto-finalized)
```

Counts unchanged vs pre-HTTP seed. Reconcile did not touch NULL-`work_id` rows.

## Cleanup proof

```
kill 8533; kill 8534
# 18917_EMPTY; lsof -nP -iTCP:18917 -sTCP:LISTEN → no listener
# 18871 empty (executor QA port)
rm -rf /private/tmp/ontologylab-wave21-task1-verify.data \
       /private/tmp/ontologylab-wave21-task1-verify.packs
rm -f  /private/tmp/ontologylab-wave21-task1-verify.*
ls -ld /private/tmp/ontologylab-wave21-task1*  → no task1 temps
pgrep -lf 'ontologylab.serve --host 127.0.0.1 --port 18917' → none
```

8799 / PID 55560 **read-only** before and after (same start time, same argv):

```
python3.1 55560  TCP 127.0.0.1:8799 (LISTEN)
STARTED Thu Aug  6 13:51:44 2026
.venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 8799 \
  --data-dir /Users/hyunjun/Library/Application Support/ontologylab/data \
  --packs-dir /Users/hyunjun/Library/Application Support/ontologylab/packs
```

No Application Support files were opened. No executor QA roots (`ontologylab-wave21-task1.data`, `.packs`, `-probe`, `.hashqa`, `.qa.py`, `.secret.txt`) remained.

Product hashes after QA/cleanup identical to pre-mutation. `git status --short` matches the pre-verify dirty tree (other agents + this task). No new tracked/untracked product files from the verifier. No `.debug-journal.md` in the repo. No commit.

## Adversarial classes

| Class | Probe | Result |
|---|---|---|
| malformed_input | HTTP/library abs, `../`, `sources.json`, `providers.json`, `.env` | typed 400 / `KGStoreError`; no secret |
| stale_state | on-disk v2 one-byte tamper then HTTP reopen | quarantined 400; live-open `hash_mismatch`; legacy row not quarantined |
| dirty_worktree | compared status before/after; hashed only task files; did not touch other agents' dirty paths | no extra drift; HEAD unchanged |
| misleading_success_output | QA1 is 200 **with** `extraction.engine=claude`; refusals are 400 not 200-without-extraction | provenance honest. Residual: document-review 200+empty text (pre-existing swallow) |
| long_commands | recorded verbatim above | no hung command; all pytest/QA finished once |
| flaky_tests | no sleeps in product/tests; QA wait is bounded socket connect | single-run green; no retry |
| repeated_interruptions | single continuous session | not observed |
| leftover artifacts / processes | scanned `/private/tmp/ontologylab-wave21-task1*`, 18871, 18917 | none remain |

## Residual risks

1. Legacy `content_hash` is intentionally not an integrity oracle. Real and synthetic sha256-shaped values are treated the same on NULL-`work_id` rows.
2. Store-root legacy allowlist is only three basenames. SQL-planted contained UTF-8 files outside that set can still be read. Not reachable from `/api/ingest` / collect.
3. NULL `work_id` on a former v2 row would skip hash-check and skip reconcile.
4. `/api/document/{id}/review` still 200-empties on reader failure. Not an exfil hole; it can hide quarantine/escape from the document panel.
5. `kgstore.py` remains far above the 250 pure-LOC ceiling (pre-existing). This repair removed the hash compare; it did not split the module.
6. Plan Task 1 close-out (commit `fix(ingestion): preserve safe legacy provenance reads`, `step6-evidence-index.md`, independent reviews, exact full-suite on committed bytes) is **not** done. Out of this DoneClaim.

## Why not another verdict

- `false-positive`: mutation RED is the exact historical error string; HTTP QA1 is a real 200 with extraction, not a silent empty success.
- `needs-fix`: no reproduced leak, no weakened v2/path check, no failing required suite.
- `needs-human-review`: dirty worktree is real but isolated by hashes + mutation + disposable HTTP; it does not make the repair unverifiable.

## Stop condition

This file is the only write. One strict verdict: `confirmed`.
