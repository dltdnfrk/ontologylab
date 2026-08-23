# Task 7 final gate review

Date: 2026-08-24
Worker: omo senpi-task `st_01a030bf` (final re-gate)
Lane: independent closure gate on committed HEAD. Decide APPROVED for a
Task 7 evidence index + Step 8 kickoff, or NEEDS-FIX with exact missing
proof.
Mode: read-only except this file. No product/test/plan/canonical edits.
No commit. No push. No full-suite rerun. No network. No live Application
Support open. Port 8799 / PID 55560 observed only (`lsof`). Denylist
unread / unopened / unhashed / unimported.

This file supersedes its own first cut (`NEEDS-FIX`, SHA-256
`dbe5486fa40a4777a477572d3c40e62a6aec542520993b8e9dd5bb8c856a82e0`).
That stop line is historical. The three missing proofs it named now
exist and bind the required identities.

Authority (section 0 wins on conflict):
- `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md` §§6-8
- `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md` §0 and Step 7
- Plan Todo 7 in `.omo/plans/wave21-ingestion-steps5-10.md`
- Step 7 kickoff: `.omo/ulw-loop/wave21-step6-ingestion-service-20260821/step7-kickoff.md`

Prior Task 7 receipts are claims. Bindings below were recomputed on
current committed bytes.

## Verdict

**APPROVED**

Task 7 product/test bytes and the independent review bundle are ready
for a Task 7 evidence index and a Step 8 kickoff.

Bound identities (independently recomputed this re-gate):

| Fact | Required | Observed now |
|---|---|---|
| HEAD | `362b0a679483139e51d8e37748674a867d6a9b2f` | match |
| Tree | `dce1386961684e924108ded625e56dab4031384d` | match |
| Subject | `fix(extraction): preserve exact receipt identity` | match |
| Parent | `5a6378964bfc41fe2a679453a88235c548a59f4b` | match |
| 21-path perimeter | `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` | match (2050-byte C-sorted `path<TAB>content-sha256\n`) |
| Full-suite perimeter | `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867` | match (387 `ls-tree` paths, C-sorted) |
| Full suite | `2650 passed, 1 skipped, 2 xfailed` exit 0 | `task-7-final-full-suite.md`; not re-run here |

This is **not** Step 7 loop close. Index, Step 8 kickoff, aggregate, and
the evidence-only close commit remain unwritten. Plan Todo 7 is still
`- [ ]`. Those are the authorized next writes.

## Prior NEEDS-FIX — now satisfied

The first gate required three HEAD-bound reviews. Independently
rehashed and re-read this turn:

| Missing proof | File | SHA-256 | Bound identities | Verdict |
|---|---|---|---|---|
| Rebound goal | `task-7-final-goal-review.md` | `4ce20fa4b2d36f6cb4376dba715b6d80bdbeb4fd65d911adeb775bf0b153f5a4` | HEAD `362b0a6` / tree `dce13869` / suite 2650+1+2 / `9d3f5790` / `1bd10421` | **PASSED** 0.92 |
| Rebound QA | `task-7-final-manual-qa.md` | `48f71153a869aac74acc86be4920e66882e7556e38939f321eb925c0ce51518a` | same HEAD/tree; required perimeter `1bd10421`; `1eac91b2` marked untrusted | **PASS** |
| Context | `task-7-final-context-review.md` | `63c34690eaf164e440b245c3aca221dfee2bec519d12f22ebca0541530b35bb4` | same HEAD/tree/`9d3f5790`/`1bd10421`/2650+1+2 | **PASS** — evidence-index ready |

QA on this HEAD exercised installed CLI `approve` (stored `sha256:` +
`grounded_review_current`), CLI `migrate-h1` invalid (`not_sqlite`, dest
absent), real `python -m ontologylab.serve` on `127.0.0.1:64795` with
SSE `/api/jobs/stream` subscribed before `POST /api/extract`, live HTTP
approve idempotency + tampered approve 409 / reject+compensate
pack-ineligible, and direct H1 classify/materialize/finalize. Cleanup
rechecked this turn: no `/tmp` or `/private/tmp` `ontologylab-wave21-task7-final-mqa*`
roots; ports `64795` / `64550` not listening.

