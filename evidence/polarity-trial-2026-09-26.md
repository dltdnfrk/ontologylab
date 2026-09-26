# Todo 12: real-paper polarity trial - 2026-09-26

## Outcome: FAILED (G3); IS-1 NOT MET

Understood as: run the frozen task-11 corpus through the prescribed real Gemini provider exactly three times in fresh stores, measure the unchanged gates, and record failure rather than tuning the experiment to pass.

The provider test passed and all 15 chunks completed. The frozen scorer matched **0 of 102 gold triples** across the three repeats. Therefore no_effect+refutes recall is **0/51 = 0%**, below 70%; polarity accuracy and flip rate are undefined because their matched denominators are zero. This is **FAILED**, not BLOCKED: chunks exist and G1 ran. No alias remapping, relation remapping, gold changes, threshold changes, or extra extraction runs were performed.

Binding outcome rule: VERIFIED iff G1-G4 all PASS; FAILED iff G1 ran and at least one gate FAILS, naming those gates; BLOCKED iff the key is absent, provider test fails, or zero chunks return so the gates cannot be evaluated. Only VERIFIED meets IS-1. Todo 12 delivers honest evidence even when FAILED or BLOCKED.

- [ ] Follow-up for F4: resolve G3's exact-triple identity/relation mismatch and establish gold-aligned polarity recall; review corpus coverage before authorizing a new, separately recorded trial. IS-1 remains NOT MET. No implementation or new trial is authorized by this evidence row.

## Boundary and provider preflight

- Physical cwd and Git top-level: `/Users/hyunjun/Documents/MUNI/ontologylab-wt/w4-t12`; branch `completion/w4-t12`; starting HEAD `c6dea1a71149361ba80f5bb1bde985297b256aca`; origin `https://github.com/dltdnfrk/ontologylab.git`. Starting worktree was clean. No rebase; todo 15 is not in this base.
- Product source, gold data, scorer, and binding plan were not edited. No live store, protected port, launchd service, deployment, or release operation was used.
- Provider: id `gemini`, kind `openai`, base URL `https://generativelanguage.googleapis.com/v1beta/openai`, model `gemini-3.6-flash`.
- `dedicated_api_key_env("gemini", base_url)` returned `ONTOLOGYLAB_PROVIDER_GEMINI_1BDF3AFBB89F`. Only this NAME was registered; it was exported from `GOOGLE_API_KEY` within each server/probe shell. No keychain account was configured.
- `python -m ontologylab.main provider test --id gemini --model gemini-3.6-flash --data-dir R1`: exit **0**, provider elapsed **2121 ms**, reply `pong`; outer bounded probe elapsed **2.311 s**. Exactly one provider preflight request; separate from the extraction budgets. Outer timeout 320 s; product request timeout 300 s.
- Initial CLI registration failed before any network request because the bare Python runtime lacked `pydantic`. `uv sync --extra server --extra test` exited 0; registration then exited 0. The worktree virtual environment used **Python 3.12.12**. No extraction was retried for this setup issue.

## Corpus and ingestion

The five supplied `tests/gold/agrochem-polarity/sources/*.txt` files were ingested unchanged, in filename order, using authenticated **POST /api/collect** with `{"files":[absolute source paths]}` on each server. Every response was `ok=true, documents=5, created=5, duplicates=0, failures=[], conflicts=[]`. **POST /api/schema** with `{"preset":"agrochem-v2"}` had first installed active schema id **2** in every store.

Persisted documents have `source_kind=upload`, file URIs to those exact sources, and content hashes equal to the gold source hashes. The product's upload ingestion also created five `document_observations.content_kind=fulltext` rows in each store; no direct SQL eligibility edits were made. This is the user-authorized plain-upload ingestion path on the pre-todo-15 base.

**Coverage qualification:** the gold manifest calls these `body_excerpt`: selected verbatim Results/Discussion passages from full-text articles, not abstracts and not five complete article bodies. The product labels uploads fulltext, but that label does not change the actual corpus coverage. This trial uses exactly the requested files and does not claim whole-paper coverage. The fixture labels were selected before trial outputs, are null/negative-enriched, and were author-of-fixture checked rather than independently expert-adjudicated. Gold labels were never supplied to the extraction prompt.

