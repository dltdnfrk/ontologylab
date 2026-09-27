# Ultrawork Notepad - close task 37 B1
Started: 2026-09-27

## Plan
1. Verify physical cwd, Git root, origin, branch, HEAD and clean state; read B1 only.
2. Read annotation protocol, vocabulary, checker and related tests.
3. Obtain two fresh independent assertion-led reviews for the fifteen named rows.
4. Submit disagreements to a third fresh adjudicator without gold.
5. Bind all 34 reference rows to reviewed dispositions, exact source spans and rationale.
6. Compare completed blind reviews with gold; change only adjudicated siblings when justified.
7. Keep new reference-row agreement distinct from original free-enumeration agreement.
8. Replace preservation-as-review policy with a coverage invariant and regression test.
9. Check Python diagnostics and source/data consistency through the offline audit CLI.
10. Run the three requested pytest modules in the foreground, capturing the actual exit.
11. Mark one reference disposition not_reviewed, prove the new test fails, restore and verify.
12. Commit the scoped fix, verify clean state, update the canonical completion receipt, return JSON.

## Success criteria + QA scenarios
- All 34 rows have two independent reviews or a review plus adjudication, with a one-line span rationale. Run `uv run --all-extras python tests/gold/agrochem-polarity/annotation_audit.py --check`; PASS means exit 0 with 34 reviewed rows.
- Run `uv run --all-extras pytest --basetemp=/private/tmp/t37-fix-$RANDOM-$RANDOM tests/test_annotation_audit.py tests/test_statement_qualifier_gold.py tests/test_polarity_fulltext.py > /private/tmp/t37-fix.log 2>&1; echo EXIT=$?`; PASS means actual pytest exit 0.
- Mutate one disposition to not_reviewed, invoke the new coverage test, require exit 1, restore and require exit 0.
- Earlier gold, original free-enumeration submissions/receipts and silver bytes stay unchanged; Git diff and frozen-input hashes establish this.
- Commit `test(gold): review every aligned reference row`; `git status --porcelain` must be empty.

## Now
Prepare the two blinded assertion-only annotation lanes.

## Todo
Independent labels; adjudication; dispositions; separate stats; coverage test; diagnostics; pytest; mutant; commit; completion receipt.

## Findings
- Understood as: close B1 only, not redo extraction, silver, prior trials or the whole audit.
- Verified physical cwd and Git root `/Users/hyunjun/Documents/MUNI/ontologylab-wt/w11-t37`, origin `https://github.com/dltdnfrk/ontologylab.git`, branch `completion/w11-t37`, HEAD `0b783485d73ab6b534df4e5a4e809ab13ba0f804`, initially clean.
- `gold-change-record.json` ends with a preservation-only not_reviewed policy. The existing test only checks changed rows; the CLI checks agreement, not reference-row coverage.
- HEAVY: independent annotation decisions establish an evaluation-data contract. No ulw-plan review gate applies; lead self-review will be recorded.
- Topology: two parallel deep-high annotators with disjoint outputs, then one fresh deep-high adjudicator; lead owns data integration, code and checks. No planning child is needed.
- Skills: readchk for exact scope; mandela for blinded inputs and separate denominators; autobahn for the supplied annotation-only scope guard; programming/Python for the regression test; git-master for the requested atomic commit; bun-1-4 for tool orchestration.
- Leakage control: agents see assertion quotes, source papers, protocol and vocabulary only. No gold labels, existing annotations, scorer/extractor outputs, memory notes or transcripts. Per-row review is a targeted audit, not free-enumeration recall.
- Methods/culture/treatment-schedule transcription and operational biological qualifiers remain excluded. Cite existing source spans instead of duplicating operational content.
- No build is required for this data/test-only change; the requested narrow test modules and offline audit are the real surfaces.

## Learnings
- The bash tool ignores an unsupported workdir argument; explicit `cd` is required. The initial read-only probe ran in the canonical root; no write occurred. The corrected probe established the authorized worktree before any write.
- The user forbids deletion; preserve durable QA logs and scratch receipts rather than deleting them. No server, browser or live-store resource is needed.

## Findings - coverage reproduction
- Both original annotations overlap the assertion spans for 19 rows. Rows 1, 2, 3, 4, 5, 6, 17, 20, 23, 29, 30, 31, 32, 33, 34 lack two overlapping reviews.
- These fifteen rows share nine distinct asserting sentences. They were supplied without labels to two fresh tasks, `reference-annotator-a` and `reference-annotator-b`, each restricted to the protocol, vocabulary and four containing stored full texts.
- The original changed-row test passes despite the gap: `uv run --all-extras pytest --basetemp=/private/tmp/t37-baseline-$RANDOM-$RANDOM tests/test_annotation_audit.py::test_gold_changes_are_only_explicit_adjudicated_source_scope` returned 1 passed in 0.08s.
- Original adjudication sometimes abstained on endpoint expansion while still identifying the sentence's polarity and scope. Coverage must link the actual arm labels, not mistake endpoint abstention for an absent review.
- Exact packet spans were independently located in the stored text and hashed. The new review record will reference those existing spans instead of duplicating excluded incidental operational content.
- Cleanup receipt: baseline pytest exited; no service, browser or port was spawned. Scratch remains under the user-required no-deletion policy.

