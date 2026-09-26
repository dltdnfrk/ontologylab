# Second polarity trial - 2026-09-26

## Outcome: FAILED (G1, G3); IS-1 NOT MET

Exactly three authorized extraction runs were executed, without replacements.
R1 and R3 stopped at the preregistered 600-second time budget; R2 failed on a
store validation error. Chunks and scored edges exist, so the binding outcome
is FAILED, not BLOCKED. Neither the model nor any threshold was changed.

- [ ] Follow-up for F4: close G1's incomplete full-corpus extraction and the
  Product.registration_number validation failure, preserve counters on job
  failure, and close G3's low negative/null recall and identity/scope misses.
  Any further model trial needs a separate authorization and preregistration.

The [preregistration](polarity-trial-2-2026-09-26-prereg.md) was committed as
`b3743a1641dccad4260aaa7127e3b4dfa6420e25` before the provider test.
The [numerical receipt](polarity-trial-2-2026-09-26.json) contains all scorer
outputs, extraction run/chunk rows, stage counts, edge identities, miss indices,
and closed-store hashes. The worktree remained `completion/w5-t21`, based on
`ae582547da4592fc8be4f1e049e12a8ea724b85f`.

## Execution receipt

Provider registration used `dedicated_api_key_env` and the name
`ONTOLOGYLAB_PROVIDER_GEMINI_1BDF3AFBB89F`, exported from `GOOGLE_API_KEY` only
inside the shell. Provider kind/base were `openai` /
`https://generativelanguage.googleapis.com/v1beta/openai`. No keychain was used.
The one preflight returned `pong`, exit 0, provider time 2354 ms, outer time
2.626 seconds. The prescribed `gemini-3.6-flash` model was available.

All runs used `api:gemini`, `gemini-3.6-flash`, `extract-v4`, `agrochem-v2`,
temperature 0.0, seed 7, `max_engine_calls=60`, and `time_budget=600`.
Persisted decode parameters and request usage records confirm these selections.
Each server installed the schema by HTTP, then collected all five complete
bodies through `POST /api/collect`: created=5, duplicates=0, failures=[],
conflicts=[]. All 15 document observations and API document rows were fulltext;
all were extractable and their content hashes matched the frozen corpus.
Abstract-only gating was not bypassed.

Each driver subscribed to `/api/jobs/stream` before its single
`POST /api/extract`. The three isolated runs were concurrent, as in trial 1.
They shared neither stores nor provider registries. All started at
2026-09-26 23:31:43 UTC (2026-09-27 locally); the evidence retains the requested
2026-09-26 trial name. Job id `extract-20260927-083143` is scoped by data directory.
Bounded session monitors ran the foreground Python drivers, without shell `&`;
each driver owned and awaited its server. Driver wait bound was 930 seconds,
provider-test bound 320 seconds, and outer trial bound 1050 seconds.

Data prefix: `/private/tmp/ol-polarity2-20260926T232709Z`.

| Run | Directory suffix | Port / PID | Terminal state | Job seconds | Requests / cap | Successful / persisted planned chunks |
| --- | --- | --- | --- | ---: | ---: | ---: |
| R1 | -r1 | 55745 / 21833 | partial: time budget | 622.979 | 11/60 | 11/12 |
| R2 | -r2 | 55747 / 21859 | failed: store validation | 457.120 | 10/60 | 9/12 |
| R3 | -r3 | 55748 / 21860 | partial: time budget | 640.406 | 12/60 | 11/12 |

There were **33 extraction requests plus one preflight request**. R3 had one
parse rejection/retry, already included in its 12 requests; R1/R2 had none.
No provider errors, driver cancellations, resumes, or replacement runs occurred.
No edge was approved: verified-edge counts are 0/0/0.

### Failure and coverage accounting

R2's retained provenance records:
`SchemaValidationError: property 'registration_number' for entity type 'Product' must be a non-empty string`.
Its failed chunk was rolled back; 9 chunks succeeded, 1 failed, and 2 remain
pending. R1/R3 each have 11 succeeded and 1 pending chunk.