| Source | Bytes | SHA-256 |
| --- | ---: | --- |
| PMC12632097 | 743 | bd554447c224aba1e20b8a0e2bb484cf93da891e39aa3f41c4f78ba19340acdd |
| PMC12546283 | 2718 | f4058de5cec36a1c1f2d1045075c2d661cdf6fa01d91b6545a90ede0ad8b3be8 |
| PMC12563837 | 1533 | 436d765d666cc633efecc53a061b5e941b3f6c27de733dc5f16d1cd31929b9f2 |
| PMC12713700 | 2431 | e7af2ffe781b53e5d24f013c96716e153ca494f70fe7fbebcb35f968c942b7e5 |
| PMC11298438 | 2318 | 8d4bfc54ea578a01da92c798048b868120be8372bf6cb781a0d2642c6a1fbf88 |

Offline `python -m ontologylab.polarity_eval tests/gold/agrochem-polarity/gold.json` exited 0: **5 papers, 34 relations, 34 exact spans verified**, comprising supports=17, no_effect=12, refutes=5.

## Three independent runs

Each server used its own SQLite store, provider registry, jobs, and packs directory. Runs were concurrent but shared no mutable graph state. Identical job-id strings reflect the product's second-resolution naming; the **(data directory, job id)** pair identifies a run. Per-document extraction run ids below are distinct.

- R1: `/private/tmp/ol-polarity-20260926T144836389Z`
- R2: `/private/tmp/ol-polarity-20260926T144836389Z-r2`
- R3: `/private/tmp/ol-polarity-20260926T144836389Z-r3`

Each real **POST /api/extract** selected all five uploaded document ids and sent `engine=api:gemini, model=gemini-3.6-flash, max_engine_calls=60, time_budget=600, seed=7`. The API has no temperature field in this base: ApiEngine's pinned default is **temperature 0.0**, confirmed in **every persisted extraction_runs.decode_params row and every successful provider-call usage record**. Prompt version was `extract-v3`; JSON mode and parser validation were unchanged.

The driver connected to **GET /api/jobs/stream before POST /api/extract**, then consumed server-sent state changes. Each driver had a **930 s total wait bound**, no fixed sleeps and no polling loop. Each terminal SSE result was subsequently confirmed against the persisted `runs` row. All completed; **zero cancellations, interruptions, resumes, or replacement runs**. Per-run cap includes retries: 5 actual requests each, zero parse retries, total extraction requests **15** plus the one preflight request.

| Repeat | Port | Server PID | Scoped job id | Status | Requests/cap | G1 chunks | G2 claim rows | All current edges | Duration s |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| R1 | 49620 | 55809 | extract-20260926-235329 | complete | 5/60 | 5/5 | 41/41 | 49 | 201.337 |
| R2 | 49621 | 55818 | extract-20260926-235329 | complete | 5/60 | 5/5 | 41/41 | 45 | 211.259 |
| R3 | 49622 | 55824 | extract-20260926-235329 | complete | 5/60 | 5/5 | 41/41 | 52 | 192.579 |

| Repeat | Source | Document id | Extraction run id | Status |
| --- | --- | --- | --- | --- |
| R1 | PMC11298438 | rep-2ae1bfcc4183 | bf30e6904b7a4b7880b390a09424d043 | complete |
| R1 | PMC12546283 | rep-dce0d78dadec | 87961d77f0714596a319be194755f0ec | complete |
| R1 | PMC12563837 | rep-1131dec589e0 | 778c88493b4c4650b995b9968ad3a70d | complete |
| R1 | PMC12632097 | rep-5ba0e09575ec | 70f6828285cc40fbafc0da155dfaaf82 | complete |
| R1 | PMC12713700 | rep-e479d944c9e1 | 934641f0f7df4aa28d0ddd707edec9c0 | complete |
| R2 | PMC11298438 | rep-9756d3025ad0 | 7bf0fd81c6a44974abee412411c126fc | complete |
| R2 | PMC12546283 | rep-bfcb1f3838c9 | 031351fc45de4f45b9f200706cac8033 | complete |
| R2 | PMC12563837 | rep-d05dab6ce997 | bb9f6dfd693c4669a40b6ab719530f2a | complete |
| R2 | PMC12632097 | rep-3dc38eb076c1 | 2e3de76f305e4ca59a0e03495c6b75d7 | complete |
| R2 | PMC12713700 | rep-b98b275bd0e4 | e1e2ff1f19974b72bff17b2187df661a | complete |
| R3 | PMC11298438 | rep-0e2fb3bb5441 | ab077fad18f34fc0a82e95765c2ee445 | complete |
| R3 | PMC12546283 | rep-f2596289f936 | 2950f19a0dcc44ba8290245df3ba0125 | complete |
| R3 | PMC12563837 | rep-5fbe94b08f52 | cc402604c3994423aea20d4c2fc821b3 | complete |
| R3 | PMC12632097 | rep-305a38bcef4a | 05a7856ef0ae450693756a94ab4e9328 | complete |
| R3 | PMC12713700 | rep-b01f7cf4e3d1 | 1cd5c49d9f204de98e1182488df69021 | complete |

