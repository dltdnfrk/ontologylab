# DoneClaim — Task 12 review repair round 3

Executor: omo senpi-task child `st_01a0322c`
Date: 2026-08-24
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit/push)
Authority: `task-12-review-repair-2-code.md` MAJOR 1.

## Verdict

DONE. Extra valid unpublished live documents outside claimed closure stay
unshipped as rows/bytes, appear only in the inventoried
`source-fingerprint.json` witness, and reviewed/sourced labels survive
finalize/verify/list/activate/MCP. Fingerprint witness / C-036 /
membership / parser tampers refuse before serving. Extra-run witness
from Round 2 still holds. Prior R1–R6 stay GREEN.

## Design

- New `pack_source_fingerprint.py` captures canonical
  `[[document.id, IFNULL(content_hash,'')], ...]` entries, writes
  owner-read-only `{entries:[[id,hash],...]}`, loads it strictly, and
  recomputes the migration fingerprint from those pairs.
- Collect captures the authorized LIVE document witness on
  `PackV2Closure` before copy.
- `write_v2_evidence` writes `source-fingerprint.json` before finalize
  inventories it, so `artifact_inventory` / `pack_content_hash` bind
  the bytes.
- `derive_capabilities` recomputes the witness fingerprint, requires
  it equal packed C-036 `source_fingerprint`, and requires every packed
  document pair to be an exact witness member. Direct packed
  `compute_source_fingerprint(conn)` compare is gone. Receipt
  witness/root/subset, generation/ledger, decision, and scope checks
  remain.

## Changed hashes

| Path | SHA-256 |
| --- | --- |
| `ontologylab/pack_source_fingerprint.py` | `a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7` |
| `ontologylab/pack_v2_derive.py` | `7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577` |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |
| `tests/test_pack_v2_review_repair.py` | `d2088b1e863a29b69866a645754561874fe136ad0c09eebdc32e71c3a486914c` |

Unchanged Round 2 production (not required this round):

| Path | SHA-256 |
| --- | --- |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` |
| `ontologylab/pack_verifier.py` | `9fa11d41aeda3677725fa222697e98c710e1e0c474d720913eefd3d353bb1273` |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` |

Pure LOC: fingerprint 86, derive 245. Closure remains SIZE_OK. No commit.

Entry test scaffold (RED, preserved then strengthened):
`715a0ab49717905e2d5fb84fbf55cdef5652410caf91b1090b3f151a01e2e25d`

## RED (lead, before this production)

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py \
  -k 'unpublished_live_document or source_fingerprint_witness' \
  --override-ini addopts= -q --tb=line
6 failed
```

| Test | Named reason |
| --- | --- |
| unpublished live document | valid unpublished doc drops reviewed |
| tampered fingerprint witness | `source-fingerprint.json` absent |
| invalid witness ×4 (reorder/duplicate/wrong-shape/packed-missing) | `source-fingerprint.json` absent |

## GREEN

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py --override-ini addopts= -q
19 passed in 2.11s
EXIT:0
```

Focused Task 12 + prior 10-file set (now 152):

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py \
  tests/test_pack_v2_closure.py tests/test_pack_v2_verifier.py \
  tests/test_pack_v2_publication_surface.py tests/test_pack_readiness_refusal.py \
  tests/test_verified_pack_reader.py tests/test_mcp_pack_integrity.py \
  tests/test_packdiff.py tests/test_ontology_pack_publication.py \
  tests/test_staleness.py --override-ini addopts= -q
152 passed, 1 warning in 9.73s
EXIT:0
```

Affected + methodology 15-file set (Round 2 receipt):

```
139 passed, 1 warning in 9.28s
EXIT:0
```

basedpyright on fingerprint/derive/closure + tests: 0/0/0.
`python3.11 -m py_compile` on changed production files: EXIT 0.
LSP clean on the four owned files. no-excuse: 0 violations.

## Mutation (kill then gold restore)

Gold `/tmp/t12r3-gold`. Restores from those copies; post-restore SHA
matches gold.

| Mutant | File | Named test | Failure | Mutant SHA-256 | Restored |
| --- | --- | --- | --- | --- | --- |
| direct packed fingerprint compare | `pack_v2_derive.py` | `test_unpublished_live_document_*` | reviewed absent | `5cee71d5…de5e` | yes |
| copy unrelated docs | `pack_v2_closure.py` | same | extra doc present in pack DB | `3719fdc8…91d8` | yes |
| witness not inventoried | `pack_v2_closure.py` | same | reviewed absent | `38c7bddc…2ace` | yes |
| witness fingerprint unchecked | `pack_source_fingerprint.py` | `test_wrong_c036_source_fingerprint_*` | DID NOT RAISE | `798cbecf…86e8` | yes |
| packed-doc membership unchecked | `pack_source_fingerprint.py` | `test_invalid_*[packed-missing]` | DID NOT RAISE | `60e0091d…d986` | yes |
| permissive parser/order/duplicate | `pack_source_fingerprint.py` | `test_invalid_*[extra-key]` | DID NOT RAISE | `84b3c12f…2669` | yes |
| capability trust fallback | `pack_verifier.py` | `test_unreviewed_forged_labels_with_fingerprint_witness_*` | DID NOT RAISE | `cf0a9037…4df9` | yes |

## Manual QA (`t12r3-qa-*`, removed)

Authorized live extra **run** + unpublished **document** → packs
`qa-both-20260824-142215` and `qa-both-sib-20260824-142215`:

- capabilities include `reviewed` + `sourced-answer-v2`
- extra doc/run absent from pack sqlite; extra doc bytes absent
- both witnesses inventoried, mode `0444`
- `python -m ontologylab.pack_readiness --publish` EXIT 0
- standalone `pack_verifier` EXIT 0; `list_packs` / `activate_pack` reviewed
- real stdio MCP `initialize.protocolVersion=2025-06-18`; lookup hits
  PaymentGateway; unpublished text absent
- tampered `source-fingerprint.json`: verifier/list/activate/MCP
  `invalid_manifest:capabilities`; prior session lookup held
- tampered `receipt-inventory.json` on sibling: same refuse; prior
  session still held
- MCP pid 53663 rc=0; root removed

`QA_STATUS=0` `QA_CLEANED=True`

## Protected

- HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`
- index empty
- PID 55560 still `127.0.0.1:8799` inode `0x1ff51c806b197195` at entry and exit
- no Application Support / network / commit / push / full suite

DONE
