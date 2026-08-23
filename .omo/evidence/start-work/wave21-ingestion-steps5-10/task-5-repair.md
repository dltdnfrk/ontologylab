# Task 5 repair — CLI reject machine receipts

Date: 2026-08-23
HEAD: `7c159fd3efa24a5b9839e0ae32643e7f90560124` (unchanged; no commit)
Constraint: denylist unread/unedited; PID 55560 / port 8799 untouched; no
Task 6+; no full suite; no commit.

## Gap

Installed CLI `reject` persisted a grounded ReviewDecision but stdout was
only `[ontologylab] rejected node …`. Approve/quarantine/retract/compensate/
waiver already printed `decision_receipt_ids`.

## TDD

RED (`tests/test_grounded_review.py::test_cli_reject_emits_decision_receipt_ids`):

```
assert '[ontologylab] decision_receipt_ids sha256:175dc217…' in
  '[ontologylab] rejected node 43068ed9…\n'
EXIT:1
```

Named reason: receipt exists in SQLite, CLI stdout omitted it.

GREEN: `cmd_reject` calls existing `_print_review_receipts(result)`.

```
.venv/bin/python -m pytest tests/test_grounded_review.py::test_cli_reject_emits_decision_receipt_ids -q
.
EXIT:0
```

## Mutant

Removed the reject receipt print. Same test: `DID NOT RAISE` equivalent —
`decision_receipt_ids sha256:f33bdeda…` not in rejected-only stdout. Restored
the print hook.

## Verify (each once)

Focused grounded-review + CLI:

```
.venv/bin/python -m pytest tests/test_grounded_review.py tests/test_cli.py -q
.....................
EXIT:0
```

Server review tests not required (HTTP reject already returned
`decision_receipt_ids` via `{"ok": True, **result}`).

```
/Users/hyunjun/.local/bin/basedpyright ontologylab/main.py tests/test_grounded_review.py
0 errors, 0 warnings, 0 notes
```

## Hash lock

Unchanged vs Task 5 ship (except intentional `main.py` + test):

| File | SHA-256 |
| --- | --- |
| `grounded_review.py` | `105e45da8363e8737f5b4156f8d75d4b929e88a12d0f5649e387897500e417e0` |
| `grounded_review_types.py` | `d64716d46155d66d42a958aa4b5cc6cdbeca06b34a302e985e5b6a8a0d4610ba` |
| `grounded_review_ids.py` | `4af4a46e68a9a4d62e3e040fd09d9452a3e05bfdfc7da01f41c6cb92bb19c226` |
| `grounded_review_schema.py` | `cdc9ef8790d0f5ee01e4b57c214f4811d835b6fb04ec7f8457d109b9550a1771` |
| `grounded_review_store.py` | `c98f3a38cd8a3ec311b857fcb943acd8b173d684999001f9284dde6f9e09af5a` |
| `grounded_review_preflight.py` | `b6c754bf500a9e384be4dc19fe024bca7d5efbc03dc764e588d6fd9291dc2a45` |
| `grounded_review_payload.py` | `692b9a5a6b733cd1afda10ec5c33fea88b887c4e29f693a676b206db1cf3dc7a` |
| `kgstore.py` | `0f37cc1d511917ff4b766c51301ec623ea02d539a1b7298bc62a0c3b1eb64013` |
| `extraction_state.py` | `7fba7e0f397cd81837412d4857b4c68e0886c275a2dff646774fc0da15bc993e` |
| `server/routes.py` | `d4905eb8b12bb820553fa1547473f345ed48dc2fba77de872f2691d907778ab9` |
| `server/schemas.py` | `a1993b8c25ec5781c6f6b92a4601728a19dc75a698eeb4cf780972032edaeea3` |

Changed:

| File | SHA-256 |
| --- | --- |
| `main.py` | `50e32fc1a1cc6a3921a2c8b481790b4c727593b3067f483d62d370ee4a0c6d36` |
| `tests/test_grounded_review.py` | `8b990e2fecd84407680ce42aac9660fd4401f9e4c95b465df3777d5428222cbc` |

Denylist hashes unchanged from Task 5 snapshot.

## Installed CLI QA

`.venv/bin/ontologylab reject` on `/private/tmp/ontologylab-wave21-task5-repair.cli`
(now deleted):

```
EXIT 0
[ontologylab] rejected node acb4e1d5d6a943c5b7e40d91b60157c3
[ontologylab] decision_receipt_ids sha256:f109d65541069a94818ed3095cacff4d28aced6f07b13177ebc576268c6e9238
```

Persisted receipt and citation id `sha256:250d66be…` match. No
`Application Support` in output.

PID 55560 / `127.0.0.1:8799` unchanged (`ELAPSED 17-11:14:54` before and
after). QA root removed. No leftover processes.

## Stop

Reject CLI now emits the same `decision_receipt_ids` line as other grounded
review actions. Legacy rejected-line compatibility kept. No commit.
