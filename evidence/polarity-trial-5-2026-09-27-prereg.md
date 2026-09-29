# Preregistered fifth polarity trial - 2026-09-27

Understood as: measure exactly three authorized runs on the merged todo-30/31
tree, without tuning inputs, scorers, thresholds, settings, or run count to pass.
Commit this preregistration and the five path-only copied helpers before any
provider/model call. Afterward only evidence may change; freeze these six files.

## Frozen inputs

Work root: `/Users/hyunjun/Documents/MUNI/ontologylab-wt/w9-t32`.
Branch: `completion/w9-t32`.
Code commit: `1abdee4c1460366fcb67de13c3dfe53e19f54cb1`.
Origin: `https://github.com/dltdnfrk/ontologylab.git`.
Product tree: `7107ab329401c08914e64dbf17e555123d5a3076`.
Gold tree: `8c86ab606c7e6b6326c58239f836412dc2f29043`.
The user explicitly authorized this worktree and todo 32.

Corpus paths are relative to `tests/gold/agrochem-polarity/sources/full/`.
Ingest the five full bodies in filename order through HTTP.

| File | SHA-256 |
| --- | --- |
| PMC11298438.txt | 4fe0e19bc80d2cb3f388deebc38f02f20e5e1d1392db60fd50d1fbfd4ab385d9 |
| PMC12546283.txt | be7923ca6e58a248ff2cb1476cfd719dd513a3c3df152e7ab821fe02ea90c099 |
| PMC12563837.txt | 8d45778ceeb648ff318a7a0e6d1112f836e4da13cca76739e89acf300e96ed80 |
| PMC12632097.txt | 427633460b64db0d1a455098ea4f6eb21b91b0bab2f8ea5a36ec29ace7321490 |
| PMC12713700.txt | 9a876e8c7db10ed125a803962ba53e5371d9793f7371cdf35d2cf0ae3b1e99d9 |

| Gold / implementation / helper | SHA-256 |
| --- | --- |
| tests/gold/agrochem-polarity/gold-fulltext.json | cf7ea33f227540f201f2142eb7fa640bf08a1edf3cb039528c3b4828796f4f23 |
| tests/gold/agrochem-polarity/gold-qualified.json | 04601aa947fc465013eb77f2d4b10dde277c32990151ca267f8e572956836295 |
| ontologylab/extractor.py | 969a57668536079233197725c84eb70a15f0e8b3fc76fd86ed6383cba652082d |
| ontologylab/polarity_eval.py | 91a140b358228873169307ef2ba26514f18a7305ca8b8aaa21c73e975e432e21 |
| ontologylab/qualified_polarity_eval.py | 68bd707c9e623af03594a0dced88c702079caccf4b2c93a031c7aafdcaf66a46 |
| evidence/polarity5_driver.py | f1fce8697db57ce8730f34fd425d506627cd6a64bdf370a11a049be45b479d80 |
| evidence/polarity5_score.py | 1c07fb27c28686f4108c6f1f2635f42fc25c5d2a9a69ee04bef6829ff7d64df4 |
| evidence/polarity5_export.py | 1b7975ff0f034135da08e0a8cb2a373cac3083e359b1a40b0f477b88c98f941e |
| evidence/polarity5_misses.py | 53b9b492ee4db678a28f7260f0204492aa3a2a680ddf9e72640a81ec2aaf85dc |
| evidence/polarity5_verify.py | ecf973af49d2c645131bd0f8ad17d5882713e1149007a0c3bebfc151da5ce074 |

The regenerated qualified gold retains 34 findings: 17 supports, 12 no_effect,
5 refutes. Both gold validators verified all 34 spans in five papers before
registration. Labels never enter extraction prompts.

## Procedure and effective defaults

- Exactly three concurrent extraction runs, no replacements, resumes, extra runs,
  alternate providers, or quality-driven retries, in fresh directories:
  `/private/tmp/ol-polarity5-20260927T104521Z-r1`,
  `/private/tmp/ol-polarity5-20260927T104521Z-r2`,
  `/private/tmp/ol-polarity5-20260927T104521Z-r3`.
- Engine `api:gemini`; model `gemini-3.6-flash`; code-read and imported
  `PROMPT_VERSION=extract-v8`; schema agrochem-v2; temperature 0.0; seed 7.
- One provider-test request before extraction, accounted separately. Missing key,
  failed provider test, or unavailable prescribed model means BLOCKED.
  Export `ONTOLOGYLAB_PROVIDER_GEMINI_1BDF3AFBB89F` from `GOOGLE_API_KEY` only
  inside the shell. Never print/persist the value or use the keychain.
- Product defaults are `max_transport_retries=2`, `time_budget=None`.
  Omit both fields from the extraction payload. Default transport policy retries
  transient disconnection/reset/timeout/5xx errors at most twice per chunk;
  non-transient errors are not retried. Backoff is 1 then 2 seconds unless a
  longer Retry-After applies, always capped at 8 seconds. One parse retry is
  separately allowed. All initial requests, parse retries, and transport retries
  count toward the explicit **60 requests/run** cap.
