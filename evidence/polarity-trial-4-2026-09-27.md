# Fourth polarity trial - 2026-09-27

## Outcome: FAILED (primary G3); IS-1 NOT MET

Exactly three preregistered runs were executed. The **qualified-statement primary
scorer** matches **11/102** gold statements: accuracy **11/11**, negative/null
recall **0/51**, and undefined flip rate (**0/0**). G1, G2, and G4 pass; G3 fails.
Legacy comparison also fails G3: accuracy **35/46 = 76.09%**, negative/null recall
**9/51 = 17.65%**, flip **5/10 = 50%**. Legacy cannot establish VERIFIED.

All **63/63 chunks were attempted**, **60/63 succeeded**. Each run had one provider
error and ended with product status failed, after processing the remaining
chunks. No replacement, resume, alternate provider, or extra extraction run.
Chunks returned, so this is FAILED, not BLOCKED. G1 still passes its unchanged
95% point-estimate threshold.

- [ ] F4 follow-up: close qualified scope/endpoint omissions and negative/null
  recall; investigate the three provider disconnections before a separately
  authorized future trial. No product edits are authorized by this evidence.

## Frozen execution and accounting

Work root: /Users/hyunjun/Documents/MUNI/ontologylab-wt/w8-t29; branch completion/w8-t29.
Code commit: ca93d16c58791b4125fa9f44c4aeb2071eac35f5.
[Preregistration](polarity-trial-4-2026-09-27-prereg.md) and copied harnesses were
committed as **083160156d331a0a23106f40f825782ca24c539f** at **06:43:49 UTC**,
before the single preflight and all extraction starts at **06:44:14 UTC**.
Only evidence changed afterward; product, gold, scorer implementation,
preregistration, and frozen harnesses stayed unchanged.

Engine/model/prompt: **api:gemini / gemini-3.6-flash / extract-v7**.
Schema agrochem-v2, temperature 0.0, seed 7, cap **60 requests/run**.
The key was exported from GOOGLE_API_KEY only inside the launch shell to
ONTOLOGYLAB_PROVIDER_GEMINI_1BDF3AFBB89F. No keychain was used.
One preflight returned pong, exit 0, in 1,979 provider ms (2.481 outer seconds).

Each owned server installed the schema and collected the unchanged five full
bodies through HTTP. All 15 API documents were fulltext/extractable; all 15
observations were fulltext. Saved raw-text hashes match the frozen corpus.
No SQL eligibility changes or human approvals. Each driver subscribed to SSE
before its one extraction POST and checked status with bounded GETs on events.
The foreground Python driver owned and awaited all three concurrent runs and
servers. The host monitor delivered exit 0: driver completion, not successful
product extraction. No shell backgrounding or detached server was used.

The payload omitted time_budget. Automatic product budgets were
13,860.001336 / 13,860.001310 / 13,860.001200 seconds: 21 chunks, 42 request slots,
300-second request timeout, 10% reserve. The unchanged driver observer bound was
14,220 seconds. The host monitor bound was 3,600 seconds; it completed before
that bound. Neither observer fired. No trial-2 600-second override was reused.

| Run | Port / owned PID | Product state | Job seconds | Status / provenance requests | Successful / attempted / expected | Rejected entities / relations |
| --- | --- | --- | ---: | --- | --- | --- |
| R1 | 53325 / 27572 | failed | 2956.988 | 21 / 21 | 20 / 21 / 21 | 0 / 0 |
| R2 | 53327 / 27600 | failed | 2960.069 | 21 / 21 | 20 / 21 / 21 | 0 / 0 |
| R3 | 53326 / 27599 | failed | 2971.455 | 21 / 21 | 20 / 21 / 21 | 0 / 0 |

Total: **63 extraction requests plus one preflight**. status.json and provenance
agree in every run. Terminal HTTP job objects have **no engine_calls field**;
that absence is recorded, not invented or counted as zero. Each log has one
extraction POST; each provenance has one extract.start. Parse rejections/retries=0;
rejected proposals=0; never-planned chunks=0; approved edges=0. Warning counts
are 326/361/288; zero rejected proposals does not mean zero warnings.

All three errors are **provider 'gemini': request failed (RemoteDisconnected)**
on **PMC12563837, zero-based chunk 2**, character range **[22808,34210)**.
These are engine errors, not parser failures. Gold 14-20 have their source spans
wholly in that chunk: seven cases/run, including four nulls. This overlap is not
a causal estimate of recoverable findings. Errors occurred together at about
07:26:40 UTC; no cause beyond the recorded disconnection was established.
Wall-clock job durations are reported as observed, not replaced by summed
provider durations.

