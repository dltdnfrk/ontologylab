# Task 1 adversarial security review

Date: 2026-08-23
Reviewer: omo senpi-task `st_01a02e6b`
Lane: path containment, sensitive-file denial, staged/quarantined refusal, v2 hash checks, legacy `work_id`-NULL compatibility, transaction/savepoint atomicity, outbox truth/projection, current-batch quarantine filtering, exception disclosure, concurrent writers.

## Verdict

**PASS** — maximum severity **LOW**.

0 CRITICAL, 0 HIGH, 0 MEDIUM blockers. 6 LOW residuals, none reachable from `/api/ingest`, `/api/collect`, or `insert_document` without a prior SQL plant or store-root filesystem write.

## Bound identity

Prior receipts are claims. Current committed bytes:

| Fact | Required | Observed |
|---|---|---|
| HEAD | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` | match |
| Tree | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` | match |
| Perimeter SHA-256 | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` | match (23 Step 6 paths, sorted `path<TAB>file-sha256\n`) |
| Full-suite receipt | 2521 passed / 1 skipped / 2 xfailed | `task-1-full-suite.md` (not re-run here) |
| `ontologylab/kgstore.py` | repair blob `2226e9bf6b67952ccea38202203478a96fd5571bbb27b75045d53b8961eca22f` | match |

G007 `security-review.md` hashed `kgstore.py` as `ae0422d7…` and still described the pre-repair “real-looking sha256” oracle. That claim is stale. Committed `document_raw_text` (2186–2221) splits on `work_id is not None` → `read_ready_text`; legacy NULL-`work_id` ready rows decode after `resolve()` + `is_relative_to(store_root)` + basename denylist `{sources.json, providers.json, .env}` and **do not** compare `content_hash`. That is the Task 1 contract, not a regression of v2 integrity.

Canonical authority used: analysis §5 D12/D13 and invariants 5–6, 11; blueprint Step 6 / F2 / F4 / F5. Section 0 wins.

## Threat hypotheses and probes

Sentinels: `ELS-must-never-surface-9f3a` (`sources.json` / `providers.json`), `SECRET-xyz-must-never-surface` (outside secret / `.env`). Disposable roots under `/tmp/ontologylab-wave21-task1-sec-*` only. HTTP via FastAPI `TestClient` (real ASGI + Host/CSRF middleware; no bind). Library via `.venv/bin/python` against those roots.

| ID | Hypothesis | Probe | Result |
|---|---|---|---|
| H-PATH-1 | Caller `raw_text_path` is stored and later read, exfiling store secrets or `/etc/passwd` | `contain_source_path` + `ingest_item` with `/etc/passwd`, `../secret.txt`, `sources.json`, `providers.json`, `.env`, staging symlink to outside secret; HTTP `POST /api/ingest` `raw_text_path=sources.json` (unique hash) | **REFUTED.** Write-side `PathEscapeError`; zero planted `documents.raw_text_path`. HTTP 400 `error=PathEscapeError`, sentinel absent. Persisted path is always `documents/{id}/raw.txt` or `""`. |
| H-PATH-2 | v2 reader follows `..` / absolute / store-root names | `contained_documents_path` on `/etc/passwd`, `../secret.txt`, `sources.json`, `documents/../sources.json`; planted v2 row `raw_text_path=sources.json` | **REFUTED.** `PathEscapeError` / `KGStoreError: raw_text_path escapes documents/`. No sentinel. |
| H-PATH-3 | Legacy reader follows symlink to `sources.json` | SQL-planted NULL-`work_id` ready row at `documents/leg-link/raw.txt` → symlink to `sources.json` | **REFUTED.** `resolve()` then basename denylist: `legacy raw_text_path escapes safe storage`. No sentinel. |
| H-SENS-1 | Legacy planted `sources.json` / `providers.json` / `.env` / abs / `../secret` are readable | `document_raw_text` on each plant | **REFUTED.** Typed `legacy raw_text_path escapes safe storage`. No sentinel in exception text. |
| H-SENS-2 | `/api/collect` can ingest `data_dir/sources.json` and mail keys | HTTP collect `files=[sources.json]` | **REFUTED.** 200 `{error_kind: rejected}`; sentinel absent. `check_collect_file` refuses the entire store interior. |
| H-STATE-1 | Staged / quarantined bytes are served | v2 read before finalize; legacy plants `representation_state=staged\|quarantined` with contained files | **REFUTED.** `representation … is staged` / `is quarantined`. `work_snapshot` preferred id is None until ready (`test_document_view_reads_ready_bytes_only`). |
| H-HASH-1 | Task 1 repair disabled v2 ready hash | Finalize, one-byte tamper, live read; close/reopen | **REFUTED.** Live `KGStoreError: hash_mismatch` (no body/sentinel). Reopen reconcile → `quarantined`; NULL-`work_id` synthetic-hash row stays `ready` and still returns its own text. |
| H-HASH-2 | Eager ingest hash mismatch leaves domain/outbox rows | `ingest_item` with wrong `content_hash` | **REFUTED.** `failed` `FileIntegrityError`; works/documents/observations/assertions/outbox counts unchanged. |
| H-LEG-1 | Synthetic `sha256:`+`d*64` legacy rows still raise `legacy raw text hash mismatch` | `insert_document` (NULL `work_id`) + `document_raw_text` / provenance | **REFUTED (intended).** Bytes returned. Focused test `test_legacy_provenance_reads_when_hash_metadata_is_synthetic` green. |
| H-TX-1 | Service COMMIT/ROLLBACK tears caller unit; hash fail leaves partials | Committed tests + probe counts; `authority_repo` / `ingestion_service` / `provenance_outbox` never COMMIT/ROLLBACK the caller | **REFUTED.** SAVEPOINT `ingestion_service_v2` + nested `attach_identifier`. `KGStore.close` does not commit; uncommitted collect raise rolls back. |
| H-OUT-1 | Torn/tampered `provenance.jsonl` is treated as truth | Overwrite JSONL with `{not-json` + sentinel; `project_outbox` | **REFUTED.** Rebuild from SQLite `provenance_outbox`; sentinel gone; `observation.recorded` present. `mirrored_ts` only after durable replace. |
| H-Q-1 | Pre-existing quarantined representation fails a later good collect | Quarantine old v2 row, then `ingest_documents` of a new `RawDocument` | **REFUTED.** `created_count=1`. `finalize_shadow_writes` raises only if a **current** id is quarantined. |
| H-Q-2 | Current-batch `.part` tamper is accepted as ready | `shadow_persist` then corrupt matching `.part` then `finalize_shadow_writes` | **REFUTED.** `FileIntegrityError: shadow file finalization quarantined: rep-…`. No sentinel. |
| H-EXC-1 | HTTP/CLI surfaces echo exception text / file bytes | Provenance GET on planted `sources.json` source doc; review GET; unknown `work_id`; Host/CSRF; collect reject | **REFUTED as leak.** Provenance 400 `legacy raw_text_path escapes safe storage`; review 200 `text=""` (swallow, no secret); unknown work 404 `error=unknown_work` (no `unknown work_id`); Host 421; CSRF 403; collect rejected without sentinel. In-process `IngestReceipt.error` still `Type: message`; `receipt_to_dict` strips it. |
| H-CONC-1 | Concurrent writers duplicate Works, drop sentinels, or omit outbox | `tests/test_ingest_concurrency.py` (barrier threads, 5s join, no sleeps) | **REFUTED.** 8/8 passed in the focused run. Family → one Work / two Observations; second DOI one typed conflict; failpoint leaves no dangling assertion; unrelated sentinel survives. |

## Focused suite (this review)

```
.venv/bin/python -m pytest \
  tests/test_document_view.py tests/test_file_lifecycle.py \
  tests/test_provenance_api.py tests/test_provenance_outbox.py \
  tests/test_ingest_concurrency.py tests/test_ingestion_service.py \
  tests/test_ingestion_surfaces.py tests/test_error_disclosure.py \
  --override-ini='addopts=' --tb=no -q
```

`93 passed, 1 warning in 1.63s` EXIT 0. Warning is third-party Starlette/FastAPI `httpx` deprecation, not a product file.

Disposable probe: 40 PASS / 3 RESIDUAL / 0 FAIL (library + TestClient). Follow-up unique-hash HTTP ingest: 400 `PathEscapeError`, `leak=false`.

## LOW residuals (non-blocking)

### L1 — Legacy reader is store-root + three basenames

A SQL-planted NULL-`work_id` **ready** row whose path is any other UTF-8 file under the data dir (observed: `provenance.jsonl`) is decoded. Not reachable from ingest/collect/`insert_document` (those paths are `documents/{id}/raw.txt` or refused). Same residual class G007 already logged.

### L2 — Basename denylist is case-sensitive

On this APFS volume, planted `raw_text_path=SOURCES.JSON` resolved to the same inode as `sources.json` and returned the sentinel. Still SQL-plant only. HTTP/CLI cannot persist that column.

### L3 — `work_id IS NULL` skips v2 hash and startup reconcile

`reconcile_files` is `work_id IS NOT NULL AND (staged OR documents/% + hash length 71)`. SQL `UPDATE documents SET work_id=NULL` on a former v2 row made a one-byte tamper readable. Ingest/HTTP always assign a Work. Reconcile still scopes to v2.

### L4 — `/api/document/{id}/review` 200-empties reader failure

`document_review_context` swallows `KGStoreError` → `text=""`. Observed on planted `leg-src`: HTTP 200, empty text, no sentinel. Honesty gap for the document panel, not exfil. Pre-existing.

### L5 — In-process receipts keep raw `Type: message`

`ingest_item` `except Exception` returns `FileIntegrityError: …` / `InvalidIngestItem: unknown work_id: …`. CLI/HTTP/shadow map to tokens (`invalid_item`, `unknown_work`, `PathEscapeError`, `internal_error`). Collect unexpected exceptions are `internal_error` (`main.py:601-604`, `routes.py:1961-1963`).

### L6 — Eager hash-mismatch leftover `.part`

Mismatch raises before `staged_paths.append`, so `_discard_staged` misses the file until the next `reconcile_files` orphan cleanup. Bytes are the caller’s payload, not a store secret.

## Controls that hold on committed bytes

- **Path / symlink (write):** `contain_source_path` rejects absolute, `..`, store-root names, and staging symlink escapes. Caller path is never the stored column (`test_caller_path_is_never_persisted`).
- **Path (v2 read):** `contained_documents_path` is `documents/`-only after `resolve()`, with explicit symlink-escape check.
- **Path (legacy read):** store-root `is_relative_to` + `{sources.json, providers.json, .env}` + ready-only. Catch is `(FileLifecycleError, OSError, UnicodeDecodeError)` → `KGStoreError(str(exc))`; never returns file bytes.
- **Collect data-dir:** entire store interior refused before read (`check_collect_file`).
- **v2 hash / ready-only:** `read_ready_text` re-hashes; staged/quarantined raise `FileNotReady`. Startup `KGStore.open` reconciles then `project_outbox` then commits if a tx is open.
- **Legacy compatibility:** NULL-`work_id` synthetic hashes readable; unsafe paths still typed-refuse.
- **Transactions:** service/shadow/outbox/authority are SAVEPOINT-scoped and do not COMMIT/ROLLBACK the caller. Surfaces commit, then reconcile/project. `insert_document` still self-commits (legacy path; collect/shadow no longer call it).
- **Outbox:** SQLite is truth; JSONL is atomic rebuild + event-id dedupe; `mirrored_ts` after replace; malformed payload fails closed (`test_malformed_payload_fails_closed`).
- **Current-batch quarantine:** filter is `decision.representation_id in current_ids`.
- **Exception / CSRF / DNS rebinding:** ingest surfaces sanitize; collect `internal_error`; Host 421; cross-site POST 403. Product bind remains loopback / no-auth.
- **Concurrency:** fixture-bound IMMEDIATE writers; UNIQUE reservation; typed conflict; no sentinel loss.

## What was not re-run

- Exact full `.venv/bin/python -m pytest` (2521/1/2). Bound to `task-1-full-suite.md` on this same HEAD/tree/perimeter.
- G008 mutants m1–m3 kill/restore (prior evidence; containment/staged/path tests are green on current bytes).
- Live `ontologylab.serve` listener. TestClient is the same app factory + middleware.
- Multi-process writers. F2 tests use threads + `ConcurrencyBarrier` on one WAL file, which is the committed fixture contract.

## Confidence

`0.90`

Not 0.95: HTTP was TestClient not a bound socket; F2 is threaded not multi-process; L2 is real on macOS and would matter if a SQL injection ever appeared (none found in the new filters — they are constants / bound parameters).

## Blockers

None.

## Protected-boundary cleanup

- No read/write of `~/Library/Application Support/ontologylab/`.
- No external network.
- Port 8799 / PID 55560 **read-only** before and after: same DEVICE `0x1ff51c806b197195`, same start `Thu Aug 6 13:51:44 2026`, same argv (`serve --port 8799 --data-dir …/Application Support/ontologylab/data`).
- Disposable probe roots deleted (`tmp_exists=false`). `/tmp/ontologylab-wave21-task1-sec-probe.py` removed after the run. No leftover listeners.
- No product/test/plan/canonical edits. No commit/push. Working tree product/test clean except pre-existing `?? ontologylab/graphify-out/`.
- This file is the only write.

## Stop

Strict verdict: **PASS**. Maximum severity: **LOW**.
