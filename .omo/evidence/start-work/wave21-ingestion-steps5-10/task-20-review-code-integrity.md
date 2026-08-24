# Task 20 code/integrity review — Step 10 close (G019)

Reviewer: omo senpi-task `st_01a03287`
Date: 2026-08-25
Lane: independent integrity review of Step 10 close on frozen
HEAD `0855ff32dca1691d1acbe05ad56f884cef07773a`. Product/test
read-only. This file is the only write. No pytest, full suite,
product edit, commit, push, network, Application Support, 8799,
or 9C.

## Verdict

**PASS**

**Confidence:** 0.93

HEAD / tree / product-test perimeter MATCH the freeze and the
suite receipt. Owned product/test bytes equal HEAD. Task 18
gate is **APPROVED** (60/60). Task 19 gate is **APPROVED** with
ingest NO-GO and `release.go=false`. The close report is
`NO-GO` and does not imply production GO. `STOP_BEFORE_STEP_9C`
is on the suite receipt, NO-GO report, T18/T19 gates, matrix,
and machine receipt. Commit is not on `origin/main`.

The 2882-pass suite is a **bound claim** (identities match; not
re-executed here).

No CRITICAL. No MAJOR.

## Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

1. Task 18 matrix `release_candidate` remains `5974b782…` /
   perimeter `3e00c64d…` (pre-T19 test lock). T19 added tests
   only; product-only perimeter is unchanged. Not a GO path.

## Independent rebind

| Item | Observed | Claim |
|---|---|---|
| HEAD | `0855ff32dca1691d1acbe05ad56f884cef07773a` | MATCH |
| tree | `c22554bdc513ada9ec25af3e974b264f6881d2e5` | MATCH |
| product/test perimeter | `9520e8a5c0531c56805893200ba9d0fcab83af9edf476dda72ff6adbd7d6bf84` | MATCH (recomputed `git ls-tree`) |
| owned vs HEAD | `git diff --quiet` exit 0 | MATCH |
| not pushed | `merge-base --is-ancestor HEAD origin/main` exit 1 | HOLD |

Suite receipt `task-20-committed-suite.md`
(`814cdc42046a555d5551b576fdf0e1ccf1b38eee28cd6ebd849b258717c57813`):
2882 passed / 1 skipped / 2 xfailed / 1 warning / 1234.43s /
exit 0; same HEAD/tree/perimeter before and after; STOP token
present.

NO-GO report `task-20-nogo-report.md`
(`3f8f82eb819ceea8293cdf98e4befa44c01b220de1c9db0dfdf53cb470d31108`):
overall `NO-GO`; ingest row NO-GO; other capability rows GO;
explicitly “not a Step 9C decision.”

### Task 18 / 19 gates

| Gate | SHA-256 | Verdict | Bound |
|---|---|---|---|
| `task-18-final-gate.md` | `791e7973552a695a28123902ae3fe43635d6c2dd1cd32c0cf62c4d848c570b23` | **APPROVED** | 60 unique / 60 killed / 0 survive; matrix `12bfc765…` |
| `task-19-final-gate.md` | `29d47a61a5bed6d5ad4d4d5e1d467e051ade596540dce6d863ef1d280af39e4f` | **APPROVED** | ingest NO-GO; `go=false` |

Parsed machine receipt
`tests/fixtures/wave21/step10-release-receipt-v1.json`
(`d2b87ce849fa3bca2d89301aac4c7a94e4523b41af288496feff2267f2bb8743`):

| Field | Value |
|---|---|
| `release.go` | `false` (bool) |
| `release.production_authorized` | `false` (bool) |
| `release.stop_token` | `STOP_BEFORE_STEP_9C` |
| `release.reasons` | `current_ingest_performance_threshold_exceeded` |
| ingest `status` | `refused` |
| target migration `verdict` | `pass` |
| matrix summary | 60/60/0/60; `mandatory_stop=STOP_BEFORE_STEP_9C` |

No production-GO or `authorized: true` string in the close
report or receipt.

## Bind

| Fact | Observed |
|---|---|
| Subject | `test(release): bind wave21 performance and capability receipts` |
| PID 55560 | still `127.0.0.1:8799` DEVICE `0x1ff51c806b197195` |
| Application Support | ino `102434596` mtime_ns `1785487752937707432` size `192` (stat only) |
| extra dirty | `?? ontologylab/graphify-out/` only |

## Method

Read suite receipt, NO-GO report, T18/T19 final gates, machine
receipt, matrix summary. Recomputed HEAD/tree/perimeter.
Confirmed `git diff --quiet` and not-pushed. Did **not** rerun
pytest or remesure ingest.

## Residuals (do not flip)

- MINOR 1 (T18 RC is parent of T19).
- 2882 result not re-executed.
- Ingest NO-GO remains a bound measurement claim.

## Protected

- Product/test not edited
- Prior gates/receipts not rewritten
- No tests/full suite
- PID 55560 observe-only; Application Support stat-only
- No commit/push/network/9C