R2 exposes a second accounting defect: the failure handler creates a new
`Provenance(..., seed=0)` at `ontologylab/server/jobs.py:678`, replacing
`status.json` counters with the failure event's zero calls. The append-only
provenance still contains **10 actual engine-call events**. The frozen
trial-1-style accounting harness correctly stopped with AssertionError
(exit 1) on the disagreement. Read-only accounting then preserved both
values (`engine_calls=10`, `status_engine_calls=0`,
`status_counter_agrees=false`) and checked the provenance request cap.
No product, scorer, or preregistered harness file was changed to hide it.
R1/R3 provenance counts agree with status.json (11/12 respectively).

G1 below retains trial 1's persisted `extraction_chunks` denominator. This does
**not** mean the whole corpus was processed: the frozen chunker produces
4/4/4/5/4 chunks in filename order, **21 per run**, but the extractor only
created plans for the first three documents before stopping. Nine chunks per
run were never planned. Whole-corpus successful coverage is therefore
**31/63 = 49.21%**, lower than the recorded G1 value. Neither PMC12632097 nor
PMC12713700 reached extraction in any run. G1 fails under either denominator;
the missing papers remain in G3's gold denominators.

## Gates and confidence intervals

Intervals are 95% percentile case-bootstrap intervals: 2,000 resamples,
seed 7, individual binary outcomes, exactly the frozen scorer's method.
Pool numerators/denominators and concatenated outcomes, not averaged rates.
Undefined rates/CIs remain null. Threshold decisions use point estimates,
not confidence bounds. G4 is an observed count, so its CI is not applicable.

| Gate / metric | R1 | R2 | R3 | Pooled | Threshold / pooled verdict |
| --- | --- | --- | --- | --- | --- |
| G1 successful chunks | 11/12 = 91.67% [75,100] | 9/12 = 75% [50,100] | 11/12 = 91.67% [75,100] | 31/36 = 86.11% [75,97.22] | >=95%: FAIL |
| G2 claim polarity set | 67/67 = 100% [100,100] | 50/50 = 100% [100,100] | 49/49 = 100% [100,100] | 166/166 = 100% [100,100] | >=90%: PASS |
| G3 matched-gold accuracy | 6/6 = 100% [100,100] | 5/5 = 100% [100,100] | 3/3 = 100% [100,100] | 14/14 = 100% [100,100] | >=80%: PASS |
| G3 no_effect recall | 0/12 [0,0] | 1/12 = 8.33% [0,25] | 0/12 [0,0] | 1/36 = 2.78% [0,8.33] | Diagnostic |
| G3 refutes recall | 0/5 [0,0] | 1/5 = 20% [0,60] | 0/5 [0,0] | 1/15 = 6.67% [0,20] | Diagnostic |
| G3 combined negative/null recall | 0/17 [0,0] | 2/17 = 11.76% [0,29.41] | 0/17 [0,0] | 2/51 = 3.92% [0,9.8] | >=70%: FAIL |
| G3 supports-when-no_effect flip | 0/0, null | 0/1 = 0% [0,0] | 0/0, null | 0/1 = 0% [0,0] | <=15%: PASS pooled |
| G4 observed cross-polarity collapses | 0; 0 pairs | 0; 1 pair | 0; 0 pairs | 0; 1 pair; CI N/A | Zero collapses: PASS |

All three per-run G1/G3 verdicts are FAIL; per-run G2 passes. Null flip
denominators in R1/R3 are not zero flip rates. The 14 matched gold relations
contain no wrong-polarity exact matches; **88/102 gold relations are missing**.
The perfect conditional accuracy therefore does not establish adequate recall.

G4's observed R2 pair is cyantraniliprole / controls / Drosophila suzukii:
supports edge `7bb8dd9c17ee45588cb3b26d19a02024`, no_effect edge
`52385e0a873e46a29e33f7f54638555c`. General edge merges were 7/8/9; those
24 merges are not cross-polarity collapse counts. R3 also has a separate
supports/refutes contradiction, not a supports/no_effect pair.
R1/R3 offered no persisted supports/no_effect pair to inspect. As preregistered,
G4 is the persisted-row observation plus the tested polarity-aware identity
contract, not an exhaustive audit of unretained raw provider responses.