## Gates and 95% confidence intervals

Unchanged thresholds: G1 >=95%; G2 >=90%; G3 accuracy >=80%, combined negative/null
recall >=70%, AND flip <=15%; G4 zero observed supports/no_effect collapses.
Every run and pooled result is **G1 PASS / G2 PASS / G3 FAIL / G4 PASS** under
both scorers. CIs: unchanged 2,000 case-bootstrap resamples, seed 7, 95% percentile
method; pool concatenated outcomes, not averaged rates. Decisions use point
estimates; undefined values remain null. G4 has no rate CI.

### PRIMARY: qualified statements / gold-qualified.json

| Metric | R1 | R2 | R3 | Pooled |
| --- | --- | --- | --- | --- |
| G1 successful chunks | 20/21; 95.24% [85.71, 100.00] | 20/21; 95.24% [85.71, 100.00] | 20/21; 95.24% [85.71, 100.00] | 60/63; 95.24% [88.89, 100.00] |
| G2 polarity set | 120/121; 99.17% [97.52, 100.00] | 136/136; 100.00% [100.00, 100.00] | 121/121; 100.00% [100.00, 100.00] | 377/378; 99.74% [99.21, 100.00] |
| polarity_accuracy | 3/3; 100.00% [100.00, 100.00] | 4/4; 100.00% [100.00, 100.00] | 4/4; 100.00% [100.00, 100.00] | 11/11; 100.00% [100.00, 100.00] |
| recall_no_effect | 0/12; 0.00% [0.00, 0.00] | 0/12; 0.00% [0.00, 0.00] | 0/12; 0.00% [0.00, 0.00] | 0/36; 0.00% [0.00, 0.00] |
| recall_refutes | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/15; 0.00% [0.00, 0.00] |
| recall_no_effect_refutes | 0/17; 0.00% [0.00, 0.00] | 0/17; 0.00% [0.00, 0.00] | 0/17; 0.00% [0.00, 0.00] | 0/51; 0.00% [0.00, 0.00] |
| supports_when_gold_no_effect_flip_rate | 0/0; undefined (CI null) | 0/0; undefined (CI null) | 0/0; undefined (CI null) | 0/0; undefined (CI null) |

The 11 matched statements are all supports. Matched accuracy of 100% does not
establish polarity readiness: no qualified negative/null statement matches,
and flip is undefined rather than a passing zero. Matched gold per run:
**3/34, 4/34, 4/34**.

### SECONDARY: legacy triples / gold-fulltext.json

| Metric | R1 | R2 | R3 | Pooled |
| --- | --- | --- | --- | --- |
| G1 successful chunks | 20/21; 95.24% [85.71, 100.00] | 20/21; 95.24% [85.71, 100.00] | 20/21; 95.24% [85.71, 100.00] | 60/63; 95.24% [88.89, 100.00] |
| G2 polarity set | 120/121; 99.17% [97.52, 100.00] | 136/136; 100.00% [100.00, 100.00] | 121/121; 100.00% [100.00, 100.00] | 377/378; 99.74% [99.21, 100.00] |
| polarity_accuracy | 10/14; 71.43% [50.00, 92.86] | 12/15; 80.00% [60.00, 100.00] | 13/17; 76.47% [58.82, 94.12] | 35/46; 76.09% [63.04, 89.13] |
| recall_no_effect | 2/12; 16.67% [0.00, 41.67] | 3/12; 25.00% [0.00, 50.00] | 4/12; 33.33% [8.33, 58.33] | 9/36; 25.00% [11.11, 38.89] |
| recall_refutes | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/15; 0.00% [0.00, 0.00] |
| recall_no_effect_refutes | 2/17; 11.76% [0.00, 29.41] | 3/17; 17.65% [0.00, 41.18] | 4/17; 23.53% [5.88, 47.06] | 9/51; 17.65% [7.84, 27.45] |
| supports_when_gold_no_effect_flip_rate | 2/3; 66.67% [0.00, 100.00] | 2/3; 66.67% [0.00, 100.00] | 1/4; 25.00% [0.00, 75.00] | 5/10; 50.00% [20.00, 80.00] |

Legacy matched gold: **13/34, 13/34, 16/34**, pooled **42/102**. Conflicting labels
all count, producing 46 predictions, not 42. There are **11 wrong matched
predictions** (4/3/4), separate from the 60 missing triples.

