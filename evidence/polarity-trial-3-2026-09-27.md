# Third polarity trial - 2026-09-27

## Outcome: FAILED (G3); IS-1 NOT MET

Exactly three preregistered runs completed all **63/63 chunks**, using
**21 requests per run**. G1, G2, and G4 pass. G3 fails all three pooled
components: accuracy **22/30 = 73.33%**, negative/null recall
**5/51 = 9.80%**, and supports-when-no_effect flip **4/12 = 33.33%**.
Complete processing did not establish polarity readiness.

The binding rule is unchanged: VERIFIED iff all four pooled gates pass;
FAILED iff G1 ran and any gate fails; BLOCKED only for the prescribed
preflight/zero-return blockers. This is FAILED, not BLOCKED or VERIFIED.

- [ ] F4 follow-up: close G3's endpoint/scope alignment and wrong-polarity
  findings, without collapsing distinct populations or relaxing frozen gold.
  Any further model trial requires separate authorization and preregistration.

The [preregistration](polarity-trial-3-2026-09-27-prereg.md) and
[driver](polarity3_driver.py) were committed as
`cd9461aad72d74942d43cf845489c926a313b3b8` at 02:03:07 UTC, before preflight
and before all three extraction starts at 02:03:27 UTC.
The [numerical receipt](polarity-trial-3-2026-09-27.json) retains complete
scorer outputs, CIs, chunk records, HTTP receipts, candidate edge IDs, and hashes.

## Frozen execution

Worktree: `/Users/hyunjun/Documents/MUNI/ontologylab-wt/w7-t26`;
branch `completion/w7-t26`; code commit
`9b88c304dba37061ed8b8a2b089625eeecf06361`.
Engine/model/prompt: `api:gemini` / `gemini-3.6-flash` / `extract-v5`.
Schema `agrochem-v2`, temperature 0.0, seed 7, request cap 60.
All 63 provider usage records and all 15 extraction streams confirm the
selected engine/model/decode parameters and prompt version.

Provider registration used kind `openai`, base URL
`https://generativelanguage.googleapis.com/v1beta/openai`, and the name
`ONTOLOGYLAB_PROVIDER_GEMINI_1BDF3AFBB89F` from `dedicated_api_key_env`.
Its value was exported from `GOOGLE_API_KEY` inside the shell, never printed
or stored in a keychain. The single separate preflight returned `pong`,
exit 0, provider time 2109 ms, outer elapsed 2.538 seconds.

Each server installed the schema through HTTP, collected the unchanged five
full bodies in filename order, and verified five fulltext/extractable documents.
All collection responses report created=5, duplicates=0, failures=[],
conflicts=[]. All 15 observations are fulltext. Every retained `raw.txt` hash
equals its frozen corpus hash. No gold labels entered extraction prompts,
no eligibility was changed through SQL, and no edge was approved.

Trial 2's driver explicitly sent `time_budget=600`, which exhausted R1/R3.
That was a trial override, not the old 7200-second product default.
This trial omitted the field: each run recorded the product's automatic
budget of **13860.001 seconds**, 21 chunks, 42 request slots, 300-second
request timeout, and 10% local reserve. The observer timeout was 14220 seconds,
not a product budget override; no observer or request timeout occurred.

The reused driver subscribed to SSE before its single extraction POST and
checked job status with bounded HTTP GETs on state events. All three runs
were concurrent, as in trial 2, with independent stores and servers.
The host tool returned asynchronously rather than holding one blocking tool
call; the foreground Python command itself awaited all three trials and their
servers and exited 0. No shell `&`, detached server, extra run, resume,
cancellation, replacement, or provider fallback was used.

Data prefix: `/private/tmp/ol-polarity3-20260927T020107Z`.
The identical job id `extract-20260927-110327` is scoped by each data directory.