## Claims/stages HTTP reconciliation

Every nonzero API relation/polarity bucket matched independent SQLite
`GROUP BY relation_type, json_extract(qualifiers_json,'$.polarity')` counts.
The numerical receipt retains the complete bucket counts.

| Stage | R1 | R2 | R3 |
| --- | ---: | ---: | ---: |
| threat | 9 | 11 | 15 |
| control | 68 | 41 | 42 |
| mechanism | 9 | 7 | 4 |
| resistance | 21 | 18 | 20 |
| application | 6 | 4 | 9 |
| trial | 0 | 0 | 0 |
| safety | 4 | 4 | 3 |
| diagnostics / interpretation / other | 0 | 0 | 0 |
| Total current edges | 117 | 85 | 93 |

## Comparison and miss breakdown

| Measurement | Trial 1 | Todo-19 offline replay | Trial 2 |
| --- | --- | --- | --- |
| Matched gold | 0/102 | 43/102 | 14/102 |
| Accuracy | null | 35/43 = 81.40% [69.77,93.02] | 14/14 = 100% [100,100] |
| Negative/null recall | 0/51 [0,0] | 11/51 = 21.57% [9.8,33.33] | 2/51 = 3.92% [0,9.8] |
| Flip rate | null | 3/8 = 37.5% [12.5,75] | 0/1 = 0% [0,0] |
| Outcome | FAILED: G3 | FAILED: G3 | FAILED: G1, G3 |

Trial 1 used excerpts and extract-v3. Todo 19 replayed retained proposals with
complete source context; it made no new model calls. Trial 2 used complete
bodies and extract-v4, but retained trial 1's 600-second budget, which was
insufficient, and R2 hit an additional validation error. These are measured
end-to-end results, not an isolated causal test of prompt quality.

Categories below partition only unmatched triples. Gold numbers are the
unchanged 1-based relation order in gold-fulltext.json. All 88 assigned IDs
were checked against the scorer's missing_triples; no diagnostic candidate
was counted as a recovered match.

| Primary category | R1 | R2 | R3 | Total |
| --- | ---: | ---: | ---: | ---: |
| surface | 4 | 5 | 1 | 10 |
| relation | 0 | 0 | 4 | 4 |
| absent | 17 | 22 | 19 | 58 |
| scope | 7 | 2 | 7 | 16 |
| Total | 28 | 29 | 31 | 88 |

- **Surface:** R1/R2 gold 7-10 retain `D. suzukii oviposition`, without the
  recorded full-name alias required by the scorer. R2 gold 13 is
  `cyantraniliprole + PB treatment`; R3 gold 17 is `R blackgrass plants`
  rather than `R blackgrass population`. PBO is already a recorded alias
  of piperonyl butoxide; this last mismatch is the target label, not that alias.
- **Relation:** R3 gold 7-10 have controls/Drosophila suzukii candidates,
  not inhibits/oviposition assertions. Both relation and endpoint detail differ.
- **Scope:** all runs' gold 29-30 use `Botrytis cinerea isolates` instead of
  the gold species node. R1/R3 gold 12-13 target adults; gold 14-16 have
  susceptible S-population control candidates, not resistant R-population
  claims. S and R are different findings: this category never asserts
  equivalence or licenses identity collapse.
- **Absent:** all runs' gold 1-6 and 21-28 belong to the two unvisited papers
  (42 instances). Also absent are gold 31 in all runs, gold 11 in R1/R3,
  gold 17 in R1, gold 14-20 in R2, and gold 18-20 in R3. Missing combination
  assertions and missing resistance assertions are not replaced with
  ingredient-only or unrelated mechanisms. Full per-run lists and candidate
  edge identities are preserved in the numerical receipt.

## Verification, shutdown, and retained paths

- Corpus/gold/extractor/scorer SHA-256 values still equal preregistration.
  `git diff ae58254 -- ontologylab tests pyproject.toml uv.lock` is empty.
  Both preregistered harness files also retain their original hashes.
- Existing tests ran once: `tests/test_polarity_eval.py`,
  `tests/test_polarity_identity.py`, `tests/test_polarity_fulltext.py`:
  **55 passed, exit 0**, 3.15 seconds. The fresh pytest basetemp did not exist
  before invocation. No product mutation or application build was performed:
  this is evidence-only work and product bytes must remain frozen.