- Automatic budget: 21 chunks, min((2+2)*21,60)=60 request slots,
  300-second request timeout, 10% local reserve plus 8 seconds backoff reserve
  per slot: **20,280 seconds plus setup elapsed**. Record the actual budget
  and effective retry count from provenance. Do not reinstate the old 600-second
  trial override.
- Reuse trial 4's foreground Python driver owning and awaiting all three servers.
  It subscribes to SSE before each single POST and polls status with GET on
  events inside the bounded observation loop. Readiness=45 seconds, HTTP=30,
  preflight=320, observation=14,220, shutdown=30. The unchanged observation bound
  is shorter than the new maximum product budget; if reached, record the
  shortfall and cancel, never add a run. No shell backgrounding of the driver
  or servers. Host completion is observed through a monitor, as in trial 4.
- Never use port 8799, touch PIDs 87584/3284, or access Application Support.
  Separate dynamic loopback ports, stores, provider registries, and packs roots.
  HTTP schema installation and collection must yield five fulltext/extractable
  documents per run. No SQL eligibility changes or human approvals.
- Record statuses, provenance, successful/attempted/expected chunk coverage,
  retry events, rejected proposals, request counters and stage rows. Stop and
  await every owned server; independently prove PID absence and closed ports.
  Delete nothing; retain and list all temporary paths.

## Binding gates and statistics: unchanged from trial 4

| Gate | PASS requirement |
| --- | --- |
| G1 | Successful parsing in at least 95% of planned chunks |
| G2 | Polarity set on at least 90% of schema-valid claim relation rows |
| G3 | Matched-gold polarity accuracy >=0.80 AND no_effect+refutes recall >=0.70 AND supports-when-gold-no_effect flip rate <=0.15 |
| G4 | Zero observed supports/no_effect same-triple collapses; contradictory rows coexist with distinct ids in find_contradictions(include_proposed=True) |

PRIMARY: `score_polarity(..., qualified=True)` against regenerated
`gold-qualified.json`. SECONDARY: unchanged legacy
`score_polarity(..., qualified=False)` against `gold-fulltext.json`.
Gold-specified qualifier slots constrain primary matches; extras do not block.
Do not edit the scorers or relax relation/direction/alias identity after results.

Use unchanged `_rate`: 2,000 case-bootstrap resamples, seed 7, 95% percentile
CIs. Pool concatenated binary outcomes, never averaged rates or merged graphs.
Report all gates and CIs per run and pooled. Decisions use point estimates.
Undefined rates and CIs remain null. G4 is an observed count; CI not applicable.
G1 retains the durable extraction_chunks denominator; separately report full
coverage out of 63 chunks (21/run; paper counts 4/4/4/5/4), including unplanned
chunks. Do not mislabel transport or persistence failures as parse failures.
G4 retains the persisted-row plus existing insertion-contract scope, not an
unrecorded raw-provider replay.

Outcome: VERIFIED iff all four pooled PRIMARY gates pass. FAILED iff G1 ran
and at least one gate fails, naming those gates. BLOCKED iff key is absent,
provider test fails, or zero chunks return so gates cannot be evaluated.
Only VERIFIED satisfies IS-1. Legacy results cannot establish VERIFIED.

## Evidence and interpretation

Immediately after the three runs export ALL persisted edges, nodes, aliases,
original qualifiers/polarities, citations and evidence spans, including
noncurrent rows, to `evidence/polarity-trial-5-2026-09-27-edges.json`.
The path-only copied exporter still emits its literal `trial: 4`; correct only
that envelope metadata to `trial: 5` when saving, never graph rows or scripts.
Replay both scorers from the durable export and require equality to store scores.

Write `evidence/polarity-trial-5-2026-09-27.md` and `.json` and the explicitly
requested canonical `.omo/evidence/task-32-ontologylab-completion.md`.
Report miss categories surface/relation/absent/scope, keeping wrong matched
polarity separate; classification never changes scoring. Compare trials 1-4
and todo 30's offline estimate (23/102 matches, 21/23 accuracy, 6/51
negative/null recall on retained trial-4 output, not new model observations).

Scan retained artifacts with exact-key `grep -a -F -c -f /dev/stdin -- FILE`;
pass the key through stdin, check every exit, report counts only; require zero.
Run existing focused scorer/identity/fulltext and qualifier tests once on a
fresh test path; check helper diagnostics, frozen hashes, HTTP surfaces, and
database integrity. Build/mutation are not applicable to evidence-only changes.

Same-corpus regression, not an independent holdout: prior misses informed both
fixes and vocabulary; verifier/designer overlap and no independent expert gold
adjudication remain. A new independently adjudicated holdout is the independence
fix, outside this authorized trial. Bootstrap CIs ignore within-paper and
between-repeat dependence. No causal attribution to an individual fix.
