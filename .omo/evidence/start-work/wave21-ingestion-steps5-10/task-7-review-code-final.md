# Task 7 review-code final — recovered security-repair-2

Reviewer: omo senpi-task `st_01a03065`
Date: 2026-08-24
HEAD: `5a6378964bfc41fe2a679453a88235c548a59f4b` (unchanged; no commit)
Claim: `task-7-security-repair-2.md` (treated as a claim)
Constraint: report is the only durable write; mutants via apply_patch
reverse only; denylist unread/unopened/unimported; no Application
Support; no network; no 8799 / PID 55560; no full suite.

## Verdict

**PASSED**

**Confidence:** 0.94

Prior five MAJOR code-review repairs remain at their freeze hashes
and still die when reverted. The new current-pointer / member-cite
seam is architecturally sound: additive `grounded_review_current`
written inside `grounded_review_v1` after persist+before status,
idempotent same-id, historical fallback exact-unique else quarantine,
no first-tip / `ORDER BY` winner, member citations join current
`citations` + revision + Representation/run/selection. Eight
independent mutants killed and restored. Focused 25 / owner 124 /
affected 157 / basedpyright 0/0/0 once.

## Freeze

All claimed owned hashes MATCH current bytes (pre-tests = post-mutants).

Code-review five (unchanged vs `task-7-review-code-recheck.md`):

| Path | SHA-256 | file / pure |
|---|---|---|
| `ontologylab/citation.py` | `6050d74cb87cffca1143056ae5341ab455eab7bd33bdf9cad2674ce717d4ed80` | 84 / 65 |
| `ontologylab/citation_bind.py` | `b045f72bfb8623c75668b81a2f936c6f0629bb1cd3753ec3bf5092782fcc9e8c` | 257 / 236 |
| `ontologylab/citation_store.py` | `da42b2da42205cb57c92ba87fb675cec007f97244cb081bec675b81d250e3ce4` | 202 / 183 |
| `ontologylab/citation_types.py` | `1b3209c242ef87e38cd0e8046ad11ac2060c3ad0b4391af9c434990bae60ae78` | 104 / 86 |
| `ontologylab/h1_classify_cite.py` | `1ad78d2c47a5939f5db94c14dfba7cbf95e6c3005bf27734e2345da76f76d1c6` | 242 / 223 |
| `ontologylab/h1_existing.py` | `1c5f63d5aa71f3aff935a976352710a5cfe08d904ec50b6a990c513c2cea2e98` | 222 / 197 |
| `ontologylab/h1_materialize.py` | `f477b557f0896ec3f4ee3b15d2095dd9d8635b8446e78711e07a5c00491e73d0` | 222 / 205 |
| `tests/step7_valid_stale.py` | `10e71ed154ae6dee93263f244f7049dc8ae072cdece11e01482eaa8ffdc01d34` | 183 / 168 |

Security-repair-2 owned:

| Path | SHA-256 | file / pure |
|---|---|---|
| `ontologylab/grounded_review.py` | `745004019c0dcbdf84a6cf86875f2d9338e1410b124cd048d1d74bbacf2e5ca0` | 255 / 230 |
| `ontologylab/grounded_review_schema.py` | `9fc80b3b50e8391fd1dd4e9425ebf900710f5a9e91a59021c1076266902f30c5` | 74 / 68 |
| `ontologylab/grounded_review_store.py` | `bccd4f7d629b65af32dd36ebf748f0a313fd26f5ecdde441ce5cacc45053cd0d` | 244 / 217 |
| `ontologylab/grounded_review_members.py` | `187df60da17791aceda2a96b73e005aa08253e0cff9856bd0505ab74bd89566a` | 86 / 77 |
| `ontologylab/h1_existing_review.py` | `bd36a80dc55871c389fb1da8210c54a314c36acfaa4a0928536aca786820c98a` | 177 / 162 |
| `ontologylab/h1_materialize_review.py` | `d23dec0f34a08b9e4a6f9c1c365b0e7428e3a002303a1b82d5b35656f2379cee` | 88 / 77 |
| `ontologylab/h1_finalize.py` | `b7f803229239d9e5df8674779b82d1f950b71e723146005cdf86244f85aca2ad` | 162 / 142 |
| `tests/step7_sec2_support.py` | `5463a6729acf94b051bfb724d043ce745db6fd1927c8dbd9244ef1f32f2a12de` | 76 / 68 |
| `tests/test_step7_security_repair_2.py` | `d64ee3a90c17f8ba22e48868113262d0b34082fa337798601c4288cd0df813af` | 204 / 193 |
| `tests/test_step7_security_members.py` | `c8f7e4cc499bc36c6afeeaf1cc284332b8f09eb1e174c6171bf892650a89078c` | 152 / 140 |
| `tests/test_step7_citation_bind.py` | `38f21a3ecd46f437993d735be80ef759d25945e91746bac65bc49295ddb8ffc2` | 104 / 96 |
| `tests/test_step7_review_repair.py` | `892fa15e8f810a78b795e09df19b206e4a74c58ffde47b6ac6f6b85f40f1a886` | 212 / 198 |
| `tests/test_step7_tampered_non_approval.py` | `40cf516b905082769a3d9d40f154c7ece1ce172ccb85cb7270c7e596dc30a3dd` | 141 / 119 |

