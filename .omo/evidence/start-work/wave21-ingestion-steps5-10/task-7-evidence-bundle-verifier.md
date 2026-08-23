# AdversarialVerify — Task 7 closure bundle (pre-commit)

Verifier: omo senpi-task `st_01a030e7`
Date: 2026-08-24
Mode: read-only except this file. No product/test/plan/canonical/git
edit. No commit. No push. No pytest. No network. No live Application
Support open. Port 8799 / PID 55560 observed only (`lsof`). Denylist
unread / unopened / unhashed / unimported.

Claim under test: the 12-file Task 7 closure bundle written at 08:09,
before the evidence-only commit.

Authority (section 0 wins on conflict):

- `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md`
- `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md` §0
- `.omo/plans/wave21-ingestion-steps5-10.md` Tasks 7 and 8

## Verdict

`CONFIRMED`

The 12-file bundle is internally consistent, freeze-matched, and honest
on current bytes. Product/test HEAD and both required perimeters are
unchanged. Reviews, suite, chain, supersession, cleanup, aggregate, and
the Step 8 kickoff all hold. The Step 6 evidence-only commit candidate
set below is exact, parseable, and product/test-clean. No false or
missing claim blocks the authorized evidence-only commit.

## Closure artifact SHA-256 freeze

Independently `hashlib.sha256` of current file bytes. Lead prefixes all
MATCH.

| Artifact | SHA-256 | Lead |
|---|---|---|
| `task-7-wave21-ingestion-steps5-10.md` (combined receipt) | `9a57b6f994a43701e8fc7c6098bfee4dc38d3c615d100cef8d604e986786ac28` | `9a57b6f9` |
| `G007/a1/commit-boundary.txt` | `31b5629f11d86cca8219d1e77d421092c4bacf2bc644127fc4737680521f1fd4` | `31b5629f` |
| `G007/a1/final-suite.txt` | `a1bb8963f2ff3190a8d447d8ef8f4800b3e025ea561748575f4631e024431d02` | `a1bb8963` |
| `G007/a1/quality-gate.json` | `b63e9e9d8c5123417ae69fa67329e476b2653e40eb0ea8b0a6ee70e017fbf79b` | `b63e9e9d` |
| `G007/a1/scope-cleanup.txt` | `375113cd441050683f0b54df73c0d37e5a3fab9bef833477130c2d14e879818b` | `375113cd` |
| `G007/a1/step7-evidence-index.md` | `64b4ac4f2a8bf6724f8cbc231a44458db4cf6f507f76eb36cebba93578aaa3cc` | `64b4ac4f` |
| `aggregate-active.json` | `928f06db2192d29287d6737ea7e4344103632102707a01e2d6fd81be38b792a8` | `928f06db` |
| `aggregate-complete.json` | `ef14b1e22b4879337da10c75613612e06880a58b96a1a682cd69d8b0d1bec4db` | `ef14b1e2` |
| `brief.md` | `45cabe253650a979119b45153c9c8dfcc23eb09d8bc21647c21c97cfc1f6be18` | `45cabe25` |
| `goals.json` | `2ca52a5117222a9eea4859de3f3a71d32abba783d290f1cdb57ddf570d77c353` | `2ca52a51` |
| `ledger.jsonl` | `5abad1374ff1511ca1f19945f98c5b2fa854435a815ba81c3975e3a1d8b848b7` | `5abad137` |
| `step8-kickoff.md` | `eefb09a27b3bd4d27afb3b1d56d7baafc3177c363e3bdc40f426a2d7b70e17df` | `eefb09a2` |

## JSON / JSONL syntax

`json.loads` succeeded on `quality-gate.json`, `aggregate-active.json`,
`aggregate-complete.json`, and `goals.json`.

`ledger.jsonl` has 12 valid objects (`plan_reconstructed` through
`aggregate_completed`). Bytes end `\n\n`, so a 13th `splitlines()`
entry is empty. That extra blank line is not a record and does not
change the frozen digest `5abad137…`. Every non-empty line parses.

