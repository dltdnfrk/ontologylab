# DoneClaim — Task 12 review repair round 2

Executor: omo senpi-task child
Date: 2026-08-24
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit/push)
Authority: `task-12-review-repair-code.md` MAJOR 1.

## Verdict

DONE. Extra valid live receipts outside claimed closure stay unshipped
as rows, appear only in the inventoried source witness, and reviewed/
sourced labels survive finalize/verify/MCP. Witness/C-036/membership
tampers refuse before serving. Prior R1–R6 stay GREEN.

## Design

- `seal_receipt_inventory` now exposes canonical
  `[family, receipt_id, body_digest]` entries.
- Collect captures the authorized LIVE entries on `PackV2Closure`.
- `write_v2_evidence` writes owner-read-only `receipt-inventory.json`
  before finalize inventories it, so `pack_content_hash` binds the bytes.
- `derive_capabilities(..., pack_root=)` recomputes the witness root,
  requires it equal the packed C-036 root, reseals packed receipts, and
  requires packed entries ⊆ witness. Extra witness rows are audit-only.

## Changed hashes

| Path | SHA-256 |
| --- | --- |
| `ontologylab/pack_v2_derive.py` | `e5ee3cc0b4be2c987d368d72bb9d6d0ee998d1b2156163c357ad83577e3c5946` |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` |
| `ontologylab/pack_v2_closure.py` | `24d2e2f31671d988b8a28aec409b360df057d0e12ca57d2820d46c4b6503cba2` |
| `ontologylab/pack_verifier.py` | `9fa11d41aeda3677725fa222697e98c710e1e0c474d720913eefd3d353bb1273` |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` |
| `tests/test_pack_v2_review_repair.py` | `97cdaaa515ac295de105cdbfc3686feec048b2b69236e10b4969fba039bf1cad` |

Pure LOC: derive 245. No commit.

## RED (before production)

```
.venv/bin/python -m pytest \
  tests/test_pack_v2_review_repair.py::test_extra_live_run_keeps_reviewed_labels_and_stays_unshipped \
  tests/test_pack_v2_review_repair.py::test_tampered_source_inventory_witness_is_refused \
  tests/test_pack_v2_review_repair.py::test_packed_receipt_absent_from_witness_is_refused \
  --override-ini addopts= -v --tb=short
3 failed in 0.49s
EXIT:1
```

| Test | Named reason |
| --- | --- |
| extra live run | disk caps unreviewed (`reviewed` absent) |
| tampered witness | `FileNotFoundError: receipt-inventory.json` |
| packed not in witness | same missing witness file |

## GREEN

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py --override-ini addopts= -q
10 passed
EXIT:0
```

Focused Task 12 + prior 140-set (now 143):

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py \
  tests/test_pack_v2_closure.py tests/test_pack_v2_verifier.py \
  tests/test_pack_v2_publication_surface.py tests/test_pack_readiness_refusal.py \
  tests/test_verified_pack_reader.py tests/test_mcp_pack_integrity.py \
  tests/test_packdiff.py tests/test_ontology_pack_publication.py \
  tests/test_staleness.py --override-ini addopts= -q
143 passed, 1 warning in 6.84s
EXIT:0
```

Affected + methodology:

```
139 passed, 1 warning in 7.34s
EXIT:0
```

basedpyright on derive/manifest/readiness/seal + new tests: 0 errors.
`python3.11 -m py_compile` on changed production files: EXIT 0.
LSP clean on `pack_v2_derive.py`.

## Mutation (kill then gold restore)

| Mutant | File | Named test | Failure | Mutant SHA-256 | Restored |
| --- | --- | --- | --- | --- | --- |
| direct subset-root compare | `pack_v2_derive.py` | `test_extra_live_run_*` | reviewed absent | `b148aac5…d9e1` | yes |
| copy all unrelated rows | `pack_v2_closure.py` | same | extra run present in pack DB | `e19754c3…36df` | yes |
| witness not inventoried | `pack_v2_closure.py` | same | reviewed absent | `fa8ef6a0…8a7d` | yes |
| witness root unchecked | `pack_v2_derive.py` | `test_tampered_source_inventory_*` | DID NOT RAISE | `7d8b59e1…2ef8` | yes |
| packed-subset unchecked | `pack_v2_derive.py` | `test_packed_receipt_absent_*` | DID NOT RAISE | `145f6e0c…80d5` | yes |
| capability trust fallback | `pack_verifier.py` | `test_forged_reviewed_labels_*` | DID NOT RAISE | `4824d311…7352` | yes |

## Manual QA (`t12r2-qa-n7d9vumw`, removed)

Authorized live extra run → pack `qa-extra-20260824-135026`:

- capabilities include `reviewed` + `sourced-answer-v2`
- extra run absent from pack sqlite (1 packed run)
- witness includes extra run id
- `verify_pack` ok; MCP lookup works, schema 2
- tampered witness reload: `PackIntegrityError`; prior lookup held

`QA_STATUS=0` `QA_CLEANED=True`

## Protected

- HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`
- PID 55560 still `127.0.0.1:8799` inode `0x1ff51c806b197195`
- no Application Support / network / commit / push / full suite

DONE
