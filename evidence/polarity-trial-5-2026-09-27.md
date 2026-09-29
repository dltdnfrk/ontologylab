# Fifth polarity trial - 2026-09-27

## Outcome: FAILED (primary G3); IS-1 NOT MET

Exactly three preregistered runs completed all **63/63 chunks**. Qualified
PRIMARY matches **20/102** gold statements: accuracy **18/20 = 90%**,
negative/null recall **6/51 = 11.76%**, flip **0/6 = 0%**. G1, G2, G4 pass;
G3 fails the unchanged 70% recall threshold. Every run has the same verdict.
Complete processing and accurate polarity on a small matched subset do not
establish polarity readiness.

Legacy SECONDARY also fails G3: accuracy **39/48 = 81.25%**, recall
**12/51 = 23.53%**, flip **4/12 = 33.33%**. Legacy cannot establish VERIFIED.
Chunks returned and gates ran: FAILED, not BLOCKED. No replacement, resume,
alternate provider, scorer relaxation, product edit, or extra run was used.

- [ ] F4 follow-up: close missing assertion scope and negative/null recall,
  including refutes versus measured no_effect. IS-1 remains NOT MET. This
  report does not authorize another model trial or product change.

## Frozen execution and accounting

Work root: /Users/hyunjun/Documents/MUNI/ontologylab-wt/w9-t32; branch completion/w9-t32.
Code commit: 1abdee4c1460366fcb67de13c3dfe53e19f54cb1, todos 30/31 integrated.
[Preregistration](polarity-trial-5-2026-09-27-prereg.md) and five path-only
copied helpers were committed as **7830f7d1a1312cf31b6cd1ab3a27508600d55a36** at **10:47:48 UTC**,
before the single provider test and extraction starts at **10:48:02 UTC**.
Only evidence changed afterward. All 15 frozen corpus/gold/code/helper hashes
match. Product/gold/config diff from the base is empty; preregistration and
helpers remain unchanged.

Engine/model/prompt: **api:gemini / gemini-3.6-flash / extract-v8**.
Schema agrochem-v2; temperature 0.0; seed 7; cap **60 requests/run including
all retries**. The dedicated provider key was exported from GOOGLE_API_KEY
only inside the launch shell, without printing it or using a keychain.
One separate preflight returned pong, exit 0, 1,947 provider ms
(2.160480 outer seconds).

Each isolated server installed the schema and collected five complete bodies
through HTTP. All 15 API documents were fulltext/extractable; all 15 observations
were fulltext. Every persisted raw body hash equals its corpus source.
No SQL eligibility changes or approvals; verified edges=0/0/0. Each run has one
extraction POST and one extract.start event. Identical second-resolution job IDs
are scoped by independent data directories.

The foreground Python command owned and awaited all three concurrent drivers
and servers. The host monitor delivered exit 0; no shell backgrounding was used.
Each driver subscribed to SSE before POST, then checked status by event-driven
GET inside its bounded loop. No observer fired.

Payload fields time_budget and max_transport_retries were omitted. Provenance
confirms **effective transport retry limit 2** and automatic budgets
**20,280.000762 / 20,280.000831 / 20,280.000694 seconds**: 21 chunks,
60 request slots, 300 seconds/request, 10% reserve plus 8 seconds/backoff slot.
The unchanged 14,220-second observer is shorter than the worst-case product
budget but was never reached. No product default was overridden.

| Run | Port / owned PID | State | Job seconds | Status / provenance requests | Successful / attempted / expected | Transport / parse retries | Rejected entities / relations |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| R1 | 64135 / 97353 | complete | 963.233 | 21 / 21 | 21 / 21 / 21 | 0 / 0 | 0 / 0 |
| R2 | 64139 / 97366 | complete | 1038.118 | 22 / 22 | 21 / 21 / 21 | 0 / 1 | 0 / 0 |
| R3 | 64138 / 97365 | complete | 972.925 | 21 / 21 | 21 / 21 / 21 | 0 / 0 | 0 / 0 |

**64 extraction requests plus one preflight = 65 provider requests**.
Status.json and provenance agree. Terminal HTTP jobs have no engine_calls
field; absence is null, not zero. No transport retries or engine errors occurred.
R2 performed one counted parse retry on PMC12563837 chunk 0 after
"relation[0] occurs_in: undeclared qualifier 'polarity'"; the next request
succeeded. This is not a rejected proposal: proposal rejection events/counts
are zero. Warning counts are 317/356/324. All chunks were planned and attempted.
The transient transport retry branch was configured but not exercised.