## Product/test HEAD and full-suite perimeter

| Fact | Required | Observed now |
|---|---|---|
| `git rev-parse HEAD` | `362b0a679483139e51d8e37748674a867d6a9b2f` | match |
| `HEAD^{tree}` | `dce1386961684e924108ded625e56dab4031384d` | match |
| Subject | `fix(extraction): preserve exact receipt identity` | match |
| Parent | `5a6378964bfc41fe2a679453a88235c548a59f4b` | match |
| Full-suite perimeter | `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867` | match; SHA-256 of `LC_ALL=C`-sorted `git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml` (387 paths) |
| Tracked `ontologylab` / `tests` / `scripts` / `pyproject.toml` vs HEAD | clean | `git diff --name-status HEAD --` those paths empty |
| Staged index | empty | `git diff --cached --name-only` empty |
| `origin/main` | `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` | match; `merge-base --is-ancestor 362b0a6 origin/main` exit 1 |
| Remote contains HEAD | no | `git branch -r --contains 362b0a6` empty |
| Reflog | local commits only | `HEAD@{0}` is the product repair commit; no push/amend/reset/checkout |

HEAD and `9d3f5790` are unchanged. Pytest was not re-run; suite
`2650 passed, 1 skipped, 2 xfailed`, exit 0 is bound to
`task-7-final-full-suite.md`
`c047fe84a6fc5c6aa185a1d48195f89a4b9c4e2a223f25f8a10bcb955c47c261`.

## 21-path C-sort perimeter (never `1eac` as authority)

Recomputed from `git show HEAD:<path>` SHA-256, then SHA-256 of
`LC_ALL=C` / Python `sorted` `path<TAB>content-sha256\n` over the exact
`git diff-tree --name-only -r 362b0a6` set (21 paths, 2050 bytes):

`1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b`

21/21 blob digests MATCH the authorized freeze in
`task-7-review-repair-commit.md`. `git diff-tree` path set equals that
table.

`1eac91b2…` appears in the 12 files only as a superseded
locale-dependent diagnosis (`step7-evidence-index.md` “Superseded
evidence”). It is not the bound perimeter in `quality-gate.json`,
`goals.json`, `ledger.jsonl`, `final-suite.txt`, `commit-boundary.txt`,
`brief.md`, or `step8-kickoff.md`. A `rg 1eac` hit on
`task-2-product-commit.md` hash `…15871eacbccd74…` is a different hex
string, not the rejected perimeter.

## Exact Task 2–7 commit chain

`git show -s --format='%H tree=%T parent=%P subject=%s'` plus
`git merge-base --is-ancestor 63e326f 362b0a6` and first-parent count
`63e326f..362b0a6` = 8. Linear, conventional, local-only.

| Task | Commit | Tree | Parent | Subject | Perimeter (recomputed) |
|---|---|---|---|---|---|
| 2 | `49ac5249fbfaecf0e18a00d08392166ea79250d5` | `2023a1bb…` | `63e326f` | `feat(extraction): bind runs and chunks to representations` | `1287ca36…` 7 paths MATCH |
| 3 | `1afd0f85b038475a3b0a43f477febd1b25bfce01` | `d60bc0eb…` | `49ac5249` | `feat(extraction): receipt preferred representation selection` | `0021ce5d…` 14 paths MATCH |
| 4 | `7c159fd3efa24a5b9839e0ae32643e7f90560124` | `64166739…` | `1afd0f85` | `feat(citations): seal representation grounding receipts` | `bbf7f76b…` 11 paths MATCH |
| 5 | `0a3c7a21d5ee8fbcfb7aa7bf521921e0e333ea29` | `be6cc43c…` | `7c159fd3` | `feat(review): require append-only grounding decisions` | `82ba0621…` 13 paths MATCH |
| 6 | `8f0e45fdfa1d70e39a91c03737ecb31cb1add3fb` | `c69020eb…` | `0a3c7a21` | `feat(migration): backfill historical grounding receipts` | `7edeb5be…` 17 paths MATCH |
| 7 integration | `4878c2f262e6909deb94ff61ef6d04a7e990edd7` | `4289084a…` | `8f0e45fd` | `feat(extraction): complete representation-grounded review flow` | `da88d057…` 17 paths MATCH |
| suite seam | `5a6378964bfc41fe2a679453a88235c548a59f4b` | `d295cb05…` | `4878c2f2` | `test(server): synchronize jobs stream change` | only `M tests/test_server.py`; blob `8a420db2bb95e77817afb369061dee0ba772b134e4520ea54c210393689eb3cb` MATCH at HEAD |
| final repair | `362b0a679483139e51d8e37748674a867d6a9b2f` | `dce13869…` | `5a637896` | `fix(extraction): preserve exact receipt identity` | `1bd10421…` 21 paths MATCH |

