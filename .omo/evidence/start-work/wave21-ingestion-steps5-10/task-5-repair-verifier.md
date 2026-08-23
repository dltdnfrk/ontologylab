# AdversarialVerify — wave21 task-5 repair (CLI reject receipts)

Verifier: omo senpi-task `st_01a02f51` (repair re-verify)
Date: 2026-08-24
HEAD: `7c159fd3efa24a5b9839e0ae32643e7f90560124` (unchanged; no commit)
Claim: `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-repair.md`
Constraint: report only as durable write; denylist unread; no Task 6 / full
suite / commit; PID 55560 / port 8799 untouched.

## Verdict

`confirmed`

Confidence: `0.96`

The repair is exactly one call in `cmd_reject` to the existing
`_print_review_receipts` helper, locked by
`test_cli_reject_emits_decision_receipt_ids`. Suppressing that call restores
`main.py` to the pre-repair Task 5 hash and fails the new test because the
ReviewDecision exists in SQLite while stdout is only the legacy rejected
line. Installed `.venv/bin/ontologylab reject` prints the stored receipt id
and keeps the rejected line. Every other Task 5 owned hash still matches the
prior verifier freeze.

## Freeze (pre-test = post-mutation = post-QA)

HEAD `7c159fd3efa24a5b9839e0ae32643e7f90560124`. Staged paths: none.
PID 55560 `127.0.0.1:8799` inode `0x1ff51c806b197195` before QA, after QA,
and after cleanup.

Vs prior Task 5 verifier freeze (`task-5-verifier.md`):

| Path | SHA-256 | vs prior freeze |
| --- | --- | --- |
| `ontologylab/grounded_review.py` | `105e45da8363e8737f5b4156f8d75d4b929e88a12d0f5649e387897500e417e0` | MATCH |
| `ontologylab/grounded_review_ids.py` | `4af4a46e68a9a4d62e3e040fd09d9452a3e05bfdfc7da01f41c6cb92bb19c226` | MATCH |
| `ontologylab/grounded_review_payload.py` | `692b9a5a6b733cd1afda10ec5c33fea88b887c4e29f693a676b206db1cf3dc7a` | MATCH |
| `ontologylab/grounded_review_preflight.py` | `b6c754bf500a9e384be4dc19fe024bca7d5efbc03dc764e588d6fd9291dc2a45` | MATCH |
| `ontologylab/grounded_review_schema.py` | `cdc9ef8790d0f5ee01e4b57c214f4811d835b6fb04ec7f8457d109b9550a1771` | MATCH |
| `ontologylab/grounded_review_store.py` | `c98f3a38cd8a3ec311b857fcb943acd8b173d684999001f9284dde6f9e09af5a` | MATCH |
| `ontologylab/grounded_review_types.py` | `d64716d46155d66d42a958aa4b5cc6cdbeca06b34a302e985e5b6a8a0d4610ba` | MATCH |
| `ontologylab/kgstore.py` | `0f37cc1d511917ff4b766c51301ec623ea02d539a1b7298bc62a0c3b1eb64013` | MATCH |
| `ontologylab/extraction_state.py` | `7fba7e0f397cd81837412d4857b4c68e0886c275a2dff646774fc0da15bc993e` | MATCH |
| `ontologylab/server/routes.py` | `d4905eb8b12bb820553fa1547473f345ed48dc2fba77de872f2691d907778ab9` | MATCH |
| `ontologylab/server/schemas.py` | `a1993b8c25ec5781c6f6b92a4601728a19dc75a698eeb4cf780972032edaeea3` | MATCH |
| `ontologylab/critic.py` | `eb0a3aec8d34ccadffe3c9c3cb07b394a2ae7c09734644a8cd41910099f352b0` | MATCH |
| `ontologylab/main.py` | `50e32fc1a1cc6a3921a2c8b481790b4c727593b3067f483d62d370ee4a0c6d36` | CHANGED (repair) |
| `tests/test_grounded_review.py` | `8b990e2fecd84407680ce42aac9660fd4401f9e4c95b465df3777d5428222cbc` | CHANGED (repair) |

Denylist meta-only (unread/unedited; hashes unchanged from Task 5 snapshot):
`review_decision.py` `6aa8781a…`, ids `278aef15…`, schema `d69db550…`,
store `cd582050…`, types `abf7171f…`, `review_grounding.py` `4bc5f793…`.
No denylist imports in the two changed files. No H1 / pack-v2 / Task 6
symbols.

## Inspected delta

`cmd_reject` now calls `_print_review_receipts(result)` after the legacy
`[ontologylab] rejected {kind} {id}` line. Helper unchanged. No other
`main.py` repair hunk beyond that one call relative to the prior Task 5
`main.py` (`504bb8de…`).

New test `test_cli_reject_emits_decision_receipt_ids` drives
`ontologylab.main.main(["reject", …])` on a planted grounded node, asserts
exit 0, keeps the rejected line, then asserts stdout contains
`decision_receipt_ids {stored.receipt_id}` from `list_review_decisions`.
That pins the machine token + stored receipt, not prose.

## Mutation

Removed only the `_print_review_receipts(result)` line in `cmd_reject`.
Mutant `main.py` hash became
`504bb8de26dea05281bf6df68d29b60346f58cfcfd5895cd7719dbe1b0290093`
(exact pre-repair Task 5 bytes).

```
.venv/bin/python -m pytest tests/test_grounded_review.py::test_cli_reject_emits_decision_receipt_ids -q --tb=short
F
EXIT:1
AssertionError: assert '[ontologylab] decision_receipt_ids sha256:2998a383…' in
  '[ontologylab] rejected node 0d502a4a…\n'
```

Named reason holds: decision persisted, stdout omitted the receipt.
Restored `main.py` hash `50e32fc1…`. Test file hash unchanged during mutate.

## Automated (each once)

```
.venv/bin/python -m pytest tests/test_grounded_review.py tests/test_cli.py -q --tb=short
.....................
21 passed
```

```
/Users/hyunjun/.local/bin/basedpyright ontologylab/main.py tests/test_grounded_review.py
0 errors, 0 warnings, 0 notes
```

No full suite. No retry-to-pass.

## Installed CLI QA

`.venv/bin/ontologylab reject` on disposable
`/private/tmp/ontologylab-wave21-task5-repair-vfy.cli` (removed):

```
EXIT 0
[ontologylab] rejected node d7711a2f043a435e8bc41766d979977f
[ontologylab] decision_receipt_ids sha256:02c80d92f78521bbebe67add4d07d34cf5f636361f75e8d329ca79ba5d698163
```

Stored `list_review_decisions` receipt
`sha256:02c80d92f78521bbebe67add4d07d34cf5f636361f75e8d329ca79ba5d698163`
matches stdout exactly. Actor `qa-repair`, reason `repair-cli-reject`,
citation digest `sha256:5c056261…`, citation id `sha256:e2c26f6d…`.
Gateway `rejected`; service/edge still `proposed`. No
`Application Support` / home-path leak.

## Cleanup

Removed QA root, QA driver, main.py backup, `.debug-journal.md`.
`ls /private/tmp/ontologylab-wave21-task5-repair-vfy*` → none.
Serve processes: only PID 55560. Inode `0x1ff51c806b197195` unchanged
(`ELAPSED 17-11:15:51` start → `17-11:17:27` end). Product hashes MATCH
freeze. No staged paths. No commit.

## Stop

`confirmed`. CLI reject now emits the stored ReviewDecision receipt beside
the legacy rejected line. Isolated suppress-print mutant fails for that
reason and restores byte-identically.