## Gates from persisted numbers

| Gate | Binding threshold | Pooled measurement | Verdict |
| --- | --- | --- | --- |
| G1 | Parse success >=95% of chunks | 15 succeeded / 15 planned chunks = **100%**; 15 counted requests, 0 parse rejections, 0 engine errors | PASS |
| G2 | Polarity set on >=90% of schema-valid claim relations | 123 / 123 current schema-valid claim edge rows = **100%**; supports=89, no_effect=23, refutes=11, omitted=0 | PASS |
| G3 | Accuracy >=0.80 AND no_effect+refutes recall >=0.70 AND flip rate <=0.15 | Matched gold 0/102; accuracy undefined (0/0); combined recall **0/51=0%**; flip rate undefined (0/0) | **FAIL** |
| G4 | Zero supports/no_effect same-triple merges; contradictory rows coexist | **0 observed cross-polarity collapses**, **2 coexisting supports/no_effect pairs**, 4 distinct edge ids in R2 | PASS |

G1 uses `extraction_chunks` statuses and `extraction_runs`, reconciled with `provenance.jsonl` engine-call events and `status.json.engine_calls`, not console success text. All five chunks in each run succeeded on their first attempt. G2 counts current proposed/verified edge rows whose active schema relation declares a polarity qualifier; it excludes the **23 non-claim rows** whose unspecified polarity is legitimate. Deduplicated mentions are not counted as extra graph rows. No edge was approved: verified-edge count is zero in all three stores.

### G3 scorer and bootstrap

`score_polarity(read_only_connection, gold_path)` was called separately on each fresh store. Rates were pooled by summing their recorded numerators/denominators, not by merging graphs or averaging rates. The existing `_rate` helper then bootstrapped the concatenated binary outcomes: **2,000 resamples, seed 7, confidence 95%, individual-outcome sampling**. Missing triples count as recall misses. Undefined denominators remain null and never become perfect accuracy or zero flip rate.

| Metric | R1 | R2 | R3 | Pooled | Pooled bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: | --- |
| Matched gold relations | 0/34 | 0/34 | 0/34 | 0/102 | Not a rate gate |
| Polarity accuracy | 0/0 | 0/0 | 0/0 | Undefined | null |
| no_effect recall | 0/12 | 0/12 | 0/12 | 0/36 = 0% | [0, 0] |
| refutes recall | 0/5 | 0/5 | 0/5 | 0/15 = 0% | [0, 0] |
| Combined no_effect+refutes recall | 0/17 | 0/17 | 0/17 | 0/51 = 0% | [0, 0] |
| Supports-when-gold-no_effect flip rate | 0/0 | 0/0 | 0/0 | Undefined | null |

Every cell in the supports/refutes/no_effect/omitted confusion matrices is **0**, because no exact gold triple matched. The scorer reports 34 missing gold relations in each run. Found/spurious four-tuples are 49/49, 45/45, and 52/52; four-tuple F1 is 0 in every run. These are exact-match scores, not a claim that every extracted statement is semantically false. Within-paper and between-repeat dependence are not modeled by these case-bootstrap intervals; [0,0] is the empirical all-miss interval, not proof that future recall must be zero.

An independent parameterized SQL lookup of each gold triple reproduced **0/34 exact matches in each database**, and all three `PRAGMA integrity_check` calls returned `ok`. Examples in R1 explain the mismatch without changing the score: gold `Poa annua` vs persisted `P. annua`; gold `Botrytis cinerea` vs `B. cinerea`; gold `R blackgrass population` vs `blackgrass`; gold `inhibits` isolate-specific claims vs persisted `controls`. The mandated scorer normalizes punctuation/case but neither expands abbreviations nor remaps relations. No post-hoc relaxed score was substituted.

### G4 coexistence evidence

`find_contradictions(conn, include_proposed=True, limit=10000)` returned totals R1=0, R2=2, R3=0. R2's two same-triple supports/no_effect pairs have distinct row ids:

