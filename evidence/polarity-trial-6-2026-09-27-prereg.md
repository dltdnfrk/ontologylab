# Preregistered sixth polarity trial - 2026-09-27

Understood as: execute approved todo 35, measuring exactly three runs of the
merged todo-33/34 product against frozen aligned gold without tuning after results.
This document and the five copied helpers must be committed before any model call.
After that commit only evidence may change; this preregistration and helpers freeze.

## Frozen inputs

Work root: /Users/hyunjun/Documents/MUNI/ontologylab-wt/w10-t35
Branch: completion/w10-t35. Base: 7fa01945c9fdd9ef68d5134c21733ec205441d2a.
Origin: https://github.com/dltdnfrk/ontologylab.git. The user explicitly authorized
this worktree even though the container registry does not yet list it.
Physical cwd, Git root, branch and origin were checked; the starting tree was clean.

| File | SHA-256 |
| --- | --- |
| tests/gold/agrochem-polarity/sources/full/PMC11298438.txt | 4fe0e19bc80d2cb3f388deebc38f02f20e5e1d1392db60fd50d1fbfd4ab385d9 |
| tests/gold/agrochem-polarity/sources/full/PMC12546283.txt | be7923ca6e58a248ff2cb1476cfd719dd513a3c3df152e7ab821fe02ea90c099 |
| tests/gold/agrochem-polarity/sources/full/PMC12563837.txt | 8d45778ceeb648ff318a7a0e6d1112f836e4da13cca76739e89acf300e96ed80 |
| tests/gold/agrochem-polarity/sources/full/PMC12632097.txt | 427633460b64db0d1a455098ea4f6eb21b91b0bab2f8ea5a36ec29ace7321490 |
| tests/gold/agrochem-polarity/sources/full/PMC12713700.txt | 9a876e8c7db10ed125a803962ba53e5371d9793f7371cdf35d2cf0ae3b1e99d9 |
| tests/gold/agrochem-polarity/gold-aligned-qualified.json | e452fc84003f719666f969383e61cbb29b0c7e94e88ff4fa36a1f7ea3f2aaaa8 |
| tests/gold/agrochem-polarity/gold-aligned.json | ddec4dc1478ddd34c9e7d170ab556094c757739fdd074c216c1b5e6c4dba6d5e |
| tests/gold/agrochem-polarity/gold-qualified-normalized.json | ad02a4ec7481bd4737237e6bf774bd9a8718e9804df2a24aaa788f0eb0adf7bf |
| tests/gold/agrochem-polarity/gold-fulltext.json | cf7ea33f227540f201f2142eb7fa640bf08a1edf3cb039528c3b4828796f4f23 |
| ontologylab/extractor.py | 83f1dd84e30ff6188a7d6cd5b69b6a301688c531107643daa0913cec7f26ccb8 |
| ontologylab/polarity_eval.py | 91a140b358228873169307ef2ba26514f18a7305ca8b8aaa21c73e975e432e21 |
| ontologylab/qualified_polarity_eval.py | 68bd707c9e623af03594a0dced88c702079caccf4b2c93a031c7aafdcaf66a46 |
| ontologylab/statement_qualifiers.py | 13a57e33b0ab16ec5f2e426b03d2d42aac94cff408eb97aae62fdfd08f47a223 |
| evidence/polarity6_driver.py | 2c3d4fd7d3039c19372ebdd6bfcecfbdc9e55b8daa6fc2f24fc373eadc21b612 |
| evidence/polarity6_export.py | 1b7975ff0f034135da08e0a8cb2a373cac3083e359b1a40b0f477b88c98f941e |
| evidence/polarity6_misses.py | 53b9b492ee4db678a28f7260f0204492aa3a2a680ddf9e72640a81ec2aaf85dc |
| evidence/polarity6_score.py | 84d0e50eabcbed56c0bcafe850fe28bcb260f7557ea369e683ccd37dcdc2dbdd |
| evidence/polarity6_verify.py | 4b4adc913c4d2769a88dd563fd616a9d72e017496489baa358e8bff46783f3a7 |

All four gold validators passed: five papers, 34 exact full-body spans each.
Aligned gold: 17 supports, 17 no_effect, zero refutes; historical gold:
17 supports, 12 no_effect, five refutes. Undefined refutes recall stays null.
Gold labels never enter extraction prompts. Full bodies are ingested in filename order.

## Procedure and effective settings

Identical to trial 5: exactly three concurrent runs, one extraction POST each,
no replacements, resumes, extra runs or quality-driven retries:
- /private/tmp/ol-polarity6-20260927T125639Z-r1
- /private/tmp/ol-polarity6-20260927T125639Z-r2
- /private/tmp/ol-polarity6-20260927T125639Z-r3

- Engine api:gemini; model gemini-3.6-flash; schema agrochem-v2.
- PROMPT_VERSION read and imported from code: extract-v9. Temperature 0.0; seed 7.
- Explicit max_engine_calls=60 per run, charging both passes and every retry.
  Product-default fields are omitted: time_budget=null/automatic,
  max_transport_retries=2, statement_completion=true.
