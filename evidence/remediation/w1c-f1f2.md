# W1C F1/F2 extraction job remediation evidence

Date: 2026-08-14
Task: `st_01a00287`

## Decision and backend contract

The job terminal status for a handled chunk failure is now **`failed`**. This is the smallest-blast-radius choice because the durable `extraction_runs.status` already uses `failed`, `failed` is already in `TERMINAL_STATUSES`, and every browser transition consumer already handles it. No new status value was introduced.

The HTTP jobs API and SSE payload now receive:

```json
{
  "status": "failed",
  "error": "extraction engine failed",
  "progress": ["... engine error on <doc>#<chunk>: extraction engine failed", "... extraction failed: extraction engine failed"]
}
```

The raw engine exception remains in the job's on-disk `provenance.jsonl` and is absent from `Job.as_status()`.

## Baseline characterization before production edits

Command:

```text
.venv/bin/python -m pytest \
  tests/test_partial_chunk_failure.py::test_fully_successful_extraction_job_ends_complete \
  tests/test_partial_chunk_failure.py::test_engine_factory_failure_is_redacted_and_failed \
  tests/test_partial_chunk_failure.py::test_retry_only_reinvokes_failed_chunk_without_duplicates -v
```

Output:

```text
collected 3 items
tests/test_partial_chunk_failure.py ... [100%]
3 passed in 0.90s
```

This pins: full success -> `complete`; engine-factory failure -> `failed` with `error: "extraction engine failed"`; retry invokes only failed chunk, attempts are `[1, 2, 1, 1]`, and proposals/citations are not duplicated.

## Failing-first proofs

### False success

```text
FAILED tests/test_partial_chunk_failure.py::test_partial_chunk_failure_job_status_matches_durable_run
>       assert job.status != "complete"
E       AssertionError: assert 'complete' != 'complete'
E        + where 'complete' = Job(... error=None ...).status
1 failed in 0.83s
```

The test had already read durable run status `failed` and chunk 1 as `failed/engine_error`; the first assertion exposed the API job's false `complete`.

### Raw chunk error disclosure

```text
FAILED tests/test_error_disclosure.py::test_chunk_engine_error_is_redacted_from_job_status
>       assert SECRET not in payload
E       assert 'ELS-must-never-surface-9f3a' not in '{...}'
E         'ELS-must-never-surface-9f3a' is contained here:
E           alid/?key=ELS-must-never-surface-9f3a", "[ontologylab] ...
1 failed in 1.18s
```

## Mutation checks

### Revert job status mapping only

Mutated the `chunk_failed` terminal branch back to `complete`, kept tests, then restored `ontologylab/server/jobs.py`:

```text
>       assert job.status != "complete"
E       AssertionError: assert 'complete' != 'complete'
FAILED tests/test_partial_chunk_failure.py::test_partial_chunk_failure_job_status_matches_durable_run
1 failed in 0.21s
status mutation test exit=1 (expected nonzero); restored jobs.py
```

### Revert chunk redaction only

Mutated the chunk progress line back from `ENGINE_FAILURE_SUMMARY` to `{exc}`, kept tests, then restored `ontologylab/extractor.py`:

```text
>       assert SECRET not in payload
E       assert 'ELS-must-never-surface-9f3a' not in '{... "error": "extraction engine failed"}'
E         'ELS-must-never-surface-9f3a' is contained here:
E           alid/?key=ELS-must-never-surface-9f3a", "[ontologylab] ...
FAILED tests/test_error_disclosure.py::test_chunk_engine_error_is_redacted_from_job_status
1 failed in 0.71s
disclosure mutation test exit=1 (expected nonzero); restored extractor.py
```

## Consumer-impact grep

Commands:

```text
rg -n 'job\.status|status == "(running|complete|failed|cancelled)"|status in TERMINAL_STATUSES|TERMINAL_STATUSES' ontologylab --glob '*.py'
rg -n 'job\.status|j\.status|prev === "running"|statusKo\(job\.status\)' web/app.js
```

Results:

- `ontologylab/server/jobs.py`: `TERMINAL_STATUSES` already contains `failed`; running-job selection and eviction already recognize it.
- `ontologylab/server/routes.py:2286`: cancellation reports an already-terminal status generically.
- `web/app.js:2334`: explicitly handles the `running -> failed` transition.
- `web/app.js:1899,2258,2294,2323-2357,4215,4726-4737`: running/terminal rendering and status badges already accept `failed`.
- Therefore no consumer receives an unhandled status value. A distinct `completed_with_failures` value would have bypassed the explicit browser transition branches and terminal set.

