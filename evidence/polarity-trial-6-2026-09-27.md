# Sixth polarity trial - 2026-09-27

## Outcome: FAILED (primary G3); IS-1 NOT MET

Exactly three preregistered runs completed **63/63 chunks**. PRIMARY qualified
aligned-gold accuracy is **24/24 = 100%**, negative/null recall **10/51 = 19.61%**,
and flip **0/10 = 0%**. G1, G2 and G4 pass; G3 fails the unchanged 70% recall
threshold. Every run fails G3 under every scorer. Completed extraction and
accurate labels on a small matched subset do not establish polarity readiness.

SECONDARY aligned legacy: accuracy **43/52 = 82.69%**, negative/null recall
**16/51 = 31.37%**, flip **9/19 = 47.37%**. It fails recall and flip; R3 also
fails accuracy. Secondary scores cannot establish VERIFIED. Chunks returned
and gates ran: FAILED, not BLOCKED.

- [ ] F4 follow-up: close qualified negative/null recall and missing assertion
  scope, investigate completion's rejected source spans, and retain successful
  proposal pass attribution for a future authorized measurement. IS-1 remains
  NOT MET. This receipt does not authorize product edits or another model run.

## Frozen execution and effective defaults

Work root: /Users/hyunjun/Documents/MUNI/ontologylab-wt/w10-t35; branch completion/w10-t35.
Base: 7fa01945c9fdd9ef68d5134c21733ec205441d2a, incorporating todos 33 and 34.
[Preregistration](polarity-trial-6-2026-09-27-prereg.md) and five copied helpers
were committed as **ac931c6ead337b069f986dfe97d5ef2de9e2d10e** at **12:58:51 UTC**, before the single
provider test and extraction starts at **12:59:14 UTC**. Helpers differ from
trial 5 only in paths and the scorer's qualified-target names. The exporter's
literal envelope trial=4 was corrected to 6; graph rows were not changed.
All 18 frozen hashes match; no product, scorer, gold, dependency/configuration,
preregistration or copied helper changed after preregistration.

Engine/model/prompt: **api:gemini / gemini-3.6-flash / extract-v9**.
Schema agrochem-v2; temperature 0.0; seed 7. Cap: **60 requests/run**, counting
all passes and retries. Payload omits time_budget, max_transport_retries and
statement_completion. Provenance confirms automatic budgets
**20280.000590 / 20280.000633 / 20280.000641 seconds**, retry limit **2** and
completion **true**. There are 21 chunks, 60 budgeted request slots, 300 seconds
per request, 10% reserve and eight seconds backoff reserve per slot.

First-pass parse retry limit is one; transient transport retry limit is two.
Completion gets at most one optional request per eligible chunk and no retries;
it reserves four first-pass slots for each remaining chunk. Enabled does not
mean every chunk receives completion. No retry, provider error, completion
response exception or timeout occurred. The 14220-second driver observation
bound and 3600-second host bound were not reached.

The key was exported from GOOGLE_API_KEY only inside the launch shell to the
dedicated provider variable. No key value was printed or stored in evidence.
One separate provider test returned pong, exit 0, 1753 provider ms
(1.980521 outer seconds). Each run installed schema and collected five full
bodies through HTTP. All 15 documents/observations were fulltext and extractable;
every retained body hash matches the corpus. No eligibility edits or approvals.

The foreground Python driver owned and awaited all three concurrent runs and
servers, with SSE subscribed before POST and bounded status GETs on events.
The host monitor delivered **exit 0**. Each run has exactly one extraction POST
and one extract.start event. Identical job IDs are scoped by separate stores.
No replacement, resume, alternate provider or additional extraction run occurred.

| Run | Port / owned PID | State | Job seconds | First / completion / retries | Status / provenance requests | Successful / attempted / expected | Rejected entities / relations |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| R1 | 58076 / 17775 | complete | 1280.745 | 21 / 12 / 0 | 33 / 33 | 21 / 21 / 21 | 0 / 39 |
| R2 | 58078 / 17786 | complete | 1325.646 | 21 / 13 / 0 | 34 / 34 | 21 / 21 / 21 | 0 / 23 |
| R3 | 58077 / 17785 | complete | 1337.069 | 21 / 13 / 0 | 34 / 34 | 21 / 21 / 21 | 2 / 36 |

