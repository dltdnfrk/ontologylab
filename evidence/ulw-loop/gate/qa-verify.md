# OntologyLab ulw-loop gate verification

Independent re-verification of adversarial QA claims in `evidence/ulw-loop/`.
Did not trust artifact prose; reproduced or inspected each required check.
Edited nothing except this report. No commits. Never bound or touched port 8799.
Never touched protected PID 55560 (`ontologylab.serve`) or PID 70970 (`uvicorn search_server`).

Verifier: omo senpi-task `st_01a00b73` on 2026-08-16 (local).
Working tree `ontologylab/server/routes.py` was already dirty (`M`) with the
`InvalidateAction` fix; mutation cycle restored it byte-identical.

## 1. Artifact integrity

Every `evidence/ulw-loop/g0*` file exists and is non-empty.
JSON files parse with `json.load`. Extra file `g003-fullsuite.log` is present
(not in the `json|txt|md` glob) and is also non-empty.

| path | bytes | empty | json |
|---|---:|---|---|
| evidence/ulw-loop/g001-red.txt | 4296 | no | n/a |
| evidence/ulw-loop/g002-green.txt | 1576 | no | n/a |
| evidence/ulw-loop/g002-mutation.txt | 4878 | no | n/a |
| evidence/ulw-loop/g003-fullsuite.log | 3114 | no | n/a |
| evidence/ulw-loop/g004-curl.txt | 617 | no | n/a |
| evidence/ulw-loop/g005-f6.json | 96186 | no | ok |
| evidence/ulw-loop/g006-f1ui.json | 12600 | no | ok |
| evidence/ulw-loop/g007-f5.json | 16828 | no | ok |
| evidence/ulw-loop/g008-f7ui.json | 76361 | no | ok |
| evidence/ulw-loop/g009-f4.md | 26662 | no | n/a |
| evidence/ulw-loop/g010-f3.md | 8412 | no | n/a |
| evidence/ulw-loop/g011-f1f2.txt | 8277 | no | n/a |
| evidence/ulw-loop/g012-newprobes.json | 35290 | no | ok |

Count: 13 files. 5 JSON files, all parse. Step 1: **passed**.

## 2. Core fix + mutation

### 2a. Baseline (working tree with InvalidateAction)

Command: `.venv/bin/python -m pytest tests/test_bitemporal.py -k invalidate -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/hyunjun/Documents/MUNI/ontologylab
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 10 items / 3 deselected / 7 selected

tests/test_bitemporal.py .......                                         [100%]

================== 7 passed, 3 deselected, 1 warning in 7.48s ==================
```

Pre-mutation `routes.py` sha256:
`b9640a525bfedecf5b9db668f21ca2003f28fef28dae0f5713f685ed67ac2107`
Working tree: `M ontologylab/server/routes.py`
Live signature: `def invalidate_edge(..., body: InvalidateAction)`

### 2b. Snapshot + checkout HEAD

```
cp ontologylab/server/routes.py /private/tmp/gate-verify.py
# snapshot sha256: b9640a525bfedecf5b9db668f21ca2003f28fef28dae0f5713f685ed67ac2107
git checkout HEAD -- ontologylab/server/routes.py
# HEAD sha256: f689be95e4c1e24823940271d55671213e3eb138565dd4d8856b4ac51927234c
# HEAD signature: def invalidate_edge(..., body: ProposalAction)
```

### 2c. Mutation pytest (must fail 422)

Command: `.venv/bin/python -m pytest tests/test_bitemporal.py -k "test_invalidate_api or test_invalidate_api_body_needs_no_id" -v`

```
collected 10 items / 8 deselected / 2 selected

tests/test_bitemporal.py FF                                              [100%]

=================================== FAILURES ===================================
_____________________________ test_invalidate_api ______________________________
>       assert res.status_code == 200 and res.json()["ok"] is True
E       assert (422 == 200)
E        +  where 422 = <Response [422 Unprocessable Entity]>.status_code
tests/test_bitemporal.py:233: AssertionError

_____________________ test_invalidate_api_body_needs_no_id _____________________
E       AssertionError: {"detail":[{"type":"missing","loc":["body","id"],"msg":"Field required"}]}
E       assert 422 == 200
E        +  where 422 = <Response [422 Unprocessable Entity]>.status_code
tests/test_bitemporal.py:260: AssertionError

FAILED tests/test_bitemporal.py::test_invalidate_api - assert (422 == 200)
FAILED tests/test_bitemporal.py::test_invalidate_api_body_needs_no_id
================== 2 failed, 8 deselected, 1 warning in 0.26s ==================
MUTATION_EXIT=1
```

Both invalidate API tests failed with HTTP 422, matching g002-mutation.txt.

### 2d. Restore

```
cp /private/tmp/gate-verify.py ontologylab/server/routes.py
diff -q ontologylab/server/routes.py /private/tmp/gate-verify.py
# no output; DIFF_Q_RC=0 (byte-identical)
# both sha256: b9640a525bfedecf5b9db668f21ca2003f28fef28dae0f5713f685ed67ac2107
# restored signature: def invalidate_edge(..., body: InvalidateAction)
```

### 2e. Post-restore pytest

Command: `.venv/bin/python -m pytest tests/test_bitemporal.py -k invalidate -v`

