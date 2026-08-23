# Task 1 reviews — Step 6 real-surface QA

Date: 2026-08-23
Worker: omo senpi-task `st_01a02e6a`
Mode: independent real-surface reproduction on fresh disposable fixtures.
No product/test/plan/canonical edits. No commit. No push. No network.
No live Application Support open. Port 8799 / PID 55560 not mutated.

## Verdict

`PASS`

Confidence: `0.94`

Every required Step 6 surface on committed bytes behaved as specified:
direct `ingest_item` staged then ready; installed CLI ingest/collect and
installed HTTP collect/sample returned typed receipts; research
`ingest_documents` plus HTTP provenance returned extraction + excerpt;
contained legacy rows with synthetic `sha256:`+`d*64` read; v2 one-byte
tamper was `hash_mismatch` live-open and HTTP 400 quarantined after reopen;
unsafe legacy paths and staged rows refused typed with zero secret leak;
torn/malformed/failpoint outbox left prior domain state and rebuilt JSONL
from SQLite. Temp roots, the 19173 listener, and PID 70821 are gone. PID
55560 / `127.0.0.1:8799` are byte-identical before and after.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` |
| Tree | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` |
| Subject | `feat(ingestion): complete transactional v2 shadow service` | match |
| Perimeter SHA-256 | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` | match before and after QA |
| Full-suite receipt | 2521 passed / 1 skipped / 2 xfailed | `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-1-full-suite.md` (`st_01a02e51`); not re-run in this lane |
| Research seam | `jobs.py` still calls `ingest_documents` | `ontologylab/server/jobs.py:894` |

Perimeter recipe (product-commit): SHA-256 of sorted `path<TAB>file-sha256\n`
over the 23 committed Step 6 paths. Working-tree bytes of those 23 paths
matched `HEAD:` blobs. `git diff --stat -- ontologylab tests` empty after QA.

Prior executor/verifier/G007 reports were treated as claims only. This pass
reproduced the surfaces on new roots and port **19173**.

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | direct `ingest_item` | `staged` → reopen `ready`; same-key `duplicate`; counts stay 1 | `rep-b08dbb8f3016` staged then ready; retry duplicate; docs/works/obs/outbox = 1 | PASS |
| S2 | installed CLI `ingest --help` | exit 0; `--items`, `{write,queue,sample}`, `--data-dir` | exit 0; all three flags present | PASS |
| S3 | installed CLI ingest write ×2 | first `staged`/`created`; second `duplicate`; same ids | `work-5ccfdcf10a90` / `rep-9f9b317e97e1` / `obs-3237a0aded2e`; second duplicate | PASS |
| S4 | installed CLI `collect --file` | one new document + Observation + outbox | `rep-41df7894060e`; lib docs=3 obs=3 outbox=3 | PASS |
| S5 | research `ingest_documents` | one Work + Observation + outbox; DOI bound | `rep-660b392f3675` / `work-d1b28ecab157` / `10.1000/t1qa.research` | PASS |
| S6 | HTTP `POST /api/collect/sample` ×2 | 200 created then created=false; same id; one Observation | `rep-a21864842c9b`; key `collect.sample:sample://onboarding/order-system` | PASS |
| S7 | HTTP `POST /api/collect` files | 200 `{ok, documents:1, created:1, duplicates:0}` | exact that body | PASS |
| S8 | HTTP provenance legacy | 200 + `extraction.engine=claude` + PaymentGateway excerpt | 200; excerpt highlighted; synthetic hash still readable | PASS |
| S9 | HTTP provenance research | 200 + RiskEngine excerpt | 200; `The >>>RiskEngine<<< reports…` | PASS |
| S10 | HTTP provenance v2 before tamper | 200 + ready bytes | 200; excerpt `>>>v2 ready<<< body for task1 qa` | PASS |
| S11 | live-open v2 one-byte tamper | typed `hash_mismatch`; no secret | `KGStoreError: hash_mismatch`; leak=[] | PASS |
| S12 | HTTP v2 tamper after reopen | 400 quarantined; no secret | `400 {"detail":"representation rep-86ddbd6183c7 is quarantined"}` | PASS |
| S13 | unsafe abs / `../` / `sources.json` / `providers.json` / `.env` | 400 escape; no secret | all five HTTP 400 `legacy raw_text_path escapes safe storage` | PASS |
| S14 | staged legacy | 400 staged; bytes not returned | `400 representation rep-staged is staged` | PASS |
| S15 | torn / malformed / failpoint outbox | typed failure; prior domain + good JSONL remain | torn rebuilt; malformed JSONL unchanged; failpoint unmarked; replay byte-stable | PASS |
| S16 | cleanup + PID 55560 | 19173 empty; fixtures gone; 8799 unchanged | proven below | PASS |