Hang-fix independent verifier
`task-7-hangfix-commit-verifier.md` confirms `5a637896`. The other
seven product/test commits have the commit reports/verifiers hashed
below.

## Cited receipt hashes and paths

Every SHA-256 cited by `step7-evidence-index.md` / `quality-gate.json`
/ `final-suite.txt` / `scope-cleanup.txt` / `ledger.jsonl` was
recomputed from the live start-work file. 34/34 MATCH, including:

| Role | File | SHA-256 |
|---|---|---|
| Final suite | `task-7-final-full-suite.md` | `c047fe84a6fc5c6aa185a1d48195f89a4b9c4e2a223f25f8a10bcb955c47c261` |
| Goal | `task-7-final-goal-review.md` | `4ce20fa4b2d36f6cb4376dba715b6d80bdbeb4fd65d911adeb775bf0b153f5a4` |
| Code | `task-7-review-code-final.md` | `aeb97646b9bc71a667df00462d42d65e57eb1eaa774849b2e52b6a608dc8c9fc` |
| Manual QA | `task-7-final-manual-qa.md` | `48f71153a869aac74acc86be4920e66882e7556e38939f321eb925c0ce51518a` |
| Security | `task-7-review-security-final.md` | `522a1bef03c0552e4646b840ff61f8df8750165dd52b1b43e2a289deda3b0580` |
| Context | `task-7-final-context-review.md` | `63c34690eaf164e440b245c3aca221dfee2bec519d12f22ebca0541530b35bb4` |
| Gate | `task-7-final-gate-review.md` | `bb398a788b2b025a9c8f01818f07f448a4ec4863b7ea5a006193a20289e86430` |
| T2..T6 + T7 integration + identity-repair executor/verifier/commit/commit-verifier set | 28 files | all MATCH index table |

53 path-like citations inside the 12 files exist and are non-empty
(authority docs, Step 6 index/kickoff, start-work receipts, sibling
G007/a1 + ulw-loop artifacts).

## Review / suite / gate coverage

Live file verdicts rebound by `quality-gate.json`:

| Lane | File verdict | `quality-gate.json` |
|---|---|---|
| Goal | **PASSED** 0.92 on HEAD `362b0a6` / `1bd10421` / `9d3f5790` / 2650+1+2 | `passed` |
| Code | **PASSED** 0.94; 21/21 freeze = HEAD blobs | `passed` |
| Manual QA | **PASS** on committed HEAD real surfaces | `pass` |
| Security | **PASSED**; 21/21 freeze = HEAD blobs | `passed` |
| Context | **PASS** — evidence-index ready | `pass` |
| Gate | **APPROVED** | `approved` |
| Suite | **PASSED** 2650 / 1 / 2, exit 0, 1274.66s | `2650/1/2/0` |

Code/security reviews were written on parent `5a637896` against the
same 21 blobs now at HEAD. The index states “21/21 HEAD blobs”, not
that those reports were authored after `362b0a6`. Honest.