## Manual QA through live HTTP API

Disposable data directory: `/private/tmp/ontologylab-w1c-qa-84163`
Ephemeral endpoint: `127.0.0.1:52099`
Server PID: `84183`
Protected port 8799 was not touched (PID 55560 remained listening).

The live app used a stub engine wrapping `MockEngine` and raising exactly once on call/chunk 1 with:

```text
request failed url=https://example.invalid/?key=SYNTHETIC_SECRET
```

POST response:

```http
HTTP/1.1 202 Accepted
content-type: application/json

{"job_id":"extract-20260815-081017","status":"running"}
```

Single terminal GET with `curl -sS -i http://127.0.0.1:52099/api/jobs/extract-20260815-081017`:

```http
HTTP/1.1 200 OK
content-type: application/json

{"job_id":"extract-20260815-081017","kind":"extract","status":"failed","phase":"","engine":"mock","model":null,"started_ts":1786749017.63287,"finished_ts":1786749017.6605492,"totals":{"nodes_new":2,"nodes_merged":4,"edges_new":2,"edges_merged":1},"progress":["[ontologylab] 326e14726f2e4064877a989a052b02e5#0: +2 nodes (+0 merged), +1 edges","[ontologylab] engine error on 326e14726f2e4064877a989a052b02e5#1: extraction engine failed","[ontologylab] 326e14726f2e4064877a989a052b02e5#2: +0 nodes (+2 merged), +0 edges","[ontologylab] 326e14726f2e4064877a989a052b02e5#3: +0 nodes (+2 merged), +1 edges","[ontologylab] extraction failed: extraction engine failed"],"steps":[],"sources":[],"error":"extraction engine failed"}
```

Binary disclosure check:

```text
grep 'SYNTHETIC_SECRET\|example.invalid' curl-status.txt
# no matches
```

SQLite query:

```sql
SELECT r.status AS run_status, c.chunk_index, c.status AS chunk_status,
       c.attempts, c.error_kind
FROM extraction_runs r
JOIN extraction_chunks c ON c.run_id=r.id
ORDER BY c.chunk_index;
```

Output:

```text
run_status  chunk_index  chunk_status  attempts  error_kind
----------  -----------  ------------  --------  ------------
failed      0            succeeded     1
failed      1            failed        1         engine_error
failed      2            succeeded     1
failed      3            succeeded     1
```

The API job and durable extraction run both say `failed`.

## Adversarial probes

- **Misleading success output:** fixed and covered by failing-first status test plus live HTTP/SQLite comparison; final progress now says extraction failed rather than done.
- **Cancel/resume:** all 16 existing `tests/test_job_cancel.py` tests passed with the new status tests; explicit cancellation still wins through non-empty `stopped_reason` and remains `cancelled`.
- **Stale state:** retry test verifies only failed chunk is called again, attempts `[1,2,1,1]`, unchanged proposal counts, and no duplicate citation groups.
- **Repeated interruptions:** immediate retry after the one-chunk failure completes and changes only the failed chunk's attempt count.
- **Malformed input:** `test_off_schema_chunk_output_marks_job_and_run_failed` verifies `parse_rejected` produces job/run `failed` with the same generic public error.

## Automated verification

The requested `timeout` executable is not installed on this Darwin workstation (`/bin/bash: timeout: command not found`). The same 900/1800-second bounds were enforced with `subprocess.run(..., timeout=...)`.

Targeted command covered the real extraction-state filename (`tests/test_extraction_lifecycle.py`) and the new status file:

```text
.venv/bin/python -m pytest tests/test_error_disclosure.py \
  tests/test_partial_chunk_failure.py tests/test_extraction_lifecycle.py \
  tests/test_e2e_mvp.py tests/test_pipeline_e2e.py -v

40 passed, 1 warning in 2.10s
```

Full suite, once:

```text
.venv/bin/python -m pytest
2265 passed, 6 skipped, 1 warning in 1353.50s (0:22:33)
```

No regressions or pre-existing failures were observed. The warning is the existing FastAPI/Starlette `httpx` deprecation warning.

Language-server diagnostics: no errors in all four changed source/test files; no diagnostics in the two production files.

## Cleanup receipt

```text
PID 84183 terminated
removed /private/tmp/ontologylab-w1c-qa-84163
```

Final checks found no `/private/tmp/ontologylab-w1c-qa-*` directories and no PID 84183. Port 8799 remained owned by protected server PID 55560 throughout.
