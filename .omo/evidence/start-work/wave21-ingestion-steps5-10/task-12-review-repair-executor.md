# DoneClaim — Task 12 review repair (R1–R6)

Executor: omo senpi-task child
Date: 2026-08-24
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit/push)
Authority: `task-12-review-goal.md`, `task-12-review-code.md`,
`task-12-review-security.md`, pack-contract §§7–8, blueprint §0 / Step 8.

## Verdict

DONE. All six blocking REDs are GREEN on real surfaces. Ten named mutants
died and restored. PID 55560 / 8799 untouched.

## Repair

| Path | Role | SHA-256 |
| --- | --- | --- |
| `ontologylab/pack_v2_derive.py` | counts / exclusions / C-036 caps / evidence | `53ff5ac530e2e62a5cf069c4a54eca0332a427a3e2c6f245119c5cd5debe0a55` |
| `ontologylab/pack_v2_manifest.py` | finalize uses derived counts + caps | `6e87c1075e327942ce6ef4ab118350345efa675b5045984dda23ef91d8f34675` |
| `ontologylab/pack_v2_closure.py` | exclusions + packed C-036 copy | `2db1454ae6517d29a038e1c94c6ee47f4f614659e68801f4f9ce90843dd14d55` |
| `ontologylab/pack_verifier.py` | derive counts; refuse forged caps; allow `sha256:` evidence paths | `e9ad5467f6a5cba3d658a21613819fef22b6a1f79d56180f36ceb4395f81cc53` |
| `ontologylab/pack_readiness.py` | CLI JSON for closure/build refusals | `550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21` |
| `ontologylab/mcp_server.py` | fact receipts + `document_raw_text` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` |
| `tests/test_pack_v2_review_repair.py` | six RED/GREEN public surfaces | `5594956f904017e4ac1ca50bde019b2632afc157966e6a5db9ed1d8d10662276` |
| `tests/test_pack_v2_closure.py` | honest count assertions | `96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff` |
| `tests/test_pack_v2_verifier.py` | count keys + default exclusions | `5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b` |
| `tests/test_packdiff.py` | `_v2_wrap` uses derive | `296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6` |

Pure LOC: derive 188, manifest 111, readiness 246. No commit.

`document_raw_text` is a `PackSession` method (same MCP logic surface).
It is not a 16th FastMCP tool so the pinned 15-tool methodology /
two-tier / method-surface contracts stay GREEN.

## RED (before production)

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py --override-ini addopts= -v --tb=line
7 failed in 0.75s
EXIT:1
```

| Test | Named reason |
| --- | --- |
| MCP provenance | `pack_schema_version` missing (`None == 2`) |
| counts | `observations` 0 == 1 |
| exclusions | `KeyError: exclusions` |
| FULL raw text | `PackSession` has no `document_raw_text` |
| excerpt limitation | activate `path_mismatch` on `sha256:` evidence path |
| CLI closure | exit 1 + traceback `sourced_none:source` |
| forged labels | `DID NOT RAISE PackVerifyRefused` |

## GREEN

Focused repair + Task 8–11 surfaces (once on final bytes):

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py \
  tests/test_pack_v2_closure.py tests/test_pack_v2_verifier.py \
  tests/test_pack_v2_publication_surface.py tests/test_pack_readiness_refusal.py \
  tests/test_verified_pack_reader.py tests/test_mcp_pack_integrity.py \
  tests/test_packdiff.py tests/test_ontology_pack_publication.py \
  tests/test_staleness.py --override-ini addopts= -q
140 passed, 1 warning in 7.37s
EXIT:0
```

Affected 133 + methodology signature (once):

```
.venv/bin/python -m pytest tests/test_mcp_session.py tests/test_staleness.py \
  tests/test_pack_discovery_validation.py tests/test_pack_hash.py \
  tests/test_mcp_two_tier.py tests/test_packbuilder.py \
  tests/test_pack_schema_contract.py tests/test_method_mcp_surface.py \
  tests/test_cli.py tests/test_pipeline_e2e.py tests/test_migration.py \
  tests/test_pack_completeness.py tests/test_citation_receipts.py \
  tests/test_grounded_review.py tests/test_methodology_foundation_baseline.py \
  --override-ini addopts= -q