**101 extraction requests plus one preflight = 102 provider requests**.
Status.json equals provenance in every run. Terminal HTTP jobs have no
engine_calls field; that absence is null, not zero. Per-paper chunk counts
in filename order are **4/4/4/5/4** in each run; all succeeded, none unplanned.
HTTP stage buckets equal SQLite (212/226/215 rows). No edge is verified.
Warnings are 393/400/398, distinct from retries and rejected proposals.

## Gates and 95% confidence intervals

Thresholds: G1 >=95%; G2 >=90%; G3 accuracy >=80%, negative/null recall >=70%
and flip <=15%; G4 zero observed supports/no_effect collapses. Every run and
pooled result under all four targets: **G1 PASS / G2 PASS / G3 FAIL / G4 PASS**.
Intervals use unchanged _rate: 2000 case-bootstrap resamples, seed 7, 95%
percentiles. Pool binary outcomes, not mean rates or merged graphs. Decisions
use point estimates. Undefined values remain null. Aligned gold has no refutes
rows, so refutes recall is undefined rather than a successful zero.

### PRIMARY: qualified / gold-aligned-qualified.json

| Metric | R1 | R2 | R3 | Pooled |
| --- | --- | --- | --- | --- |
| G1 successful chunks | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 63/63; 100.00% [100.00, 100.00] |
| G2 claim polarity | 127/127; 100.00% [100.00, 100.00] | 154/154; 100.00% [100.00, 100.00] | 151/151; 100.00% [100.00, 100.00] | 432/432; 100.00% [100.00, 100.00] |
| polarity_accuracy | 5/5; 100.00% [100.00, 100.00] | 8/8; 100.00% [100.00, 100.00] | 11/11; 100.00% [100.00, 100.00] | 24/24; 100.00% [100.00, 100.00] |
| recall_no_effect | 1/17; 5.88% [0.00, 17.65] | 4/17; 23.53% [5.88, 41.18] | 5/17; 29.41% [11.76, 52.94] | 10/51; 19.61% [9.80, 31.37] |
| recall_refutes | 0/0; undefined [null] | 0/0; undefined [null] | 0/0; undefined [null] | 0/0; undefined [null] |
| recall_no_effect_refutes | 1/17; 5.88% [0.00, 17.65] | 4/17; 23.53% [5.88, 41.18] | 5/17; 29.41% [11.76, 52.94] | 10/51; 19.61% [9.80, 31.37] |
| supports_when_gold_no_effect_flip_rate | 0/1; 0.00% [0.00, 0.00] | 0/4; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/10; 0.00% [0.00, 0.00] |

Matched gold: **5/34, 8/34, 11/34**, pooled **24/102**. Missing: **29/26/23**.
No wrong matched primary labels; all ten correctly recovered negative/null
statements are no_effect. Claim rows total 432: 351 supports, 81 no_effect,
zero refutes. Polarity presence does not establish gold coverage.

### SECONDARY: legacy / gold-aligned.json

| Metric | R1 | R2 | R3 | Pooled |
| --- | --- | --- | --- | --- |
| G1 successful chunks | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 63/63; 100.00% [100.00, 100.00] |
| G2 claim polarity | 127/127; 100.00% [100.00, 100.00] | 154/154; 100.00% [100.00, 100.00] | 151/151; 100.00% [100.00, 100.00] | 432/432; 100.00% [100.00, 100.00] |
| polarity_accuracy | 14/16; 87.50% [68.75, 100.00] | 15/17; 88.24% [70.59, 100.00] | 14/19; 73.68% [52.63, 89.47] | 43/52; 82.69% [71.15, 92.31] |
| recall_no_effect | 5/17; 29.41% [11.76, 52.94] | 6/17; 35.29% [11.76, 58.82] | 5/17; 29.41% [11.76, 52.94] | 16/51; 31.37% [19.61, 43.14] |
| recall_refutes | 0/0; undefined [null] | 0/0; undefined [null] | 0/0; undefined [null] | 0/0; undefined [null] |
| recall_no_effect_refutes | 5/17; 29.41% [11.76, 52.94] | 6/17; 35.29% [11.76, 58.82] | 5/17; 29.41% [11.76, 52.94] | 16/51; 31.37% [19.61, 43.14] |
| supports_when_gold_no_effect_flip_rate | 2/5; 40.00% [0.00, 80.00] | 2/6; 33.33% [0.00, 66.67] | 5/8; 62.50% [25.00, 87.50] | 9/19; 47.37% [26.32, 68.42] |

