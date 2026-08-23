# AdversarialVerify — wave21 steps 5–10 / task-4 (repair re-verification)

Verifier: omo senpi-task `st_01a02f2a` (fresh independent pass after `task-4-repair.md`)
Date: 2026-08-24
HEAD: `1afd0f85b038475a3b0a43f477febd1b25bfce01` (unchanged; no commit/push)
Scope: Task 4 DoneClaim + four-decision coverage repair. Report only.
Constraint: no product/test/plan/Boulder/ledger/canonical-doc edits; no Application Support read/write; no external network; no 8799 / PID 55560 mutation; no Task 5+.

Prior executor (`task-4-executor.md`), recovery (`task-4-verifier-recovery.md`), retry (`task-4-verifier-retry.md`), and repair (`task-4-repair.md`) treated as claims. Every hash, mutant outcome, suite count, and QA value below was re-measured on current bytes.

## Verdict

`confirmed`

Confidence: `0.94`

Precondition freeze matches. Repair is test-only (`tests/test_citation_receipt_decisions.py`). The retry-verifier `_existing` column swap (`representation_id` → `representation_content_hash`, other key columns unchanged) is a **semantic no-op** on every valid fixture: Task 2 run+chunk receipt IDs already uniquely determine Representation, so the swapped column cannot collide. It is not a surviving mutant.

The meaningful content-hash authority decision is killed: replacing Representation ID with content hash in `citation_receipt_id` collapses the new same-hash two-Representation test. Isolated profile, plan, and selection mutants die with `DID NOT RAISE CitationRefused`. Missing vs foreign selection distinguish `MISSING_RECEIPT` vs `CROSS_BIND` in one store. Current code mints distinct receipts and refuses cross-bind. Product hashes restored byte-identically. Decisions 4 / focused 52 / affected 137 / basedpyright 0 once. Direct-library QA matches. PID 55560 / `127.0.0.1:8799` inode `0x1ff51c806b197195` unchanged.

## Precondition (independent freeze)

Independent SHA-256 vs executor/repair freeze (pre-mutation, post-restore, post-QA — identical):

| File | SHA-256 | vs freeze |
| --- | --- | --- |
| `citation_store.py` | `28986db331bd062f4f858d0cbc1f9bc9d09a5769ce1b4c3918af761e49b04c29` | MATCH (DoneClaim) |
| `citation_verify.py` | `c30d0fdec2417b66c3bc208a02f0359ba9bfec715a785743968ef914ac6428db` | MATCH (DoneClaim) |
| `citation_bind.py` | `e90287d1ee8549ca27ed4718a30de6d86395b53d5e2a7646d38b0c2932e55dc7` | MATCH (DoneClaim) |
| `citation.py` | `37a21316babc973ccd5a790e67ac507e54c81fc37554ff647ec67a305f905b8b` | MATCH |
| `citation_ids.py` | `e4d897578170c8060ab29f4b7a85996f2c0d323b888107e710e23041ba7a9b62` | MATCH |
| `citation_schema.py` | `54e64614bd055c2c8433c894ce60cdd9f24213ef4bc7a9732c4e5ed4a9a74c5a` | MATCH |
| `citation_types.py` | `ad0e6c44081b8efb2a577deb57f988a9934013abe3d84f4d1aa9993e08ce8f94` | MATCH |
| `extractor.py` | `f2ddc74799d1cd43de41d800d12d41c876959c198eca67bc882b3186e2be09a5` | MATCH |
| `extraction_state.py` | `3144da3be7c002db6ba79518a66fc907d322ee62580f1b6f7784f88229914b5c` | MATCH |
| `tests/test_citation_receipts.py` | `b626dc0cb63c4c90c52275134ca5c6baf2bb9db0f1341108c223b40491e586d2` | MATCH |
| `tests/test_citation_receipt_decisions.py` | `b3c0f1be8741898a92e1d6b947cafc359bf7c5fb5f9013aa9d211a1a27092f7b` | MATCH (repair; test-only) |

`git diff -- ontologylab/extractor.py ontologylab/extraction_state.py` is still only the Task 4 hooks: `ensure_citation_schema` import/call (+2) and `persist_chunk_citations` after `insert_proposed(..., commit=False)` (+16). No other hunks. No leftover `/private/tmp/ontologylab-wave21-task4*` before this pass. No pytest/mutate process.

## Decision 3 — query swap is a no-op; digest authority is the real kill

### Schema / key / runtime proof

`citation_receipts` UNIQUE key is

`(representation_id, run_receipt_id, chunk_receipt_id, fact_kind, fact_id, start_offset, end_offset)`.

Resume lookup `_existing` uses that same key. Content hash is a stored integrity column, not part of the identity key.

Task 2 identities already embed Representation:

- `run_receipt_id = digest("extraction-run-v1", representation_id, content_hash, policy, config, plan_id)`
- `chunk_receipt_id = digest("extraction-chunk-v1", run_id, …)`
- run table `UNIQUE (representation_id, policy_identity, config_identity)`
- chunk table `UNIQUE (run_receipt_id, chunk_index)`