`quality-gate.json` also binds product commit, tree, `1bd10421`,
`9d3f5790`, and `prohibited.* = false`. Those flags match the
protected-boundary observations below.

## Honest supersession

Index “Superseded evidence” correctly names:

- pre-repair `needs-fix` task-local verifiers
- `task-7-review-goal.md` / `task-7-review-qa.md` on parent `5a637896`
- the 2630-test parent receipt
- interrupted suite receipts
- locale-dependent `1eac91b2…`
- older ledger events that used `1eac91b2…`

The reconstructed `ledger.jsonl` does **not** re-assert `1eac91b2`.
Gate “Index must not copy” list is respected: no 2630-as-final, no
pack v2 / F11 / `FULL_V2_AUTHORITY` / 9C / Wave 2.1 complete, no
“waived facts already excluded from publication”. Waivers are stated
as pack-ineligible decisions (Step 7), not as Step 8 publication.

Honest boundary matches blueprint §0: Step 7 owns C-024/F9, C-032, H1
rehearsal; Step 8 owns F11/pack/MCP; Step 9 owns F3/F7/F8 and 9C.
`FULL_V2_AUTHORITY = False` at `ontologylab/ingestion_shadow.py:33`.

## Aggregate / goals / no contradictory active goal

- `goals.json`: G002–G007 all `complete`; `activeGoalId` is JSON
  `null`; `aggregateCompletion.status` is `complete` on HEAD
  `362b0a6` / `1bd10421` / `9d3f5790` / 2650+1+2 / gate approved.
- `aggregate-complete.json`: `status=complete`, same product commit
  and evidence-index path.
- `aggregate-active.json`: `status=active`, `source=start-work
  evidence reconstruction`. This is the Step 4/5/6 sibling pair
  (Step 6 closer left the active sibling untouched on purpose), not
  an in-progress goal. No goal object is `active` / `in_progress`.

Ledger last event is `aggregate_completed` / `protected_boundary=held`.

## Step 8 kickoff

