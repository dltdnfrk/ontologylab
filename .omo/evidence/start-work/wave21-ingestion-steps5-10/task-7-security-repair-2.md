# Task 7 security-repair-2 — exact current ReviewDecision + member cites

Executor: omo senpi-task `st_01a03089` (recovery of `st_01a02fa3`)
Date: 2026-08-24
HEAD: `5a6378964bfc41fe2a679453a88235c548a59f4b` (unchanged; no commit)
Sources: `task-7-review-code.md`, `task-7-review-code-recheck.md`,
`task-7-review-security.md`, `task-7-review-security-recheck.md`,
`task-7-review-repair.md`.
Constraint: no Application Support, network, 8799, PID 55560, Task 8/9C,
full suite, or denylist read/import/stage. Mutants via apply/restore
bytes only — no git checkout/restore/reset.

## Verdict

**DONE.** Live scoped waiver is the H1 review family when colliding-time
stale approve/waiver share actor/reason/decided/as-of. Same-cite
different-scope and smaller ids cannot win. Multiple indistinguishable
tips quarantine and never mint an eligible `approve` / `pack_ineligible=0`
twin. Additive `grounded_review_current` pointer updates in the same
review SAVEPOINT; rollback, idempotent same-id write, and historical
exact-unique fallback hold. Tampered reject/quarantine/compensate bind
only current fact-member Citation ids, force `pack_ineligible=1`, and
do not re-verify ready bytes. Approve stays 409 / zero-write.
Code-review repairs (run-bound chunk, current-run citation mint,
selection uniqueness, no `created_ts` live bind, exact cite set) are
unchanged at their freeze hashes.

## Current-state audit (before this recovery)

HEAD matched. Prior worker left owned bytes; `task-7-security-repair-2.md`
was missing. Tracked dirty were the 13 Task7 paths plus new
`grounded_review_members.py` and four Task7 tests. Denylist six files
remained `??` and were not opened.

Freeze-vs-worktree at recovery start:

| Path | vs code-recheck freeze |
|---|---|
| citation.py / citation_bind.py / citation_store.py / citation_types.py | MATCH |
| h1_classify_cite.py / h1_existing.py / h1_materialize.py | MATCH |
| tests/step7_valid_stale.py + three repair tests | MATCH |
| h1_existing_review.py / h1_materialize_review.py | MATCH — **H1 exact tip not implemented** |
| grounded_review.py / schema / store | CHANGED — pointer table + SAVEPOINT write already started |
| grounded_review_members.py | NEW — member cite filter already started |

Baseline once (current bytes, no product edit yet):

```
tests/test_step7_security_repair_2.py
tests/test_step7_review_repair.py
tests/test_step7_citation_bind.py
tests/test_step7_tampered_non_approval.py
tests/test_step7_h1_existing.py
tests/test_grounded_review_identity.py
2 failed, 25 passed
```

Failed for the right reason: H1 linked a minted eligible approve, not
the live waiver. Tampered reject digest and pointer rollback already
passed. Code-review repair tests stayed green.

## RED

- Colliding stale approve + smaller stale waiver (same actor/reason/time)
  → dest `family_receipt_id` was a minted `approve` / pack 0.
- Same-cite different-scope second waiver → live waiver unlinked; eligible
  twin minted.
- Two same-cite scopes with pointer deleted → eligible mint instead of
  typed quarantine.
- Waiver after stale extra Citation → digest was live ∪ stale.
- Compensate predecessor followed later-sorting stale row, not pointer.
- `return waivers[0]` / skip pointer / mint on history / union all fact
  cites / omit membership / `ineligible=False` / `_should_require` False /
  `conn.commit()` around pointer all survive without the new tests.

## GREEN (once each; no retry-to-pass)

```
security + repair focused after split:
tests/test_step7_security_repair_2.py
tests/test_step7_security_members.py
tests/test_step7_review_repair.py
13 passed. EXIT 0

owner+integration+repair+sec2:
tests/test_extraction_receipts.py tests/test_preferred_selection.py
tests/test_research_selection.py tests/test_citation_receipts.py
tests/test_grounded_review.py tests/test_grounded_review_identity.py
tests/test_h1_migration.py tests/test_step7_integration.py
tests/test_step7_integration_h1.py tests/test_step7_h1_existing.py
tests/test_step7_review_repair.py tests/test_step7_tampered_non_approval.py
tests/test_step7_citation_bind.py tests/test_step7_security_repair_2.py
tests/test_step7_security_members.py
124 passed, 1 warning. EXIT 0

affected research/extractor/kgstore/cli/server/migration + identity/H1/repair/sec2:
157 passed, 1 warning. EXIT 0   # pre-split file set; product H1/review
                                 # unchanged after the later test split
                                 # except members annotation + str() coerce

basedpyright <changed Python>: 0 errors, 0 warnings, 0 notes
```

