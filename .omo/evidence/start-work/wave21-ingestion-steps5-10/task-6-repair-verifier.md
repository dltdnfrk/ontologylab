# AdversarialVerify — wave21 steps 5–10 / task-6 repair

Verifier: omo senpi-task `st_01a02f7f` (repair reverify)
Date: 2026-08-23
HEAD: `0a3c7a21d5ee8fbcfb7aa7bf521921e0e333ea29` (unchanged; no commit/push)
Scope: Re-verify the four Task 6 residuals closed in `task-6-repair.md`.
Constraint: report is the only durable verifier write; product/test bytes
restored to the pre-mutant freeze; denylist unread/unopened/unimported;
no Application Support; no network; no 8799 / PID 55560 mutation.

Repair claim (`task-6-repair.md`) treated as a claim. Every hash, mutant
outcome, suite observation, and QA value below was re-measured on current
bytes.

## Verdict

`confirmed`

Confidence: `0.93`

The four residuals from `task-6-verifier.md` are closed on current bytes:

1. Source/destination overlap is typed `source_overlap` **before**
   mkdir/open/copy. Same root, dest-inside-source, dest-is-source-file,
   symlink dest→source-root, hardlinked dest store, and symlink dest
   store are refused. Source tree hashes stay identical; refused dest
   paths are not created; hardlink/symlink aliases gain no `h1_*` tables.
   Dest that is a *safe* ancestor (different `kg.sqlite` inode) is allowed
   and leaves the source tree unchanged.
2. Every verified H1 row has a non-null `family_receipt_id` that exists
   in the matching Task 2/4/5 table (`extraction_run_receipts` /
   `extraction_chunk_receipts` / `citation_receipts` /
   `grounded_review_decisions`). Quarantined rows keep NULL and are not
   materialized. Receipt payload includes ordered
   `(family, anchor_id, family_receipt_id)`; omitting the bind kills the
   family-id test (`family_id is None`).
3. Verified reviews seal `raw_byte_seal`/`file_hash` to the Citation
   representation hash and `span_hash` to Task 5 `citation_set_digest`.
   `family_receipt_id` equals the ReviewDecision `receipt_id`.
4. NULL `verified_ts` is `missing_timestamp` quarantine, zero Task 5
   rows for that fact, and no `0.0` decided_ts anywhere.

Four isolated repair mutants died and restored. Focused GREEN 84 dots /
100% once; H1 file has 22 tests; basedpyright 0/0/0 once. Original ten
decision tests are still present. No Task 7+ / pack / commit / full suite.

## Precondition (independent freeze)

HEAD `0a3c7a21d5ee8fbcfb7aa7bf521921e0e333ea29`. Staged owned paths: none.
Tracked owned diff still only `ontologylab/main.py` `+3` `add_h1_parser`.
PID 55560 listening `127.0.0.1:8799` inode `0x1ff51c806b197195` before
tests, after mutants, after QA, and after cleanup.

Owned SHA-256 (pre-tests = post-mutation = post-QA):