`step8-kickoff.md` is a self-contained ` ```text ` prompt plus
“Use this prompt verbatim”. The inner prompt is decision-complete for
plan Tasks 8–12:

1. one-snapshot pack v2 closure (`full`/`excerpt`; sourced `none` /
   dangling / cross-generation / missing receipt / incomplete stream /
   v1 rewrite fail closed)
2. strict dynamic inventory + standalone verifier
3. one verified opener (`mode=ro&immutable=1`; failed replacement
   preserves prior session)
4. F11 + C-036 refusal; ready complete unreviewed fixture may publish
5. Step 8 close: mutation matrix, verifier + stdio MCP on the same
   snapshot, exact suite, six review lanes, index, verbatim Step 9
   kickoff, aggregate, evidence-only commit

Named mutants in the prompt cover the plan Task 8–11 kill lists.
Evidence discipline (RED, isolated mutant restore, machine-consumed
assertions, disposable fixtures, no sleeps, basedpyright, no
amend/rebase/reset/push, no live data / 8799 / network / planning
docs) is present.

Forbids Step 9+ / 9C:

- “Implement Step 8 only”
- “Do not implement Step 9A/9B/9C, authority flip, production
  migration or any cutover”
- “Do not enable FULL_V2_AUTHORITY”
- “Explicitly report that Step 9C remains unauthorized. Do not
  execute or imply production cutover”

Writing a Step 9 kickoff is listed only as a Task 12 close artifact,
not as Step 9 execution.

## Protected / cleanup / no-push / no planning edit

Observe-only, compared to `task-7-final-manual-qa.md` /
`task-7-final-gate-review.md` recorded metadata:

| Check | Observed now |
|---|---|
| PID 55560 / 8799 | `python3.1` PID `55560` `127.0.0.1:8799` DEVICE `0x1ff51c806b197195` LISTEN |
| Application Support dir (stat only; contents not read) | ino `102434596` mtime `1785487752` size `192` MATCH QA |
| Canonical analysis | ino `251846735` mtime `1787198701` size `43015` MATCH QA |
| Blueprint | ino `251846738` mtime `1787198279` size `40995` MATCH QA |
| Plan | ino `270282236` mtime `1787505626` size `45752` MATCH QA; Task 7/8 still `- [ ]` |
| QA leftovers | no `/tmp` or `/private/tmp` `ontologylab-wave21-task7-final-mqa*`; ports 64795 / 64550 / 18447 not listening |
| Denylist (git metadata only) | six `review_decision*` / `review_grounding.py` paths `commit=0` `index=0` still `??`; not opened |
| Untracked residual | same classified set as the final gate (`.gjc`, `.sisyphus`, `artifacts`, untracked docs, graphify, denylist, `uv.lock`) |
| Push | none; `origin/main` still `4ee5465b…` |

## Residuals (not blocking)

- `ledger.jsonl` ends with an extra blank line after 12 valid
  records. Freeze still `5abad137…`. Records parse.
- Hang-fix receipts exist and confirm `5a637896` but are not in the
  index receipts table. They are in the commit candidate set below.
- `task-7-final-full-suite.md` names a superseded
  `task-7-full-suite-2.md` that is not on disk. None of the 12
  closure files cite that filename; the index only says
  “interrupted suite receipts”. That file is excluded.

## Evidence-only COMMIT CANDIDATE SET

Policy: same include/exclude as Step 6
`task-1-evidence-commit.md` (21-path evidence-only close). Apply that
rule to Step 7. Do not commit this set here.

### Closer resolution

There is no `task-7-closer.md`. The closer receipt is
`task-7-wave21-ingestion-steps5-10.md` (`# Task 7 closure receipt`,
verdict `CLOSURE BUNDLE WRITTEN; EVIDENCE-ONLY COMMIT PENDING`,
SHA-256 `9a57b6f994a43701e8fc7c6098bfee4dc38d3c615d100cef8d604e986786ac28`).
Include it. This file is the closer-verifier analog of
`task-1-closer-verifier.md` and is also in the set.

The closer named `brief.md` and `aggregate-active.json` as closure
artifacts. Step 6 policy excludes those two (active sibling + loop
brief). This candidate set follows Step 6, not the closer's looser
list. Start-work receipts cited by the index, hangfix commit pair,
final reviews/suite, closer, and this verifier are added, matching
Step 6's inclusion of Task 1 executor/verifier/reviews/closer.

### Count, extensions, product/test

| Fact | Value |
|---|---|
| Candidate paths | **47** (lexicographic list below) |
| Sealed (non-self) | **46** |
| This verifier | in the path list; SHA-256 **not sealed** |
| Extensions | `.md` `.txt` `.json` `.jsonl` only |
| Every included file | nonempty; JSON objects parse; `ledger.jsonl` 12 objects |
| HEAD / tree | still `362b0a679483139e51d8e37748674a867d6a9b2f` / `dce1386961684e924108ded625e56dab4031384d` |
| Product/test vs HEAD | `git diff --name-status HEAD -- ontologylab tests scripts pyproject.toml` empty |
| Staged index | empty |

Sealed candidate perimeter (46 non-self paths, SHA-256 of `LC_ALL=C`
sorted `path<TAB>content-sha256\n`, 6642 bytes):

`9c0b4b8f796552d9bd6135d4464f8e0819a52cd96d92b106653a5964b3d4a49c`

The committer must recompute the 47-path perimeter after this file is
frozen, using the observed self-hash. Do not copy a self-hash from
this file; none is sealed here.

### Lexicographically sorted exact path list (47)

