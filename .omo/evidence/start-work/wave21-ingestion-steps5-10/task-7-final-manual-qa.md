# Task 7 final independent manual QA

Date: 2026-08-24
Worker: omo senpi-task `st_01a030be`
Mode: independent hands-on QA on committed HEAD. Installed CLI,
`python -m ontologylab.serve`, live curl HTTP, direct H1
classify/materialize/finalize. No product/test/plan edits. No stage,
commit, or push. No external network. No live Application Support open.
Port 8799 / PID 55560 observe-only. Denylist unread / unopened /
unhashed.

## Verdict

`PASS` (report-only perimeter correction; surfaces not re-run)

Committed Step 7 on `362b0a679483139e51d8e37748674a867d6a9b2f`
(`fix(extraction): preserve exact receipt identity`) reproduced the
required real surfaces:

- CLI help + happy grounded approve + typed invalid `migrate-h1`
- Live FastAPI extract citation-bind `AMBIGUOUS` with zero citation writes
- Live HTTP approve idempotency + `grounded_review_current` pointer
- Live HTTP tampered-nonapproval: approve 409 / zero-write; reject and
  compensate append pack-ineligible decisions on the current pointer
- Direct H1 classify/materialize/finalize: colliding stale twins keep the
  live waiver; missing citation family classifies `missing_span`;
  indistinguishable tips finalize `ungrounded` and do not mint

Disposable roots and QA listeners are gone. PID 55560 inode/device
`0x1ff51c806b197195` is unchanged.

## Authority actually read (not summaries)

- Canonical Step 7 kickoff:
  `.omo/ulw-loop/wave21-step6-ingestion-service-20260821/step7-kickoff.md`
- Plan Task 7 close criteria:
  `.omo/plans/wave21-ingestion-steps5-10.md` (Task 7; not edited)
- Blueprint owner: Step 7 owns C-024/F9, C-032 grounding, H1 rehearsal
  (`.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md`
  §0.1–0.3; read only)
- Final code review: `task-7-review-code-final.md` **PASSED**
- Final security review: `task-7-review-security-final.md` **PASSED**
- Repair commit verifier: `task-7-review-repair-commit-verifier.md`
  **CONFIRMED** commit `362b0a6`, tree `dce1386`, required `LC_ALL=C`
  21-path record perimeter
  `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b`.
  Locale-sort digest
  `1eac91b2b3a58bbd61a013c9b42fba9832b03621b76e53118a023cd543ec2ea7`
  is superseded and untrusted (bare `sort`, not `LC_ALL=C`).
- Final full suite: `task-7-final-full-suite.md`
  `2650 passed, 1 skipped, 2 xfailed`, exit 0, perimeter
  `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867`

This run did **not** re-execute the full suite. It exercised user
surfaces against the committed bytes.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `362b0a679483139e51d8e37748674a867d6a9b2f` | match before and after |
| Subject | `fix(extraction): preserve exact receipt identity` | match |
| Parent | `5a6378964bfc41fe2a679453a88235c548a59f4b` | match (`git log -1`) |
| Tree | `dce1386961684e924108ded625e56dab4031384d` | match |
| Owned 21 paths vs HEAD | clean | `git diff --quiet` exit 0 |
| 21-path `LC_ALL=C` record perimeter | `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` | required; `1eac91b2…` superseded/untrusted |
| Interpreter | `.venv/bin/python` | used |
| CLI | `.venv/bin/ontologylab` | used |
| HTTP | real `python -m ontologylab.serve` | `127.0.0.1:64795` (not 8799) |
| SSE | subscribe `/api/jobs/stream` before `POST /api/extract` | first snapshot `jobs: []` then POST |
| Denylist | unread/unhashed | six paths still `??`; `git ls-tree HEAD` count 0 |
| Product/test dirty | none | empty `git diff --stat -- ontologylab tests` |

Driver (disposable, now deleted):
`/tmp/ontologylab-wave21-task7-final-mqa.VgvxUv/driver.py`