Do not treat `task-7-review-goal.md` or `task-7-review-qa.md` as
HEAD-bound. They remain parent-`5a63789` / suite-2630 survivors only as
history.

## Binding identity (independently recomputed)

| Fact | Required / claimed | Observed now |
|---|---|---|
| HEAD | `362b0a679483139e51d8e37748674a867d6a9b2f` | match |
| Tree | `dce1386961684e924108ded625e56dab4031384d` | match |
| Subject | `fix(extraction): preserve exact receipt identity` | match |
| Parent | `5a6378964bfc41fe2a679453a88235c548a59f4b` | match |
| Hang-fix subject | `test(server): synchronize jobs stream change` | match |
| Product commit | `4878c2f262e6909deb94ff61ef6d04a7e990edd7` | ancestor; `feat(extraction): complete representation-grounded review flow`; parent `8f0e45f` |
| 21-path repair set | exact `git diff-tree` of HEAD | 21 paths (unchanged from first gate) |
| 21-path content SHA-256 | code-final / security-final / commit table | 21/21 MATCH `HEAD:` and working tree |
| 21-path perimeter | `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` | match. Do **not** copy `1eac91b2…` |
| Full-suite perimeter | `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867` | match (387 paths) |
| Full-suite receipt | `2650 passed, 1 skipped, 2 xfailed` exit 0 | `task-7-final-full-suite.md` SHA-256 `c047fe84a6fc5c6aa185a1d48195f89a4b9c4e2a223f25f8a10bcb955c47c261` |
| Tracked `ontologylab` / `tests` / `scripts` / `pyproject.toml` vs HEAD | clean | `git diff --quiet` exit 0 |
| Staged index | empty | `git diff --cached --quiet` exit 0 |
| `origin/main` | unpushed | still `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`; `origin/main...HEAD` is `0 51` |
| Hang-fix blob | `tests/test_server.py` SHA-256 `8a420db2bb95e77817afb369061dee0ba772b134e4520ea54c210393689eb3cb` | match at HEAD |
| Repair-commit verifier | live file confirms `1bd10421` | SHA-256 `2bf08af3c725649acaeca3e6930c443e14fdf18d0c9f777064769ee59b1a9cd0` |

## Live review bundle (cite these)

| Review | File SHA-256 | Bound HEAD | Verdict | Usable |
|---|---|---|---|---|
| Goal (rebound) | `4ce20fa4b2d36f6cb4376dba715b6d80bdbeb4fd65d911adeb775bf0b153f5a4` | `362b0a6` | PASSED 0.92 | **yes** |
| Manual QA (rebound) | `48f71153a869aac74acc86be4920e66882e7556e38939f321eb925c0ce51518a` | `362b0a6` | PASS | **yes** |
| Code final | `aeb97646b9bc71a667df00462d42d65e57eb1eaa774849b2e52b6a608dc8c9fc` | parent + 21-path freeze | PASSED 0.94 | **yes** (21 blobs = HEAD) |
| Security final | `522a1bef03c0552e4646b840ff61f8df8750165dd52b1b43e2a289deda3b0580` | parent + 21-path freeze | PASSED | **yes** (21 blobs = HEAD) |
| Context | `63c34690eaf164e440b245c3aca221dfee2bec519d12f22ebca0541530b35bb4` | `362b0a6` | PASS | **yes** |
| Gate | this file | `362b0a6` | **APPROVED** | live |
| Full suite | `c047fe84a6fc5c6aa185a1d48195f89a4b9c4e2a223f25f8a10bcb955c47c261` | `362b0a6` | PASSED 2650+1+2 | **yes** |

Parent-bound `task-7-review-goal.md` / `task-7-review-qa.md` are
superseded. Original code/security FAIL files remain historical.

## Contract / RED / mutation / typing / QA / suite / protection

Unchanged from the first gate's HOLD table, now with HEAD-bound QA:

