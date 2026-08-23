# AdversarialVerify — wave21 steps 5–10 / task-7 repair 2

Verifier: omo senpi-task `st_01a02fb8` (final reverify of `task-7-repair-2.md`)
Date: 2026-08-23
HEAD: `8f0e45fdfa1d70e39a91c03737ecb31cb1add3fb` (unchanged; no commit/push)
Scope: Independent proof that valid self-consistent stale identities
do not link, and that `grounded-review-v2` hashes both timestamps.
Constraint: report is the only durable verifier write; mutants via
apply_patch reverse only; denylist unread/unopened/unimported; no
Application Support; no network; no 8799 / PID 55560 mutation.

Repair-2 claim treated as a claim. Every hash, mutant, suite count, and
QA value below was re-measured on current bytes.

## Verdict

`confirmed`

Confidence: `0.94`

Valid internally consistent wrong-policy/config rows no longer become
H1 `family_receipt_id`. Only-stale mints exactly one `legacy-h1-v1` run
with the classified seal. Live+stale links the live Task 2/4/5 ids,
stale absent, no third run. Citation reuse requires the full Task 4
tuple after `get_citation_receipt`. Review reuse requires the full
Task 5 payload (selection/policy/run/predecessor/waiver/pack/time).
`grounded-review-v2` hashes `decided_ts` and `as_of_ts` independently.
Skip-selection, unique-seal fallback, loosened cite/review, skip
`existing_review`, and omit-decided / omit-as-of mutants all died and
restored to the freeze. Owner+integration 104, affected 137, basedpyright
0 once. Real uvicorn HTTP approve on port 64678 returned the stored
`sha256:` id. C-024 / typed-review integration tests remain GREEN.
PID 55560 inode `0x1ff51c806b197195` unchanged.

## Precondition (independent freeze)

HEAD `8f0e45fdfa1d70e39a91c03737ecb31cb1add3fb`. Index empty. Tracked
dirty are the eight product files listed below. Untracked owned:
`h1_existing.py`, `h1_existing_cite.py`, `h1_existing_review.py`,
`tests/step7_valid_stale.py`, `tests/test_grounded_review_identity.py`,
`tests/test_step7_h1_existing.py`, plus the three prior Step 7
integration files. All other committed Task 2–6 paths equal HEAD. No
Task 8 / pack-v2 / F11 / MCP product work.

Owned SHA-256 (pre-tests = post-mutation = post-QA):

| Path | SHA-256 | pure LOC |
| --- | --- | --- |
| `ontologylab/h1_existing.py` | `62be4af9e06140f539d3ead6b7ad2734078c4c442f665ca3631a2626e849deac` | 196 |
| `ontologylab/h1_existing_cite.py` | `934637311f7422faf31b92a7f4bc403a4bf2428a6ed4b5bcf701a50077500c6b` | 149 |
| `ontologylab/h1_existing_review.py` | `6d71e56d240ba3c0c3d9499de2cde24651bb78889ff154e2f5d81b5bc69bff8e` | 133 |
| `ontologylab/grounded_review_ids.py` | `42426bcf4bf1234aa01df2ac054aed205f7786180889352d108bd8204ecdf638` | 139 |
| `ontologylab/h1_finalize.py` | `019aec92d90b68e42fbe16e10df3d4d463fcf08995faf931ac0e689bdc46ea42` | 135 |
| `ontologylab/h1_materialize.py` | `beeda982c33bae2ab9937f598c8978d4302e66d9ed8457389a950c88df7b1171` | 189 |
| `ontologylab/h1_materialize_review.py` | `763eff83552cb0ccac81dbfa070d93a17ef90a51808a0cd97c97662129b37272` | 68 |
| `ontologylab/grounded_review_store.py` | `434e16ed98acaeb7670a4cb1b49791ce2454ea5bf99537dd8403b61df18d2368` | 177 |
| `ontologylab/grounded_review_types.py` | `f1b9c9b203a0114e78d57db3955fc3877b3c8b31f05df299c828c239b908381b` | 109 |
| `ontologylab/kgstore.py` | `a64e55ee5591dd94ad77e260cb1633f4c57a3d86ce5ea51830aab007db97a096` | pre-existing oversized |
| `tests/test_grounded_review_identity.py` | `75058dcac6bff2f0ec58ea221a46c683fec2c83c1099b2f17fbac5793466fcaf` | 208 |
| `tests/test_step7_h1_existing.py` | `c742bdbf3776ef4cf1ed7ae18c22ec4728c3a90f5e02be7b8578089384fa114d` | 195 |
| `tests/step7_valid_stale.py` | `9c4db0e3a91a17f4099f469aa88768dd9dc4015976627af55a6407554e55ae13` | 119 |

Matches repair-2. All new modules ≤250.

Denylist metadata only (unread): same six untracked paths, sizes 6279 /
1652 / 2229 / 6434 / 1928 / 5697. No denylist imports on owned paths.