Passing root:
`/private/tmp/ontologylab-wave21-task7-final-mqa.daW1F1`

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | CLI `--help` + `approve --help` | exit 0; lists `approve` / `migrate-h1` | both EXIT 0 | PASS |
| S2 | CLI happy `approve` | exit 0; prints stored `sha256:`; pointer set | `sha256:7f15c808…` == `grounded_review_current` | PASS |
| S3 | CLI invalid `migrate-h1` | exit 2; `not_sqlite`; no dest sqlite | EXIT 2; dest sqlite `[]` | PASS |
| S4 | Live HTTP extract bind ambiguity | SSE-first; job failed `CitationRefused` / `ambiguous`; cite count 0→0 | 202 then SSE `failed`; provenance `ambiguous: multiple extraction chunks…`; cites 0→0 | PASS |
| S5 | Live HTTP approve + repeat | 200 + pointer; second 409; pointer/count unchanged | 200 `sha256:c7078b28…`; 409 `cannot approve a 'verified' item`; count 1 | PASS |
| S6 | Live HTTP tampered approve | 409; zero decisions; status `proposed` | 409 `citation_ungrounded: not_ready: … quarantined`; decisions 0 | PASS |
| S7 | Live HTTP tampered reject/compensate | 200 pack-ineligible; live cites only; pointer advances; predecessor = reject | reject `sha256:30ab505e…` pack 1; stale cite absent; compensate `sha256:eded47fd…` pred=reject | PASS |
| S8 | Direct H1 colliding stale | classify/materialize/bind keep live waiver; stale twins unlinked | existing=materialized=bound=`sha256:7daa6232…`; stale approve/waiver not bound | PASS |
| S9 | Direct H1 missing-review | classify before cite receipts → `missing_span`; after cites, no existing/mint; bind `ungrounded` | pre `missing_span`; after existing/materialized null; persisted `quarantined/ungrounded` | PASS |
| S10 | Cleanup + PID 55560 | QA gone; 8799 unchanged | proven below | PASS |

## Commands and outputs

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Interpreter: `.venv/bin/python`
CLI: `.venv/bin/ontologylab`
Env: no `DATA_DIR`; no `PYTEST_*`; no `ONTOLOGYLAB_OFFLINE`. HTTP extract
used `engine=mock` (no egress). All stores under `/tmp/ontologylab-wave21-task7-final-mqa.*`.

### Preflight

```text
HEAD=362b0a679483139e51d8e37748674a867d6a9b2f
subject=fix(extraction): preserve exact receipt identity
tree=dce1386961684e924108ded625e56dab4031384d
owned_vs_head_exit=0
denylist_absent_from_HEAD_tree
PID 55560 ALIVE  TCP 127.0.0.1:8799 (LISTEN)  DEVICE 0x1ff51c806b197195
AS ino=102434596 mtime=1785487752 size=192
analysis.md ino=251846735 mtime=1787198701 size=43015
blueprint.md ino=251846738 mtime=1787198279 size=40995
plan.md ino=270282236 mtime=1787505626 size=45752
```

Allocated loopback port `64795` (refused if 8799).

### S1 — CLI help

```text
ARGV: [".venv/bin/ontologylab", "--help"]
EXIT: 0
usage: ontologylab [-h]
                   {reconcile,method,collect,ingest,extract,review,approve,reject,quarantine,review-retract,review-compensate,approve-with-waiver,invalidate,entity,critic,eval,rerank-download,merge-scan,merge-queue,merge,merge-dismiss,build-pack,pack-diff,build-mcpb,search,embed,registry,provider,migrate-h1}
                   ...
    approve             Approve proposed item(s) -> verified (human gate).
    migrate-h1          Rehearse historical receipt migration on a backup-API
                        copy.
```

```text
ARGV: [".venv/bin/ontologylab", "approve", "--help"]
EXIT: 0
usage: ontologylab approve [-h] [--id ID] [--filter FILTER] [--cascade]
                           [--by BY] [--note NOTE] [--data-dir DATA_DIR]
```

### S2 — CLI happy approve

Plant: C-024 publisher abstract + unknown-stage PMC full text, research
extract via `MockEngine`, then installed CLI (not `main()` in-process).

```text
ARGV: [".venv/bin/ontologylab", "approve", "--id", "7f7293f8c5eb49859613d760df55d99d",
       "--by", "cli-mqa", "--note", "cli grounded",
       "--data-dir", "/private/tmp/ontologylab-wave21-task7-final-mqa.daW1F1/cli"]
EXIT: 0
[ontologylab] approved node 7f7293f8c5eb49859613d760df55d99d
[ontologylab] decision_receipt_ids sha256:7f15c808d34bfd3307fec125270aa1827c0a959dcbd89f00404e6c5453d51bd9
CLI_POINTER: {
  "current": ["sha256:7f15c808d34bfd3307fec125270aa1827c0a959dcbd89f00404e6c5453d51bd9"],
  "decisions": [{
    "receipt_id": "sha256:7f15c808d34bfd3307fec125270aa1827c0a959dcbd89f00404e6c5453d51bd9",
    "action": "approve",
    "pack_ineligible": 0,
    "citation_receipt_ids_json": "[\"sha256:64dc8f1289a761420d31ceb4601a19310acf82b0750aed167f7de7dc80f80ba5\"]",
    "predecessor": null
  }],
  "status": "verified",
  "decision_count": 1
}
```

### S3 — CLI invalid migrate-h1