| Triple | supports edge id | no_effect edge id |
| --- | --- | --- |
| cyantraniliprole / controls / D. suzukii | 0d705b2fa3da4019bf88fcf5669ddc34 | 2110232c53c5453285943d4592456035 |
| deltamethrin / controls / D. suzukii | 85652999db4d41b9badecd0f04b4ccf4 | d3f7e28e4acc4661910fa1a35e48055f |

The chunk receipts record general edge merges R1=0, R2=1, R3=0. This general counter is not a count of cross-polarity merges: the insertion lookup includes exact polarity in its identity predicate (`ontologylab/kgstore_proposed.py:188-199`). The observed contradictory pairs remain four separate rows, and the existing opposite-polarity/same-polarity identity tests pass. G4 reports the prescribed store/API observation, not an exhaustive replay of raw model outputs: raw provider reply bodies are not retained by this extraction path, and no hidden input-level merge audit is claimed.

## Required claims/stages API counts

These are from **GET /api/claims/stages?include_proposed=true**, independently matched to `GROUP BY relation_type, json_extract(qualifiers_json,'$.polarity')` over current persisted proposed/verified edges. Every API relation/polarity count equals the corresponding SQLite count in all three runs. Complete JSON responses are retained in the numerical receipt.

| Stage key | R1 | R2 | R3 |
| --- | ---: | ---: | ---: |
| threat | 1 | 1 | 3 |
| control | 31 | 31 | 29 |
| mechanism | 0 | 0 | 0 |
| resistance | 9 | 9 | 11 |
| application | 4 | 0 | 4 |
| trial | 4 | 4 | 5 |
| safety | 0 | 0 | 0 |
| diagnostics | 0 | 0 | 0 |
| interpretation | 0 | 0 | 0 |
| other | 0 | 0 | 0 |
| **Total** | **49** | **45** | **52** |

| Nonzero relation | R1 polarity counts | R2 polarity counts | R3 polarity counts |
| --- | --- | --- | --- |
| applied_at_rate | unspecified=3 | 0 | unspecified=3 |
| applied_by | unspecified=1 | 0 | unspecified=1 |
| controls | no_effect=8, supports=19 | no_effect=7, refutes=2, supports=21 | no_effect=5, refutes=2, supports=19 |
| damages | supports=1 | supports=1 | supports=1 |
| evaluated_in | unspecified=4 | unspecified=4 | unspecified=5 |
| occurs_in | 0 | 0 | unspecified=2 |
| resistant_to | refutes=2, supports=7 | refutes=2, supports=7 | refutes=2, supports=9 |
| synergizes_with | no_effect=1, refutes=1, supports=2 | no_effect=1 | no_effect=1, supports=2 |

## Verification and retained receipts

- Provider test: exit 0, one real request; gold validator: exit 0, all 34 spans valid.
- `.venv/bin/python -m pytest -v -p no:cacheprovider --basetemp=/private/tmp/ol-polarity-20260926T144836389Z/pytest-scorer --junitxml=/private/tmp/ol-polarity-20260926T144836389Z/scorer-tests.xml tests/test_polarity_eval.py tests/test_polarity_identity.py`: **exit 0; 32 passed, 0 failed, 0 errors, 0 skipped** in 1.71 s. The basetemp path did not exist before this invocation. Tests were run once; no test or product bytes changed.
- Actual HTTP surface: three schema installs, three five-document ingests, three bounded extraction requests and SSE completions, and three claims/stages reads. Scorer, direct SQL, stage reconciliation, and database integrity checks passed as accounting checks; the measured product-quality G3 gate failed.
- Scratch drivers were parsed under the actual Python 3.12.12 runtime, which resolves this worktree's package and supports `asyncio.timeout`. The temp-file LSP used an incompatible context (reported missing package imports and missing `asyncio.timeout`); JSON LSP was unavailable because `biome` is not installed. Runtime syntax/JSON checks were used instead; no application build or mutation test was needed for an evidence-only commit.
- Scratch drivers: `/private/tmp/ol-polarity-20260926T144836389Z/trial_driver.py` (SSE-before-POST, cancellation on timeout) and `/private/tmp/ol-polarity-20260926T144836389Z/score_trial.py` (read-only accounting). Numerical receipt: `/private/tmp/ol-polarity-20260926T144836389Z/trial-receipt.json`; SHA-256 **a30bfa48cc3a0f4f3b8cb066f2845a0dac821628d22f042d23aa19a34401f47f**. It includes extraction run/chunk rows, scorer outputs, provenance hashes, full API stage responses, and cleanup observations.
- Per-run source records: `R*/kg.sqlite` and `R*/jobs/extract-20260926-235329/{provenance.jsonl,status.json}`. Database hashes below were taken after server shutdown. The committed corpus and scorer are recoverable from starting HEAD.