## Now - independent review pending
Both annotators are running. The lead has mapped the nineteen previously covered rows to their original submissions and read all original adjudication decisions.

## Todo - after labels return
Adjudicate new disagreements; record per-reference dispositions; compare labels only after both submissions finish; update changed adjudicated labels and separate stats; implement and verify coverage guard; commit and receipt.

## Findings - guard and first submission
- Added `reference_coverage()` to the existing offline checker and a dedicated `test_every_aligned_reference_row_has_a_reviewed_disposition`. It requires ordered complete row coverage, reviewed status, literal character/byte spans, two distinct lanes, cited annotation arms and recorded adjudication when claimed.
- Added `reference_annotations()` to validate the targeted packet submissions and recompute their agreement independently of the original free-enumeration receipt.
- Python diagnostics are clean after correcting two TypedDict/inference errors. JSON LSP is unavailable because biome is not installed; JSON parsing and source-bound runtime checks will validate these data files without installing a dependency.
- Annotator A returned nine reviews, with statement counts 1, 1, 2, 3, 3, 4, 4, 3, 7. Its vocabulary and literal qualifier checks passed. Its complete submission is preserved in `reference-annotator-a.json`.
- Annotator B's first completion exposed only a handoff sentence, so the same lane was asked to return its already-completed JSON without new reads or relabeling. No labels from A were sent.

## Now - second artifact pending
Await the complete B artifact, then send the two completed labels and source quotes to a fresh adjudicator.

## Findings - both submissions complete
- B returned all nine reviews and 28 arms. Both submissions pass the literal-qualifier/vocabulary boundary and name exactly the six allowed inputs.
- A fresh third task, `reference-adjudicator` (`st_01a0e39d`), received the protocol, nine quotes and two complete label sets. Eleven already-covered sentence packets were subsequently added using only original submitted labels and asserting quotes; it still receives no gold.
- Post-submission comparison found that original row 12's PB arm occurs only in B, although both annotators covered its sentence. It will use the permitted one-review-plus-adjudication disposition rather than falsely citing A's cyantraniliprole arm.
- New targeted agreement is stored in `reference-agreement.json`: 28/28 submitted arms, 14 reciprocal scope matches, statement match rate 0.5, no polarity disagreement within those matches, conditional kappa 1.0. This is not merged with the original free-enumeration agreement and does not claim human validation.
- After both annotators finished, the lead compared historical scope: several reference qualifiers come from context rather than the asserting sentence. Only explicit adjudication will determine new sibling changes; original gold remains immutable.
- The coverage checker now supports either two independent records or one record plus a recorded adjudication, so the PB arm is not forced into a fictitious second review.

## Now - adjudication pending
Await all twenty sentence decisions; prepare exact source bindings and review links without applying labels prematurely.

## Findings - completed adjudication and conflicting writes
- All twenty decisions were returned in the adjudicator's consolidated final JSON, with the protocol as its only file read. R07/R09 also contain explicitly labeled collective projections; split-arm observations remain separate.
- The intended completed comparison changes no polarity labels. Relative to starting HEAD, 27 qualifier sets change and rows 4, 11, 14, 15, 26, 27, 28 are confirmed unchanged. The cumulative difference against gold-aligned-qualified is 30 qualifier sets.
- A real coverage-test run exposed a saved B artifact different from the actual returned B JSON. The unexpected file had SHA-256 `931aad74793d0365089499b45babd8e7354c667f5acc68f6f35f55bf5dfd4b90`; the actual returned submission renders to `5d22212d32c0ff9aff86f69eb0f44e50a2b6736308877a0f5548f416cbda0b8a`. It was corrected to the returned artifact, and exact byte equality was checked.
- Further checks found unrelated changes to the guard, nine decisions on disk instead of the returned twenty, and altered dispositions. This establishes a conflicting-writer problem, not a scientific-label disagreement. The current bytes are being preserved pending ownership clarification.
- The source-binding check also identified that E packets belong to reference-adjudication-inputs.json, not the nine-packet targeted-annotation registry. That lookup was corrected while preserving source verification.
- Python diagnostics passed, but the real CLI returned EXIT=1 because the on-disk competing nine-decision artifact lacks the E decisions. No passing final test receipt is claimed.
- `git diff --exit-code 0b783485d73ab6b534df4e5a4e809ab13ba0f804 --` the five protected historical gold files and the silver directory returned `IMMUTABLE_EXIT=0`.
- Asked the user to stop the competing writer before reconciliation. File-modification watches are armed for reference-adjudication.json and reference-review.json.

## Now - ownership clarification
Preserve the conflicting worktree bytes. Await the user's writer-stopped decision; then reconcile to the actual completed blinded submissions and run the final checks.

## Todo - remaining
Resolve competing edits; finish sibling/receipt integration; targeted pytest; not_reviewed mutant and restore; real audit and diagnostics; requested commit with clean tree; canonical completion receipt and DoneClaim.