```text
ARGV: [".venv/bin/ontologylab", "migrate-h1",
       "--source", ".../cli/not-a-db.txt",
       "--dest", ".../cli-h1-bad"]
EXIT: 2
{"code":"not_sqlite","message":"not_sqlite: source is not a sqlite database: /private/tmp/ontologylab-wave21-task7-final-mqa.daW1F1/cli/not-a-db.txt"}
invalid_dest_sqlite: []
```

### S4 — live serve + SSE-first extract bind ambiguity

Plant: C-024 ready Representations only (no prior extract) plus two
self-consistent Task 2 runs covering PMC chunk 0. Serve:

```text
SERVE_ARGV: [".venv/bin/python", "-m", "ontologylab.serve",
             "--host", "127.0.0.1", "--port", "64795",
             "--data-dir", ".../http-bind",
             "--packs-dir", ".../packs-bind"]
SERVE_READY pid=71599 port=64795
```

Subscribe first:

```text
SSE_ARGV: ["curl", "-sS", "-N", "--no-buffer", "--max-time", "50",
           "-H", "Accept: text/event-stream",
           "http://127.0.0.1:64795/api/jobs/stream"]
```

First snapshot (`jobs: []`), then:

```text
ARGV: ["curl", "-sS", "-D", "-", "-X", "POST", "--max-time", "30",
       "http://127.0.0.1:64795/api/extract",
       "-H", "Content-Type: application/json",
       "--data-binary", "{\"engine\": \"mock\", \"doc_ids\": [\"rep-7020f642b5eb\"], \"max_engine_calls\": 8, \"time_budget\": 30}"]
EXIT: 0
HTTP/1.1 202 Accepted
{"job_id":"extract-20260824-074202","status":"running"}
```

SSE after trigger:

```text
event: jobs
data: {"jobs": []}

event: jobs
data: {"jobs": [{"job_id": "extract-20260824-074202", "status": "running", "engine": "mock", "error": null, ...}]}

event: jobs
data: {"jobs": [{"job_id": "extract-20260824-074202", "status": "failed",
  "progress": ["[ontologylab] extract failed: unexpected CitationRefused"],
  "error": "unexpected CitationRefused"}]}
```

Job provenance (disk, not browser):

```text
{"step": "job.failed", "payload": {"job_id": "extract-20260824-074202",
  "type": "CitationRefused",
  "error": "ambiguous: multiple extraction chunks cover this representation span"}}
```

Citation table count `0 → 0`. Serve log order: startup, `GET /api/jobs/stream`
200, `POST /api/extract` 202. Port `64795 ≠ 8799`.

### S5 — live HTTP grounded approve idempotency + current pointer

New serve on the same port, data-dir `http-review`.

```text
ARGV: ["curl", ... "http://127.0.0.1:64795/api/proposals/approve",
       "--data-binary", "{\"id\": \"939dbfd1cbfd42a380e1294445eb452d\", \"by\": \"http-mqa\", \"note\": \"http grounded\"}"]
HTTP/1.1 200 OK
{"ok":true,"kind":"node",
 "decision_receipt_ids":["sha256:c7078b28fbdca24faaf22f24afc978f626d00316147572519b620366658ed4d1"],
 "approved_ids":["939dbfd1cbfd42a380e1294445eb452d"]}
HTTP_POINTER_AFTER_FIRST: current=[sha256:c7078b28…] decision_count=1 status=verified
```

Repeat same body:

```text
HTTP/1.1 409 Conflict
{"detail":"cannot approve a 'verified' item; reopen it first"}
HTTP_POINTER_AFTER_SECOND: current=[sha256:c7078b28…] decision_count=1 status=verified
pointer_stable=true count_stable=true
```

Same-id persist is a no-op inside `persist_decision`; the HTTP surface
refuses a second approve as `InvalidTransition` and does not append or
move the pointer.

### S6 / S7 — live HTTP tampered non-approval

Ready bytes appended `X` after a live extract + extra stale Citation.
Approve:

```text
HTTP/1.1 409 Conflict
{"detail":"citation_ungrounded: not_ready: representation rep-15cbf18150e4 is quarantined"}
TAMPER_AFTER_APPROVE: current=[] decisions=[] status=proposed decision_count=0
```

Reject:

```text
HTTP/1.1 200 OK
{"ok":true,
 "decision_receipt_ids":["sha256:30ab505e37a59574838bd984bd7cd9f10074129e34c4243073a792aa39b4f864"],
 "decisions":[{"action":"reject","pack_ineligible":true,
   "citation_receipt_ids":["sha256:b9072b6e0c580bcadc549a27a6a24738e75c588e96b694d22991bd5dfa7e4ffb"],
   "predecessor_receipt_id":null}]}
```

Stale extra cite `sha256:e9e0e703…` is absent from the reject digest.
Pointer = reject id.