Matched gold: **14/34, 15/34, 17/34**, pooled **46/102**. Conflicting labels
all count, giving 52 predictions, not 46. Nine wrong matched predictions
(2/2/5) are separate from 56 missing triples. Every run predicts supports for
gold 4 and 21; R3 additionally does so for aligned no_effect gold 29/30/31.

### Trial-5 comparable: qualified / gold-qualified-normalized.json

| Metric | R1 | R2 | R3 | Pooled |
| --- | --- | --- | --- | --- |
| G1 successful chunks | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 63/63; 100.00% [100.00, 100.00] |
| G2 claim polarity | 127/127; 100.00% [100.00, 100.00] | 154/154; 100.00% [100.00, 100.00] | 151/151; 100.00% [100.00, 100.00] | 432/432; 100.00% [100.00, 100.00] |
| polarity_accuracy | 5/5; 100.00% [100.00, 100.00] | 7/8; 87.50% [62.50, 100.00] | 11/11; 100.00% [100.00, 100.00] | 23/24; 95.83% [87.50, 100.00] |
| recall_no_effect | 1/12; 8.33% [0.00, 25.00] | 3/12; 25.00% [0.00, 50.00] | 5/12; 41.67% [16.67, 75.00] | 9/36; 25.00% [11.11, 38.89] |
| recall_refutes | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/15; 0.00% [0.00, 0.00] |
| recall_no_effect_refutes | 1/17; 5.88% [0.00, 17.65] | 3/17; 17.65% [0.00, 35.29] | 5/17; 29.41% [11.76, 52.94] | 9/51; 17.65% [7.84, 27.45] |
| supports_when_gold_no_effect_flip_rate | 0/1; 0.00% [0.00, 0.00] | 0/3; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/9; 0.00% [0.00, 0.00] |

Matched gold remains 24/102. The historical label for gold 11 creates one
wrong matched prediction in R2. All 15 historical refutes instances miss
correct polarity. This score uses the frozen current dose normalization,
not trial 5's older dose rule; a retained-output baseline is reported below.

### Trial-5 comparable: legacy / gold-fulltext.json

| Metric | R1 | R2 | R3 | Pooled |
| --- | --- | --- | --- | --- |
| G1 successful chunks | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 63/63; 100.00% [100.00, 100.00] |
| G2 claim polarity | 127/127; 100.00% [100.00, 100.00] | 154/154; 100.00% [100.00, 100.00] | 151/151; 100.00% [100.00, 100.00] | 432/432; 100.00% [100.00, 100.00] |
| polarity_accuracy | 12/16; 75.00% [56.25, 93.75] | 13/17; 76.47% [52.94, 94.12] | 13/19; 68.42% [47.37, 89.47] | 38/52; 73.08% [59.62, 84.62] |
| recall_no_effect | 3/12; 25.00% [0.00, 50.00] | 4/12; 33.33% [8.33, 58.33] | 4/12; 33.33% [8.33, 58.33] | 11/36; 30.56% [16.67, 44.44] |
| recall_refutes | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/15; 0.00% [0.00, 0.00] |
| recall_no_effect_refutes | 3/17; 17.65% [0.00, 41.18] | 4/17; 23.53% [5.88, 47.06] | 4/17; 23.53% [5.88, 47.06] | 11/51; 21.57% [11.76, 33.33] |
| supports_when_gold_no_effect_flip_rate | 2/3; 66.67% [0.00, 100.00] | 2/4; 50.00% [0.00, 100.00] | 2/4; 50.00% [0.00, 100.00] | 6/11; 54.55% [27.27, 81.82] |

