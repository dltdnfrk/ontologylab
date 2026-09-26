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