Two Representations with identical bytes therefore **cannot** share `run_receipt_id` or `chunk_receipt_id`. QA observed `run_ids_distinct=true` and `chunk_ids_distinct=true` for `rep-a` / `rep-b` at the same content hash.

`put_once` calls `verify_binding` **before** `_existing`. `_verify_run_chunk` raises `CROSS_BIND` if `run.representation_id != binding.representation_id`. A forged pair (representation B + run/chunk of A) never reaches `_existing`.

Therefore on every valid path that reaches `_existing`:

- `(run_receipt_id, chunk_receipt_id)` already uniquely determine `representation_id`
- same-hash two-Representation fixtures still miss each other after swapping the first column to `representation_content_hash`
- same-identity retry still hits because that row’s content hash is the ready-byte hash already verified against the run

The isolated swap cannot change insert vs converge vs conflict on any valid fixture. Counting it as a surviving mutant would be a false fail.

The digest-half of `test_citation_identity_keeps_representation_not_content_hash` uses the **same** fake run/chunk IDs with `rep-a` vs `rep-b`. That is not a persist collision; it is the identity function. Persist uses `_put`, which mints distinct run/chunk IDs. Authority that would collapse same bytes under two Representations is `citation_receipt_id` including `binding.representation_id`, not the `_existing` first column.

### Isolated mutants (kill then byte-identical restore)

| # | Isolated change | Mutant SHA-256 | Exit | Behavioral failure | Restored |
| --- | --- | --- | --- | --- | --- |
| 3a | `_existing` `representation_id` → `representation_content_hash` (run/chunk/fact/span unchanged) | `35c66cefd3f7b6fd8577dda7af8dc0441246f8543999b84c9d09afc027bf8098` | **0** | **none** — proven no-op; not counted as surviving | yes, `28986db3…` |
| 3b | `citation_receipt_id` digest: `binding.representation_id` replaced by `binding.representation_content_hash` | `1f1769f14bd342eaaf2ece83d46880d14c186e754f45f7127b975f8be531e052` | 1 | `assert 'sha256:d2acf4ba…' != 'sha256:d2acf4ba…'` in `test_citation_identity_keeps_representation_not_content_hash` | yes, `e4d89757…` |
| 5 | drop `coordinate_profile` from chunk-field match only | `38dd55a5d879ae7b0af3a3054b1e050689135447461b315cc7a8b276deef84a7` | 1 | `DID NOT RAISE CitationRefused` in `test_mismatched_chunk_profile_refuses_with_zero_rows` | yes, `c30d0fde…` |
| 6 | drop chunk `plan_receipt_id` from chunk-field match only | `2ebc4d4c6e33676439a2b65524cd45d189719995af1da6b7a68f04c9238ee43e` | 1 | `DID NOT RAISE CitationRefused` in `test_mismatched_chunk_plan_refuses_with_zero_rows` | yes, `c30d0fde…` |
| 7 | do not call `_verify_selection` | `489e36782e7bdad3f34a0935069b3deca3d78787b22455fa22b2bf6401e29665` | 1 | `DID NOT RAISE CitationRefused` in `test_missing_or_foreign_selection_receipt_refuses_with_zero_rows` | yes, `c30d0fde…` |

Rows 5–7 restore `citation_verify.py` `c30d0fdec2417b66c3bc208a02f0359ba9bfec715a785743968ef914ac6428db`. Row 3b restores `citation_ids.py` `e4d897578170c8060ab29f4b7a85996f2c0d323b888107e710e23041ba7a9b62`.

3a mutant hash matches the retry-verifier isolated #3 (`35c66cef…`) and stayed green on the **new** four-test file (`....` EXIT:0). 5/6/7 mutant hashes match retry-verifier isolated #5/#6/#7; those now fail the intended assertion instead of staying green.

## Automated (each command once; no retry)

Decisions (expected 4):

```
.venv/bin/python -m pytest tests/test_citation_receipt_decisions.py -q --tb=short
....
EXIT:0
```

Focused Task 4 (expected 52):

```
.venv/bin/python -m pytest tests/test_citation_receipts.py tests/test_citation_receipt_decisions.py tests/test_acceptance_criteria.py tests/test_extraction_receipts.py tests/test_preferred_selection.py tests/test_research_selection.py -q --tb=short
....................................................
EXIT:0
```

52 passed. Starlette/`httpx` deprecation warning only.

Affected (expected 137):

```
.venv/bin/python -m pytest tests/test_extractor.py tests/test_run_extraction.py tests/test_research_run.py tests/test_research_source_surface.py tests/test_research_ready_boundary.py tests/test_provenance.py tests/test_provenance_api.py tests/test_normalization.py tests/test_kgstore.py tests/test_pack_completeness.py -q --tb=short
........................................................................ [ 52%]
.................................................................        [100%]
EXIT:0
```

137 passed.

Static (changed Task 4 Python once):

