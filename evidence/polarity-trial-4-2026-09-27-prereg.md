# Preregistered fourth polarity trial - 2026-09-27

Understood as: measure exactly three authorized runs on the fixed tree, not
tune the corpus, gold, extractor, scorer, thresholds, or runs to obtain a pass.
This preregistration and driver are committed before any provider/model call.
Afterward only evidence may change; this preregistration and driver stay frozen.

## Frozen tree and inputs

Work root: `/Users/hyunjun/Documents/MUNI/ontologylab-wt/w8-t29`.
Branch: `completion/w8-t29`.
Code commit: `ca93d16c58791b4125fa9f44c4aeb2071eac35f5`.
Origin: `https://github.com/dltdnfrk/ontologylab.git`.
Product tree: `775f94ce78b1832db62ff27b4170d530f697cb54`.
Gold tree: `b2c6fd816c7b264354f469b75efb236db8bad6f7`.
The user explicitly authorized this worktree and todo on 2026-09-27.

Corpus paths are relative to `tests/gold/agrochem-polarity/sources/full/`,
ingested in filename order through the same HTTP collection surface as trial 2.

| File | SHA-256 |
| --- | --- |
| PMC11298438.txt | 4fe0e19bc80d2cb3f388deebc38f02f20e5e1d1392db60fd50d1fbfd4ab385d9 |
| PMC12546283.txt | be7923ca6e58a248ff2cb1476cfd719dd513a3c3df152e7ab821fe02ea90c099 |
| PMC12563837.txt | 8d45778ceeb648ff318a7a0e6d1112f836e4da13cca76739e89acf300e96ed80 |
| PMC12632097.txt | 427633460b64db0d1a455098ea4f6eb21b91b0bab2f8ea5a36ec29ace7321490 |
| PMC12713700.txt | 9a876e8c7db10ed125a803962ba53e5371d9793f7371cdf35d2cf0ae3b1e99d9 |

Secondary gold: `tests/gold/agrochem-polarity/gold-fulltext.json`;
SHA-256 `cf7ea33f227540f201f2142eb7fa640bf08a1edf3cb039528c3b4828796f4f23`.
The validator verified all 34 spans in five papers: 17 supports, 12 no_effect,
5 refutes. Labels never enter extraction prompts.

| Frozen implementation | SHA-256 |
| --- | --- |
| ontologylab/extractor.py | 1aa3c4a993842b51e944d033aaaca4f5e48bb12ed48ececf78b84fc9231bdb77 |
| ontologylab/polarity_eval.py | 4d9742f343ed2477e64271a3851e473b0e2f67b1e767623ccdb8123e7eea5ba1 |
| evidence/polarity4_driver.py | 006b039099a7c798597adf6df023a169b57e215950e37216f0c24969a647a70b |

## Procedure and limits

- Exactly three extraction runs, concurrent as in trial 2, without replacements,
  resumes, or quality-driven retries, in fresh directories:
  `/private/tmp/ol-polarity4-20260927T064204Z-r1`,
  `/private/tmp/ol-polarity4-20260927T064204Z-r2`,
  `/private/tmp/ol-polarity4-20260927T064204Z-r3`.
- Engine `api:gemini`; model `gemini-3.6-flash`; code-read `PROMPT_VERSION`
  `extract-v7`; schema `agrochem-v2`; temperature 0.0; seed 7.
- Register provider `gemini`, kind `openai`, base URL
  `https://generativelanguage.googleapis.com/v1beta/openai`, with the env name
  from `dedicated_api_key_env`: `ONTOLOGYLAB_PROVIDER_GEMINI_1BDF3AFBB89F`.
  Export its value from `GOOGLE_API_KEY` inside the shell only. Never print,
  persist, or send the key to a keychain.
- One provider-test request before extraction, accounted separately as in
  trials 1 and 2. Missing key, failed test, or unavailable prescribed model
  means BLOCKED; no alternate model and no extra test requests.
- Three distinct loopback servers, ports, stores, registries, and packs roots.
  Never use port 8799, touch PIDs 87584/3284, or access Application Support.
- Use `POST /api/schema`, then `POST /api/collect` for the five full bodies.
  Verify all five API documents and observations are fulltext and extractable.
  No SQL eligibility manipulation, approval, or abstract-only extraction.
- Subscribe to `/api/jobs/stream` before each single `POST /api/extract`.
  The payload includes all document ids, `max_engine_calls=60`, `seed=7`,
  and NO `time_budget`. Each request, including the allowed parse retry, counts
  against the 60-request per-run ceiling.
- Trial 2 explicitly supplied `time_budget=600`: this was a trial override,
  not the former product default of 7200 seconds. It caused R1/R3 exhaustion.
  Reusing it would bypass todo 25. Use the new automatic default instead:
  21 chunks, 42 possible requests including one retry/chunk, 300 seconds per
  request, 10% local reserve = 13860 seconds plus elapsed setup.
