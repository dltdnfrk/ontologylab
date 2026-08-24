# Task 20 Step 10 close — independent manual QA

Date: 2026-08-25
Worker: omo senpi-task `st_01a03289`
Mode: independent G019 QA of frozen HEAD
`0855ff32dca1691d1acbe05ad56f884cef07773a`. Product/test
**read-only**. Did **not** rerun the full suite. One bounded claims
file. No product edits, commit, push, network, Application Support
open, 8799 mutation, or Step 9C.

## Verdict

`PASS`

Perimeter independently recomputed `9520e8a5…` before and after.
Receipt fields: `go=false`, `production_authorized=false`,
`stop_token=STOP_BEFORE_STEP_9C`, ingest `refused`, target
`verdict=pass`. Claims pytest: `5 passed in 11.00s`. PID 55560 /
`0x1ff51c806b197195` observe-only, unchanged. Application Support
`lstat` unchanged. No product/test drift.

## Identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `0855ff32dca1691d1acbe05ad56f884cef07773a` | match before and after |
| Perimeter | `9520e8a5c0531c56805893200ba9d0fcab83af9edf476dda72ff6adbd7d6bf84` | match before and after |
| Product/test vs HEAD | identical | `git diff --quiet` exit 0 |
| HTTP / 8799 | observe-only | PID 55560 LISTEN `127.0.0.1:8799` device `0x1ff51c806b197195` |
| Application Support | observe-only `lstat` | ino `102434596` mtime_ns `1785487752937707432` size `192` |

## Commands and outputs

### Perimeter

```text
git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml \
  | LC_ALL=C sort | shasum -a 256
9520e8a5c0531c56805893200ba9d0fcab83af9edf476dda72ff6adbd7d6bf84
```

Same digest after pytest.

### Receipt parse

`tests/fixtures/wave21/step10-release-receipt-v1.json`:

```text
release.go = False                         (bool)
release.production_authorized = False      (bool)
release.stop_token = STOP_BEFORE_STEP_9C
release.reasons = [current_ingest_performance_threshold_exceeded]
performance.current_ingest_create_and_duplicate.status = refused
performance.current_ingest_create_and_duplicate.reason = performance_threshold_exceeded
performance.target_v2_migration.verdict = pass
```

### Bounded tests

```text
.venv/bin/python -m pytest tests/test_wave21_release_claims.py \
  --override-ini addopts= -q
.....
5 passed in 11.00s
EXIT:0
```

### Protected observe-only

```text
python3.1 55560  TCP 127.0.0.1:8799 (LISTEN)  device 0x1ff51c806b197195
AS ino=102434596 mtime_ns=1785487752937707432 size=192
```

Unchanged after the command.

## Did not

- rerun the full suite
- edit product, tests, or the receipt fixture
- open Application Support data
- bind/kill/retarget 8799 or PID 55560
- use network, commit, push, or Step 9C

## Stop

```text
STOP_BEFORE_STEP_9C
```

Strict verdict: **PASS**.