```
/Users/hyunjun/.local/bin/basedpyright \
  ontologylab/citation.py ontologylab/citation_types.py \
  ontologylab/citation_ids.py ontologylab/citation_schema.py \
  ontologylab/citation_store.py ontologylab/citation_verify.py \
  ontologylab/citation_bind.py ontologylab/extractor.py \
  ontologylab/extraction_state.py tests/test_citation_receipts.py \
  tests/test_citation_receipt_decisions.py
0 errors, 0 warnings, 0 notes
EXIT:0
```

No full suite. No retry-to-pass.

## Prior confirmed contracts (current tests/code)

| Contract | Evidence this pass |
| --- | --- |
| Overlap: one fact, distinct Citation receipts | `test_overlapping_chunks_yield_distinct_citation_receipts` in the 52 |
| Document offsets, not chunk-local | `test_citation_receipt_uses_document_offsets_not_chunk_local` in the 52; parse rebase remains `chunk.char_offset + span` in bind (untouched `e90287d1…`) |
| Unicode / `document-utf8-v1` | `verify_binding` slices `document_text[start:end]` (Python `str`); QA `café` at `[5,9)` hash `sha256:850f7dc43910ff890f8879c0ed26fe697c93a067ad93a7d50f466a7028a9bf4e` |
| Caller-owned transaction / SAVEPOINT | `test_put_citation_receipts_leaves_caller_transaction_uncommitted` in the 52; `citation.py` only `SAVEPOINT citation_receipts_v1` / `ROLLBACK TO` / `RELEASE`; no `COMMIT` / connection `ROLLBACK` / `executescript` in citation modules |
| No Task 5 | `ReviewDecision` / `approve_with_grounding_waiver` / `waiver` absent from `ontologylab/citation*.py` and both citation test files. Concurrent untracked `review_decision*.py` not read, not edited |

## Direct-library QA

Driver `/private/tmp/ontologylab-wave21-task4-repair-verify.qa.py` against `/private/tmp/ontologylab-wave21-task4-repair-verify.qa` (removed). No HTTP, no 8799, no sleeps.

Observed (verbatim typed results):

- identity: same content hash; digest distinct; receipts `sha256:38e9655cf63d15838f2bd1cc24d86a3c135e17cd8c73004aefb11770086c0be6` / `sha256:e8256131fdc2c00736f9106bb7b3291b6b022b4adc027d151b2014989a256e14`; reps `rep-a` / `rep-b`; run+chunk IDs distinct; rows 2; cross-bind `CitationRefused` / `CROSS_BIND` / `run receipt is bound to a different representation`; rows stay 2
- profile: `CitationRefused` / `MISSING_RECEIPT` / `chunk receipt fields do not match the citation binding`; rows 0
- plan: `CitationRefused` / `MISSING_RECEIPT` / `chunk receipt fields do not match the citation binding`; rows 0
- selection (one store): missing `CitationRefused` / `MISSING_RECEIPT` / unknown `sha256:00…`; rows 0; foreign `CitationRefused` / `CROSS_BIND` / `selection receipt is bound to a different representation`; foreign_rep `rep-a6c4f4dd57e5` ≠ home `rep-fcc6f228284f`; rows 0
- unicode (prior contract): `café` `[5,9)`, slice equals, hash `sha256:850f7dc4…`

PID 55560 before QA `17-10:18:21` / after tests `17-10:20:46`, same command, same listen inode `0x1ff51c806b197195`. No QA listener.

## Adversarial classes

| Class | Observable |
| --- | --- |
| stale_state | same-identity persist still creates then converges via Representation+run+chunk key; conflicting digest is `conflict` (existing 52); QA cross-bind keeps 2 rows |
| malformed_input | profile/plan/missing/foreign selection → typed `CitationRefused`; row counts 0 |
| dirty_worktree | Task 4 product hashes frozen; repair added only `tests/test_citation_receipt_decisions.py`; unrelated docs/`.sisyphus`/`graphify-out`/`review_decision*` left untouched |
| misleading_success_output | 3a stays green because it is a no-op, not because coverage is missing; 3b/5/6/7 fail the named assertion |
| flaky_tests | no sleeps; receipt IDs are SHA-256; suites passed on first run |
| repeated_interruptions | no leftover mutate/QA process; hashes match freeze after every restore |

## Cleanup

Removed verifier-owned `/private/tmp/ontologylab-wave21-task4-repair-verify.qa/`, `.qa.py`, and session `.debug-journal.md`. Product/test hashes MATCH freeze. HEAD unchanged. No commit/push. No leftover pytest/QA process.

## Risks / out of scope

- Isolated `_existing` content-hash column swap remains a no-op while run+chunk stay in the resume key. That is accepted, not ignored.
- Task 5 ReviewDecision / waiver / cascade is not part of Task 4. Concurrent untracked `review_*` files exist; they were not verified.
- Historical citation-receipt migration (Task 6 / H1) is not implemented. `KGStore.citations()` remains the legacy `{source_doc_id, source_span}` projection.
- No full suite this pass (per scope).

`confirmed`: meaningful content-hash authority mutant dies; isolated profile/plan/selection mutants die; exact query swap proven no-op rather than ignored; regressions/static/QA/cleanup pass; product bytes restored.