```
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-2-commit-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-2-executor.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-2-product-commit.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-2-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-commit-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-product-commit.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-repair-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-repair.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-commit-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-product-commit.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-repair-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-repair.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-commit-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-product-commit.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-repair-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-repair.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-6-commit-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-6-product-commit.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-6-repair-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-6-repair.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-commit-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-evidence-bundle-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-context-review.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-full-suite.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-gate-review.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-goal-review.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-manual-qa.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-hangfix-commit-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-hangfix-commit.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-product-commit.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-repair-2-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-repair-2.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-review-code-final.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-review-repair-commit-verifier.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-review-repair-commit.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-review-security-final.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-security-repair-2.md
.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-wave21-ingestion-steps5-10.md
.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/commit-boundary.txt
.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/final-suite.txt
.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/quality-gate.json
.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/scope-cleanup.txt
.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/step7-evidence-index.md
.omo/ulw-loop/wave21-step7-representation-grounding-20260824/aggregate-complete.json
.omo/ulw-loop/wave21-step7-representation-grounding-20260824/goals.json
.omo/ulw-loop/wave21-step7-representation-grounding-20260824/ledger.jsonl
.omo/ulw-loop/wave21-step7-representation-grounding-20260824/step8-kickoff.md
```

Composition: 5 G007/a1 + 4 loop completion + 20 Task 2–6 index-cited
receipts + 18 Task 7 final/hangfix/closer/this verifier.

### Non-self SHA-256 (46)

