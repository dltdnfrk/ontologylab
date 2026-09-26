# Preregistered second polarity trial - 2026-09-26

Understood as: measure the authorized full-text/extract-v4 rerun, not tune the
corpus, gold, extractor, scorer, or thresholds until the trial passes.
This document must be committed before the first provider test or model call.

## Frozen inputs

Worktree: `/Users/hyunjun/Documents/MUNI/ontologylab-wt/w5-t21`,
branch `completion/w5-t21`, clean starting revision
`ae582547da4592fc8be4f1e049e12a8ea724b85f`.
Origin: `https://github.com/dltdnfrk/ontologylab.git`.
Product tree `HEAD:ontologylab`: `383bc8f807258f9e6e0fa9423e403f991acdf291`.
Gold tree `HEAD:tests/gold/agrochem-polarity`:
`9e7455f22c2eaa5b9d440180122370ad69a8168d`.
No corpus, gold, or product/scoring code changes after this commit.

All corpus paths below are relative to
`tests/gold/agrochem-polarity/sources/full/`. Ingest in filename order.

| File | SHA-256 |
| --- | --- |
| PMC11298438.txt | 4fe0e19bc80d2cb3f388deebc38f02f20e5e1d1392db60fd50d1fbfd4ab385d9 |
| PMC12546283.txt | be7923ca6e58a248ff2cb1476cfd719dd513a3c3df152e7ab821fe02ea90c099 |
| PMC12563837.txt | 8d45778ceeb648ff318a7a0e6d1112f836e4da13cca76739e89acf300e96ed80 |
| PMC12632097.txt | 427633460b64db0d1a455098ea4f6eb21b91b0bab2f8ea5a36ec29ace7321490 |
| PMC12713700.txt | 9a876e8c7db10ed125a803962ba53e5371d9793f7371cdf35d2cf0ae3b1e99d9 |

Gold: `tests/gold/agrochem-polarity/gold-fulltext.json`, SHA-256
`cf7ea33f227540f201f2142eb7fa640bf08a1edf3cb039528c3b4828796f4f23`.
Offline validation: five papers, 34 exact spans, supports=17, no_effect=12,
refutes=5. Labels never enter extraction prompts.

`ontologylab/extractor.py` SHA-256:
`f7600ad74a9ebf0e588b1c4bec1f63711639857e58698978c76a3e787d978f7f`.
`ontologylab/polarity_eval.py` SHA-256:
`7b240a311b00460450adcc37dc5624dd9bc1775a79e9f89dc099a8c7d8e9f55a`.

## Fixed procedure and request budget

- Exactly three extraction runs, without replacements or quality-driven retries,
  in fresh disposable data directories:
  `/private/tmp/ol-polarity2-20260926T232709Z-r1`,
  `/private/tmp/ol-polarity2-20260926T232709Z-r2`,
  `/private/tmp/ol-polarity2-20260926T232709Z-r3`.
- Engine `api:gemini`; model `gemini-3.6-flash`; prompt `extract-v4`;
  schema `agrochem-v2`; temperature 0.0; seed 7.
- Provider kind `openai`, base URL
  `https://generativelanguage.googleapis.com/v1beta/openai`.
  Register only the name returned by `dedicated_api_key_env`:
  `ONTOLOGYLAB_PROVIDER_GEMINI_1BDF3AFBB89F`. Bind it from `GOOGLE_API_KEY`
  inside the shell; never print or persist its value or use the keychain.
- One provider-test request before extraction, accounted separately as in trial 1.
  If the key is missing, the provider test fails, or the prescribed model is
  unavailable, stop and record BLOCKED; do not choose another model.
- Each run uses its own server, free loopback port, packs directory and store.
  Never use port 8799, PIDs 87584/3284, or Application Support.
- Install the schema using `POST /api/schema`; ingest the five unchanged complete
  bodies through `POST /api/collect`. Check persisted observations and
  `/api/documents`: all five must be fulltext and extractable. Do not bypass
  abstract-only gating or edit eligibility through SQL.
- Subscribe to `/api/jobs/stream` before `POST /api/extract`. Send all five
  document ids, `max_engine_calls=60`, `time_budget=600`, `seed=7`.
  The budget includes retry requests. Use the trial-1 bounded 930-second
  driver wait; cancel a timed-out job, record it, and never replace it.
- Record provider errors, terminal job state, chunk statuses, actual requests
  from provenance reconciled to `status.json`, decode parameters, and
  `/api/claims/stages?include_proposed=true`. Stop each owned server and prove
  its port closed. Delete nothing.

## Gates and statistics (unchanged)

Gates are decided from pooled recorded numerators/denominators; also report
each run separately. No threshold is tested against a confidence bound.

| Gate | PASS requirement |
| --- | --- |
| G1 | Successful parsing in at least 95% of planned chunks |
| G2 | Polarity set on at least 90% of schema-valid claim relation rows |
| G3 | Matched-gold polarity accuracy >=0.80 AND no_effect+refutes recall >=0.70 AND supports-when-gold-no_effect flip rate <=0.15 |
| G4 | Zero observed supports/no_effect same-triple collapses; contradictory rows coexist with distinct ids in `find_contradictions(include_proposed=True)` |

Use the frozen `ontologylab.polarity_eval.score_polarity` and `_rate`:
2,000 case-bootstrap resamples, seed 7, 95% percentile intervals, individual
outcomes, as in trial 1. Pool concatenated binary outcomes, not averaged rates
or merged graphs. Report G1/G2 rate intervals using the same method. G4 is an
observed count, not a sampled proportion; its CI is not applicable.
Undefined denominators and their CIs remain null. Missing triples are recall
misses; do not relax relation/direction matching or add post-hoc aliases.
G4 observes persisted rows and the existing insertion identity contract, not
an unrecorded raw-provider-response replay.

Binding outcome: VERIFIED iff all four gates PASS. FAILED iff G1 ran and
at least one gate FAILS, naming those gates. BLOCKED iff the key is absent,
provider test fails, or zero chunks return so gates cannot be evaluated.
Only VERIFIED satisfies IS-1. Provider errors never justify extra runs.

## Reporting and limitations

Write `evidence/polarity-trial-2-2026-09-26.md` and the task-21 receipt.
Compare trial 1 and todo-19's offline full-text replay without equating
offline alias recovery with new model performance. Categorize unmatched
gold triples as surface, relation, absent, or scope; this diagnostic does
not alter the frozen score. Preserve any wrong-polarity exact matches separately.
Record exact-value credential scanning with `grep -c` without printing the
credential, file hashes, closed-port evidence, and every retained temp path.

These are five previously studied, null/negative-enriched papers, not an
independent held-out benchmark. Gold labels lack independent expert
adjudication. Source-grounded prompt changes were informed by prior misses:
this is a same-corpus regression trial, not proof of generalization.
Case-bootstrap intervals do not model within-paper or between-repeat
dependence. An independent, newly adjudicated holdout would be needed for
generalization claims; it is outside this fixed trial.