| ID | Result | Note |
|---|---|---|
| C-024 / F9 / C-032 / H1 rehearsal | **HOLD** | rebound goal re-read HEAD sources/tests; 21/21 freeze MATCH |
| RED / mutation / typing | **HOLD (bound)** | code-final / security-final on freeze = HEAD |
| Performance | **N/A** | Step 7 has no p95 budget |
| Manual QA | **HOLD** | rebound QA on this HEAD; cleanup rechecked empty |
| Full suite | **HOLD (bound)** | 2650 / 1 / 2 on `9d3f5790`; not re-run |
| Commits | **HOLD** | `4878c2f` → `5a63789` → `362b0a6`; no push |
| Protection | **HOLD** | denylist sizes only 6279 / 1652 / 2229 / 6434 / 1928 / 5697; still untracked. Observe-only PID `55560` `127.0.0.1:8799` DEVICE `0x1ff51c806b197195`. Application Support metadata only: ino `102434596` mtime `1785487752` size `192`. `FULL_V2_AUTHORITY = False`. |
| Independent reviews | **HOLD** | goal + QA + context now HEAD-bound; code/security-final attach via blob match |

## Authorization

**Authorized now**

- Write the Task 7 evidence index from the survivor table in
  `task-7-final-context-review.md` and this gate.
- Write the Step 8 kickoff prompt.

**Index must freeze**

- commit `362b0a679483139e51d8e37748674a867d6a9b2f`
- tree `dce1386961684e924108ded625e56dab4031384d`
- 21-path perimeter `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b`
- full-suite perimeter `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867`
- suite `2650 passed, 1 skipped, 2 xfailed`

**Index must not copy**

- `1eac91b2…` as the 21-path perimeter
- suite 2630 as the final committed-state receipt
- `task-7-review-goal.md` / `task-7-review-qa.md` as HEAD-bound
- this file's first-cut `NEEDS-FIX` stop line
- pack v2 / F11 / `FULL_V2_AUTHORITY` / 9C / Wave 2.1 complete
- “waived facts already excluded from publication”

## Residual `git status --short` (classified)

```
?? .gjc/                                               unrelated
?? .sisyphus/                                          unrelated
?? artifacts/                                          unrelated
?? docs/CONANSSAM-PROMPT-2026-08-08.bak                 unrelated
?? docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md   planning (untracked; not edited)
?? docs/OMO-INGESTION-WAVE-2.1-IMPLEMENTATION-HANDOFF-2026-08-20.md
?? docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md  canonical (untracked; not edited)
?? docs/ONTOLOGYLAB-DETAILED-SMOKE-RESULT-2026-08-08 2.md
?? docs/WAVE-2.1-DEEP-RESEARCH-REMEDIATION-GJC-2026-08-20.md
?? graphify-out/                                       generated
?? ontologylab/graphify-out/                           generated
?? ontologylab/review_decision.py                      denylist (unread)
?? ontologylab/review_decision_ids.py                  denylist
?? ontologylab/review_decision_schema.py               denylist
?? ontologylab/review_decision_store.py                denylist
?? ontologylab/review_decision_types.py                denylist
?? ontologylab/review_grounding.py                     denylist
?? uv.lock                                             unrelated
```

Tracked product/test bytes have not drifted from `HEAD:`.

## Protected-boundary / cleanup

- Did not read or write `~/Library/Application Support/ontologylab/` contents.
- Did not use external network.
- Did not bind, kill, or retarget port 8799 or PID 55560.
- Observe-only `lsof`: PID `55560` `127.0.0.1:8799` DEVICE
  `0x1ff51c806b197195`.
- Did not open, hash, import, or stage the six denylist files.
- Did not run pytest or basedpyright.
- This file is the only write.

## Stop

Strict verdict: **APPROVED**.

Task 7 evidence index and Step 8 kickoff are authorized on commit
`362b0a679483139e51d8e37748674a867d6a9b2f` / tree
`dce1386961684e924108ded625e56dab4031384d` / 21-path perimeter
`1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` /
full-suite perimeter
`9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867` /
suite **2650 + 1 + 2**.