| Path | SHA-256 | bytes | pure LOC |
| --- | --- | --- | --- |
| `ontologylab/h1.py` | `d986c6bc42ce8940bafdc58761342ed1b784c0654c4c1a9e4631232b5e6906a2` | 3707 | 110 |
| `ontologylab/h1_bytes.py` | `834d90ee101fbbe0bad13751d2c59882fbf6280f030259a1e04fa4642b55a1e6` | 1721 | 50 |
| `ontologylab/h1_classify.py` | `70a04874bb927c98b01dae8c96022b0aaaecae4411ae4ad651e8027dc248521f` | 4175 | 112 |
| `ontologylab/h1_classify_cite.py` | `002dc1647f8f73e49687a6e19ccf9bfe281a05a4d39792213b22323fdf9c07f3` | 7583 | 197 |
| `ontologylab/h1_cli.py` | `dfb1f986e6391f8d5ccba8cb3681372f56929d08e9039a65e1e20e6bb1036c35` | 2050 | 49 |
| `ontologylab/h1_decisions.py` | `223bed696e9fef900b20c06ad51546a354c9ee87ade094304e2a2de5b3972c44` | 1871 | 58 |
| `ontologylab/h1_finalize.py` | `02563b9f904a78306c4b1add18fa38cbe72250507ffe746ac288e9f4bcb89a4e` | 4625 | 131 |
| `ontologylab/h1_ids.py` | `c5f655ada9e46a5e9ef0eadee9d5d73b8246a54e032e735614124f5b9fa67815` | 1293 | 44 |
| `ontologylab/h1_inventory.py` | `92625f0d8404611752e6882a545c1a30d40e49841a24379bec094ecdbce24b18` | 6105 | 164 |
| `ontologylab/h1_materialize.py` | `93b5f70ae884620ad6db2c1f7c4d88be644dea48523874f1c599ba738f55f3a6` | 6753 | 185 |
| `ontologylab/h1_materialize_review.py` | `8592f90b92c9e9270bf9d1106ddd76d1a9d1edf21e72da4279f4fac64f397bf6` | 2543 | 69 |
| `ontologylab/h1_migrate.py` | `8e66e6c7b244542d290fec6f86b44acccfe9c777fc4318ed9baa63b5dc0c2404` | 5222 | 153 |
| `ontologylab/h1_schema.py` | `53231dad362795af2dfca4df13717bbb499bf6408cd3de07f86904e4b3c5c71e` | 1625 | 52 |
| `ontologylab/h1_store.py` | `caae8c76b7f501115561ec5c9973f1810b210a736cfa501f2989ae1e29c4a7a0` | 2727 | 70 |
| `ontologylab/h1_types.py` | `cbdd3c6182d54cb242db56f5d18328a26fae08515978fd3390ba2bb851e365af` | 3720 | 129 |
| `ontologylab/main.py` | `c0fe3c32e80eee383c667fde1fcc5a75c72e9d51d430215e273b9acfe544b989` | 90989 | 2022 (hook only) |
| `tests/test_h1_migration.py` | `65dea7fa47e32393a3c7b85a8043aadf3001d8cc892b66b8f52ca86c48d44d21` | 30044 | 814 |

`h1_classify_cite.py` is in the 200–250 warning band (197). No H1 module
exceeds 250.

Denylist metadata only (unread, unhashed): same six untracked paths,
sizes 6279 / 1652 / 2229 / 6434 / 1928 / 5697. `rg` on owned H1 / main /
`test_h1_migration.py`: no `review_decision*` / `review_grounding` imports.

No Task 7+ / pack-v2 / Step 9C symbols in owned H1 files.

## What current bytes do

- `_refuse_overlap` runs in `run_h1_operator` after the 16-byte SQLite
  magic check and in `prepare_h1_copy`, both **before** `mkdir` /
  `prepare_backup_copy` / `KGStore.open`. It resolves both paths, refuses
  dest==source file, dest==source parent, dest_db==source, dest inside
  `source.parent` (`relative_to`), and `dest_db.exists() and dest_db.samefile(source)`
  (hardlink / symlink alias).
- `H1ReviewAnchor.decided_ts` is `float | None`. Inventory copies NULL as
  `None`, never `0.0`. `classify_review` quarantines `missing_timestamp`
  before actor/reason checks. `materialize_review` also returns `None` if
  `decided_ts is None`.
- `commit_one` / `commit_run_unit` classify, then inside SAVEPOINT
  `h1_anchor`: mint Task 2/4/5 (run+chunks together; citation; review),
  `with_family_receipt`, persist H1, checkpoint. Quarantine keeps
  `family_receipt_id=None`. Chunk H1 rows look up the Task 2 chunk
  receipt minted in the preceding run savepoint (same operator unit;
  lookup by representation + index + exact start/end).
- `build_receipt` hashes `family_receipts` as ordered
  `[family, anchor_id, family_receipt_id]`.
- Review seals: `span_hash = citation_set_digest(citation receipt ids)`;
  `raw_byte_seal`/`file_hash` = unique `representation_content_hash`.

## GREEN (once)

```
.venv/bin/python -m pytest tests/test_h1_migration.py \
  tests/test_extraction_receipts.py tests/test_citation_receipts.py \
  tests/test_grounded_review.py tests/test_migration_backfill.py \
  tests/test_migration_rehearsal.py -q --tb=line
........................................................................ [ 85%]
............                                                             [100%]
```

84 test functions (22+16+16+18+7+5). 84 dots, no `F`. No full suite.
No retry-to-pass.

```
basedpyright <all changed h1_*.py + main.py + tests/test_h1_migration.py>
0 errors, 0 warnings, 0 notes
EXIT:0
```

## Isolated repair mutants (kill then exact restore)