- Both Python harnesses passed LSP diagnostics and py_compile. JSON LSP is
  unavailable because biome is absent; JSON parsing is the validation fallback,
  without installing anything or changing dependencies.
- All three closed databases passed integrity_check and foreign_key_check.
  Manual surface verification was the real HTTP schema/collect/documents/
  extraction/SSE/stages path, not direct route-function calls.
- Only owned PIDs 21833, 21859, 21860 received SIGTERM after terminal job state.
  Each server emitted its finished event and exited -15. `ps` on those PIDs
  returned no rows (exit 1). Independent socket checks returned
  **ECONNREFUSED (61)** for 55745, 55747, 55748. Protected PIDs 87584/3284,
  port 8799, launchd, and Application Support were untouched.
- An exact-value scan ran `grep -a -F -c -- <environment value> <artifact>`
  separately over **280 existing retained files**, including SQLite files,
  logs, source copies, test artifacts, and preregistered harnesses:
  **0 matches**, with every grep exit checked (0 or 1). No credential value
  was printed. The final scan, including both new evidence files and the
  requested task receipt, checked **283 files: 0 matches**.

Nothing was deleted. Retained temporary roots:

1. `/private/tmp/ol-polarity2-20260926T232709Z-r1`
2. `/private/tmp/ol-polarity2-20260926T232709Z-r2`
3. `/private/tmp/ol-polarity2-20260926T232709Z-r3`
4. `/private/tmp/ol-polarity2-20260926T232709Z-tests`

Each run root retains its store, provider-name registry, uploaded sources,
server log, HTTP receipt, and job provenance/status. R1 additionally retains
preflight.json, scoring.json, tests.log, and tests.xml. Worktree-local `.venv`
and `.omo/evidence/polarity2_driver.py`, `polarity2_score.py` are retained.
Store/provenance hashes and per-document extraction run ids are in the
numerical receipt.

Residual limits: incomplete processing, a model-output/store validation failure,
and failed G1/G3 are measured defects, not deferred successful runs. The gold
was author-of-fixture checked, not independently expert-adjudicated; this
same-corpus regression trial is not an independent holdout. Bootstrap intervals
do not account for correlated claims or repeated papers. Frozen evidence does
not authorize fixing these defects or running extra model calls here.

## Requested retained-WAL audit

The orchestrator requested a foreground audit after the original evidence
commit. Each run's http-receipt.json, server.log, and complete extraction
provenance were reread: terminal states remain partial/failed/partial and
engine-call counts remain **11/10/12**. All three logs contain application
shutdown completion and the finished-server event. All six driver/server PIDs
21822/21828/21835/21833/21859/21860 are absent (`ps` exit 1).

R2's retained files were checked before and after two read-only SQLite reads:

| File | Bytes | SHA-256, unchanged by audit |
| --- | ---: | --- |
| kg.sqlite | 925696 | 90cbe4393364396c92c0637eb640990c6d8a6f66ac72d4d6d12c839adef56da6 |
| kg.sqlite-wal | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| kg.sqlite-shm | 32768 | fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb |

Both `mode=ro` and `mode=ro&immutable=1` connections returned integrity `ok`,
no foreign-key errors, 85 edges, and identical full `score_polarity` results
against gold-fulltext.json. The WAL is empty and no WAL frames are required
to recover the scored state from the main database. No checkpoint command,
file deletion, or database write was issued.

`lsof` initially exposed this session's own retained read-only Bun inspection
handle (PID 84912), not a surviving server. Its owned Database.close() was
called; a repeated lsof over the three exact paths returned no rows (exit 1).
The files remain in place.

A foreground rescore of all three stores exited 0 and reproduced every
per-run and pooled G1-G4 number and CI in the numerical receipt. No provider
request was made. Fresh socket checks returned ECONNREFUSED (61) on all three
ports. The exact-environment-value grep scan again checked 283 files with
0 matches. The original numerical receipt, corpus, gold, and product code
remain unchanged; this addendum records the extra read-only verification.