| Run | Root suffix | Port / owned PID | Terminal state | Job seconds | Provenance requests | status.json requests | Successful / attempted / expected chunks | Rejected entities / relations |
| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |
| R1 | -r1 | 49500 / 66338 | complete | 1150.029 | 21 | 21 | 21 / 21 / 21 | 0 / 0 |
| R2 | -r2 | 49501 / 66370 | complete | 1101.268 | 21 | 21 | 21 / 21 / 21 | 0 / 0 |
| R3 | -r3 | 49502 / 66371 | complete | 1086.987 | 21 | 21 | 21 / 21 / 21 | 0 / 0 |

There were **63 extraction requests plus one preflight request**. Parse
rejections/retries=0, provider errors=0, never-planned chunks=0. Every chunk
succeeded on its first attempt. The frozen chunker still produces 4/4/4/5/4
chunks per paper. No chunk shortfall remains in this sample.

Todo-23 rejection events and terminal HTTP rejection counts agree at zero.
These runs did not exercise that rejection branch; zero is not an independent
proof of its error-path behavior. Todo-24 status/provenance accounting agrees
in every run. Each log has exactly one extraction POST and each provenance
has exactly one `extract.start`.

## Gates and 95% confidence intervals

All intervals use unchanged `_rate`: 2000 case-bootstrap resamples, seed 7,
95% percentile intervals over individual binary outcomes. Pool concatenated
outcomes, not averaged rates or merged stores. Decisions use point estimates,
not CI bounds. Undefined values remain null; G4 is a count with CI N/A.

| Gate / metric | R1 | R2 | R3 | Pooled | Threshold / pooled verdict |
| --- | --- | --- | --- | --- | --- |
| G1 successful chunks | 21/21, 100% [100,100] | 21/21, 100% [100,100] | 21/21, 100% [100,100] | 63/63, 100% [100,100] | >=95%: PASS |
| G2 claim polarity set | 120/120, 100% [100,100] | 132/132, 100% [100,100] | 122/122, 100% [100,100] | 374/374, 100% [100,100] | >=90%: PASS |
| G3 matched-prediction accuracy | 11/13, 84.62% [61.54,100] | 6/7, 85.71% [57.14,100] | 5/10, 50% [20,80] | 22/30, 73.33% [56.67,90] | >=80%: FAIL |
| G3 no_effect recall | 2/12, 16.67% [0,41.67] | 2/12, 16.67% [0,41.67] | 1/12, 8.33% [0,25] | 5/36, 13.89% [2.78,25] | Diagnostic |
| G3 refutes recall | 0/5, 0% [0,0] | 0/5, 0% [0,0] | 0/5, 0% [0,0] | 0/15, 0% [0,0] | Diagnostic |
| G3 combined negative/null recall | 2/17, 11.76% [0,29.41] | 2/17, 11.76% [0,29.41] | 1/17, 5.88% [0,17.65] | 5/51, 9.80% [1.96,17.65] | >=70%: FAIL |
| G3 supports-when-no_effect flip | 2/3, 66.67% [0,100] | 1/3, 33.33% [0,100] | 1/6, 16.67% [0,50] | 4/12, 33.33% [8.33,58.33] | <=15%: FAIL |
| G4 observed collapses | 0; 1 pair | 0; 1 pair | 0; 1 pair | 0; 3 pairs; CI N/A | Zero: PASS |

Every run separately has G1 PASS, G2 PASS, G3 FAIL, G4 PASS.
R1/R2 accuracy alone passes; their recall and flip fail. R3 fails all G3
components. Matched gold triples are 12/34, 7/34, 10/34, pooled **29/102**.
R1 has two polarities for one matched triple, so accuracy has 30 predictions,
not 29; the scorer counts both rather than choosing the favorable one.

G4 observed pairs:

| Run / triple | supports edge | no_effect edge |
| --- | --- | --- |
| R1 prochloraz / controls / dry bubble disease | 2fbfd800a75f4c94aeb88d7842787f1a | cdbeaa0af4ee4ec381ac786a314c6288 |
| R2 cyantraniliprole / controls / spotted wing drosophila | ef8d89925f4c4a2c9965210510f10083 | a10351cc8b934a96aa13835af080e886 |
| R3 cyantraniliprole / controls / Drosophila suzukii | dafb08ee176c45898d57714b0eac9eb3 | 3ccd6f4a3f194e3eba73150c9b5ce5e3 |

