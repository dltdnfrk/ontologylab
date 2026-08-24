# Task 17 independent security/scope review — Step 9 closure packet

Date: 2026-08-24
Reviewer: omo senpi-task `st_01a03288`
HEAD: `42d3dcb3940d4d40697dac07bf28f4dbfcd28b81`
Frozen inputs (rehashed after review; not rewritten):

| Artifact | SHA-256 |
|---|---|
| `task-17-step9-full-suite.md` | `26b3d085cef0128cfbfd8a05064cd4a90e4de86fa97f716112f6c42340657922` |
| `step9-evidence-index.md` | `a9ef8b460bfa75834f1546816abe2b005a6f9447516460ab52b558864cb57fd7` |
| `step10-kickoff.md` | `792a161d41db086f444fa28c9511abe2472ea427bd8ba829410c9a57860f5f3e` |

Constraint: evidence/product/test read-only; no full suite, commit, push, 9C, network, Application Support, or 8799 mutation.

## Verdict

**PASS**

The closure packet does not authorize Step 9C, does not launder historical NEEDS-FIX into a silent PASS, and does not invent Step 10 performance thresholds. All 23 indexed authoritative receipt hashes rematch on disk. The Task 13→16 commit chain is linear (`77baabe` → `8c75c6d` → `0d63dfe` → `42d3dcb`). `HEAD` and `42d3dcb^{tree}` are `0a20eb1d587b5c7f6767d86eba1d55990ac65f50`. The **committed** machine stop blob at `42d3dcb:.omo/.../task-16-step9b-runbook.json` has `authorized=false` (bool), `commands_present=false` (bool), window/receipt/approver `null`, and `stop_token=STOP_BEFORE_STEP_9C`. Historical NEEDS-FIX security receipts still exist and still hash to the values cited by the final gates. Product/test working tree is clean aside from unrelated `ontologylab/graphify-out/`.

Maximum severity: none (LOW residuals: uncommitted “closure candidate” packet; dual perimeter-hash disclosure; T13 PASS security omitted from the authoritative table; operator+approver 9A/9B dual-sign leftover from Task 16).

## Attacks

### Stale receipt hashes — HOLD

Every authoritative index row was rehashed. All 23 MATCH. Spot-check of gate-cited historical hashes also MATCH:

- `task-13-review-security.md` `ede5cf14…` (NEEDS-FIX)
- `task-13-review-repair-security.md` `cd4a6dc3…` (PASS)
- `task-14-review-security.md` `341ce6f7…` (NEEDS-FIX)
- `task-14-review-repair-security.md` `0473e46c…` (NEEDS-FIX)
- `task-14-review-repair2-security.md` `560f5ce2…` (PASS, indexed)
- Task 16 runbook/stop SHA-256 MATCH the Task 16 freeze

### History laundering — HOLD

Index lists historical files separately and says they are not rewritten. Final gates for 13–16 are **APPROVED** and still label R0/R1 security as historical **NEEDS-FIX**. Those NEEDS-FIX files remain on disk with the cited hashes. Repair-2 / T15 / T16 security PASS receipts are the ones treated as current. No NEEDS-FIX file was retitled PASS.

### Omissions — HOLD (non-blocking gap)

All named historical files exist. Authoritative table uses final-gate + commit-verifier as the T13 security stand-in and does not hash `task-13-review-repair-security.md` (PASS) in that table. The file exists and matches the gate. Not a stop-token or authority leak.

### Perimeter-label confusion — HOLD as disclosed

`task-17-step9-full-suite.md` records two distinct product/test perimeter hashes (`2ca26476…` commit-blob vs `6318ba4e…` working-byte) and states the preflight ledger mislabeled them. Index does **not** collapse them into one unnamed perimeter; it only pins HEAD/tree. That is a documented algorithm split, not a byte rewrite.

### Commit chain / unverified commits — HOLD

```text
b75d81c (parent)
  77baabe  Task 13
    8c75c6d  Task 14
      0d63dfe  Task 15
        42d3dcb  Task 16  HEAD, tree 0a20eb1d
```

`git ls-tree 42d3dcb` contains the three stop artifacts and the cutover modules. The index/suite/Step 10 kickoff are **closure-candidate** working-tree evidence, not that commit. Index status says “closure candidate” and defers Step 10 until an evidence-only closure commit is independently verified. No extra product commit after the suite identity.

### Production-capable wording / 9C leakage — HOLD

Index: “Production cutover: not authorized”, `STOP_BEFORE_STEP_9C`. Suite ends with `STEP_9B_COMPLETE` / `STOP_BEFORE_STEP_9C`. Committed JSON (parsed from `git show 42d3dcb:…runbook.json`, not the working copy) is boolean-false / null / `STOP_BEFORE_STEP_9C`. Step 10 kickoff: “Step 10 is release evidence, not Step 9C. It cannot authorize production.” Resume still requires a newer direct 9C request, named window, approval identity, and fresh preflight. “Close Step 10 before production cutover” is scoped by that stop.

### Invented Step 10 thresholds — HOLD

Kickoff forbids inventing more favorable release thresholds and binds comparison to frozen `wave21-perf-v1` `019a986f…`. No new numeric SLO appears in the kickoff.

### Live-data / network aliases — HOLD

Index and kickoff forbid Application Support, 8799/PID 55560 mutation, external network, and production commands. No live path is offered as a rehearsal root.

### Protected cleanup — HOLD

AS dir `ino=102434596` `mtime_ns=1785487752937707432` `size=192` unchanged. PID 55560 still `127.0.0.1:8799` device `0x1ff51c806b197195`. No 9C, no network, no product/test edit.

## Final Task 13–16 security/gates (read-only)

| Task | Current security | Gate | Commit verifier |
|---|---|---|---|
| 13 | historical NEEDS-FIX then repair **PASS** | APPROVED | PASS |
| 14 | R0/R1 NEEDS-FIX then repair2 **PASS** | APPROVED | PASS |
| 15 | **PASS** | APPROVED (rebind2) | PASS |
| 16 | **PASS** | APPROVED | PASS; machine stop re-checked on committed blob |

## Residuals (non-blocking)

- Closure index/suite/kickoff are not in `42d3dcb`; they are the packet that still needs an evidence commit + verifier (already stated).
- Authoritative table omits the T13 PASS security hash (present via final gate).
- Historical-file list is titled “NEEDS-FIX” but also names some later PASS repair files.
- Dual perimeter algorithms remain; do not treat either hash as the other.

## What was not run

- Full pytest (suite receipt treated as a claim; HEAD/tree identity rematched).
- Step 9C, push, commit.

## Confidence

`0.95`

Receipt rematch, commit ancestry, committed JSON parse, and stop-token checks are mechanical. Suite wall-clock result was not re-executed.

## Protected-boundary cleanup

- No Application Support content read/write. Directory identity unchanged.
- No external network.
- 8799 / PID 55560 observe-only.
- Frozen closure/index/kickoff SHA-256 MATCH entry. Indexed receipts not rewritten.
- No commit/push. This file is the only durable write.

## Stop

Strict verdict: **PASS**. Maximum severity: none (LOW residuals only).

```text
STEP_9B_COMPLETE
STOP_BEFORE_STEP_9C
```