| Repeat | Closed kg.sqlite SHA-256 | Extraction provenance.jsonl SHA-256 |
| --- | --- | --- |
| R1 | 148a719dd2362756b4370097a5cae59c7e83bb387946d6535024e21a2c191696 | 9c6d77c54dfbdfa7dc9997120e34fe1fb63b1e4e95086c2db79573065093648e |
| R2 | 21bad5769320f792b05f6cd5b72f6f6b5817d1328394b34f530c47f86e4a8ab8 | b8ec5e31f2c5b7635298ee7b0118f244327716a32a35f3e7e9b42e0454bcbfa7 |
| R3 | 1a5ce7a60458bfce7b7886ef194229ed4d3ebdc27c6fa27118d5c403bcc1137e | 26e188a06abf8677712e11ebdc955a70a894186e16563060da2f636ab3596f4c |

## Cleanup and limitations

Sent SIGTERM only to the ownership-checked server PIDs **55809, 55818, 55824**. All emitted their finished-server event. Their wrappers **55801, 55805, 55817** also exited; `ps` over all six returned no rows (exit 1). Monitor exit 241 reflects the deliberately terminated server's signal result; the extraction drivers had already exited 0. TCP connection checks to **127.0.0.1:49620, :49621, :49622** each returned **ECONNREFUSED**. No trial server remains.

No cleanup deletion was issued. Retained temp roots: R1, R2, R3 as listed above; the test scratch subtree `/private/tmp/ol-polarity-20260926T144836389Z/pytest-scorer`, its XML receipt, the two drivers, stores, raw source copies, and job receipts remain. A worktree-local ignored `.venv` was provisioned and retained. Before saving the final numerical receipt, all **132 existing files** under the three trial roots were scanned for the exact environment credential: **0 matches**. Captured provider/server/scorer text was scrubbed before delivery or saving; evidence and numerical receipt were separately checked before writing. Only the environment variable name appears in artifacts.

Residual limitations: G3 is unmet; whole-paper coverage is not established by body excerpts; fixture labels lack independent expert adjudication; exact-name/relation scoring confounds polarity with identity alignment; outcome-level bootstrap does not model clustered claims. G4's observation is limited to persisted contradictory rows and the tested polarity-aware insertion contract. None of these limitations was hidden by lowering a threshold or rerunning the trial.

## Todo 16 addendum: exact store-identity re-score

**Outcome remains FAILED (G3); IS-1 remains NOT MET.** The original zero
was partly a scorer defect: both evaluators already use `normalize_name`,
but `polarity_eval` ignored `node_aliases`. The store resolves a canonical
name first, then a unique recorded alias within the same schema and entity
type. The corrected polarity scorer follows that rule without calling the
store resolver's merge-queue write path. Ambiguous aliases do not match;
alias spellings do not create extra predictions or hide conflicting polarity.
Two gold triples resolving to one extracted identity are refused rather than
awarded duplicate credit.

Only recorded aliases were added to matching. The gold file, its labels,
source bytes, thresholds, and bootstrap implementation are unchanged. No
gold-declared aliases were added: an unrecorded abbreviation or a loss of
population, combination, or oviposition scope is not silently made equivalent.
No model, provider, ingestion, extraction, or server was run for this addendum.

### All 102 original misses

The [per-instance table](polarity-trial-2026-09-26-misses.md) contains all
34 gold relations in each of R1/R2/R3. It records exact-identity neighbors,
source-linked diagnostic candidates, and whether the corrected scorer
actually credits a match. The [machine receipt](polarity-trial-2026-09-26-rescore.json)
contains full edge IDs, SQL results, per-run scores/CIs, and file hashes.
Diagnostic examples are not semantic matching rules.

| Original primary miss | R1 | R2 | R3 | Total |
| --- | ---: | ---: | ---: | ---: |
| Entity surface mismatch | 23 | 24 | 22 | 69 |
| Relation-type mismatch | 7 | 7 | 7 | 21 |
| Direction mismatch | 0 | 0 | 0 | 0 |
| Truly absent | 4 | 3 | 5 | 12 |
| Total | 34 | 34 | 34 | 102 |

The categories use the table's explicit precedence and retain secondary
causes. All 21 relation-type cases also lose endpoint detail. Of 69 surface
cases, 17 drop the R-population scope; surface difference alone is not proof
of equivalence. Case/punctuation normalization was already correct.