| Path | SHA-256 |
|---|---|
| `task-2-commit-verifier.md` | `f9bd0e1519cd8997586e39f7bdfabb1cd7bbc67db3b7254f09c7048035f40b28` |
| `task-2-executor.md` | `9339fc228bc05c8e25fd5192289f9f5bb9c28ac22bd2228b7aeb9f7a7ce358c0` |
| `task-2-product-commit.md` | `228086b00f2d17aa9c7f3d125a15871eacbccd7411b42f77dcfbb95de10f1821` |
| `task-2-verifier.md` | `92f42339da0ddafc865c8e824c83b328a2380af0876ba892ed9f19976f80eba1` |
| `task-3-commit-verifier.md` | `ec31486afb44a782e2f4bf38826689b48c6a78bfd5b765f3ab8cb477dbf1372c` |
| `task-3-product-commit.md` | `624a0e62803ed89c1b04e48082370e6ad6836249b0b82e1f0c184a2972f8792e` |
| `task-3-repair-verifier.md` | `d2929a06151b8289895af2eec66de0db38b859c1175252ac5a02ca23efdcfb04` |
| `task-3-repair.md` | `162a3e750e3de9cdb507a2cdf90a832466d5ee6d6bf474855b2e8587bdc5d523` |
| `task-4-commit-verifier.md` | `39e80929609aba7ee8fe89b52b8c6df7b32516bea980c82f1064f9dfabe6c719` |
| `task-4-product-commit.md` | `52437d986b8e5e349c1e1b83344bc409067ddc8e4a61b34ecbb887f0a5c0d40f` |
| `task-4-repair-verifier.md` | `779a30a7829fc47a63853d6003e403becd95c1764e13ec3d984b9b6fd5990a29` |
| `task-4-repair.md` | `959f5db0e1ab2251c529559fe6d14f7ade00b11d98898907bb3738610ab41302` |
| `task-5-commit-verifier.md` | `c7db2dade1358d2b6b2593f48a5014e75790a788b9605779e7eb5c2ff4814a3a` |
| `task-5-product-commit.md` | `821986773c7d2aab1db47a55d9fd00a98155d7ea6f395a7ceec31782169fb8e4` |
| `task-5-repair-verifier.md` | `5c1d19da9fd3a2214da7ee725f8fb6b20b3607039070447c23c9c2186cd11289` |
| `task-5-repair.md` | `746752371d8fda80552a4c0ddfbc349ba52a5c7a63bdcc96d184ab07118f38ae` |
| `task-6-commit-verifier.md` | `f0826e822b8e4f9f2b4fb627810cfa21725134a014ba94f31eadb60322c49926` |
| `task-6-product-commit.md` | `ca5fa405461fe3f8a19d6091c1225429bc9b867508db08eacb0aab634e695a94` |
| `task-6-repair-verifier.md` | `4775cd3053b5efd15809a625ef5526f4246bcdfbc46c42cedd502c9fe72c1039` |
| `task-6-repair.md` | `59320d4c084949c6bb5437cb7f8bd075f2d9a14a12e687a4fb6009f4e8c6a82b` |
| `task-7-commit-verifier.md` | `572425ece54d610863a6f739d7e34494b07d86d7dadd760791bd6b4f985e6a41` |
| `task-7-evidence-bundle-verifier.md` | *not sealed; observe after write* |
| `task-7-final-context-review.md` | `63c34690eaf164e440b245c3aca221dfee2bec519d12f22ebca0541530b35bb4` |
| `task-7-final-full-suite.md` | `c047fe84a6fc5c6aa185a1d48195f89a4b9c4e2a223f25f8a10bcb955c47c261` |
| `task-7-final-gate-review.md` | `bb398a788b2b025a9c8f01818f07f448a4ec4863b7ea5a006193a20289e86430` |
| `task-7-final-goal-review.md` | `4ce20fa4b2d36f6cb4376dba715b6d80bdbeb4fd65d911adeb775bf0b153f5a4` |
| `task-7-final-manual-qa.md` | `48f71153a869aac74acc86be4920e66882e7556e38939f321eb925c0ce51518a` |
| `task-7-hangfix-commit-verifier.md` | `f47a255dc144e79f4ee95ae9555a7491e2a363dde6961881a257ef74cf8ae6e3` |
| `task-7-hangfix-commit.md` | `bcb49df9b862e359b3ceb345fd4be6501a65530ed09545e601a2c4c5f9dabcb5` |
| `task-7-product-commit.md` | `83b10c30ea6772060915edcc4087efa4358db6b9546c6ffc1e9078baa63dc440` |
| `task-7-repair-2-verifier.md` | `4e3910dc1f802f04e4dda6b192819fddce3a32378604bd78687512b00faa2f63` |
| `task-7-repair-2.md` | `f57db204432ed702c468c5fe27265c7e1dcddcb8f2cc58921635fc15949d6af5` |
| `task-7-review-code-final.md` | `aeb97646b9bc71a667df00462d42d65e57eb1eaa774849b2e52b6a608dc8c9fc` |
| `task-7-review-repair-commit-verifier.md` | `2bf08af3c725649acaeca3e6930c443e14fdf18d0c9f777064769ee59b1a9cd0` |
| `task-7-review-repair-commit.md` | `563c0dd2d347cfd6f277cd3308544e965289244b094c8c4c5b32031183190b61` |
| `task-7-review-security-final.md` | `522a1bef03c0552e4646b840ff61f8df8750165dd52b1b43e2a289deda3b0580` |
| `task-7-security-repair-2.md` | `356c23a9fcfa339a512848fc5d05ddbf9039bf75d62395a9d4455d7d88bc19dc` |
| `task-7-wave21-ingestion-steps5-10.md` | `9a57b6f994a43701e8fc7c6098bfee4dc38d3c615d100cef8d604e986786ac28` |
| `G007/a1/commit-boundary.txt` | `31b5629f11d86cca8219d1e77d421092c4bacf2bc644127fc4737680521f1fd4` |
| `G007/a1/final-suite.txt` | `a1bb8963f2ff3190a8d447d8ef8f4800b3e025ea561748575f4631e024431d02` |
| `G007/a1/quality-gate.json` | `b63e9e9d8c5123417ae69fa67329e476b2653e40eb0ea8b0a6ee70e017fbf79b` |
| `G007/a1/scope-cleanup.txt` | `375113cd441050683f0b54df73c0d37e5a3fab9bef833477130c2d14e879818b` |
| `G007/a1/step7-evidence-index.md` | `64b4ac4f2a8bf6724f8cbc231a44458db4cf6f507f76eb36cebba93578aaa3cc` |
| `aggregate-complete.json` | `ef14b1e22b4879337da10c75613612e06880a58b96a1a682cd69d8b0d1bec4db` |
| `goals.json` | `2ca52a5117222a9eea4859de3f3a71d32abba783d290f1cdb57ddf570d77c353` |
| `ledger.jsonl` | `5abad1374ff1511ca1f19945f98c5b2fa854435a815ba81c3975e3a1d8b848b7` |
| `step8-kickoff.md` | `eefb09a27b3bd4d27afb3b1d56d7baafc3177c363e3bdc40f426a2d7b70e17df` |