Driver-internal `http-provenance-safe-legacy-research-v2` printed FAIL only
because it looked for the contiguous substring `v2 ready body`. The live
excerpt is span-highlighted (`>>>v2 ready<<< body`). Product response is
HTTP 200 with the ready bytes. Scored PASS from the captured body.

## Commands and outputs

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Interpreter: `.venv/bin/python` (CPython 3.12.12)
Installed scripts: `.venv/bin/ontologylab`, `.venv/bin/ontologylab-serve`
Env: `ONTOLOGYLAB_OFFLINE=1`. No `PYTHONPATH` / `PYTEST_*` / `DATA_DIR`.
HTTP port: `127.0.0.1:19173` (not 8799). Ready waited on
`Application startup complete` / `Uvicorn running` (event, no sleep).

### S1 — direct service

```
ingest_item(...) → status=staged
  work_id=work-a01cdb54a4fd
  representation_id=rep-b08dbb8f3016
  observation_id=obs-7cc27338703d
  identifier_id=wi-33bbb132ea3b
  raw_text_path=documents/rep-b08dbb8f3016/raw.txt
  representation_state=staged
  provenance_outbox=1 mirrored_ts=NULL

KGStore.open again
  representation_state=ready
  document_raw_text == staged body
  outbox.mirrored_ts set
  project_outbox #1 written=1 marked=0
  project_outbox #2 written=1 marked=0; bytes identical
  same-key retry status=duplicate; same representation_id
```

DB after ingest and after retry (unchanged):

```
documents=1 nodes=0 edges=0 works=1
document_observations=1 work_identifiers=1 identifier_assertions=1
provenance_outbox=1 shadow_ingest_queue=absent
```

### S2 / S3 / S4 — installed CLI

```
$ .venv/bin/ontologylab ingest --help
usage: ontologylab ingest [-h] --items ITEMS [--mode {write,queue,sample}]
                          [--data-dir DATA_DIR]
  --items ITEMS         JSON file of ingest items (list or single object).
  --mode {write,queue,sample}
  --data-dir DATA_DIR   Working data directory (default: ROOT/data).
EXIT=0
```

```
$ .venv/bin/ontologylab ingest --mode write \
    --items /private/tmp/ontologylab-wave21-t1qa.items.json \
    --data-dir /private/tmp/ontologylab-wave21-t1qa.lib
{"error_class":null,"error_classes":[],"ok":true,"receipts":[{
  "idempotency_key":"t1qa-cli-write",
  "identifier_id":"wi-491af338c59a",
  "observation_id":"obs-3237a0aded2e",
  "representation_id":"rep-9f9b317e97e1",
  "status":"staged","work_created":true,"work_id":"work-5ccfdcf10a90"}]}
EXIT=0
```

Same command again:

```
status=duplicate
work_id=work-5ccfdcf10a90 representation_id=rep-9f9b317e97e1
observation_id=obs-3237a0aded2e identifier_id=wi-491af338c59a
observation_created=false work_created=false
EXIT=0
```

```
$ .venv/bin/ontologylab collect \
    --file /private/tmp/ontologylab-wave21-t1qa.cli-notes.md \
    --data-dir /private/tmp/ontologylab-wave21-t1qa.lib
[ontologylab] new document rep-41df7894060e <- file:///private/tmp/ontologylab-wave21-t1qa.cli-notes.md
[ontologylab] collected 1 document(s) (1 new)
EXIT=0
```

Lib store after CLI ingest + collect:

```
documents=3 nodes=0 edges=0 works=3
document_observations=3 work_identifiers=2 identifier_assertions=2
provenance_outbox=3 shadow_ingest_queue=0
```

File collect has no DOI, so identifiers stay at 2 (direct + CLI ingest).

### S15 — outbox replay / torn / fail closed

Isolated root `/private/tmp/ontologylab-wave21-t1qa.outbox`.

Torn `provenance.jsonl` (`stale` + truncated `torn`) then `project_outbox`:

```
written=1
rebuilt event_id=sha256:6fbb2dcded6884eb6ad4d71cb8d90c88acbe186b877f250d62599c7635c3fd89
"torn" absent; "stale" absent
counts unchanged: documents=1 works=1 observations=1 outbox=1
```

Malformed payload `{not-json}`:

```
MalformedOutboxPayload: malformed payload for evt-bad
JSONL bytes unchanged
evt-bad mirrored_ts=NULL
```

Failpoint `before_durable_mirror` after a second Observation:

```
RuntimeError: armed:before_durable_mirror
JSONL bytes unchanged
new event mirrored_ts=NULL
domain counts stay documents=2 observations=2
```

