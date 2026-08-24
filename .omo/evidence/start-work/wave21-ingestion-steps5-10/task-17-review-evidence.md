# Task 17 evidence audit — Step 9A/9B closure

Reviewer: omo senpi-task `st_01a03287`
Date: 2026-08-24
Lane: independent evidence/code audit of Step 9 closure artifacts.
Product/test/evidence **read-only**. This file is the only write.
Narrow static/hash checks only. No full suite. No commit/push;
no network; no Application Support contents; no 8799 / PID 55560;
no 9C; no plan edits.

Authority: Step 9 kickoff (9A/9B only); plan Task 17 (close 9A/9B,
index, Step 10 kickoff, suite on committed perimeter). Bound to
HEAD `42d3dcb3940d4d40697dac07bf28f4dbfcd28b81`.

Frozen closure artifacts (MATCH claimed prefixes):

| Artifact | SHA-256 |
|---|---|
| `task-17-step9-full-suite.md` | `26b3d085cef0128cfbfd8a05064cd4a90e4de86fa97f716112f6c42340657922` |
| `step9-evidence-index.md` | `a9ef8b460bfa75834f1546816abe2b005a6f9447516460ab52b558864cb57fd7` |
| `step10-kickoff.md` | `792a161d41db086f444fa28c9511abe2472ea427bd8ba829410c9a57860f5f3e` |

## Verdict

**PASS**

**Confidence:** 0.92

The committed chain `77baabe → 8c75c6d → 0d63dfe → 42d3dcb` is
linear and matches the index. Current `HEAD` / `HEAD^{tree}` equal
the suite and index identities (`42d3dcb3…` /
`0a20eb1d587b5c7f6767d86eba1d55990ac65f50`). All **23**
authoritative receipt hashes MATCH on disk. All **17** historical
paths exist; first-pass NEEDS-FIX files still say NEEDS-FIX;
repair2/final-gate/commit-verifier receipts close the named
holes. Committed code contains the five required surfaces.
Committed runbook JSON is `authorized=false` /
`commands_present=false` / `STOP_BEFORE_STEP_9C`. Step 10
kickoff is exactly three post-closure tasks, pins the frozen
`wave21-perf-v1` manifest, and cannot authorize 9C.

The 2873-pass suite is a **bound claim** (HEAD/tree unchanged
before/after in the receipt). This audit did not re-execute it.

No blocking evidence defect.

## Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

1. **Step 10 kickoff reuses “Task 17/18/19”** for plan Tasks
   18–20. The three work items match the plan; the numbers
   collide with this Step 9 closure task. Not a 9C path.

2. **Working-byte perimeter `6318ba4e…` is not independently
   recomputed here.** Commit-blob perimeter
   `2ca26476278fb2ca25c35182505ed48c47f2f7571edcfb73084d14eb37aaf129`
   **reproduced** via
   `git ls-tree -r 42d3dcb -- ontologylab tests scripts pyproject.toml | LC_ALL=C sort | shasum -a 256`.
   Suite labels the two algorithms correctly and does not
   collapse them.

## Requirements map (committed `42d3dcb`)

| Requirement | Where | Status |
|---|---|---|
| Disposable state machine | `77baabe` `cutover_rehearsal.py` `CutoverPhase` | HOLD |
| All readers + two bundles | `8c75c6d` `record_all_reader_observation`; JSON 6 kinds / min 2 | HOLD |
| State-bound flip | rehearsal flip + runbook §3 (no caller pin) | HOLD |
| Forward rollback + additive recovery | `0d63dfe` `enter_forward_rollback` / compensation | HOLD |
| Runbook + stop | `42d3dcb` three Task 16 artifacts | HOLD |
| Historical NEEDS-FIX preserved | 17 listed files present; T13/T14 first-pass still **NEEDS-FIX** | HOLD |
| Final repairs close them | T13 repair+gate APPROVED; T14 repair2 PASS + gate APPROVED; T15 review PASS + rebind2 APPROVED; T16 operator/security/QA PASS + gate APPROVED | HOLD |
| Commit chain | parents `b75d81c→77baabe→8c75c6d→0d63dfe→42d3dcb` | HOLD |
| Suite on committed HEAD/tree | receipt 2873/1 skip/2 xfail; identities MATCH live HEAD/tree | HOLD as bound claim |
| Dual perimeters labeled | commit-blob reproduced; working-byte named separately | HOLD |
| 23 hashes / 17 paths | 23/23 MATCH; 17/17 exist | HOLD |
| Step 10 tasks + baseline | exactly 3 tasks; manifest `019a986f878bcba5b2ba8c67a1451d8fc19af021988e28bdd9f7e2287f82f0b1` MATCH `tests/fixtures/wave21/perf-v1.json` | HOLD |
| No 9C | index/suite/kickoff/runbook/stop all `STOP_BEFORE_STEP_9C`; JSON approval fields null; `git merge-base --is-ancestor 42d3dcb origin/main` exit 1 | HOLD |

## Bind

| Fact | Observed |
|---|---|
| HEAD | `42d3dcb3940d4d40697dac07bf28f4dbfcd28b81` |
| Tree | `0a20eb1d587b5c7f6767d86eba1d55990ac65f50` |
| Subject | `docs(evidence): add step 9B operator stop` |
| Product dirty | only unrelated `?? ontologylab/graphify-out/` |
| PID 55560 | still `127.0.0.1:8799` DEVICE `0x1ff51c806b197195` |
| Application Support | ino `102434596` mtime_ns `1785487752937707432` size `192` (stat only) |

Index / suite / Step 10 kickoff are gitignored under `.omo/`
(expected until the evidence-only closure commit).

## Method

Read kickoff, plan Task 17, index, suite receipt, Step 10
kickoff, T13–T16 final-gate/commit-verifier/review verdicts.
Rehashed all 23 table rows. Counted 17 historical paths.
Verified parent chain, HEAD/tree, committed runbook JSON, perf
manifest SHA-256, and commit-blob perimeter. Did **not** rerun
`UV_NO_SYNC=1 uv run --all-extras pytest`.

## Residuals (do not flip)

- MINOR 1–2 above.
- 2873 result not re-executed in this audit.
- Working-byte algorithm not reconstructed beyond the suite’s
  label.
- Index lists some PASS/DONE files inside the “historical
  NEEDS-FIX” path list (the first-pass NEEDS-FIX files themselves
  are untouched).

## Protected

- HEAD/tree unchanged by this review
- Product/test/evidence bytes not rewritten
- Prior receipts not rewritten
- PID 55560 observe-only
- Application Support stat-only
- No commit/push/network/full suite/9C