## Architecture (current bytes)

- Run: if a preferred-selection receipt selects this Representation,
  link the unique self-consistent run with that `policy_hash` + document
  seal. Else link only the deterministic `legacy-h1-v1` expected id when
  representation, seal, policy, config, extractor, prompt, decode, and
  receipt-id all match. `_compatible_run` / unique same-rep+seal
  fallback is gone (`return None` after legacy miss).
- Citation: expected run from `current_run_receipt_id` (selection policy
  or already-linked H1 run), covering chunk, selection/policy from the
  selection receipt else `legacy-h1-v1`. Reuse only that exact Task 4
  tuple after `get_citation_receipt`.
- Review: cite set is only those exact citations; require selection,
  policy, run from that set, no predecessor, pack-eligible, empty
  waiver, decided/as-of == anchor time; v1-or-v2 id of the stored
  payload.
- `review_decision_id` v2 includes `decided_ts` and `as_of_ts` as
  `:.9f`. Historical v1 unchanged. Persist same-id/different-payload is
  `CONFLICT`; same payload is a no-op.

## Independent valid-stale plants (not the suite)

`plant_valid_stale_*` via `put_extraction_receipts` /
`put_citation_receipts` / `build_decision` (self-consistent ids, correct
seal, wrong policy/config).

Only-candidate (`_single_rep_source`, no F9 selection):

```
stale        = sha256:831ba6a89f4fcd08…
linked       = {sha256:f3b3338565b8fbb7…}   # minted legacy
stale_linked = false
minted_count = 1
minted_legacy = true
minted_seal  = true
one_linked   = true
```

Live C-024 + valid stale run/cite/review:

```
live_run_linked     = true
stale_run_linked    = false
run_count           = 2
no_third_run        = true
live_cite_linked    = true
stale_cite_linked   = false
live_review_linked  = true
stale_review_linked = false
```

Time:

```
now=10 vs now=99     ids differ
decided 10 vs 99, same as_of    ids differ
as_of 10 vs 99, same decided    ids differ
```

Legacy no-selection path (same `_single_rep_source` + valid stale run):
`stale_linked=false`, `linked_n=1`.

## GREEN (once each)

```
owner+integration 104:
104 dots. EXIT:0

affected 126 + identity + H1-existing:
137 dots. EXIT:0
(claim said 132 = 126+identity only; adding the five H1-existing
tests is 137, all green)

basedpyright <all changed Python>
0 errors, 0 warnings, 0 notes. EXIT:0
```

No full suite. No retry-to-pass.

## Isolated mutants (apply_patch reverse)

| # | Mutant | Killing observation | Restored |
| --- | --- | --- | --- |
| skip selection cross-link | live ≠ minted third | `62be4af9…` |
| unique same-rep+seal fallback | only-stale run linked | `62be4af9…` |
| cite offsets `ORDER BY created_ts DESC` | live cite ⊈ stale | `93463731…` |
| review skip `_review_matches` | live review ≠ minted | `6d71e56d…` |
| skip `existing_review` | live review ⊈ minted (both H1 tests) | `763eff83…` |
| omit `decided_ts` from v2 | 10.0 == 99.0 (same as_of); as_of test still GREEN | `42426bcf…` |
| omit `as_of_ts` from v2 | 10.0 == 99.0 (same decided); decided test still GREEN | `42426bcf…` |

## Manual QA

Probe + QA drivers under `/private/tmp/ontologylab-wave21-task7-r2-*`
(deleted). Public library, installed `.venv/bin/ontologylab`, **real**
`uvicorn.Server` on `127.0.0.1:64678` (startup Event, not TestClient,
not 8799). No network. No Application Support.

- clean+stale library H1: live run/review linked, stale absent, run
  count 2, pass2 hash equal, source tree unchanged, decision id matches
  stored
- interrupt 2 durable rows; resume pending 0 complete true
- overlap `source_overlap`
- tamper ready bytes → `GroundingPreflightError`
- CLI approve exit 0, printed stored `sha256:`; `migrate-h1` pending 0
  complete true
- HTTP POST `/api/proposals/approve` status 200,
  `decision_receipt_ids=['sha256:7c8bd4c70cf3…']` == stored; thread
  joined; port 64678 listen gone
- PID 55560 inode unchanged

## Adversarial classes

| Class | Observable |
| --- | --- |
| stale_state | valid stale not linked; pass2 identical; resume pending 0 |
| malformed_input | overlap `source_overlap`; tamper typed preflight |
| dirty_worktree | denylist + unrelated dirt unread; freeze hashes held |
| misleading_success_output | CLI/HTTP emit stored `sha256:` ids |
| flaky_tests | no sleeps; uvicorn startup Event before bind use |
| cancel_resume | H1 failpoint after 2, resume complete |

## Scope stop

Did not commit. Did not run the full suite. Did not implement Task 8.
Product/test bytes left at the freeze hashes above. PID 55560 / 8799
untouched.
