# Task 17 Step 9 closure — independent manual QA

Date: 2026-08-24
Worker: omo senpi-task `st_01a03289`
Mode: independent observer QA of frozen Step 9 closure artifacts.
Evidence/product/test **read-only**. Did **not** rerun the 22-minute
full suite. Independently recomputed committed HEAD/tree/commit-blob
perimeter and checked the suite receipt. Drove the bounded Step 9
surface once on disposable test copies. Validated committed runbook
JSON/stop. Checked every indexed hash/path, Step 10 frozen baseline
and three tasks, and protected observe-only identity.

No full suite, commit, push, Step 9C, network, or Application Support
open.

## Verdict

`PASS`

Live `HEAD`/`tree` equal the suite receipt (`42d3dcb3…` /
`0a20eb1d…`). Independently recomputed commit-blob product/test
perimeter `2ca26476…` (417 paths). Tracked product/test working tree
matches HEAD (`git diff --quiet` exit 0). All 23 indexed receipt
hashes match; all 17 historical paths exist. Committed runbook JSON
has `authorized=false`, `commands_present=false`, null approval
fields, and `STOP_BEFORE_STEP_9C`. Bounded Step 9 pytest:
`57 passed, 1 warning`. Step 10 kickoff still names the same HEAD/
tree/suite counts, frozen `wave21-perf-v1` `019a986f…`, exactly three
tasks, and `STOP_BEFORE_STEP_9C`. Protected PID/device/AS unchanged.
Frozen closure hashes entry == exit.

## Authority actually read (not summaries)

- `task-17-step9-full-suite.md` (`26b3d085…`)
- `step9-evidence-index.md` (`a9ef8b46…`)
- `step10-kickoff.md` (`792a161d…`)
- committed `task-16-step9b-runbook.json` / `task-16-step9c-stop.md`
  via `git show HEAD:…`
- `task-16-commit-verifier.md` (commit-blob recipe only)

Did not execute `UV_NO_SYNC=1 uv run --all-extras pytest`.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `42d3dcb3940d4d40697dac07bf28f4dbfcd28b81` | match before and after |
| tree | `0a20eb1d587b5c7f6767d86eba1d55990ac65f50` | `git rev-parse HEAD^{tree}` match |
| commit-blob perimeter | `2ca26476278fb2ca25c35182505ed48c47f2f7571edcfb73084d14eb37aaf129` | recomputed; 417 paths |
| working product/test | == HEAD | `git diff --quiet HEAD -- ontologylab tests scripts pyproject.toml` exit 0 |
| Frozen suite receipt | `26b3d085cef0128cfbfd8a05064cd4a90e4de86fa97f716112f6c42340657922` | match entry=exit ino `281903596` |
| Frozen index | `a9ef8b460bfa75834f1546816abe2b005a6f9447516460ab52b558864cb57fd7` | match entry=exit ino `281903598` |
| Frozen kickoff | `792a161d41db086f444fa28c9511abe2472ea427bd8ba829410c9a57860f5f3e` | match entry=exit ino `281903600` |
| HTTP / 8799 | observe-only | PID 55560 device `0x1ff51c806b197195` |
| Application Support | observe-only `lstat` | ino `102434596` mtime_ns `1785487752937707432` size `192` |

Suite receipt is gitignored (`.omo/`); identity was checked against
live git, not by trusting the prose alone.

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | suite receipt HEAD/tree | `42d3dcb3` / `0a20eb1d` | live git match | PASS |
| S2 | commit-blob perimeter | `2ca26476…` 417 paths | exact recompute | PASS |
| S3 | working product/test vs HEAD | identical | diff quiet 0 | PASS |
| S4 | 23 indexed hashes/paths | all exist and match | 0 mismatches | PASS |
| S5 | 17 historical receipts | exist, not rewritten | all present | PASS |
| S6 | committed runbook JSON/stop | false/null/stop | types exact | PASS |
| S7 | bounded Step 9 surface | 3-file pytest once | 57 passed, 1 warning | PASS |
| S8 | Step 10 baseline + 3 tasks | frozen + stop | match | PASS |
| S9 | protected + cleanup + hashes | observe-only; entry=exit | held | PASS |