- Reuse trial 2's foreground Python driver/server ownership and concurrent
  runs. The enclosing command waits for all three drivers and their servers.
  Each driver bounds readiness to 45 seconds, HTTP requests to 30 seconds,
  provider test to 320 seconds, job observation to 14220 seconds, and shutdown
  to 30 seconds. Event-driven status GETs follow SSE updates rather than
  fixed sleeps. These are observer/process bounds, not extraction overrides.
  On timeout cancel, record the failure, stop the owned server, and never rerun.
- Save job status, provenance, automatic budget, chunk rows, proposal rejection
  reasons/counts, and `/api/claims/stages?include_proposed=true`.
  Reconcile request counts from status, terminal HTTP status, and provenance.
  Stop every owned server and independently demonstrate its port is closed.
  Delete nothing; list retained temporary paths.

## Binding gates and statistics: unchanged

Decide pooled gates from summed numerators/denominators, also report each run.
Thresholds apply to point estimates, not CI bounds.

| Gate | PASS requirement |
| --- | --- |
| G1 | Successful parsing in at least 95% of planned chunks |
| G2 | Polarity set on at least 90% of schema-valid claim relation rows |
| G3 | Matched-gold polarity accuracy >=0.80 AND no_effect+refutes recall >=0.70 AND supports-when-gold-no_effect flip rate <=0.15 |
| G4 | Zero observed supports/no_effect same-triple collapses; contradictory rows coexist with distinct ids in find_contradictions(include_proposed=True) |

PRIMARY: `ontologylab.polarity_eval.score_polarity(..., qualified=True)` via
`ontologylab.qualified_polarity_eval.score_qualified`, against
`tests/gold/agrochem-polarity/gold-qualified.json` (SHA-256
`f22e9390d5554cddee981874ddc496e1a1ed69bb2ebfd181bfcb5c469e0f4973`).
This is the standard-conformant qualified-statement identity chosen by the user.
SECONDARY: unchanged legacy `score_polarity(..., qualified=False)` against
`gold-fulltext.json`, for comparison with trials 1-3. Gold-specified qualifier
slots constrain primary matches; extras do not block them. No scorer edits.
Qualified scorer SHA-256:
`48e294bd8e6ebf3c1c00092bb9c2015ec180b49608497678986b3d5511a31b50`.
Both use unchanged `_rate`:
2000 case-bootstrap resamples, seed 7, 95% percentile CIs. Concatenate binary
outcomes to pool; do not average rates or merge graphs. G1/G2 use the same
method. G4 is an observed count with CI not applicable. Undefined rates/CIs
remain null. Missing triples are recall misses; no relaxed relation, direction,
or post-hoc alias matching.

For comparability G1 retains trial 2's durable `extraction_chunks` denominator.
Separately report full-corpus successful AND attempted coverage out of 63
(21/run; chunk counts 4/4/4/5/4), including never-planned chunks. Do not call
unattempted or persistence-failed chunks parser failures. G4 has the same
persisted-row and existing insertion-contract scope as trial 2, not an
unrecorded raw-provider-response replay.

Outcome: VERIFIED iff all four pooled gates PASS under the PRIMARY scorer.
Always report secondary legacy gates alongside; legacy cannot establish VERIFIED. FAILED iff G1 ran and at
least one gate FAILS, naming those gates. BLOCKED iff the key is absent,
provider test fails, or zero chunks return so gates cannot be evaluated.
Only VERIFIED satisfies IS-1. Errors do not authorize replacement runs.

## Reporting and interpretation

Write `evidence/polarity-trial-4-2026-09-27.md` and `.json`, plus the requested
canonical `.omo/evidence/task-29-ontologylab-completion.md` receipt.
Compare trials 1/2/3 and todo 25's offline estimate (22/102 matched,
6/51 negative/null recall; coverage unchanged at 31/63). Distinguish actual
new model observations from offline deterministic recovery and projections.
Classify unmatched triples as surface, relation, absent, or scope, keeping
wrong-polarity exact matches separate. Categories never change the score.
Scan all retained artifacts using exact-key `grep -a -F -c` with the pattern
passed via stdin; check exits and report only counts. Require zero matches.

This is a same-corpus regression trial on five previously studied,
null/negative-enriched papers, not an independent holdout. Prior misses informed
the fixes; the verifier/designer overlap is real. Gold lacks independent expert
adjudication. An independently adjudicated new holdout would address that
limitation but is outside this authorized trial. Case-bootstrap CIs ignore
within-paper and between-repeat dependence and can be too narrow.

Immediately after the three runs, export ALL persisted nodes, aliases, edges,
qualifiers, polarities, and evidence spans (including noncurrent rows) into
`evidence/polarity-trial-4-2026-09-27-edges.json`. Future rescoring must not
require temporary stores. Do not include secrets. Retain temporary stores too.

Evidence-only verification uses existing qualified and legacy scorer/identity/fulltext tests,
driver diagnostics, exact frozen-input comparison, HTTP surfaces, and database
integrity checks. No product edits, mutation, unrelated build, or new tests.