Warning is third-party Starlette/FastAPI `httpx` deprecation. No full suite.

## Contract implemented

1. **Exact current ReviewDecision.** `existing_review` prefers
   `grounded_review_current` when that payload matches actor/reason/
   decided/as-of, valid v1/v2 id, current Task 4 cite set, selection/
   policy/run, and waiver pack=1 + nonempty defects. No
   `len(waivers)==1` shortcut. Historical fallback is exact-unique
   `_review_matches` only. `len != 1` → None.
2. **Never mint eligible twin.** `materialize_review` returns None when
   any decision already exists and lookup missed. `bind_family` then
   quarantines the review as `ungrounded`.
3. **Active Citation membership.** `_waive` and non-approve `_apply` use
   `stored_member_citations` (current `citations` anchors + revision +
   Representation/run/selection/policy). Stale extra rows stay out.
   Approve still `require_grounding` / HTTP 409 / zero-write.
4. **Pointer atomicity.** `set_current_decision` is inside
   `grounded_review_v1` with persist + status. Predecessor is the
   pointer (else last historical row). Same-id persist/pointer are
   no-ops.
5. **Preserved code-review repairs.** citation/h1_materialize/h1_existing/
   h1_classify_cite/step7_valid_stale hashes still MATCH the
   code-recheck freeze.

## Mutations (byte restore, not git)

Each mutant: single-site replace → one focused test → restore from
saved bytes. Post-restore SHA-256 MATCH the pre-mutant product hashes
then in force (`h1_existing_review` `bd36a80d…`, `h1_materialize_review`
`d23dec0f…`, `grounded_review` `74500401…`, members `5edaef32…` at
mutant time; members later became `187df60d…` for `object`→`str|None`).

| Mutant | Kill | Restored |
|---|---|---|
| `return waivers[0]` before pointer | same-cite different-scope linked smaller other | `bd36a80d…` |
| skip current-tip pointer | same-cite linked empty / not live | `bd36a80d…` |
| drop history-exists mint guard | ambiguity test minted pack-0 approve | `d23dec0f…` |
| `_waive` via `citations_for` | waiver cite set included stale | `74500401…` |
| `stored_member_citations` return all stored | tampered reject digest included stale | `5edaef32…` |
| `ineligible = False` | tampered reject `pack_ineligible is True` | `74500401…` |
| `_should_require` always False | tampered approve did not raise | `74500401…` |
| `conn.commit()` around pointer | savepoint rollback left rows | `74500401…` |

## Manual QA

Driver `/private/tmp/ontologylab-wave21-task7-sec2-qa.py` (deleted).
Library + installed `.venv/bin/ontologylab` + real uvicorn.

```
QA_PASS
waiver=sha256:e00c097a3e2e328ce5e60f9d7047284266e25fa1cbcd21d060fae494fa1e2208
h1_receipt=af9f3eaca9172ab3bb1e9363192747a21fde5d00e103a6bf8696601b14dcd4e0
pass2_equal=True
resume_complete=True
cli_rc=0
http_port=57175
approve=409 reject=200
8799_unchanged=True
```

Observed:

- H1 dest review family = live waiver; no pack-0 approve twin.
- Pass2 receipt hash identical; interrupt after 2 anchors then resume
  `complete=true` / `pending=0`.
- Source `h1_*` tables unchanged; source content hash unchanged
  (SQLite backup opened `-wal`/`-shm` only).
- Direct tamper approve `GroundingPreflightError` / `citation_ungrounded`;
  reject returned stored ids.
- Installed CLI `reject` exit 0 printed `decision_receipt_ids sha256:`.
- Real uvicorn `127.0.0.1:57175` (not 8799; startup Event; urllib):
  approve 409, reject 200 with `sha256:`.
- PID 55560 / DEVICE `0x1ff51c806b197195` unchanged before and after.

## Owned SHA-256 / pure LOC