```
collected 10 items / 3 deselected / 7 selected

tests/test_bitemporal.py .......                                         [100%]

================== 7 passed, 3 deselected, 1 warning in 0.35s ==================
RESTORE_EXIT=0
```

Step 2: **passed**.

## 3. UI honesty claims (cheap pytest)

Command:

```
.venv/bin/python -m pytest \
  tests/test_ui_failure_honesty.py \
  tests/test_partial_chunk_failure.py \
  tests/test_pack_discovery_validation.py \
  tests/test_mcp_input_contract.py \
  tests/test_mcp_pack_integrity.py
```

```
...............................................................          [100%]
63 passed, 1 warning in 1.99s
```

Step 3: **passed**.

## 4. Live spot-check (real surface)

Seeded disposable KG at `/private/tmp/gate-verify/{data,packs}` using
`tests.conftest.insert` + `tests.factories.make_entity` / `make_relation` +
`KGStore.open(kg_db_path(data))`. Approved both nodes, then the edge.

```
approved node ApiGateway=f8fca3453c60437c899e55555d4de055
approved node RateLimiter=c454c18e124c45589751e8db68bf1b61
EDGE_ID=7aa9478adcf749f29699f77c8d331c6e
edge status=verified invalidated_ts=None
SEED_OK
PORT=53284
SERVER_PID=86198
```

Readiness: 22 refused connections, then `READY try=23 http=200` on `GET /`.
Capped at 100 tries; exited on first success. Port 53284 != 8799.

Live call:

```
curl -i -X POST http://127.0.0.1:53284/api/edges/7aa9478adcf749f29699f77c8d331c6e/invalidate \
  -H "Content-Type: application/json" \
  -d '{"note":"gate-verify"}'
```

```
HTTP/1.1 200 OK
date: Sun, 16 Aug 2026 16:45:39 GMT
server: uvicorn
content-length: 139
content-type: application/json

{"ok":true,"id":"7aa9478adcf749f29699f77c8d331c6e","invalidated_ts":1786898739.819859,"invalidated_by":"local-user","reason":"gate-verify"}
CURL_RC=0
```

HTTP 200 and `ok: true`. Reproduces g004-curl.txt claim on a fresh KG.

Cleanup of this server:

```
kill 86198
# still alive after SIGTERM wait -> SIGKILL
# later: PID 86198 gone; nothing listening on 53284
rm -rf /private/tmp/gate-verify
TMP_REMOVED
```

Protected processes still alive after cleanup:

```
55560  ontologylab.serve --host 127.0.0.1 --port 8799 ...
70970  uvicorn search_server:app --host 127.0.0.1 --port 8400
```

Step 4: **passed**.

## 5. Stray state

### From this verification run

- Extra `ontologylab.serve` PID 86198: gone (`ps -p 86198` fails).
- Port 53284: nothing listening.
- `/private/tmp/gate-verify`: removed.
- `/private/tmp/gate-verify.py` snapshot: removed after restore/`diff -q`.
- No serve process other than protected 55560.
- PID 70970 left untouched.

Post-run serve inventory (`ps` + `lsof`):

```
55560  ontologylab.serve --host 127.0.0.1 --port 8799   (PROTECTED, not touched)
70970  uvicorn search_server:app --host 127.0.0.1 --port 8400  (untouched)
```

`lsof -nP -iTCP:8799 -sTCP:LISTEN` still only PID 55560.

`routes.py` after all steps: still
`b9640a525bfedecf5b9db668f21ca2003f28fef28dae0f5713f685ed67ac2107`
and still `M` (same dirty working-tree state as before this gate).

### Pre-existing `/private/tmp/ulw-*` (not created by this gate)

These were already present before verification (mtime Aug 15–16). This gate
did not create, modify, or delete them.

```
/private/tmp/ulw-ckpt.json            34054  Aug 16 16:10
/private/tmp/ulw-g003-fullsuite.log    3114  Aug 16 16:31
/private/tmp/ulw-handoff.json         28895  Aug 16 16:07
/private/tmp/ulw-proposals-1.json      7983  Aug 16 16:04
/private/tmp/ulw-proposals-all.json   21308  Aug 16 16:06
/private/tmp/ulw-proposals-fixed.json 20208  Aug 16 16:06
/private/tmp/ulw-steer-out.json      178872  Aug 16 16:07
/private/tmp/ulw-qa/                  empty dir  Aug 17 00:00
/private/tmp/ulw-qa2/                 empty dir  Aug 17 00:00
/private/tmp/ulw-qa3/                 empty dir  Aug 15 00:00
/private/tmp/ulw-qa4/                 empty dir  Aug 15 00:00
/private/tmp/ulw-qa5/                 empty dir  Aug 17 00:00
/private/tmp/ulw-qa6/                 empty dir  Aug 17 00:00
```

Hygiene note only: the original ulw-loop left `/private/tmp/ulw-*` files.
They are not stray state from this gate run. Left in place (constraint: edit
nothing except this report).

Step 5 (this run): **passed**. Pre-existing leftovers recorded, not owned here.

## Verdict

| step | result |
|---|---|
| 1 artifact integrity | passed |
| 2 invalidate tests + mutation 422 + restore identical + green | passed |
| 3 UI/MCP honesty pytest (63 passed) | passed |
| 4 live POST /api/edges/<id>/invalidate -> 200 ok:true | passed |
| 5 no extra serve; this run cleaned; 55560/70970 untouched | passed |

STATUS: passed