Seven original misses are recovered, all in R1: PB / controls / Drosophila
suzukii, and the six Botrytis cinerea / resistant_to gold relations.
R1 recorded the two full species names as aliases; R2/R3 did not.
The remaining **95 misses** comprise **62 surface, 21 relation-type,
0 direction, and 12 absent**. Six of the seven matched predictions have the
gold polarity; iprodione is predicted supports against gold refutes and
remains an error. No label was chosen to make that prediction correct.

### Corrected G3 under the unchanged thresholds

| Metric | R1 | R2 | R3 | Pooled | Pooled bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: | --- |
| Matched gold relations | 7/34 | 0/34 | 0/34 | 7/102 | Not a gate |
| Polarity accuracy | 6/7 | 0/0 | 0/0 | 0.857143 | [0.5714, 1.0000] |
| no_effect recall | 1/12 | 0/12 | 0/12 | 1/36 = 0.027778 | [0.0000, 0.0833] |
| refutes recall | 2/5 | 0/5 | 0/5 | 2/15 = 0.133333 | [0.0000, 0.3333] |
| Combined no_effect+refutes recall | 3/17 | 0/17 | 0/17 | 3/51 = 0.058824 | [0.0000, 0.1176] |
| Supports-when-gold-no_effect flip rate | 0/1 | 0/0 | 0/0 | 0.000000 | [0.0000, 0.0000] |

Zero-denominator per-run accuracy and flip rates remain undefined, not zero
or perfect. Pooling concatenates binary outcomes from the three persisted
stores; the unchanged 2,000-resample, seed-7 case bootstrap produces the CIs.
Claims within a paper and repeat are correlated; these are not clustered
or population-level intervals. In particular, a zero flip estimate from one
matched no_effect relation is weak evidence, not proof of future safety.

| Gold class | Gold instances | Matched | Correct polarity | Missing |
| --- | ---: | ---: | ---: | ---: |
| supports | 51 | 3 | 3 | 48 |
| no_effect | 36 | 1 | 1 | 35 |
| refutes | 15 | 3 | 2 | 12 |

The pooled confusion matrix has supports->supports=3,
no_effect->no_effect=1, refutes->refutes=2, refutes->supports=1;
all other cells are zero. Found four-tuples stay 49/45/52; spurious tuples
become 43/45/52. Four-tuple F1 is 0.144578/0/0 (per-run CIs in the receipt).

G3 requires accuracy >=0.80 **AND** combined recall >=0.70 **AND** flip
rate <=0.15. Accuracy and flip clear their point-estimate thresholds, but
**3/51 recall fails 0.70**. G1=15/15, G2=123/123, and G4=0 observed
cross-polarity collapses retain todo 12's PASS findings; this re-score does
not claim a new trial or a new G4 raw-output audit. Because G1 ran and G3
fails, the binding outcome is **FAILED**, never VERIFIED or BLOCKED.

### Read-only and misleading-output checks

Connections used SQLite URI `mode=ro&immutable=1`, after confirming all
three WALs were empty. This also avoids shared-memory lock writes.
All three `PRAGMA integrity_check` results were `ok`.

```sql
SELECT count(*) FROM documents;
SELECT count(*) FROM nodes;
SELECT count(*) FROM node_aliases;
SELECT relation_type, json_extract(qualifiers_json, '$.polarity'), count(*)
FROM edges
WHERE status IN ('proposed', 'verified') AND invalidated_ts IS NULL
GROUP BY relation_type, json_extract(qualifiers_json, '$.polarity');
```

| Persisted SQL count | R1 | R2 | R3 |
| --- | ---: | ---: | ---: |
| Documents | 5 | 5 | 5 |
| Nodes | 63 | 55 | 65 |
| Recorded aliases | 7 | 1 | 2 |
| Current edges | 49 | 45 | 52 |
| Polarity-bearing claim edges | 41 | 41 | 41 |
| Extraction runs / chunks | 5/5 | 5/5 | 5/5 |

Independent parameterized SQL entity resolution reproduced corrected matches
7/0/0; canonical-only SQL reproduced the original 0/0/0. These observations
come from stored rows, not console success messages. Persisted run IDs and
document hashes in the receipt agree with todo 12's stores and frozen corpus.