## Commands and outputs

### S1 / S2 / S3 — committed suite identity

```text
git rev-parse HEAD
42d3dcb3940d4d40697dac07bf28f4dbfcd28b81

git rev-parse HEAD^{tree}
0a20eb1d587b5c7f6767d86eba1d55990ac65f50

git ls-tree -r 42d3dcb3… -- ontologylab tests scripts pyproject.toml \
  | LC_ALL=C sort | shasum -a 256
2ca26476278fb2ca25c35182505ed48c47f2f7571edcfb73084d14eb37aaf129
417 paths

git diff --quiet HEAD -- ontologylab tests scripts pyproject.toml
exit 0
```

Suite receipt claimed result (not re-executed):

```text
2873 passed, 1 skipped, 2 xfailed, 1 warning in 1336.78s (0:22:16)
exit 0
```

Working-byte digest `6318ba4e…` is the lead's alternate serialization.
This observer did not re-derive that encoding. Underlying product/test
bytes are the committed blobs (S2+S3).

### S4 / S5 — index

All 23 SHA-256 rows in `step9-evidence-index.md` match current files.
All 17 historical NEEDS-FIX/repair paths exist under
`.omo/evidence/start-work/wave21-ingestion-steps5-10/`.

### S6 — committed runbook / stop

`git show HEAD:.omo/…/task-16-step9b-runbook.json` parsed with
`json.loads`:

```text
production_cutover.authorized = False   (bool)
production_cutover.commands_present = False
maintenance_window_name = None
approval_receipt = None
approved_by = None
stop_token = STOP_BEFORE_STEP_9C
reader_kinds = 6
phases = 9
minimum_complete_reader_bundles = 2
```

Committed stop certificate contains `STOP_BEFORE_STEP_9C` and
`Production cutover authorized: **NO**`.

### S7 — bounded Step 9 surface (once)

```text
UV_NO_SYNC=1 uv run pytest \
  tests/test_cutover_rehearsal.py \
  tests/test_cutover_readers.py \
  tests/test_cutover_rollback.py \
  --override-ini addopts= -q
57 passed, 1 warning in 15.25s
EXIT:0
```

Those files cover the disposable state machine, all six readers, two
bundles, drain/flip, and forward rollback / additive recovery. Warning
is the existing Starlette TestClient/httpx deprecation.

### S8 — Step 10 frozen baseline

Kickoff still records:

```text
HEAD  42d3dcb3940d4d40697dac07bf28f4dbfcd28b81
tree  0a20eb1d587b5c7f6767d86eba1d55990ac65f50
full suite  2873 passed, 1 skipped, 2 xfailed
fixture  wave21-perf-v1
manifest sha256  019a986f878bcba5b2ba8c67a1451d8fc19af021988e28bdd9f7e2287f82f0b1
```

`tests/fixtures/wave21/perf-v1.json` SHA-256 is exactly that digest
(1835 bytes). Kickoff names exactly three tasks:

1. Execute consolidated release mutation matrix
2. Compare release performance determinism and claims
3. Close Step 10 before production cutover

Mandatory stop remains `STOP_BEFORE_STEP_9C`.

### S9 — protected / hashes

```text
PID 55560 DEVICE 0x1ff51c806b197195 TCP 127.0.0.1:8799 (LISTEN)
AS ino=102434596 mtime_ns=1785487752937707432 size=192
frozen suite/index/kickoff SHA-256 entry == exit
product/test still clean vs HEAD
```

Did not:

- rerun `uv run --all-extras pytest`
- edit product, tests, plans, suite receipt, index, or kickoff
- open Application Support data
- bind/kill/retarget 8799 or PID 55560
- use network, commit, push, or Step 9C

## Residuals (not blockers)

- Closure suite/index/kickoff live under gitignored `.omo/`; they are
  not in HEAD. Their claimed git identity was checked against live
  `rev-parse` / `ls-tree`, not by `git show` of those three files.
- Working-byte digest `6318ba4e…` was not re-serialized; working
  product/test identity was proven via commit-blob + empty `git diff`.

## Stop

```text
STEP_9B_COMPLETE
STOP_BEFORE_STEP_9C
```

Strict verdict: **PASS**.