All pairs appear in `find_contradictions(include_proposed=True)` with distinct
IDs. General edge merges were 16/23/19; these 58 merges are not cross-polarity
collapses. G4 retains the preregistered persisted-row/identity-contract scope:
raw model responses were not retained for an exhaustive historical audit.

## Comparison and remaining misses

| Measurement | Trial 1, original | Trial 1, corrected scorer | Trial 2 | Todo-25 offline projection | Trial 3 |
| --- | --- | --- | --- | --- | --- |
| Matched gold | 0/102 | 7/102 | 14/102 | 22/102 | 29/102 |
| Accuracy | null | 6/7 = 85.71% | 14/14 = 100% | 22/22 = 100% | 22/30 = 73.33% |
| Negative/null recall | 0/51 | 3/51 = 5.88% | 2/51 = 3.92% | 6/51 = 11.76% | 5/51 = 9.80% |
| Flip rate | null | 0/1 | 0/1 | 0/5 | 4/12 = 33.33% |
| Coverage | 15/15 excerpt chunks | same retained runs | 31/63 full-body chunks | still 31/63 | 63/63 |
| Outcome | FAILED G3 | FAILED G3 | FAILED G1/G3 | G3 still fails | FAILED G3 |

Trial 1 used extract-v3 and excerpts; its original scorer omitted recorded
aliases. Its todo-16 corrected rescore is shown separately rather than treating
the original zero as the current-scorer baseline. Trial 2 used extract-v4 and
full bodies but stopped early. Todo 25 made no model calls: deterministic
Pathway normalization recovered eight old matches and four negative/null
findings. It was not a prediction that a new model run would recover them.
Its time projections were 1094.123 seconds for 21 requests at the prior mean
and 1444.421 at prior p95; observed job times here were 1086.987-1150.029.

The new trial gains full coverage and more matches than trial 2, but it does
not recover more correct negative/null cases than the offline projection.
These are end-to-end measurements, not isolated causal estimates of the
prompt, budget, or normalization changes.

All **73 missing triples** were assigned once, checked against the scorer's
`missing_triples`, with candidate IDs/spans in the numerical receipt:

| Primary diagnostic category | R1 | R2 | R3 | Total |
| --- | ---: | ---: | ---: | ---: |
| Surface | 8 | 10 | 7 | 25 |
| Relation / direction | 2 | 1 | 0 | 3 |
| Absent comparable assertion | 4 | 3 | 2 | 9 |
| Scope / population | 8 | 13 | 15 | 36 |
| Total | 22 | 27 | 24 | 73 |

These are descriptive nearest-candidate categories, not equivalence rules:

- Surface: shortened `isolate 620/1722`, `QST 713`, `B. velezensis Kos`,
  generic `oviposition`, `bubble development`, R3 `R population`,
  R2 `cyantraniliprole + PB treatment`, and R1 `dichobenil` differ from
  the exact gold keys. In R1/R2 the eight process candidates lack the species
  prefix entirely; the binomial-prefix resolver cannot expand a missing prefix.
- Relation: R1 PB is `associated_with / mortality`, its cyantraniliprole+PB
  candidate is `inhibits / oviposition`; R2 indaziflam has the reverse
  `Poa annua L. / resistant_to / Indaziflam` finding rather than the gold
  controls assertion. Other endpoint differences remain; none is rescored.
- Scope: all three runs have S-population controls rather than the gold
  R-population null assertions for gold 14-16. Botrytis isolate/population
  qualifiers and Poa accession-qualified targets also differ from bare gold.
  R2 joint R-and-S populations are not one R population. R3 gold 11 has
  `deltamethrin + PB bait sprays`, not the bare combination identity.
  These differences do not authorize stripping qualifiers or merging scopes.