| Database | SHA-256 before = after |
| --- | --- |
| R1/kg.sqlite | 148a719dd2362756b4370097a5cae59c7e83bb387946d6535024e21a2c191696 |
| R2/kg.sqlite | 21bad5769320f792b05f6cd5b72f6f6b5817d1328394b34f530c47f86e4a8ab8 |
| R3/kg.sqlite | 1a5ce7a60458bfce7b7886ef194229ed4d3ebdc27c6fa27118d5c403bcc1137e |

These equal todo 12's post-shutdown hashes. WAL and SHM hashes also match
before/after. All 188 enumerated retained regular-file paths were unchanged;
no file was added or removed in the trial roots. Gold SHA-256 remains
`c899bc553773f2ee4986d0d808165c7791ad7e5cd9c8ba8ff7a9187458a55203`.

The requested `uv run --all-extras pytest --basetemp=/private/tmp/t16-$RANDOM-$RANDOM tests/test_polarity_eval.py > /private/tmp/t16.log 2>&1; echo EXIT=$?`
returned **EXIT=0, 38 passed**. Before repair, the new regressions exposed
6 failures. A deliberate prefix-matching mutation credited the wrong alias
Treatment 50 as Treatment 5: **2 failures**, including the wrong-alias case;
exact matching was restored before the final passing run.

## Todo 18 addendum: document-local abbreviation replay

**Outcome remains FAILED (G3); IS-1 remains NOT MET.** The resolver is
implemented, but the retained extraction inputs do not contain the full
binomials needed to expand their abbreviated organism proposals. The
36 unrecorded-abbreviation misses in todo 16 are not 36 resolvable cases
under the document-local rule: these inputs are selected body excerpts,
not the full papers. No missing introduction, title, gold name, model
alias, or external document was supplied to the resolver.

The replay found four eligible abbreviated organism nodes per run:
`B. cinerea`, `D. suzukii`, `M. anisopliae 35.79`, and `P. annua`.
All **12** keep their names and gain `abbreviation_unresolved="absent"`.
There are **zero expansions and zero new aliases**. `B. velezensis QST 713`
is typed ActiveIngredient or Product in these stores, so it is untouched.
R1's pre-existing full-name aliases still supply its seven scorer matches;
they are not document-text evidence for an expansion.

### Implementation and replay method

`species_abbreviation.py` is separate from `normalization.py` because the
latter owns authoritative registry normalization. The new resolver reads
only the supplied raw document, uses case-sensitive whole-word matching,
counts distinct genera rather than mentions, preserves the proposal suffix
and source span, and appends the original surface as an alias on resolution.
It runs before registry/measurement normalization in `run_extraction`.
The organism scope is Crop, Pathogen, Pest, Weed, and NonTargetOrganism.
Method extraction has no equivalent seam: `method_extract.py` validates
StatementOccurrence records and imports them through MethodStore, not
ProposedEntity/insert_proposed.

The first replay exposed an integration gap missed by the happy-path test:
the store rejected the new unresolved property. Two added `run_extraction`
regressions reproduced it for absence and ambiguity. The necessary one-line
addition to `kgstore_validation.py`'s existing normalization-property
allowlist admits the string without altering installed schemas. After the
continuation instruction, that dependency fix was included. No bypass or
runtime monkeypatch was used.

1. Hash all 188 regular files in the three retained trial roots. Copy each
   entire directory to `/private/tmp/t18-replay-1`, `-2`, and `-3`; verify
   that the copies initially match every original file hash.
2. Open each copied `kg.sqlite` read-only with immutable semantics. All
   source WALs are empty. Reconstruct proposals from persisted node/edge
   snapshots, ordered by `created_ts, rowid` within document order
   `fetched_ts, rowid`. Preserve IDs, names, aliases, properties, qualifiers,
   confidence, spans, schema, and extractor stream fields.
3. Assert that all rows are proposed/extracted/current in the active
   schema, every edge's endpoints belong to its document, no node citation
   spans multiple documents, and each document has one extractor stream.
   Obtain text through the copied store's `document_raw_text` and verify
   its content hash. Apply only the new resolver; no model or registry
   normalization is rerun.
4. In each copy, create a fresh graph projection `replayed-v2.sqlite`,
   install the same schema, and copy document metadata. Insert each
   document's proposals with the real `KGStore.insert_proposed`. This uses
   `_resolve_node`, `normalize_name`, `_merge_mention`, `_add_alias`, and
   the returned ID map for relation endpoints; it does not hand-edit keys
   or feed expected matches to the scorer. The original copied `kg.sqlite`
   stays unchanged. The failed R1 `replayed.sqlite` is retained separately.