| Mutant | Decision change | Failing assertion | Restored |
| --- | --- | --- | --- |
| overlap guard | `_refuse_overlap` early `return` | `DID NOT RAISE H1SourceRefused` | yes |
| family link | `with_family_receipt` returns unbound decision | `assert family_id is not None` | yes |
| review seals | verified review seals `None` | `assert raw_seal` → `None` | yes |
| timestamp sentinel | NULL `verified_ts` → `0.0` | `assert 'verified' == 'quarantined'` | yes |

Final owned SHA-256 matched the freeze.

## Original ten decisions still covered

These tests are still in `tests/test_h1_migration.py` and were part of the
22-test H1 GREEN run:

| Original decision | Still-present test |
| --- | --- |
| content-hash run authority | `test_h1_same_hash_two_reps_do_not_share_run_authority` |
| root-only / all-family inventory | `test_h1_classifies_every_node_edge_citation_review_anchor` |
| guess/clamp/nearest span | `test_h1_out_of_range_span_is_quarantined_not_repaired` |
| non-idempotent rerun | `test_h1_rerun_is_idempotent_and_byte_identical` |
| source mutation | `test_h1_operator_does_not_mutate_source` |
| missing-as-verified | `test_h1_missing_span_is_quarantined_not_verified` |
| quarantine excluded from pending | `test_h1_pending_zero_includes_quarantine` |
| skipped cancellation checkpoint | `test_h1_interrupt_resume_does_not_duplicate` |
| raw/file/span seals omitted | `test_h1_verified_receipts_seal_raw_file_and_span_hashes` |
| review family omitted | `test_h1_receipt_families_include_run_chunk_citation_review` |

## Fresh real-surface QA

Root: `/private/tmp/ontologylab-wave21-task6-repair-vfy-qa` (deleted).
Public `prepare_h1_copy` / `run_h1_operator` plus installed
`.venv/bin/ontologylab migrate-h1`. No port bind. No Application Support.
No sleeps.

Overlap (all `code=source_overlap`, source tree unchanged, no H1 table on
source / alias store):

| Case | Result |
| --- | --- |
| dest == source parent | refused; no `h1_anchor_receipts` on source |
| dest inside source tree | refused; dest path absent |
| dest is the source file | refused; source unchanged |
| dest is safe ancestor (new dir) | allowed; pending 0; source unchanged |
| dest symlink → source parent | refused; no new nested dest |
| dest/`kg.sqlite` hardlink to source | refused; source hash unchanged; no H1 table |
| dest/`kg.sqlite` symlink to source | refused; no H1 table on source |

Happy path:

- pass 1/2 dump+receipt identical (`TWOPASS_EQUAL True`); pending 0;
  verified 6 / quarantined 2
- `FAMILY_LINKS null_verified=0 matched=6 quarantined_null=2`
- verified review: `family_receipt_id == ReviewDecision.receipt_id`,
  `span_hash == citation_set_digest`, raw/file == representation hash
  `24c97a0e…` (`REVIEW_LINK_OK True`)
- invalid edge citation stays `{"start":0,"end":999}`, quarantined
  `out_of_range`, `family_receipt_id` NULL, no Task 5 row
- NULL `verified_ts`: `quarantined` / `missing_timestamp` / NULL family
  id; Task 5 count 0; remaining decided_ts values `[1.0, 1.0]` (no `0.0`)
- failpoint after 3 durable receipts; resume pending 0, 8 unique, complete
- CLI ok: exit 0, JSON pending 0 complete true
- CLI same-root: exit 2 `source_overlap`
- CLI dest-inside-source: exit 2, `nested` dest absent

No secret or live data-dir paths in CLI JSON.

## Residuals (do not flip the verdict)

Chunk Task 2 receipts are minted in the run SAVEPOINT; the chunk H1 row
is persisted in a follow-up SAVEPOINT that looks up that already-minted
id by representation + index + exact offsets. Citation/review/run mint
and persist in one SAVEPOINT. Family ids still match the Task 2/4/5
rows; this is not the old persist-then-materialize-later hole.

`h1_classify_cite.py` is 197 pure LOC (warning band).

## Cleanup

Removed `/private/tmp/ontologylab-wave21-task6-repair-vfy-qa`,
`/private/tmp/ontologylab-wave21-task6-repair-vfy-qa.py`,
`/private/tmp/ontologylab-wave21-task6-repair-vfy-journal`,
`/private/tmp/ontologylab-wave21-task6-repair-vfy-restore`.
No leftover verifier PIDs. PID 55560 / inode `0x1ff51c806b197195` on
`127.0.0.1:8799` unchanged. Owned SHA-256 still match the freeze.
No commit.