Replay after the failpoint:

```
project #1 written=2 marked=1
project #2 written=2 marked=0
JSONL bytes identical
```

### S5 / S8–S14 seed (HTTP data-dir)

HTTP root `/private/tmp/ontologylab-wave21-t1qa.http` before listen:

| Row | id | work_id | state | notes |
|---|---|---|---|---|
| research | `rep-660b392f3675` | `work-d1b28ecab157` | ready | DOI `10.1000/t1qa.research`; node `fd7e86e7421047fea8c6c1b9a734c5b1` |
| legacy | `3f96cdfef1a640e199d7c2b22b991569` | NULL | ready | `content_hash=sha256:`+`d*64`; node `033e974e9aa84fdca8807f7484620e33` |
| v2 | `rep-86ddbd6183c7` | `work-ac4372b531aa` | ready | node `ffcc01c6040e4d45aae852167c0d61c6` |
| v2-live | `rep-4695b4685e13` | set | ready then live-tampered | library `hash_mismatch` |
| plants | `doc-abs` `doc-trav` `doc-src` `doc-prov` `doc-env` `rep-staged` | NULL | ready / staged | abs, `../secret`, `sources.json`, `providers.json`, `.env`, staged |

Seed counts:

```
documents=10 nodes=9 edges=0 works=3
document_observations=3 work_identifiers=3 identifier_assertions=3
provenance_outbox=3 shadow_ingest_queue=0
```

Library unsafe (same planted rows, before HTTP):

```
abs/trav/src/prov/env → KGStoreError: legacy raw_text_path escapes safe storage
staged → KGStoreError: representation rep-staged is staged
SECRET-xyz-must-never-surface / ELS-must-never-surface-9f3a not in any error
```

Live-open v2 tamper (same sqlite connection, no reopen):

```
LIVE_TAMPER_TYPED KGStoreError hash_mismatch
LIVE_TAMPER_LEAK []
```

### S6 / S7 / S8–S14 — installed HTTP

```
$ .venv/bin/ontologylab-serve --host 127.0.0.1 --port 19173 \
    --data-dir /private/tmp/ontologylab-wave21-t1qa.http \
    --packs-dir /private/tmp/ontologylab-wave21-t1qa.packs
PID 70821
INFO:     Started server process [70821]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:19173 (Press CTRL+C to quit)
```

Server log (verbatim, in order):

```
INFO:     127.0.0.1:62698 - "POST /api/collect/sample HTTP/1.1" 200 OK
INFO:     127.0.0.1:62699 - "POST /api/collect/sample HTTP/1.1" 200 OK
INFO:     127.0.0.1:62700 - "GET /api/documents HTTP/1.1" 200 OK
INFO:     127.0.0.1:62701 - "POST /api/collect HTTP/1.1" 200 OK
INFO:     127.0.0.1:62702 - "GET /api/provenance/node/033e974e9aa84fdca8807f7484620e33 HTTP/1.1" 200 OK
INFO:     127.0.0.1:62703 - "GET /api/provenance/node/fd7e86e7421047fea8c6c1b9a734c5b1 HTTP/1.1" 200 OK
INFO:     127.0.0.1:62704 - "GET /api/provenance/node/ffcc01c6040e4d45aae852167c0d61c6 HTTP/1.1" 200 OK
INFO:     127.0.0.1:62705 - "GET /api/provenance/node/ffcc01c6040e4d45aae852167c0d61c6 HTTP/1.1" 400 Bad Request
INFO:     127.0.0.1:62706 - "GET /api/provenance/node/node-abs HTTP/1.1" 400 Bad Request
INFO:     127.0.0.1:62707 - "GET /api/provenance/node/node-trav HTTP/1.1" 400 Bad Request
INFO:     127.0.0.1:62708 - "GET /api/provenance/node/node-src HTTP/1.1" 400 Bad Request
INFO:     127.0.0.1:62709 - "GET /api/provenance/node/node-prov HTTP/1.1" 400 Bad Request
INFO:     127.0.0.1:62710 - "GET /api/provenance/node/node-env HTTP/1.1" 400 Bad Request
INFO:     127.0.0.1:62712 - "GET /api/provenance/node/node-staged HTTP/1.1" 400 Bad Request
INFO:     Shutting down
INFO:     Finished server process [70821]
```