## Gates and 95% confidence intervals

Unchanged thresholds: G1 >=95%; G2 >=90%; G3 accuracy >=80%, negative/null
recall >=70%, AND flip <=15%; G4 zero observed supports/no_effect collapses.
All runs and both pooled scorers: **G1 PASS / G2 PASS / G3 FAIL / G4 PASS**.
CIs: 2,000 case-bootstrap resamples, seed 7, 95% percentile method. Pool
concatenated binary outcomes, not averaged rates or merged graphs. Decisions
use point estimates; undefined values remain null. G4 has no rate CI.

### PRIMARY: qualified statements / regenerated gold-qualified.json

| Metric | R1 | R2 | R3 | Pooled |
| --- | --- | --- | --- | --- |
| G1 successful chunks | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 63/63; 100.00% [100.00, 100.00] |
| G2 polarity set | 133/133; 100.00% [100.00, 100.00] | 125/125; 100.00% [100.00, 100.00] | 142/142; 100.00% [100.00, 100.00] | 400/400; 100.00% [100.00, 100.00] |
| polarity_accuracy | 6/6; 100.00% [100.00, 100.00] | 6/7; 85.71% [57.14, 100.00] | 6/7; 85.71% [57.14, 100.00] | 18/20; 90.00% [75.00, 100.00] |
| recall_no_effect | 2/12; 16.67% [0.00, 41.67] | 2/12; 16.67% [0.00, 41.67] | 2/12; 16.67% [0.00, 41.67] | 6/36; 16.67% [5.56, 27.78] |
| recall_refutes | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/15; 0.00% [0.00, 0.00] |
| recall_no_effect_refutes | 2/17; 11.76% [0.00, 29.41] | 2/17; 11.76% [0.00, 29.41] | 2/17; 11.76% [0.00, 29.41] | 6/51; 11.76% [3.92, 19.61] |
| supports_when_gold_no_effect_flip_rate | 0/2; 0.00% [0.00, 0.00] | 0/2; 0.00% [0.00, 0.00] | 0/2; 0.00% [0.00, 0.00] | 0/6; 0.00% [0.00, 0.00] |

Matched gold: **6/34, 7/34, 7/34**; missing: **28/27/27**. All six correctly
recovered negative/null statements are no_effect; none of 15 refutes instances
was recovered correctly. R2/R3 gold 11 matches but is labeled no_effect rather
than refutes. These two wrong predictions are separate from 82 missing
statements. All 400 claim rows have polarity, but none has refutes:
338 supports and 62 no_effect.

### SECONDARY: legacy triples / gold-fulltext.json

| Metric | R1 | R2 | R3 | Pooled |
| --- | --- | --- | --- | --- |
| G1 successful chunks | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 21/21; 100.00% [100.00, 100.00] | 63/63; 100.00% [100.00, 100.00] |
| G2 polarity set | 133/133; 100.00% [100.00, 100.00] | 125/125; 100.00% [100.00, 100.00] | 142/142; 100.00% [100.00, 100.00] | 400/400; 100.00% [100.00, 100.00] |
| polarity_accuracy | 13/15; 86.67% [66.67, 100.00] | 13/16; 81.25% [62.50, 100.00] | 13/17; 76.47% [52.94, 94.12] | 39/48; 81.25% [68.75, 91.67] |
| recall_no_effect | 4/12; 33.33% [8.33, 58.33] | 4/12; 33.33% [8.33, 58.33] | 4/12; 33.33% [8.33, 58.33] | 12/36; 33.33% [19.44, 50.00] |
| recall_refutes | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/5; 0.00% [0.00, 0.00] | 0/15; 0.00% [0.00, 0.00] |
| recall_no_effect_refutes | 4/17; 23.53% [5.88, 47.06] | 4/17; 23.53% [5.88, 47.06] | 4/17; 23.53% [5.88, 47.06] | 12/51; 23.53% [11.76, 35.29] |
| supports_when_gold_no_effect_flip_rate | 1/4; 25.00% [0.00, 75.00] | 1/4; 25.00% [0.00, 75.00] | 2/4; 50.00% [0.00, 100.00] | 4/12; 33.33% [8.33, 58.33] |