- Automatic budget: 21 chunks, min((2+2+1)*21,60)=60 slots,
  300 seconds/request with 10% reserve plus 8 seconds backoff reserve:
  20,280 seconds plus setup elapsed. Record actual provenance values.
- First pass allows one parse retry and two transient transport retries;
  backoff 1/2 seconds, Retry-After capped at eight seconds. Completion makes
  exactly one optional request per eligible chunk, no completion retries.
  It reserves four first-pass request slots per remaining chunk and the
  corresponding time; enabled does not imply it runs on every chunk.
- A single separate provider-test request precedes extraction. Export
  ONTOLOGYLAB_PROVIDER_GEMINI_1BDF3AFBB89F from GOOGLE_API_KEY only inside
  the shell, without printing or persisting its value or using a keychain.
- Reuse the trial-5 driver, changing only paths. It owns and awaits all servers,
  subscribes to SSE before POST, and obtains status on SSE events in a bounded
  loop. Bounds: readiness 45 seconds, HTTP 30, preflight 320, observation
  14,220, shutdown 30. The observer is shorter than maximum product budget;
  report a shortfall if reached and never replace the run. The foreground
  driver is supervised through the host monitor, with no shell backgrounding.
- Never access port 8799, PIDs 87584/3284, launchd or Application Support.
  Use isolated dynamic loopback ports, stores, provider and pack roots.
  Each run must collect five fulltext/extractable documents through HTTP.
  No eligibility edits or human approvals. Stop and await all owned servers,
  independently prove PID absence and closed ports, delete nothing.

## Binding gates and statistics (unchanged)

| Gate | PASS requirement |
| --- | --- |
| G1 | At least 95% of planned chunks successfully parsed |
| G2 | Polarity on at least 90% of schema-valid claim relation rows |
| G3 | Matched polarity accuracy >=0.80 AND no_effect+refutes recall >=0.70 AND supports-when-gold-no_effect flip <=0.15 |
| G4 | Zero observed supports/no_effect same-triple collapses; distinct IDs coexist in find_contradictions(include_proposed=True) |

PRIMARY: qualified scorer, gold-aligned-qualified.json.
SECONDARY: legacy scorer, gold-aligned.json.
TRIAL-5 COMPARABLE: qualified scorer on gold-qualified-normalized.json,
and legacy scorer on gold-fulltext.json. Do not change matching rules or gold.

Unchanged _rate: 2,000 seeded case-bootstrap resamples, seed 7, 95% percentile
intervals. Report all four gates per run and pooled. Pool concatenated binary
outcomes, not averaged rates or merged graphs. Decisions use point estimates;
undefined rates/intervals remain null. G4 is an observed count, no CI.
G1 uses durable extraction_chunks; separately report success/attempted/expected
coverage over 63 chunks, 21/run, paper counts 4/4/4/5/4. Transport/persistence
failures are not parse failures. G4 has persisted-row plus insertion-contract
scope, not unrecorded raw-response replay.

Outcome VERIFIED only if all four pooled PRIMARY gates pass; FAILED if chunks
returned and any primary gate fails; BLOCKED if missing key, failed preflight,
or zero returned chunks prevents gate evaluation. Only VERIFIED meets IS-1.
Secondary or comparable scores cannot establish VERIFIED.

## Evidence and analysis

Export every persisted edge, node, alias, citation, original polarity/qualifier,
span and extraction row to evidence/polarity-trial-6-2026-09-27-edges.json before
scoring. Correct only the copied exporter's literal envelope trial=4 to trial=6.
Add pass annotations separately from unchanged table rows where provenance
supports them; unavailable attribution remains explicit null, never guessed.
The product logs request pass but does not persist the successful proposal-to-pass
map. If merged rows cannot be assigned, report identified counts and bounds for
completion contribution rather than claiming a causal or exact first-only replay.
Replay all four scorers from this durable export and compare with store results.

Write evidence/polarity-trial-6-2026-09-27.md and .json, and the requested artifact
/Users/hyunjun/Documents/MUNI/ontologylab/.omo/evidence/task-35-ontologylab-completion.md.
Report chunk coverage; first/completion requests and statements where attributable;
completion match contribution (or explicit identification limits); retries;
status/provenance agreement; rejected proposals; diagnostic miss categories;
comparisons to trials 3-5 and todo-33 offline qualified 12/51, legacy 17/51.
Miss categories never change matches; wrong matched polarity stays separate.

Exact-key secret scan via grep -a -F -c -f /dev/stdin -- FILE: key through stdin,
every exit checked, counts only, zero required. Check helper diagnostics, frozen
hashes, database integrity, HTTP receipts and existing focused tests once on a
fresh path. Build/mutation are not applicable: no product behavior is changed.

Same-corpus regression, not an independent holdout. Prior misses informed fixes
and gold adjudication; verifier/designer overlap remains. An independently
adjudicated holdout is the independence fix, outside this trial. Case-bootstrap
ignores within-paper and between-repeat dependence. Do not causally attribute
score changes to one fix or completion, and do not introduce another model run.
