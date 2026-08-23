# Repair 2 — wave21 steps 5–10 / task-7

Executor: omo senpi-task `st_01a02fa3` (second repair after `task-7-repair-verifier.md`)
Date: 2026-08-23
HEAD: `8f0e45fdfa1d70e39a91c03737ecb31cb1add3fb` (unchanged; no commit)
Constraint: no Application Support, network, port 8799, or PID 55560.
Denylist unread/unedited/unimported. Mutants via apply_patch reverse only.

## Verdict

Valid self-consistent stale identities no longer link. Run reuse is
selection-cross-link or exact `legacy-h1-v1` expected id only — the unique
same-Representation+seal fallback is gone. Citation reuse requires the
full Task 4 tuple (run/chunk/profile/plan/selection/policy). Review reuse
requires the full Task 5 payload including selection/policy/run/
predecessor/waiver/pack. `grounded-review-v2` hashes `decided_ts` and
`as_of_ts`. Only-stale mints one legacy receipt; live+stale links live
with no third run.

## RED (current bytes before product)

```
test_decided_and_as_of_time_change_review_decision_id
assert 'sha256:0770a9db6c7414e6…' != 'sha256:0770a9db6c7414e6…'
```

`now=10` and `now=99` shared an id.

```
test_valid_stale_run_only_is_not_linked
assert stale_run not in {stale_run}
```

Only-candidate valid wrong-policy run linked.

```
test_live_run_wins_over_valid_stale_without_third_id
assert {minted} == {live}
```

Two valid same-seal runs → mint a third legacy id.

```
test_valid_stale_citation_is_not_linked
live_cite ⊈ linked
```

Offsets+hash unique-match did not require run/policy.

```
test_valid_stale_review_is_not_linked
assert set() == {live_review}
```

Cite-set included the valid stale citation; live review did not match.

## GREEN

```
.venv/bin/python -m pytest \
  tests/test_extraction_receipts.py tests/test_preferred_selection.py \
  tests/test_research_selection.py tests/test_citation_receipts.py \
  tests/test_grounded_review.py tests/test_grounded_review_identity.py \
  tests/test_h1_migration.py tests/test_step7_integration.py \
  tests/test_step7_integration_h1.py tests/test_step7_h1_existing.py \
  -q --tb=line
OWNER:0
104 dots
```

```
affected 126 + identity:
AFFECTED:0
132 dots
```

```
basedpyright <changed Python>
0 errors, 0 warnings, 0 notes
```

No full suite. No retry-to-pass.

## Contract

- Run: if a preferred-selection receipt selects this Representation,
  link the unique self-consistent run with that policy hash + document
  seal. Else link only the deterministic `legacy-h1-v1` expected id
  when every classified field matches. Never unique-seal fallback.
- Citation: derive expected run from that same current link, expected
  chunk covering the span, selection/policy from the selection receipt
  (else legacy). Reuse only that exact Task 4 tuple after Task 4 verify.
- Review: cite set is only those exact citations; require selection,
  policy, run, no predecessor, pack-eligible, empty waiver; v1-or-v2
  id of the stored payload (v2 now includes times).
- `review_decision_id` v2 includes `decided_ts` and `as_of_ts` as
  `:.9f`. Historical v1 unchanged.

## Mutations (apply_patch, exact reverse, no git checkout)

Pre/post product SHA-256 matched the freeze after reverse.

| # | Mutant | Killing observation | Restored |
| --- | --- | --- | --- |
| 1/7 | unique same-rep+seal fallback | only-stale run linked | `62be4af9e061…` |
| 2 | skip selection cross-link | live ≠ minted third | `62be4af9e061…` |
| 3 | citation offsets+hash `ORDER BY created_ts DESC` | live cite ⊈ stale id | `934637311f74…` |
| 4 | skip `existing_review` | live review ≠ minted | `763eff83552c…` |
| 5 | omit `decided_ts` from v2 | 10.0 id == 99.0 id (same as_of) | `42426bcf4bf1…` |
| 6 | omit `as_of_ts` from v2 | 10.0 id == 99.0 id (same decided) | `42426bcf4bf1…` |

Prior forged-stale and persist-CONFLICT repairs preserved; owner suites green.

## Manual QA

Driver `/private/tmp/ontologylab-wave21-step7-repair2-qa.py` against
`/private/tmp/ontologylab-wave21-step7-repair2-qa` (deleted). Library +
installed CLI `migrate-h1` + TestClient HTTP approve (host `testserver`).

All true / 0:

- only-stale unlinked; legacy minted
- live run/cite/review exact; stale absent; run count 2 (no third)
- source tree unchanged; pass2 receipt hash equal; resume pending 0
- CLI pending 0 exit 0; `now=10` vs `99` ids differ
- HTTP 200 with `decision_receipt_ids`
- PID 55560 / `127.0.0.1:8799` listen line unchanged

Cleanup: QA root and driver removed.

## Owned SHA-256

| Path | SHA-256 | pure LOC |
| --- | --- | --- |
| `ontologylab/h1_existing.py` | `62be4af9e06140f539d3ead6b7ad2734078c4c442f665ca3631a2626e849deac` | 196 |
| `ontologylab/h1_existing_cite.py` | `934637311f7422faf31b92a7f4bc403a4bf2428a6ed4b5bcf701a50077500c6b` | 149 |
| `ontologylab/h1_existing_review.py` | `6d71e56d240ba3c0c3d9499de2cde24651bb78889ff154e2f5d81b5bc69bff8e` | 133 |
| `ontologylab/grounded_review_ids.py` | `42426bcf4bf1234aa01df2ac054aed205f7786180889352d108bd8204ecdf638` | 139 |
| `ontologylab/h1_finalize.py` | `019aec92d90b68e42fbe16e10df3d4d463fcf08995faf931ac0e689bdc46ea42` | 135 |
| `ontologylab/h1_materialize.py` | `beeda982c33bae2ab9937f598c8978d4302e66d9ed8457389a950c88df7b1171` | 189 |
| `ontologylab/h1_materialize_review.py` | `763eff83552cb0ccac81dbfa070d93a17ef90a51808a0cd97c97662129b37272` | 68 |
| `tests/test_grounded_review_identity.py` | `75058dcac6bff2f0ec58ea221a46c683fec2c83c1099b2f17fbac5793466fcaf` | 208 |
| `tests/test_step7_h1_existing.py` | `c742bdbf3776ef4cf1ed7ae18c22ec4728c3a90f5e02be7b8578089384fa114d` | 195 |
| `tests/step7_valid_stale.py` | `9c4db0e3a91a17f4099f469aa88768dd9dc4015976627af55a6407554e55ae13` | 119 |

## Post-write review

1. Run / citation / review lookup each own one family.
2. Expected tuples derived from classified unit + selection/current run link; Task 4 verify at the citation boundary.
3. Status match uses `match` + default `None` for open review status strings.
4. No `Any` / ignore / cast.
5. Unique-seal fallback deleted.
6. Planter helpers shared by tests and QA.
7. Tests fail if a valid wrong-policy row links or a third id is minted.
8. Public lookups ≤3 parameters.
9. No post-insert confirm selects.
10. Positive names (`selection_run_receipt`, `expected_cite_ids`).
11. No new logging.

## Scope stop

Did not commit. Did not run the full suite. Did not implement Task 8.
PID 55560 / 8799 / live data untouched.