### G4 and persisted rows

| Run | Observed collapses | Coexisting supports/no_effect pairs | All edge merges |
| --- | ---: | ---: | ---: |
| R1 | 0 | 8 | 18 |
| R2 | 0 | 9 | 27 |
| R3 | 0 | 13 | 16 |
| Pooled | 0 | 30 | 61 |

All pairs have distinct IDs and appear in find_contradictions(include_proposed=True).
The numerical receipt lists every pair. This retains trial 3's persisted-row
and insertion-contract scope, not raw-response replay. The existing API groups
by core triple: pairs may have different qualifiers, not identical scientific
contexts. General merges are not cross-polarity collapses.

## Miss breakdown

Every miss was assigned once. [The JSON receipt](polarity-trial-4-2026-09-27.json)
retains candidate IDs, qualifier mismatches, spans, initial mechanical categories,
and reviewed decisions. Categories do not change any scorer match.

| Scorer / category | R1 | R2 | R3 | Total |
| --- | ---: | ---: | ---: | ---: |
| primary / scope | 21 | 20 | 22 | 63 |
| primary / relation | 2 | 2 | 2 | 6 |
| primary / surface | 2 | 1 | 3 | 6 |
| primary / absent | 6 | 7 | 3 | 16 |
| legacy / scope | 11 | 11 | 10 | 32 |
| legacy / relation | 2 | 2 | 2 | 6 |
| legacy / surface | 2 | 1 | 3 | 6 |
| legacy / absent | 6 | 7 | 3 | 16 |
| Primary all missing | 31 | 30 | 30 | 91 |
| Legacy all missing | 21 | 21 | 18 | 60 |

Scope: exact primary core with unmet qualifier slots, or legacy qualified-name
to core-node migration. Relation: exact endpoints with different relation or
direction. Surface: related strain-only labels, different disease, or broader
crop endpoint, **not proven equivalence**. Absent: no comparable persisted
assertion for that treatment/combination after same-paper review; unrelated
one-endpoint neighbors cannot establish presence.

- R2 gold 4 has correct no_effect / Crop trial 1 row
  c83b3cc9389746aa9270bac6ab11e8d5, but lacks object_aspect_qualifier=bubble
  development. Its background supports row remains separate.
- R2 gold 7 has correct endpoints, polarity, Bioassay 2, and oviposition, but
  dose is **dilute doses**, not frozen **dilute**. No semantic remapping was added.
- R2 gold 14 has no_effect with **putative resistant (R) population**, not
  **R population**, and no dose. R1 preserves R population but lacks dose.
  Separate S-population supports rows are not substitutes.
- Gold 21-28 mix missing study/population/dose slots with spelling differences
  such as postemergence versus post-emergence. Different treatment arms are
  not interchangeable. Gold 32-34 omit or shorten sampled-population scope.
- Gold 29/30 have reversed controls candidates, not resistant_to assertions.
- QST 713/Kos strain-only nodes remain in R1/R3. R2's QST candidate targets
  **wet**, not dry, bubble disease. No disease identity was merged.
- Absent cases: all runs' gold 15-17; R1/R2 gold 12 and 31; R1 gold 13;
  R2 gold 6 and 11. Ingredient/mode-of-action rows do not replace comparisons.

Primary has no wrong exact matches because only supports statements match.
Legacy wrong matches: R1 gold 4/11/21/23; R2 gold 4/21/23; R3 gold 4/11/23/31.
Identity recovery alone would not resolve these label disagreements.

## Comparison with trials 1-3

| Trial / scorer | Matched gold | Accuracy | Negative/null recall | Flip | Coverage | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| 1 original | 0/102 | undefined | 0/51 | undefined | 15/15 excerpt chunks | FAILED G3 |
| 1 corrected scorer | 7/102 | 6/7 (85.71%) | 3/51 (5.88%) | 0/1 | same retained excerpt runs | FAILED G3 |
| 2 legacy | 14/102 | 14/14 (100%) | 2/51 (3.92%) | 0/1 | 31/63 full-body chunks | FAILED G1/G3 |
| 3 legacy | 29/102 | 22/30 (73.33%) | 5/51 (9.80%) | 4/12 (33.33%) | 63/63 full-body chunks | FAILED G3 |
| 4 legacy | 42/102 | 35/46 (76.09%) | 9/51 (17.65%) | 5/10 (50%) | 60/63 successful; 63/63 attempted | FAILED G3 |
| 4 qualified PRIMARY | 11/102 | 11/11 (100%) | 0/51 (0%) | undefined (0/0) | same three trial-4 runs | FAILED G3 |