Compensate:

```text
HTTP/1.1 200 OK
{"decision_receipt_ids":["sha256:eded47fd0fb2261cbc71e70e6dce8b9de30225f514a83600c2a0ef742dccdddd"],
 "decisions":[{"action":"compensate","pack_ineligible":true,
   "predecessor_receipt_id":"sha256:30ab505e37a59574838bd984bd7cd9f10074129e34c4243073a792aa39b4f864"}]}
TAMPER_AFTER_COMPENSATE: current=[sha256:eded47fd…] decision_count=2
```

### S8 / S9 — direct H1 classify / materialize / finalize

Backup-API copies only (`prepare_h1_copy`). No `run_h1_operator` as the
assertion path.

Colliding stale approve + smaller stale waiver, pointer still on live
scoped waiver:

```text
H1_COLLIDING:
  waiver_id     = sha256:7daa6232fb975c8b99c9778cf054e81b34d07391e8d1c8224343ee94c7054fd7
  stale_approve = sha256:717884391208602be919d2a88595bdc869e60524e8ce28a121d9add6ce66b6d4
  stale_waiver  = sha256:145a1226fd3493b71f426c11bfaefe4aaf7a3c7d2c90b6d4970fbc66cae3cd25
  reviews[0]:
    classified=verified
    existing=sha256:7daa6232…
    materialized=sha256:7daa6232…
    bound_family=sha256:7daa6232…
    bound_class=verified
```

Missing-review / indistinguishable tips (pointer deleted, two same-cite
scopes):

```text
H1_MISSING:
  classify_before_cite_receipts: classified=quarantined reason=missing_span
  after_cite_commit:
    classified=verified
    existing=null
    materialized=null
    bound_class=quarantined
    bound_reason=ungrounded
  persisted_review: classification=quarantined reason=ungrounded family=null
```

No eligible pack-0 approve twin was minted.

## Cleanup and protected boundary

After QA, disposable servers and roots were removed:

```text
# leftover QA listeners
lsof -nP -iTCP:64795 -sTCP:LISTEN  → none
lsof -nP -iTCP:64550 -sTCP:LISTEN  → none
ps -p 71540,71599,72647,72671      → gone

# PID 55560 / 8799 unchanged
python3.1 55560  10u  IPv4 0x1ff51c806b197195  TCP 127.0.0.1:8799 (LISTEN)

# Application Support directory metadata unchanged (contents not read)
ino=102434596 mtime=1785487752 size=192

# planning docs unchanged
analysis.md   ino=251846735 mtime=1787198701 size=43015
blueprint.md  ino=251846738 mtime=1787198279 size=40995
plan.md       ino=270282236 mtime=1787505626 size=45752

# product/test worktree
git diff --stat -- ontologylab tests scripts pyproject.toml  → empty
git diff --cached --stat                                     → empty
HEAD                                                         → 362b0a679483139e51d8e37748674a867d6a9b2f
```

Root deletion:

```text
rm -rf /tmp/ontologylab-wave21-task7-final-mqa.daW1F1 /tmp/ontologylab-wave21-task7-final-mqa.VgvxUv
rm_exit=0
ls: /tmp/ontologylab-wave21-task7-final-mqa.daW1F1: No such file or directory
ls: /tmp/ontologylab-wave21-task7-final-mqa.VgvxUv: No such file or directory
ls: /tmp/ontologylab-wave21-task7-final-mqa.*: No such file or directory
daW1F1_absent=true
VgvxUv_absent=true
64795_clear
55560 DEVICE 0x1ff51c806b197195 still LISTEN 127.0.0.1:8799
AS ino=102434596 mtime=1785487752 size=192
HEAD=362b0a679483139e51d8e37748674a867d6a9b2f


Did not:

- read or write `~/Library/Application Support/ontologylab/` data
- bind, kill, or retarget port 8799 or PID 55560
- use external network
- edit planning/authority documents
- edit product or tests
- stage, commit, or push
- read or hash the six untracked `review_decision*` / `review_grounding.py`
  denylist files
- run Step 9C or claim production readiness

## Residuals (not blockers)

- Tampered approve surfaces as `not_ready` / representation quarantined
  after the ready-byte append, not the library-test string
  `invalid_hash: hash_mismatch`. Contract holds: HTTP 409, zero decision
  rows, status remains `proposed`.
- The bind serve process was SIGKILL'd (`exit=-9`) after the SSE curl
  held the connection past the terminal event. Listener is gone. Later
  review/tamper serves shut down with SIGTERM (`exit=-15`) and
  `Application shutdown complete`.
- SQLite backup-API may create `-wal`/`-shm` beside a source file. H1
  writes stayed on dest copies.

## Stop

Strict verdict: **PASS**.