- Absent: R1/R2 gold 11; every run gold 17; R1/R3 gold 23;
  R1/R2 gold 31. Ingredient-only, synergy, or mode-of-action statements do
  not replace the missing combination/efficacy/resistance assertions.

Wrong-polarity exact matches are separate from those 73 misses: R1 gold 4
and 21 predict supports against no_effect; R2 gold 4 does so; R3 gold 4 does
so, while gold 7, 8, 21, and 22 predict refutes against no_effect.
That is **eight incorrect matched predictions**. R1 gold 4 also has the
correct no_effect row, retained alongside its incorrect supports row.
Identity recovery alone cannot fix these label disagreements.

## Verification, retained artifacts, and limits

- Existing tests ran once: `tests/test_polarity_eval.py`,
  `tests/test_polarity_identity.py`, `tests/test_polarity_fulltext.py`:
  **55 passed, exit 0, 2.91 seconds**. Fresh basetemp:
  `/private/tmp/ol-polarity3-20260927T020107Z-tests`.
- All three immutable/read-only databases passed integrity and foreign-key
  checks. WAL files were absent when scoring; no checkpoint or deletion was
  performed. The closed database hashes are in the numerical receipt.
- HTTP stage buckets exactly match SQLite grouping, with 203/231/207 current
  edges. Full-text ingestion, schema, extraction, status/SSE and stages were
  exercised through the real HTTP surface, not direct route-function calls.
- All three evidence harnesses passed LSP error diagnostics. JSON was parsed
  directly because the JSON LSP's `biome` executable is unavailable; no
  dependency was installed to change that. No application build or mutation
  was applicable: product, scorer, tests, corpus, and gold stayed frozen.
- `git diff 9b88c30 -- ontologylab tests pyproject.toml uv.lock` is empty;
  corpus/gold/extractor/scorer and frozen-driver hashes match preregistration.
  The protocol, driver, and thresholds were not changed after preregistration.
- Only owned server PIDs 66338/66370/66371 were terminated after terminal
  job state. Every log records application shutdown and a finished server.
  Independent `ps` checks find no such PIDs. Ports 49500/49501/49502 each
  return **61 (ECONNREFUSED)**. Port 8799, PIDs 87584/3284, launchd, and
  Application Support were untouched.
- Exact-value `grep -a -F -c -f /dev/stdin -- FILE`, with every exit checked,
  scanned the retained stores, logs, sources, test outputs, protocol, and
  harnesses: **275 files, 0 matches** before final report files were added.
  The key was passed through stdin, never a displayed command argument.
  The final scan including this Markdown, numerical receipt, and requested
  task receipt checked **278 files, 0 matches**.

Nothing was deleted. Retained temporary roots:

1. `/private/tmp/ol-polarity3-20260927T020107Z-r1`
2. `/private/tmp/ol-polarity3-20260927T020107Z-r2`
3. `/private/tmp/ol-polarity3-20260927T020107Z-r3`
4. `/private/tmp/ol-polarity3-20260927T020107Z-tests`

Each run retains its SQLite store, provider-name registry, uploaded texts,
server log, HTTP receipt, provenance, and status. R1 also retains preflight,
scoring, tests.log, and tests.xml. The worktree retains `.venv` and the three
evidence harnesses. Reproduce scoring without model calls:

```sh
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python evidence/polarity3_score.py \
  tests/gold/agrochem-polarity/gold-fulltext.json \
  /private/tmp/ol-polarity3-20260927T020107Z-r1 \
  /private/tmp/ol-polarity3-20260927T020107Z-r2 \
  /private/tmp/ol-polarity3-20260927T020107Z-r3
```

The five papers were studied during earlier fixes; this is a same-corpus
regression trial, not a held-out benchmark. Gold lacks independent expert
adjudication. Case-bootstrap intervals ignore paper/repeat dependence.
No gate-review approval is invented: the binding gate calculation was checked
directly in this execution; a separate orchestrator review remains separate.