Matched gold: **14/34, 15/34, 15/34**, pooled **44/102**. All conflicting labels
count: 48 predictions, not 44. Nine wrong predictions (2/3/4) are separate from
58 missing triples. Every run fails recall and flip; R3 additionally fails
accuracy. Wrong matches: gold 4 supports in all runs, gold 11 no_effect in R2/R3,
gold 21 supports in R3, gold 23 no_effect in all runs.

### G4 and persisted rows

| Run | Observed collapses | Coexisting supports/no_effect pairs | All edge merges |
| --- | ---: | ---: | ---: |
| R1 | 0 | 8 | 21 |
| R2 | 0 | 9 | 17 |
| R3 | 0 | 16 | 19 |
| Pooled | 0 | 33 | 57 |

Every pair has distinct IDs and appears in find_contradictions(include_proposed=True).
The JSON lists every pair. This retains the persisted-row and insertion-test
scope, not raw-response replay. The API groups core triples; pairs may have
different qualifiers, not identical scientific contexts. General edge merges
are not cross-polarity collapses.

## Miss breakdown

The [JSON receipt](polarity-trial-5-2026-09-27.json) preserves mechanical
categories, candidate IDs, qualifiers, spans, and reviewed categories/reasons.
Each missing statement is counted once; categories never change scorer matches.

| Scorer / category | R1 | R2 | R3 | Total |
| --- | ---: | ---: | ---: | ---: |
| primary / scope | 20 | 20 | 17 | 57 |
| primary / relation | 3 | 2 | 6 | 11 |
| primary / surface | 2 | 2 | 2 | 6 |
| primary / absent | 3 | 3 | 2 | 8 |
| legacy / scope | 12 | 12 | 9 | 33 |
| legacy / relation | 3 | 2 | 6 | 11 |
| legacy / surface | 2 | 2 | 2 | 6 |
| legacy / absent | 3 | 3 | 2 | 8 |

Scope: exact core with unmet gold slots, or legacy qualified-name/core-node
migration. Relation: different relation/direction, sometimes also lost legacy
endpoint scope. Surface: unresolved strain-bearing endpoint, not proven
equivalence. Absent: no comparable assertion after all-edge endpoint review;
unrelated one-endpoint neighbors, ingredient and mechanism rows do not suffice.

- Gold 4: all runs retain the no_effect crop-trial row but omit bubble_development.
  Background supports remains separate.
- Gold 7-10: R1/R2 preserve Bioassay 2 and oviposition but omit dilute dose;
  R3 uses controls rather than inhibits.
- Gold 14: R2/R3 retain R population and dose 1x, not frozen 1x recommended rate.
  No dose equivalence was added. R1's core row instead describes S population.
- Gold 18-20 omit population/dose/context or retain only fresh_weight rather
  than the combined aspect. R3 gold 20 also uses a different population slot.
- Gold 24-28 omit sampled population; gold 32-34 omit or shorten collection
  years/population. Normalized study values do not fill missing qualifiers.
- Gold 5/6 retain QST 713/Kos or abbreviated strain-bearing names instead of
  core-node/qualifier identity. Gold 29/30 have reversed controls candidates,
  not resistant_to assertions.
- Reviewed absent: R1 gold 11/16/31, R2 gold 16/17/31, R3 gold 17/31.
  R1 gold 15 and R3 gold 7-10 are reviewed relation misses under both scorers;
  the legacy helper initially called them absent because scoped endpoints did
  not resolve. Original mechanical outputs remain in the JSON.

## Comparison with trials 1-4 and todo 30

| Trial / scorer | Matched gold | Accuracy | Negative/null recall | Flip | Coverage |
| --- | --- | --- | --- | --- | --- |
| 1 original / original legacy | 0/102 | 0/0 | 0/51 | 0/0 | 15/15 excerpt chunks |
| 1 corrected / corrected legacy | 7/102 | 6/7 | 3/51 | 0/1 | same retained excerpts |
| 2 / legacy | 14/102 | 14/14 | 2/51 | 0/1 | 31/63 full-body chunks |
| 3 / legacy | 29/102 | 22/30 | 5/51 | 4/12 | 63/63 full-body chunks |
| 4 / legacy | 42/102 | 35/46 | 9/51 | 5/10 | 60/63 succeeded; 63/63 attempted |
| 4 / qualified primary | 11/102 | 11/11 | 0/51 | 0/0 | same trial-4 runs |
| todo 30 offline / normalized qualified | 23/102 | 21/23 | 6/51 | not remeasured here | same retained trial-4 runs; no new calls |
| 5 / qualified PRIMARY | 20/102 | 18/20 | 6/51 | 0/6 | 63/63 successful |
| 5 / legacy | 44/102 | 39/48 | 12/51 | 4/12 | same trial-5 runs |