Sources: [trial 1](polarity-trial-2026-09-26.md), [corrected trial 1](polarity-trial-2026-09-26-misses.md),
[trial 2](polarity-trial-2-2026-09-26.md), [trial 3](polarity-trial-3-2026-09-27.md).
Trial 1 used excerpts/extract-v3; trial 2 full bodies/extract-v4; trial 3
full bodies/extract-v5; trial 4 extract-v7 with qualified extraction.
Todo 25's offline projection was 22/102 matches and 6/51 negative/null recall,
still 31/63 coverage: not new model observations.

Legacy recall/matches improve over trial 3, but flip worsens and gates still
fail. Primary and legacy are different identities, not alternative thresholds.
No qualified rescore of earlier trials is claimed. These are end-to-end
regression observations, not isolated causal effects of todo 27 versus 28.

## Durable export, verification, and limits

[Complete export](polarity-trial-4-2026-09-27-edges.json), SHA-256:
b47e296c5629261741f7364bd30bb9028dc08b941d2e9ab3c3f863e39390cc9b.
Written immediately after all three runs, before scoring. It retains ALL
persisted nodes (191/219/181), edges (199/216/178), aliases (120/127/90), citations
(542/588/480), original qualifiers/polarities/source_span fields, documents,
schema and extraction rows. Empty citation_receipts tables and original null
spans remain empty/null. Totals: **593 nodes, 593 edges, 1,610 citations**.

The saved export was read back. Both scorers were rerun on independently
reconstructed in-memory stores: every scorer field, including CIs and misses,
equals the original-store result. This replay does not open temporary stores:

    PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python evidence/polarity4_export.py rescore evidence/polarity-trial-4-2026-09-27-edges.json tests/gold/agrochem-polarity/gold-qualified.json tests/gold/agrochem-polarity/gold-fulltext.json

- Tests ran once: polarity_eval, polarity_identity, polarity_fulltext,
  statement_qualifier_scoring, statement_qualifier_identity, statement_qualifier_gold:
  **69 passed, exit 0, 4.31 seconds**. JUnit and log are retained beside this report;
  basetemp was fresh.
- All three read-only/immutable databases passed integrity and foreign-key checks.
  HTTP stage buckets exactly match SQLite: 199/216/178 current edges. Real schema,
  collect, extract, SSE, status, and stages HTTP surfaces were exercised.
- All five Python evidence helpers have zero LSP error diagnostics. JSON artifacts
  parse. JSON LSP was unavailable because biome is absent; no installation or
  product dependency change was made.
- Build/mutation: not applicable to evidence-only changes on frozen product/scorers.
  The diff from ca93d16 for ontologylab, tests, pyproject.toml, and uv.lock is empty;
  frozen input and driver hashes match preregistration.
- Owned servers were terminated after terminal state and awaited. Independent ps
  checks find PIDs 27572/27600/27599 absent; ports **53325/53327/53326** each return
  **61 (ECONNREFUSED)**. Port 8799, PIDs 87584/3284, launchd, and Application Support
  were untouched.
- Exact-key grep -a -F -c -f /dev/stdin -- FILE checks every exit and supplies the
  key through stdin, never a displayed argument. Initial scan: **336 files,
  0 matches**. Final delivered-artifact scan: **0 matches**, including this report,
  numerical receipt, export, helpers, temporary artifacts, and canonical receipt.

Nothing was deleted. Retained temporary roots:
- /private/tmp/ol-polarity4-20260927T064204Z-r1
- /private/tmp/ol-polarity4-20260927T064204Z-r2
- /private/tmp/ol-polarity4-20260927T064204Z-r3
- /private/tmp/ol-polarity4-20260927T064204Z-tests

Each run retains its database, uploads, registry names, logs, status, provenance,
and HTTP receipt; this worktree retains its isolated .venv. Rescoring no longer
requires /private/tmp to survive a reboot.

This is a same-corpus regression on five previously studied, null/negative-enriched
papers, not an independent holdout. Prior misses informed fixes; verifier/designer
overlap and lack of independent expert adjudication remain. An independently
adjudicated new holdout would address that limitation but is outside this trial.
Case-bootstrap CIs ignore within-paper and between-repeat dependence.
