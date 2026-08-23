# Task 4 repair — isolated mutant coverage

Date: 2026-08-23
HEAD: `1afd0f85b038475a3b0a43f477febd1b25bfce01` (unchanged; no commit)
Trigger: `task-4-verifier-retry.md` `needs-fix` because isolated mutants 3, 5, 6, 7 stayed green.
Constraint: product bytes unchanged; tests only; no Task 5; no 8799 / PID 55560 mutation.

## Verdict

Coverage-only repair. Product SHA-256 matches the executor freeze. Four
decision-specific tests in `tests/test_citation_receipt_decisions.py` make
the isolated profile, plan, and selection mutants fail, and make
Representation-removed-from-seal fail. The verifier's exact `_existing`
column swap (`representation_id` → `representation_content_hash` with
run/chunk still in the key) remains a no-op on valid fixtures (distinct
Task 2 run/chunk IDs); that is not a production mis-bind.

## Product hashes (unchanged)

| File | SHA-256 |
| --- | --- |
| `citation_store.py` | `28986db331bd062f4f858d0cbc1f9bc9d09a5769ce1b4c3918af761e49b04c29` |
| `citation_verify.py` | `c30d0fdec2417b66c3bc208a02f0359ba9bfec715a785743968ef914ac6428db` |
| `citation_bind.py` | `e90287d1ee8549ca27ed4718a30de6d86395b53d5e2a7646d38b0c2932e55dc7` |
| `citation_ids.py` | `e4d897578170c8060ab29f4b7a85996f2c0d323b888107e710e23041ba7a9b62` |

New tests: `tests/test_citation_receipt_decisions.py`
`b3c0f1be8741898a92e1d6b947cafc359bf7c5fb5f9013aa9d211a1a27092f7b` (301 pure LOC).

## Mutant → test mapping

Recipes copied from `task-4-verifier-retry.md` isolated table.

| # | Isolated recipe | Test | Current code | Isolated mutant |
| --- | --- | --- | --- | --- |
| 3a | `_existing` `representation_id` → `representation_content_hash` (other key columns unchanged) | `test_citation_identity_keeps_representation_not_content_hash` persist half | GREEN: two same-hash Representations + same fact/span mint two receipts; cross-bind refuses | GREEN — run/chunk still distinguish the rows. No behavior change. |
| 3b | drop `binding.representation_id` from `citation_receipt_id` digest | same test, digest half | GREEN: IDs differ | RED `assert 'sha256:b88bae…' != 'sha256:b88bae…'` |
| 5 | drop `coordinate_profile` from chunk-field match only | `test_mismatched_chunk_profile_refuses_with_zero_rows` | GREEN `missing_receipt`, 0 rows | RED `DID NOT RAISE CitationRefused` |
| 6 | drop chunk `plan_receipt_id` from chunk-field match only | `test_mismatched_chunk_plan_refuses_with_zero_rows` | GREEN `missing_receipt`, 0 rows | RED `DID NOT RAISE CitationRefused` |
| 7 | do not call `_verify_selection` | `test_missing_or_foreign_selection_receipt_refuses_with_zero_rows` | GREEN missing=`missing_receipt`, foreign=`cross_bind`, 0 rows | RED `DID NOT RAISE CitationRefused` |

Profile/plan fixtures use a sibling `extraction_chunk_receipts` row so the
binding still passes `CoordinateProfile()` / run.plan equality. Only the
named chunk-field comparison is exercised. Selection fixture claims a
missing id and a real selection bound to another Representation.

Each mutant was applied alone, observed, then byte-restored (hashes above).

## Commands (once, no retry)

Current tests GREEN:

```
.venv/bin/python -m pytest tests/test_citation_receipt_decisions.py -q --tb=short
....
EXIT:0
```

Focused (now 52):

```
.venv/bin/python -m pytest tests/test_citation_receipts.py tests/test_citation_receipt_decisions.py tests/test_acceptance_criteria.py tests/test_extraction_receipts.py tests/test_preferred_selection.py tests/test_research_selection.py -q
....................................................
EXIT:0
```

Affected (137):

```
.venv/bin/python -m pytest tests/test_extractor.py tests/test_run_extraction.py tests/test_research_run.py tests/test_research_source_surface.py tests/test_research_ready_boundary.py tests/test_provenance.py tests/test_provenance_api.py tests/test_normalization.py tests/test_kgstore.py tests/test_pack_completeness.py -q
........................................................................ [ 52%]
.................................................................        [100%]
EXIT:0
```

Static:

```
/Users/hyunjun/.local/bin/basedpyright tests/test_citation_receipt_decisions.py
0 errors, 0 warnings, 0 notes
```

## Direct-library QA

`/private/tmp/ontologylab-wave21-task4-repair.qa.py` (removed) observed:

- identity digest distinct; same content hash
- two Representations: count 2, distinct receipt IDs
- cross-bind `cross_bind`, rows stay 2
- bad profile `missing_receipt`, rows 0
- bad plan `missing_receipt`, rows 0
- missing selection `missing_receipt`; foreign selection `cross_bind`; rows 0

QA root/driver deleted. No leftover process. PID 55560 / `127.0.0.1:8799`
inode `0x1ff51c806b197195` unchanged (`ELAPSED 17-10:15:44`).

## Residual

- Isolated `_existing` content-hash column swap cannot collide while run and
  chunk stay in the resume key. Grouped hash+span lookup was already killed
  by the original two-Representation test. Product not changed.
- No ReviewDecision / waiver (Task 5).
- No commit/push.
