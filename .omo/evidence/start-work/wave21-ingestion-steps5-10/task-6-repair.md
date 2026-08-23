# Repair — wave21 steps 5–10 / task-6

Executor: omo senpi-task `st_01a02f69` (rework)
Date: 2026-08-23
HEAD: `0a3c7a21d5ee8fbcfb7aa7bf521921e0e333ea29` (unchanged; no commit)
Denylist unread/unedited/unimported; SHA-256 unchanged from task-6-executor.

## Gaps closed

1. Source/destination overlap is typed `source_overlap` before mkdir/open/copy.
   Same root, dest inside source tree, and dest store inode == source are refused.
   Source tree hashes stay identical; no nested dest is created.
2. Every VERIFIED H1 row stores `family_receipt_id` equal to the Task 2/4/5
   receipt minted in the same SAVEPOINT. Quarantined rows keep NULL and never
   materialize. Receipt root binds ordered `(family, anchor_id, family_receipt_id)`.
3. Missing `verified_ts` is `missing_timestamp` quarantine with zero
   `grounded_review_decisions`. Verified reviews seal `raw_byte_seal`/`file_hash`
   from the Citation representation hash and `span_hash` from Task 5
   `citation_set_digest`; `family_receipt_id` equals the ReviewDecision id.
   No `0.0` sentinel time.

## RED (before product edits)

```
.venv/bin/python -m pytest tests/test_h1_migration.py -q --tb=line
................FFFFFF
EXIT:1
```

Named reasons:

- `DID NOT RAISE H1SourceRefused` (same-root and dest-inside-source)
- `assert None is not None` (`family_receipt_id` null on verified rows)
- `assert None` (review seals null)
- `assert 'verified' == 'quarantined'` (NULL `verified_ts` treated as `0.0`)
- `assert 0 != 0` (CLI overlap exit 0)

16 prior H1 tests stayed green.

## GREEN

```
.venv/bin/python -m pytest tests/test_h1_migration.py -q --tb=short
......................
EXIT:0
```

22 passed.

## Mutation (kill then byte-identical restore)

| Mutant | Change | Failure | Restored |
| --- | --- | --- | --- |
| overlap check removed | `_refuse_overlap` early `return` | DID NOT RAISE | yes |
| family receipt id dropped | persist classified decision without `with_family_receipt` | `family_receipt_id is None` | yes |
| review seals dropped | verified review seals `None` | `assert None` | yes |
| missing timestamp as 0.0 | inventory `decided = 0.0` | `verified` != `quarantined` | yes |

Post-restore hashes:

| File | SHA-256 |
| --- | --- |
| `h1.py` | `d986c6bc42ce8940bafdc58761342ed1b784c0654c4c1a9e4631232b5e6906a2` |
| `h1_finalize.py` | `02563b9f904a78306c4b1add18fa38cbe72250507ffe746ac288e9f4bcb89a4e` |
| `h1_classify_cite.py` | `002dc1647f8f73e49687a6e19ccf9bfe281a05a4d39792213b22323fdf9c07f3` |
| `h1_inventory.py` | `92625f0d8404611752e6882a545c1a30d40e49841a24379bec094ecdbce24b18` |
| `h1_types.py` | `cbdd3c6182d54cb242db56f5d18328a26fae08515978fd3390ba2bb851e365af` |
| `h1_migrate.py` | `8e66e6c7b244542d290fec6f86b44acccfe9c777fc4318ed9baa63b5dc0c2404` |
| `h1_materialize.py` | `93b5f70ae884620ad6db2c1f7c4d88be644dea48523874f1c599ba738f55f3a6` |
| `h1_materialize_review.py` | `8592f90b92c9e9270bf9d1106ddd76d1a9d1edf21e72da4279f4fac64f397bf6` |
| `h1_decisions.py` | `223bed696e9fef900b20c06ad51546a354c9ee87ade094304e2a2de5b3972c44` |
| `tests/test_h1_migration.py` | `65dea7fa47e32393a3c7b85a8043aadf3001d8cc892b66b8f52ca86c48d44d21` |

## Verify (once)

Focused H1 + Task 2/4/5 + migration_backfill/rehearsal:

```
.venv/bin/python -m pytest tests/test_h1_migration.py tests/test_extraction_receipts.py tests/test_citation_receipts.py tests/test_grounded_review.py tests/test_migration_backfill.py tests/test_migration_rehearsal.py -q --tb=line
........................................................................ [ 85%]
............                                                             [100%]
EXIT:0
```

84 passed (prior 78 + 6 repair tests). No full suite. No retry.

```
/Users/hyunjun/.local/bin/basedpyright <all changed h1_*.py + main.py + tests/test_h1_migration.py>
0 errors, 0 warnings, 0 notes
```

## Manual QA

`/private/tmp/ontologylab-wave21-task6-repair.qa` (deleted).

- OVERLAP `source_overlap`, source tree unchanged, no nested dest
- INSIDE `source_overlap`, dest absent
- TWOPASS receipt equality, pending 0, source unchanged
- REVIEW_SEAL family id == ReviewDecision id, span_hash == citation_set_digest, file/raw == representation hash
- VERIFIED_FAMILY_IDS zero NULL family ids on verified rows
- MISSING_TS `quarantined missing_timestamp`, 0 Task 5 rows
- RESUME complete, pending 0
- CLI overlap exit 2 `source_overlap`; CLI ok pending 0 complete true
- PID 55560 / 8799 unchanged

Cleanup: QA root and scripts removed.

## Scope

No Task 7+. No commit. No full suite. Denylist hashes identical to task-6-executor.