```
POST /api/collect/sample
  → 200 {"ok":true,"created":true,"document_id":"rep-a21864842c9b",
         "title":"샘플 — 우리 가게 주문 시스템"}
POST /api/collect/sample
  → 200 {"ok":true,"created":false,"document_id":"rep-a21864842c9b"}
GET  /api/documents → 200 count=11 (seed 10 + sample; collect not yet)
POST /api/collect {"files":["/private/tmp/ontologylab-wave21-t1qa.http-notes.md"]}
  → 200 {"ok":true,"documents":1,"created":1,"duplicates":0}

GET /api/provenance/node/033e974e9aa84fdca8807f7484620e33
  → 200 extraction.engine=claude model=haiku prompt_version=extract-v1
    excerpt="The >>>PaymentGateway<<< validates cards through the FraudDetector. …"
    document.title="A study of gateways"
GET /api/provenance/node/fd7e86e7421047fea8c6c1b9a734c5b1
  → 200 excerpt="The >>>RiskEngine<<< reports to the FraudDetector.\n"
GET /api/provenance/node/ffcc01c6040e4d45aae852167c0d61c6
  → 200 excerpt=">>>v2 ready<<< body for task1 qa\n"

# one-byte overwrite of documents/rep-86ddbd6183c7/raw.txt (len 27 unchanged)
GET same v2 node
  → 400 {"detail":"representation rep-86ddbd6183c7 is quarantined"}

GET /api/provenance/node/node-abs   → 400 legacy raw_text_path escapes safe storage
GET /api/provenance/node/node-trav  → 400 legacy raw_text_path escapes safe storage
GET /api/provenance/node/node-src   → 400 legacy raw_text_path escapes safe storage
GET /api/provenance/node/node-prov  → 400 legacy raw_text_path escapes safe storage
GET /api/provenance/node/node-env   → 400 legacy raw_text_path escapes safe storage
GET /api/provenance/node/node-staged → 400 representation rep-staged is staged
SECRET_LEAK=[] on every body
```

DB after HTTP (sample + file collect landed; v2 quarantined; plants untouched):

```
documents=12 nodes=9 edges=0 works=5
document_observations=5 work_identifiers=3 identifier_assertions=3
provenance_outbox=5 shadow_ingest_queue=0
v2 representation_state=quarantined
sample id=rep-a21864842c9b
sample source_uri=sample://onboarding/order-system
sample work_id=work-38a8b53bd6a3
sample idempotency_key=collect.sample:sample://onboarding/order-system
```

Delta vs seed: +2 documents, +2 works, +2 observations, +2 outbox (sample +
HTTP file collect). Nodes stay 9. Queue stays 0. Identifier count stays 3
because sample/file collect have no DOI.

## Protected boundary

Photographed before QA, after server shutdown, and after fixture removal.
`lsof` DEVICE `0x1ff51c806b197195` and `ps` argv/start time are identical:

```
COMMAND     PID    USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
python3.1 55560 hyunjun   10u  IPv4 0x1ff51c806b197195      0t0  TCP 127.0.0.1:8799 (LISTEN)
55560 Thu Aug  6 13:51:44 2026
.venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 8799
  --data-dir /Users/hyunjun/Library/Application Support/ontologylab/data
  --packs-dir /Users/hyunjun/Library/Application Support/ontologylab/packs
```

No Application Support file was opened. No external network. No 8799 bind,
kill, or retarget.

## Cleanup

```
kill/wait PID 70821 → process gone; lsof :19173 empty
rm -rf /private/tmp/ontologylab-wave21-t1qa.lib
       /private/tmp/ontologylab-wave21-t1qa.http
       /private/tmp/ontologylab-wave21-t1qa.packs
       /private/tmp/ontologylab-wave21-t1qa.outbox
rm -f  /private/tmp/ontologylab-wave21-t1qa.driver.py
       /private/tmp/ontologylab-wave21-t1qa.secret.txt
       /private/tmp/ontologylab-wave21-t1qa.cli-notes.md
       /private/tmp/ontologylab-wave21-t1qa.http-notes.md
       /private/tmp/ontologylab-wave21-t1qa.items.json
       /private/tmp/ontologylab-wave21-t1qa.results.json
ls /private/tmp/ontologylab-wave21-t1qa* → none
pgrep port 19173 / t1qa → none
```

This file is the only write under the repo.

## Findings / residuals (not blockers)

1. Legacy `content_hash` is intentionally not an integrity oracle on
   `work_id IS NULL` rows. Synthetic and real sha256-shaped values read the
   contained file. v2 (`work_id is not None`) still goes through
   `read_ready_text`.
2. Legacy path allowlist is store-root + `{sources.json, providers.json, .env}`.
   HTTP ingest/collect assign `work_id` and cannot enter that branch.
3. Full suite was not re-executed here. Identity is bound to the
   `st_01a02e51` receipt on the same HEAD/tree/perimeter.

## Blockers

none

## Stop condition

This file is the only write. One strict verdict: `PASS`.