Product pure LOC ≤236. `grounded_review.py` 230 / `citation_bind.py` 236.

## Architecture (current pointer + members)

- **Additive schema.** `grounded_review_current (fact_kind, fact_id PK,
  receipt_id)` is `CREATE TABLE IF NOT EXISTS` beside the append-only
  decisions table. Decision UPDATE/DELETE triggers unchanged. Pointer
  is the only mutable row; `set_current_decision` INSERTs or UPDATEs
  the tip, never the decision payload. Same-id write is a no-op.
  Residual: `receipt_id` has no SQL `REFERENCES
  grounded_review_decisions(receipt_id)`. The API always persists the
  decision first in the same SAVEPOINT, and deletes are aborted, so a
  dangling tip is not reachable from public writers. Not a blocker.
- **SAVEPOINT ownership.** `_write_batch` does persist →
  `set_current_decision` → derived status inside `grounded_review_v1`.
  No `commit`/`rollback` in store helpers. Caller `ROLLBACK` removes
  decision + pointer together.
- **Exact current tip.** `existing_review` prefers the pointer only
  when the payload is aligned (actor/reason/times/v1-or-v2 id) and
  `_review_matches` the current Task 4 cite set + grounding + waiver
  pack/defects. No `waivers[0]` / `ORDER BY` shortcut. Historical
  fallback requires `len(found) == 1`; else None.
- **No eligible twin.** `materialize_review` returns None when any
  decision already exists and lookup missed. `bind_family` quarantines
  `ungrounded`.
- **Member cites.** `stored_member_citations` keeps stored receipts
  whose (representation, span) is in current `citations`, revision
  matches, and run/selection/policy equal the current Task 2/3 link.
  Stale extras stay out. Approve still `require_grounding`.
- **No INSERT OR IGNORE.** Explicit INSERT / same-id no-op / CONFLICT.
  No hidden COMMIT on the review path.

## Prior five MAJORs — still closed

Hashes MATCH the code-recheck freeze. Mutants below re-killed each
decision.

## GREEN (once each)

```
focused 25:
tests/test_step7_security_repair_2.py tests/test_step7_security_members.py
tests/test_step7_review_repair.py tests/test_step7_citation_bind.py
tests/test_step7_tampered_non_approval.py tests/test_step7_h1_existing.py
25 passed. EXIT:0
```

```
owner+integration+repair+sec2: 124 passed. EXIT:0
```

```
affected research/extractor/kgstore/cli/server/migration
+ identity/H1/repair/sec2: 157 passed. EXIT:0
```

```
basedpyright <21 changed Python>
0 errors, 0 warnings, 0 notes. EXIT:0
```

Starlette/httpx deprecation only. No full suite. No retry-to-pass.

## Isolated mutants (apply_patch reverse)

| # | Decision | Mutant | Kill | Restored |
|---|---|---|---|---|
| 1 | pointer in SAVEPOINT | `conn.commit()` around `set_current_decision` | `no such savepoint: grounded_review_v1` | `74500401…` |
| 2 | no first-tip | `return waivers[0]` | same-cite different-scope linked smaller other | `bd36a80d…` |
| 3 | no all-fact union | `stored_member_citations` return all stored | waiver/reject digest included stale | `187df60d…` |
| 4 | chunk family | cross-run `ORDER BY receipt_id` | live chunk ∉ linked | `f477b557…` |
| 5 | citation mint | skip existing + covering scan + LEGACY | linked empty ≠ live cite | `f477b557…` |
| 6 | selection unique | policy `fetchone` | `selection_run_receipt` not None | `1c5f63d5…` |
| 7 | live bind | `created_ts DESC` / no AMBIGUOUS | persist did not raise | `b045f72b…` |
| 8 | exact review tip | skip `existing_review` | linked empty (history-exists quarantine) | `d23dec0f…` |

Post-restore: 21/21 SHA-256 MATCH.

## Residuals (not blockers)

- `grounded_review_current.receipt_id` has no FK. Enforce at write
  time or add the constraint when next touching schema.
- `_citation_binding` / `containing_chunk` still covering-scan *on the
  current run*.
- `selection_policy` still latest selection by `created_ts`.
- Extractor still omits explicit Task 2 ids (multi-run extract now
  `AMBIGUOUS` instead of aliasing).
- Review SAVEPOINT still leaks on unexpected exceptions.

## Protected-boundary cleanup

- Did not read or write `~/Library/Application Support/ontologylab/`.
- Did not use external network.
- Did not bind, kill, or retarget port 8799 or PID 55560.
- Did not open denylist modules.
- Did not commit. Product/test bytes left at the freeze hashes above.
- This report is the only write.

RECOMMENDATION: APPROVE
CODE_QUALITY_STATUS: PASS
BLOCKERS: none
COMMIT: 5a6378964bfc41fe2a679453a88235c548a59f4b (unchanged)
FREEZE: 21/21 SHA-256 MATCH after mutants
SUITE: focused 25 / owner 124 / affected 157 / basedpyright 0