Sources: [trial 1](polarity-trial-2026-09-26.md),
[corrected 1](polarity-trial-2026-09-26-misses.md),
[2](polarity-trial-2-2026-09-26.md), [3](polarity-trial-3-2026-09-27.md),
[4](polarity-trial-4-2026-09-27.md),
[todo-30 offline](task-30-qualifier-normalization.json).
All live trials fail G3; trial 2 also fails G1. Undefined 0/0 is not zero.
Trial 1 used excerpts/extract-v3; trials 2/3/4 full bodies and v4/v5/v7;
trial 5 v8. Original trial-4 qualified and todo-30 normalized offline scoring
have different qualifier contracts and must not be conflated.

Qualified matching improves over original trial 4 (11 to 20) but is below
the normalized offline replay (23 to 20). Negative/null recall equals the
offline estimate, 6/51. Legacy recall rises 9/51 to 12/51 and flip falls 50%
to 33.33%, still failing. Coverage is restored. These are end-to-end results,
not isolated causal effects of normalization, prompt or retries: no transport
error occurred this time. Offline replays are not new model observations.

## Durable export, verification, and limits

[Complete export](polarity-trial-5-2026-09-27-edges.json), SHA-256:
**488e549ed6fb341634c780ea6bbea2b632cf5ec7b2a657880b8e7c0bc7148d66**.
Saved before scoring. ALL persisted nodes (194/218/185), edges (197/205/215),
aliases (117/121/123), citations (538/576/562), original qualifiers/polarities,
source spans, schema/document and extraction rows are retained, including
noncurrent rows. Totals: **597 nodes, 617 edges, 1,676 citations**. Empty receipt
tables and original null spans remain empty/null. Only the exporter's literal
trial envelope was corrected 4 to 5, as preregistered; helpers are path-only copies.

Export read-back was exact. Both scorers replayed independently from in-memory
stores reconstructed from the export: every field, CI and miss equals the
original-store result. This command does not open temporary trial stores:

    PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python evidence/polarity5_export.py rescore evidence/polarity-trial-5-2026-09-27-edges.json tests/gold/agrochem-polarity/gold-qualified.json tests/gold/agrochem-polarity/gold-fulltext.json

- Existing focused tests: **69 passed, zero failures/errors/skips, exit 0**,
  1.73 seconds. [JUnit](polarity-trial-5-2026-09-27-tests.xml) and the numerical
  receipt retain evidence and exact command; basetemp was verified absent.
- Three immutable read-only databases pass integrity and foreign-key checks.
  HTTP stage totals equal SQLite, 197/205/215. Real schema, collect, documents,
  extract, SSE, status and stages HTTP surfaces were exercised.
- Five Python helpers have zero LSP error diagnostics. JSON parses and the export
  replays. JSON LSP unavailable because biome is absent; no dependency was added.
- Build/mutation: not applicable to evidence-only changes on frozen product.
  Path-only helper copying was verified byte for byte; all input hashes match.
- Owned PIDs **97353/97366/97365** are absent. Ports **64135/64139/64138**
  independently return **61 (ECONNREFUSED)**; shutdown was awaited. Port 8799,
  PIDs 87584/3284, launchd and Application Support were untouched.
- Exact-key grep passes its pattern through stdin, checks every exit and returns
  counts only. Initial scan: **335 retained files, 0 matches**. Delivery scan:
  **338 files, 0 matches**, including this report, JSON and canonical artifact.
  No key value is included in evidence.

Nothing was deleted. Retained temporary roots:
- /private/tmp/ol-polarity5-20260927T104521Z-r1
- /private/tmp/ol-polarity5-20260927T104521Z-r2
- /private/tmp/ol-polarity5-20260927T104521Z-r3
- /private/tmp/ol-polarity5-20260927T104521Z-tests

The worktree retains its isolated .venv. Run roots retain stores, uploads,
provider names, logs, status, provenance and HTTP receipts. Future rescoring
needs only the durable export and frozen scorer/gold, not temporary stores.

Same-corpus regression on previously studied, null/negative-enriched papers,
not an independent holdout. Prior misses informed fixes and vocabulary;
verifier/designer overlap and no independent expert adjudication remain.
A new independently adjudicated holdout is the independence fix, outside this
trial. Case-bootstrap ignores within-paper and between-repeat dependence.