Start-work paths live under
`.omo/evidence/start-work/wave21-ingestion-steps5-10/`.
G007/a1 paths live under
`.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/`.
Loop paths live under
`.omo/ulw-loop/wave21-step7-representation-grounding-20260824/`.

Index-cited Task 2–6 hashes MATCH the live files (20/20). Final Task 7
review/suite/repair/commit hashes MATCH the index and `quality-gate.json`.
Hangfix pair is newly bound here:
`task-7-hangfix-commit.md` `bcb49df9…` /
`task-7-hangfix-commit-verifier.md` `f47a255d…`.

### Excluded (not a candidate)

| Path / class | Reason |
|---|---|
| `aggregate-active.json` | sibling still `status=active` (Step 4/5/6 rule) |
| `brief.md` | loop brief, not a closure artifact |
| `.omo/start-work/ledger.jsonl` | excluded active ledger |
| `.omo/boulder.json` | excluded orchestration |
| `.omo/plans/`, `.omo/drafts/` | excluded planning/drafts |
| `task-{3,4,5,6,7}-executor.md` | superseded by cited repair / repair-2 |
| `task-{3,4,5,6,7}-verifier.md`, `task-4-verifier-recovery.md`, `task-4-verifier-retry.md` | pre-fix / needs-fix |
| `task-7-repair.md`, `task-7-repair-verifier.md` | superseded by `repair-2` |
| `task-7-review-repair.md` | pre-commit first review repair; not index authority |
| `task-7-review-{code,security}.md`, `*-recheck.md` | superseded by `*-final.md` |
| `task-7-review-goal.md`, `task-7-review-qa.md` | parent `5a637896` / suite 2630 |
| `task-7-full-suite.md`, `task-7-full-suite-hang-fix.md` | interrupted / non-final suite |
| `ontologylab/`, `tests/`, `scripts/`, `pyproject.toml`, `docs/` | product / tests / docs |
| six `review_decision*` / `review_grounding.py` | denylist |
| `.gjc/`, `.sisyphus/`, `artifacts/`, `graphify-out/`, `uv.lock` | unrelated residuals |

Exclusion regex over the 47-path list: no `aggregate-active`, `brief.md`,
`boulder`, `start-work/ledger`, `plans/`, `drafts/`, `ontologylab/`,
`tests/`, `review_decision`, `review_grounding`.

## Commands used

```text
git rev-parse HEAD HEAD^{tree} origin/main
git show -s --format='%H tree=%T parent=%P subject=%s'  <8 Task2-7 commits + 63e326f>
git merge-base --is-ancestor 63e326f 362b0a6
git merge-base --is-ancestor 362b0a6 origin/main
git rev-list --count --first-parent 63e326f..362b0a6
git diff-tree --name-status -r 5a637896 362b0a6
git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml | LC_ALL=C sort | shasum -a 256
git diff --name-status HEAD -- ontologylab tests scripts pyproject.toml
git diff --cached --name-only
git branch -r --contains 362b0a6
git reflog | head
python3  # sha256 12 artifacts + 34 cited receipts; json/jsonl parse;
         # 21-path and Task2-6 / 4878c2f perimeters from git show
lsof -nP -iTCP:8799 -sTCP:LISTEN
stat  Application Support dir + analysis/blueprint/plan  # metadata only
git ls-tree / git ls-files / git status --porcelain   # denylist metadata
```

No pytest. No denylist open/hash. No live-data contents. No network.
This file is the only write.