Matched gold remains 46/102. Historical labels yield 14 wrong matched
predictions; pooled accuracy, recall and flip all fail G3.

### G4: persisted-row coexistence

| Run | Observed collapses | Supports/no_effect pairs | All edge merges |
| --- | ---: | ---: | ---: |
| R1 | 0 | 14 | 28 |
| R2 | 0 | 28 | 24 |
| R3 | 0 | 18 | 31 |
| Pooled | 0 | 60 | 83 |

All pairs have distinct IDs and appear in find_contradictions(include_proposed=True).
G4 has no CI. It retains the preregistered observed-row plus insertion-contract
scope, not an exhaustive raw-response audit. The API groups core triples;
pairs may carry different qualifiers, not identical experimental context.
General edge merges are not cross-polarity collapses.

## Completion pass: measured requests, rejections and attribution bounds

Completion made **12/13/13 requests**, 38 total. Each run skipped its first
eight eligible chunks for reserved_first_pass_budget. R1 has one further
non-triggering chunk; R2/R3 have none. Skips are default policy, not overrides.
All **100 rejected proposals** came from completion: 98 relations and two
entities. Of the relations, **96 had ungrounded_source_span** (38/22/36), and
two had parse_validation errors (one each in R1/R2). R3's two entity rejections
were parse_validation errors. The original rejection events are in the JSON;
none caused a chunk failure. Completion duplicates and response-level
completion failures were zero. First-pass parse rejections and transport
retries were zero. These observed rejections are not silently counted as retries.

The frozen product logs request pass and rejected-proposal pass, but **does
not persist the successful proposal-to-pass map or raw provider responses**.
Consequently exact successful first/completion statement counts and exact
completion match credit are **unavailable**, not zero. No runtime patch or
extra run was introduced to manufacture that measurement.

The export annotates every edge outside its unchanged table row. Creation
timestamps identify the insertion chunk. In a chunk without usable completion,
the edge is known first-pass; mixed-chunk origin remains null with possible
passes first/completion. This proves 265 first-pass-created rows and leaves
388 rows unassigned. Bounds below are identification bounds, not bootstrap CIs.

| Run | Accepted statement insertions | First accepted bound | Completion accepted bound | First-created persisted bound | Completion-created persisted bound |
| --- | ---: | --- | --- | --- | --- |
| R1 | 240 | 102-240 | 0-138 | 83-212 | 0-129 |
| R2 | 250 | 108-250 | 0-142 | 94-226 | 0-132 |
| R3 | 246 | 101-246 | 0-145 | 88-215 | 0-127 |

Accepted insertions total 736 = 653 new edges + 83 merged citations. They
exclude rejected and within-chunk duplicate proposals. Raw emitted-statement
counts are not retained. Accepted insertions on known-first-only chunks total 311
including merges; completion accepted insertions are bounded 0-425.

| Target | Known-first matched gold R1/R2/R3 | Incremental completion match bound R1/R2/R3 | Correct negative/null contribution bound |
| --- | --- | --- | --- |
| gold-aligned-qualified.json | 1/3/6 | 0-4 / 0-5 / 0-5 | 0-1 / 0-2 / 0-2 |
| gold-aligned.json | 5/6/8 | 0-9 / 0-9 / 0-9 | 0-4 / 0-4 / 0-4 |
| gold-qualified-normalized.json | 1/3/6 | 0-4 / 0-5 / 0-5 | 0-1 / 0-2 / 0-2 |
| gold-fulltext.json | 5/6/8 | 0-9 / 0-9 / 0-9 | 0-3 / 0-3 / 0-3 |

Primary incremental matched credit is bounded **0-14/24**, with correct negative
credit **0-5/51**. A known-first match cannot be newly credited to completion.
These bounds hold final node identities/aliases fixed and concern direct
persisted-edge credit, not a first-only causal counterfactual or effects on
later chunks. Zero at the lower bound is not evidence of zero contribution.