5. Commit, close, and reopen each projection read-only, then call
   `score_polarity` on those persisted rows. Compare all identity/stream
   fields and edge properties/qualifiers with the copied input; the only
   changed semantic fields are the 12 unresolved annotations. Integrity
   and foreign-key checks pass. Scores equal the corrected baseline.

This is a replay of **persisted proposal snapshots**, not unavailable raw
provider replies: earlier duplicate mentions cannot be reconstructed.
Insertion regenerates timestamps and citations; historical extraction
receipts are retained in the copied source store, not fabricated in the
new graph projection. Those differences do not enter G3.

### G3 from the reopened replay projections

| Metric | R1 | R2 | R3 | Pooled | Pooled bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: | --- |
| Matched gold relations | 7/34 | 0/34 | 0/34 | 7/102 | Not a rate gate |
| Polarity accuracy | 6/7 | 0/0 | 0/0 | 0.857143 | [0.5714, 1.0000] |
| no_effect recall | 1/12 | 0/12 | 0/12 | 1/36 = 0.027778 | [0.0000, 0.0833] |
| refutes recall | 2/5 | 0/5 | 0/5 | 2/15 = 0.133333 | [0.0000, 0.3333] |
| Combined no_effect+refutes recall | 3/17 | 0/17 | 0/17 | 3/51 = 0.058824 | [0.0000, 0.1176] |
| Supports-when-gold-no_effect flip rate | 0/1 | 0/0 | 0/0 | 0.000000 | [0.0000, 0.0000] |

R1's per-run CIs are accuracy [0.5714, 1], no_effect recall [0, 0.25],
refutes recall [0, 0.8], combined recall [0, 0.3529], and flip [0, 0].
R2/R3 recall CIs are [0, 0]; their accuracy and flip estimates/CIs remain
undefined. Pooling sums counts and uses the unchanged `_rate` bootstrap:
2,000 resamples, seed 7, individual outcomes. It does not model dependence
within papers or repeats. Fixture labels still lack independent expert
adjudication; this post-diagnosis replay is not a new holdout experiment.

G3 still requires accuracy >=0.80 AND combined recall >=0.70 AND flip
<=0.15. **3/51 recall fails**, so the unchanged outcome rule gives FAILED.
G1/G2/G4 retain the original trial verdicts; no new model trial or raw-output
merge audit is claimed. Replay documents/nodes/aliases/edges are
5/63/7/49, 5/55/1/45, and 5/65/2/52. Every relation/polarity count is
unchanged, including R2's distinct contradictory rows.

### Verification and immutable originals

The final requested seven-module pytest command returned **EXIT=0,
131 passed**. The store-validation module adds **10 passed**. The unchanged
baseline had 41 passing tests. Disabling the ambiguity check made its test
fail; restoration was byte-identical and the test passed again. Both
unresolved-persistence regressions failed before the allowlist fix and pass
in the final suite. Worktree-local type checking is clean for the resolver,
extractor, and tests. The validator retains three inherited `conn` mixin
diagnostics, reproduced against the exact pre-change file.

All **188 original files** remain SHA-identical, including WAL/SHM; no file
was added or removed in the retained trial roots:

| Original database | SHA-256 before = after |
| --- | --- |
| R1/kg.sqlite | 148a719dd2362756b4370097a5cae59c7e83bb387946d6535024e21a2c191696 |
| R2/kg.sqlite | 21bad5769320f792b05f6cd5b72f6f6b5817d1328394b34f530c47f86e4a8ab8 |
| R3/kg.sqlite | 1a5ce7a60458bfce7b7886ef194229ed4d3ebdc27c6fa27118d5c403bcc1137e |

Gold SHA-256 remains
`c899bc553773f2ee4986d0d808165c7791ad7e5cd9c8ba8ff7a9187458a55203`.
Replay driver: `/private/tmp/t18-replay-1/replay.py`, SHA-256
`5d29767d6784ef80c44d190c482607c3e3c1563671fa574897e252170031c83d`.
Full numerical receipt: `/private/tmp/t18-replay-1/replay-v2-receipt.json`,
SHA-256 `d74ceef5d32ef70131f7d8be89abba0fcf23162c543549c0f64d1917e7b6ca21`.
The task artifact `.omo/evidence/task-18-ontologylab-completion.txt`
records commands, adversarial checks, and the retained-temp inventory.
No deletion, model call, source enrichment, gold/threshold/scorer change,
population-qualifier change, or live-store/server access was performed.