139 passed, 1 warning in 7.17s
EXIT:0
```

basedpyright on new/changed typed modules (excluding pre-existing FastMCP
`reportReturnType` on `mcp_server.py` wrappers): 0 errors.
`python3.11 -m py_compile` on all changed production files: EXIT 0.
LSP clean on `pack_v2_derive.py` and `test_pack_v2_review_repair.py`.

## Mutation (kill then gold restore)

Gold `/tmp/t12-repair-gold`. Restores from those copies.

| Mutant | File | Named test | Failure | Mutant SHA-256 | Restored |
| --- | --- | --- | --- | --- | --- |
| wrong count table | `pack_v2_derive.py` | `test_v2_counts_use_packed_observation_and_review_tables` | `observations` 0==1 | `92cbcbb7…e470d` | yes |
| dropping verified counts | `pack_v2_derive.py` | same | `nodes_verified` 0==2 | `04b0b695…c559` | yes |
| constant-zero exclusions | `pack_v2_derive.py` | `test_v2_manifest_emits_required_exclusion_counts` | `ungrounded` 0>=1 | `5ec24f2b…376a` | yes |
| raw live-path fallback | `pack_v2_derive.py` | `test_full_v2_document_raw_text_*` | path `documents/…` != `evidence/…` | `6f1be88f…5654` | yes |
| missing citation provenance | `mcp_server.py` | `test_mcp_fact_results_*` | `citation_id` None | `36d442a0…562a` | yes |
| pack-only provenance | `mcp_server.py` | same | `pack_schema_version` None | `723baed9…36ab` | yes |
| CLI catches only readiness | `pack_readiness.py` | `test_cli_publish_emits_json_*` | exit 1 traceback | `11b047d5…c54d` | yes |
| manifest capability trust | `pack_verifier.py` | `test_forged_reviewed_labels_*` | DID NOT RAISE | `37154541…ff2a` | yes |
| capability comparison removed | `pack_verifier.py` | same | DID NOT RAISE | `4ed2041c…4064` | yes |
| C-036 derivation skipped | `pack_v2_derive.py` | same | unreviewed pack ships `reviewed` | `ae57b4cd…b2d` | yes |

## Manual QA (disposable `t12-qa-10_zk4be`, removed)

Reviewed/sourced pack `qa12-20260824-132710`:

- counts `observations=1` `review_decisions=3` `nodes_verified=2` `edges_verified=1`
- exclusions present; caps include `reviewed` + `sourced-answer-v2`
- standalone verifier EXIT 0
- `PackSession` lookup: work/representation/citation receipts + pack schema 2
- `document_raw_text` available, `evidence/<rep>/full.txt`, 44 bytes
- `get_staleness` `pack_verified_count=3`
- pack-diff two valid v2 packs
- forged labels on unreviewed pack: `verify_pack` `invalid_manifest`
- tampered sibling load: `PackIntegrityError`; prior lookup held
- CLI `--evidence-mode none`: exit 2, `{"code":"sourced_none",...}`, no traceback

`QA_STATUS=0` `QA_CLEANED=True`

## Protected

- HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`
- PID 55560 still `127.0.0.1:8799` inode `0x1ff51c806b197195`
- no Application Support / network / commit / push / full suite

DONE

## Round 2 — live inventory witness (unshipped extra run)

Authority: `task-12-review-repair-code.md` MAJOR 1. A legal extra live run
receipt outside claimed closure no longer drops reviewed/sourced labels.
Packed rows stay the claimed subset. Live C-036 root is rebound through
inventoried `receipt-inventory.json` (bound by `pack_content_hash`).

See `task-12-review-repair-2-executor.md` for RED/GREEN/mutation/QA/hashes.

## Round 3 — live document fingerprint witness (unshipped extra doc)

Authority: `task-12-review-repair-2-code.md` MAJOR 1. A legal unpublished
live document present at C-036 bind no longer drops reviewed/sourced
labels. Packed rows stay the claimed subset. Live C-036 fingerprint is
rebound through inventoried `source-fingerprint.json` (bound by
`pack_content_hash`). Packed `compute_source_fingerprint(pack)` is no
longer compared to the live bind.

See `task-12-review-repair-3-executor.md` for RED/GREEN/mutation/QA/hashes.

## Round 4 — packed v2 closure completeness at verify

Authority: `task-12-review-repair-3-security.md` residual. A
hash-refreshed pack that deletes a citation, document, review, run,
chunk, policy, or evidence member — or claims a dangling closure ID —
is refused as typed `invalid_manifest` before serve. Capability
witnesses still allow extra live runs/docs to stay unshipped.

See `task-12-review-repair-4-executor.md` for RED/GREEN/mutation/QA/hashes.

## Round 5 — evidence capability requires a typed v2 contract

Authority: `task-12-review-repair-4-security.md` H-SKIP-UNREV-KEEP-EV.
Advertising `evidence-self-contained-v2` on a real packed v2 graph now
always requires `pack_schema_version==2`, `evidence_mode` in
full/excerpt, and an exact typed closure mapping, then runs full
`validate_packed_v2_closure`. The frozen citation-delete + C-036 drop +
`evidence_mode`/`closure` strip no longer verifies, lists, activates, or
switches a real MCP session. Inventory-only `_write_v2` stays allowed.

See `task-12-review-repair-5-executor.md` for RED/GREEN/mutation/QA/hashes.

## Round 6 — v1 parse refuses v2 authority laundering

Authority: `task-12-review-final-security.md` MEDIUM. A reviewed+sourced
v2 pack rewritten as schema 1 or omitted schema, with raw `reviewed` /
`sourced-answer-v2` / `evidence-self-contained-v2` and a legacy
`content_hash`, is refused as typed `invalid_manifest:capabilities`
before list/activate/MCP can serve those labels or switch a live
session. `_parse_v1` also refuses v2-only contract fields and any
capability outside the historical allowlist. Legitimate v1 stays valid.

See `task-12-review-repair-6-executor.md` for RED/GREEN/mutation/QA/hashes.