## Miss breakdown

The numerical receipt preserves every mechanical category, candidate, span,
qualifier mismatch and wrong matched label. Reviewed categories below count
every missing row once. Gold 15/16/17 were mechanically surface candidates
under primary because unrelated controls rows shared the target; all-edge
review finds only ingredient/mechanism/synergy rows, so they are absent
comparable controls assertions. No category changes any score.

| Scorer / category | R1 | R2 | R3 | Total |
| --- | ---: | ---: | ---: | ---: |
| primary / scope | 20 | 18 | 17 | 55 |
| primary / relation | 3 | 3 | 0 | 6 |
| primary / surface | 3 | 2 | 3 | 8 |
| primary / absent | 3 | 3 | 3 | 9 |
| legacy / scope | 11 | 11 | 11 | 33 |
| legacy / relation | 3 | 3 | 0 | 6 |
| legacy / surface | 3 | 2 | 3 | 8 |
| legacy / absent | 3 | 3 | 3 | 9 |

Primary missing total: 78. Secondary: 56. Scope means exact core with unmet
gold qualifiers, or legacy qualified-name/core-node migration. Relation means
different relation/direction. Surface is a diagnostic candidate class, not
proven endpoint equivalence; sharing one endpoint does not prove an assertion
exists. Historical targets have the same missing-triple counts; their wrong
polarity counts differ.

- Gold 4 misses bubble_development in R1/R2; R3 recovers the qualified null.
- Gold 7-10 miss dilute dose in R1/R2; R3 retains it. Both earlier papers
  received only first-pass requests because completion reserved later slots.
- Gold 11 in R1 has field_trial:2 rather than the exact field_trial scope;
  R2 matches; R3 lacks the exact combination assertion.
- Gold 14 lacks the aligned label-rate dose and has absent/different population
  scope. Gold 18-20 omit dose, population, joint aspect or study context.
- Gold 23-28 omit the required sampled population/accessions. Gold 32-34 omit
  or shorten collection years/population. Missing slots are not normalized in.
- Gold 5/6 retain strain-bearing names or another disease/relation, not the
  required core/qualifier statement. R1/R2 gold 29-31 have reverse controls
  candidates rather than resistant_to; R3 retains resistant_to but lacks scope
  and predicts supports against aligned no_effect.

## Comparison with trials 3-5 and todo 33

| Trial / scorer | Matched gold | Accuracy | Negative/null recall | Flip | Successful coverage |
| --- | --- | --- | --- | --- | --- |
| 3 / published legacy | 29/102 | 22/30 | 5/51 | 4/12 | 63/63 |
| 4 / published qualified | 11/102 | 11/11 | 0/51 | 0/0 undefined | 60/63 |
| 4 / published legacy | 42/102 | 35/46 | 9/51 | 5/10 | 60/63 |
| 5 / published qualified | 20/102 | 18/20 | 6/51 | 0/6 | 63/63 |
| 5 / published legacy | 44/102 | 39/48 | 12/51 | 4/12 | 63/63 |
| 5 retained / current historical-qualified replay | 24/102 | 22/24 | 10/51 | 0/10 | same retained output |
| todo 33 offline / aligned qualified | 24/102 | 24/24 | 12/51 | 0/12 | same retained output |
| todo 33 offline / aligned legacy | 44/102 | 44/48 | 17/51 | 4/17 | same retained output |
| 6 / PRIMARY aligned qualified | 24/102 | 24/24 | 10/51 | 0/10 | 63/63 |
| 6 / SECONDARY aligned legacy | 46/102 | 43/52 | 16/51 | 9/19 | 63/63 |
| 6 / historical qualified | 24/102 | 23/24 | 9/51 | 0/9 | 63/63 |
| 6 / historical legacy | 46/102 | 38/52 | 11/51 | 6/11 | 63/63 |