| Path | SHA-256 | file / pure |
|---|---|---|
| `ontologylab/citation.py` | `6050d74c…d4ed80` | 84 / 65 |
| `ontologylab/citation_bind.py` | `b045f72b…cc9e8c` | 257 / 236 |
| `ontologylab/citation_store.py` | `da42b2da…e3ce4` | 202 / 183 |
| `ontologylab/citation_types.py` | `1b3209c2…60ae78` | 104 / 86 |
| `ontologylab/grounded_review.py` | `74500401…2e5ca0` | 255 / 230 |
| `ontologylab/grounded_review_schema.py` | `9fc80b3b…2f30c5` | 74 / 68 |
| `ontologylab/grounded_review_store.py` | `bccd4f7d…c45053` | 244 / 217 |
| `ontologylab/grounded_review_members.py` | `187df60d…9566a` | 86 / 77 |
| `ontologylab/h1_classify_cite.py` | `1ad78d2c…6d1c6` | 242 / 223 |
| `ontologylab/h1_existing.py` | `1c5f63d5…2e98` | 222 / 197 |
| `ontologylab/h1_existing_review.py` | `bd36a80d…20c98a` | 177 / 162 |
| `ontologylab/h1_materialize.py` | `f477b557…91e73d0` | 222 / 205 |
| `ontologylab/h1_materialize_review.py` | `d23dec0f…2379cee` | 88 / 77 |
| `ontologylab/h1_finalize.py` | `b7f80322…5aca2ad` | 162 / 142 |
| `tests/step7_valid_stale.py` | `10e71ed1…c01d34` | 183 / 168 |
| `tests/test_step7_citation_bind.py` | `38f21a3e…d8ffc2` | — |
| `tests/test_step7_review_repair.py` | `892fa15e…f1a886` | — |
| `tests/test_step7_tampered_non_approval.py` | `40cf516b…dc30a3dd` | — |
| `tests/step7_sec2_support.py` | `5463a672…2a12de` | 76 / 68 |
| `tests/test_step7_security_repair_2.py` | `d64ee3a9…f813af` | 204 / 193 |
| `tests/test_step7_security_members.py` | `c8f7e4cc…89078c` | 152 / 140 |

Product modules ≤236 pure LOC. `grounded_review.py` is 230 pure
(warning band). `citation_bind.py` 236 pure unchanged.

Full hashes:

```
745004019c0dcbdf84a6cf86875f2d9338e1410b124cd048d1d74bbacf2e5ca0 ontologylab/grounded_review.py
9fc80b3b50e8391fd1dd4e9425ebf900710f5a9e91a59021c1076266902f30c5 ontologylab/grounded_review_schema.py
bccd4f7d629b65af32dd36ebf748f0a313fd26f5ecdde441ce5cacc45053cd0d ontologylab/grounded_review_store.py
187df60da17791aceda2a96b73e005aa08253e0cff9856bd0505ab74bd89566a ontologylab/grounded_review_members.py
bd36a80dc55871c389fb1da8210c54a314c36acfaa4a0928536aca786820c98a ontologylab/h1_existing_review.py
d23dec0f34a08b9e4a6f9c1c365b0e7428e3a002303a1b82d5b35656f2379cee ontologylab/h1_materialize_review.py
b7f803229239d9e5df8674779b82d1f950b71e723146005cdf86244f85aca2ad ontologylab/h1_finalize.py
5463a6729acf94b051bfb724d043ce745db6fd1927c8dbd9244ef1f32f2a12de tests/step7_sec2_support.py
d64ee3a90c17f8ba22e48868113262d0b34082fa337798601c4288cd0df813af tests/test_step7_security_repair_2.py
c8f7e4cc499bc36c6afeeaf1cc284332b8f09eb1e174c6171bf892650a89078c tests/test_step7_security_members.py
```

## Post-write review

1. Single responsibility: current-tip lookup, no-mint materialize, member
   cite filter, pointer schema. No file needs "and" except grounded_review
   public API (pre-existing).
2. Boundary: untrusted review input still parsed into ReviewRequest /
   WaiverRequest; stored member cites are typed receipts.
3. Variants: ReviewAction still `match` + `assert_never` at derived_status.
4. Escape hatches: no Any/cast/type-ignore added. Members `_span_offsets`
   is `str | None`.
5. No extra null checks on proven values.
6. `_current_predecessor` is the current-tip seam used by write.
7. Tests fail if colliding twins, scope mismatch, ambiguity mint, stale
   cite union, or pointer commit leak return.
8. New public functions ≤3 params. Plant helper is a test fixture.
9. No post-delete verification.
10. Positive names (`current_decision_id`, `stored_member_citations`).
11. No new logging.

## Protected-boundary cleanup

- Did not read or write `~/Library/Application Support/ontologylab/`.
- No external network. Loopback only to disposable `127.0.0.1:57175`;
  listen gone after `should_exit` + join.
- Port 8799 / PID 55560 observe-only: DEVICE `0x1ff51c806b197195`.
- Denylist unread / unopened / unimported / unstaged (still `??`).
- QA root, mutant snapshot, and `/private/tmp/ontologylab-wave21-task7-sec2-*`
  drivers removed. Debug journal removed.
- No commit/push. No Task 8/9C. No full suite.

## DoneClaim

DONE. Exact current waiver is the H1 review family; colliding stale
approve/waiver and same-cite different-scope cannot win or mint an
eligible twin; indistinguishable tips quarantine; member Citation
digest excludes stale extras; pointer stays inside the review
SAVEPOINT with historical unique fallback. Verified by RED→GREEN,
8 killed mutants with restored hashes, owner 124 / affected 157 /
basedpyright 0, and real CLI + uvicorn 57175 QA. PID 55560 / 8799
untouched.