Sources: [trial 3](polarity-trial-3-2026-09-27.md),
[trial 4](polarity-trial-4-2026-09-27.md), [trial 5](polarity-trial-5-2026-09-27.md),
[todo-33 offline](polarity-trial-5-aligned-rescore-2026-09-27.json).
The current historical-qualified replay uses only the committed trial-5 edge
export, not another model run; its per-run results are included in this receipt.

Against the aligned offline estimate, primary matches remain 24 but correct
negative/null findings fall **12 to 10**. Secondary correct negatives fall
**17 to 16**, while flip increases **4/17 to 9/19**. Published trial-5 qualified
scores used an older dose contract; comparing 6/51 directly to trial 6's 9/51
would confound scoring changes with extraction. Under the current historical
contract the retained baseline is 10/51, not 6/51. More requests and full chunk
coverage did not establish improvement or close G3. These are end-to-end
regression observations, not isolated causal effects of completion.

## Durable evidence, verification and retained paths

[Full edge export](polarity-trial-6-2026-09-27-edges.json), SHA-256:
**640ba1f76cc5d7611a9555b1cba537da15a4e2231b593b464238fc9fff176110**. All persisted rows retained, including noncurrent rows:
606 nodes, 653 edges, 383 aliases and 1793 citations. Each edge has a separate
pass annotation. Original source spans, qualifier/polarity JSON, graph rows and
empty receipt tables are unchanged. The export was saved before scoring.
[Full numerical receipt](polarity-trial-6-2026-09-27.json) retains all four
scorers, per-run and pooled CIs, pass accounting, misses and gate decisions.

- All 12 scorer replays (four targets x three runs) from in-memory stores
  reconstructed from the durable export equal the original-store results,
  including CIs and missing rows. Temporary stores are unnecessary for replay.
- Focused tests ran once: **238 passed, zero failures/errors/skips, exit 0**,
  4.628 seconds. Nine test modules cover polarity, fulltext, identity, qualifier
  scoring/gold/normalization, completion and transport retries. Exact command,
  [log](polarity-trial-6-2026-09-27-tests.log) and
  [JUnit](polarity-trial-6-2026-09-27-tests.xml) are retained.
- All three immutable/read-only databases pass integrity and foreign-key checks.
  Schema, collection, documents, extract, SSE/status and stages ran through HTTP.
  Every source hash matches; exactly one extraction POST/start per run.
- Six Python helpers have no LSP error diagnostics. JSON parses and replays;
  JSON LSP is unavailable because biome is not installed. No dependency was
  added for that. Build/mutation are inapplicable to evidence-only changes.
- All 18 frozen hashes match preregistration. Product/gold/configuration and
  copied-helper diffs after preregistration are empty.
- The driver stopped and awaited owned PIDs **17775/17786/17785** after terminal
  state. All logs record server shutdown; independent ps finds those PIDs absent.
  Ports **58076/58078/58077** return **61 (ECONNREFUSED)**. No protected port,
  PID, launchd service or Application Support path was accessed.
- Initial exact-key scan: **750 retained files, zero matches**. The verifier
  supplies the key through stdin to grep -a -F -c -f /dev/stdin -- FILE, checks
  every exit, and reports counts only. Delivery scan also covers this report,
  numerical receipt and canonical task artifact: **753 files, zero matches**
  ([delivery receipt](polarity-trial-6-2026-09-27-verification.json)).

Nothing was deleted by the agent; normal product/test lifecycle cleanup was
not patched. Retained trial/test roots:
- /private/tmp/ol-polarity6-20260927T125639Z-r1
- /private/tmp/ol-polarity6-20260927T125639Z-r2
- /private/tmp/ol-polarity6-20260927T125639Z-r3
- /private/tmp/ol-polarity6-20260927T125639Z-tests

The isolated worktree .venv is retained. Run roots retain databases, source
bodies, provider names, logs, status, provenance and HTTP receipts. No additional
model calls are needed to reproduce scores from the committed export.

This is same-corpus regression on previously studied, null-enriched papers,
not independent holdout evidence. Prior misses informed fixes and gold
adjudication; verifier/designer overlap remains. An independently adjudicated
holdout is the independence fix, outside this authorization. Case-bootstrap
ignores within-paper and between-repeat dependence.
