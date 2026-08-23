# Task 7 security-repair-2 final recheck

Date: 2026-08-24
Rechecker: omo senpi-task `st_01a0306a`
HEAD: `5a6378964bfc41fe2a679453a88235c548a59f4b` (unchanged; no commit)
Claim: `task-7-security-repair-2.md` (treated as a claim; hashes, suites, mutants, and probes re-measured)
Constraint: no Application Support, network fetch, 8799, PID 55560, 9C, denylist, full suite, or product edit.

## Verdict

**PASSED**

Independent plants of colliding-time stale approve + smaller stale waiver, same-cite different-scope, and extra Citation rows now keep the live scoped waiver as the sole H1 review family (`pack_ineligible=1`, full payload). Indistinguishable tips quarantine; no eligible `approve` / pack-0 twin. Tampered approve stays `GroundingPreflightError` / HTTP 409 / zero-write. Reject / quarantine / compensate / CLI / real HTTP bind only current member cite ids, force pack 1, and update `grounded_review_current` in the same SAVEPOINT. Pointer rollback, same-id idempotency, and historical exact-unique fallback hold. All 8 named mutants die and restore.

## Bound freeze (post-mutant)

Working-tree SHA-256 MATCH the repair-2 table (rehashed after mutants):

| Path | SHA-256 |
|---|---|
| `ontologylab/citation.py` | `6050d74cb87cffca1143056ae5341ab455eab7bd33bdf9cad2674ce717d4ed80` |
| `ontologylab/citation_bind.py` | `b045f72bfb8623c75668b81a2f936c6f0629bb1cd3753ec3bf5092782fcc9e8c` |
| `ontologylab/citation_store.py` | `da42b2da42205cb57c92ba87fb675cec007f97244cb081bec675b81d250e3ce4` |
| `ontologylab/citation_types.py` | `1b3209c242ef87e38cd0e8046ad11ac2060c3ad0b4391af9c434990bae60ae78` |
| `ontologylab/grounded_review.py` | `745004019c0dcbdf84a6cf86875f2d9338e1410b124cd048d1d74bbacf2e5ca0` |
| `ontologylab/grounded_review_schema.py` | `9fc80b3b50e8391fd1dd4e9425ebf900710f5a9e91a59021c1076266902f30c5` |
| `ontologylab/grounded_review_store.py` | `bccd4f7d629b65af32dd36ebf748f0a313fd26f5ecdde441ce5cacc45053cd0d` |
| `ontologylab/grounded_review_members.py` | `187df60da17791aceda2a96b73e005aa08253e0cff9856bd0505ab74bd89566a` |
| `ontologylab/h1_classify_cite.py` | `1ad78d2c47a5939f5db94c14dfba7cbf95e6c3005bf27734e2345da76f76d1c6` |
| `ontologylab/h1_existing.py` | `1c5f63d5aa71f3aff935a976352710a5cfe08d904ec50b6a990c513c2cea2e98` |
| `ontologylab/h1_existing_review.py` | `bd36a80dc55871c389fb1da8210c54a314c36acfaa4a0928536aca786820c98a` |
| `ontologylab/h1_materialize.py` | `f477b557f0896ec3f4ee3b15d2095dd9d8635b8446e78711e07a5c00491e73d0` |
| `ontologylab/h1_materialize_review.py` | `d23dec0f34a08b9e4a6f9c1c365b0e7428e3a002303a1b82d5b35656f2379cee` |
| `ontologylab/h1_finalize.py` | `b7f803229239d9e5df8674779b82d1f950b71e723146005cdf86244f85aca2ad` |
| `tests/step7_valid_stale.py` | `10e71ed154ae6dee93263f244f7049dc8ae072cdece11e01482eaa8ffdc01d34` |
| `tests/test_step7_citation_bind.py` | `38f21a3ecd46f437993d735be80ef759d25945e91746bac65bc49295ddb8ffc2` |
| `tests/test_step7_review_repair.py` | `892fa15e8f810a78b795e09df19b206e4a74c58ffde47b6ac6f6b85f40f1a886` |
| `tests/test_step7_tampered_non_approval.py` | `40cf516b905082769a3d9d40f154c7ece1ce172ccb85cb7270c7e596dc30a3dd` |
| `tests/step7_sec2_support.py` | `5463a6729acf94b051bfb724d043ce745db6fd1927c8dbd9244ef1f32f2a12de` |
| `tests/test_step7_security_repair_2.py` | `d64ee3a90c17f8ba22e48868113262d0b34082fa337798601c4288cd0df813af` |
| `tests/test_step7_security_members.py` | `c8f7e4cc499bc36c6afeeaf1cc284332b8f09eb1e174c6171bf892650a89078c` |

Denylist unread/unopened/unimported (sizes only): 6279 / 1652 / 2229 / 6434 / 1928 / 5697.

## Independent probes

Disposable `/private/tmp/ontologylab-wave21-task7-sec-final` (deleted after). Library + installed CLI + real uvicorn `127.0.0.1:18447`.

### H1 exact current waiver

C-024 extract → stale run/cite → live scoped waiver → smaller colliding-time stale **approve** (`sha256:248dccc1…`) and stale **waiver** (`sha256:79dfae1b…`) sharing actor/reason/`decided_ts`.

| Check | Observed |
|---|---|
| Pointer | `grounded_review_current` = live `sha256:bcbef7cf87ac…` |
| Linked family | `{sha256:bcbef7cf87ac…}` verified |
| Stale ids | not linked |
| Eligible pack-0 approve | `[]` |
| Live cite set | only `sha256:e892a60b0379…` (stale extra absent) |
| Payload | action `approve_with_grounding_waiver`, pack 1, actor/reason/time, selection/policy/run, predecessor NULL, waived fact + `node:…:operator` defects |
| Pending | 0 |
| Source `h1_*` | `[]` (kg file hash drifted via `-wal`/`-shm` after backup API; not an H1 write) |
| Pass2 | receipt hash identical, `complete=true` |
| Same-cite other scope | live linked; smaller other unlinked; no eligible twin |
| Pointer deleted, unique history | live waiver still linked |
| Pointer deleted, two same-cite scopes | no family id; review `quarantined` / `ungrounded`; no eligible twin |
| Interrupt after 2 anchors / resume | durable 2; resume `pending=0` `complete=true` |

This is the prior recheck FAIL (minted `d462b033…` pack-0 twin). It does not reproduce.

### Tampered non-approval + pointer

| Surface | Observed |
|---|---|
| Library approve after +`X` ready bytes | `GroundingPreflightError: citation_ungrounded: invalid_hash: hash_mismatch`; status `proposed`; 0 rows |
| Library reject + stale extra cite | receipt; pack 1; cite set = live only (`sha256:e541da54…`); stale `sha256:53e1ece8…` absent; pointer = reject id; status `rejected` |
| Quarantine | pack 1; action `quarantine` |
| Compensate | pack 1; predecessor = quarantine id (pointer, not later-sorting stale) |
| SAVEPOINT rollback of `apply_review` | 0 decisions; pointer NULL |
| Same-id persist + `set_current_decision` | still 1 row; pointer unchanged |
| CLI `reject` | exit 0; prints stored `sha256:`; pack 1 |
| Real uvicorn `:18447` (startup Event; not 8799) | approve 409; reject 200; compensate 200; both pack 1; live cite set |

## Mutants (8; byte restore, not git)

Each: single-site replace → one focused test → restore from saved bytes. Post-restore MATCH freeze.

| # | Mutant | Kill | Restored |
|---|---|---|---|
| 1 | `return waivers[0]` before pointer | same-cite different-scope rc=1 | `bd36a80d…` |
| 2 | skip current-tip pointer | same-cite different-scope rc=1 | `bd36a80d…` |
| 3 | drop history-exists mint guard | ambiguity quarantine rc=1 | `d23dec0f…` |
| 4 | `_waive` via `citations_for` | waiver member-cite test rc=1 | `74500401…` |
| 5 | `stored_member_citations` `return stored` | tampered reject digest rc=1 | `187df60d…` |
| 6 | `ineligible = False` | tampered reject pack rc=1 | `74500401…` |
| 7 | `_should_require` always False | tampered approve zero-write rc=1 | `74500401…` |
| 8 | `conn.commit()` after pointer | pointer rollback test rc=1 | `74500401…` |

Mutant 5 first attempt (`return stored` only when the `citations` table is missing) stayed GREEN — that is not “return all stored”. The real early `return stored` after `list_stored_citation_receipts` died and restored.

## Suites (once each; no retry)

```
owner+integration+repair+sec2: 124 passed, 1 warning, 2.76s. EXIT 0
affected + identity/H1/repair/sec2: 157 passed, 1 warning, 7.78s. EXIT 0
basedpyright <21 changed Python files>: 0 errors, 0 warnings, 0 notes
```

Warning is third-party Starlette/FastAPI `httpx` deprecation. No full suite.

## Residuals (non-blocking)

- SQLite backup API can create/checkpoint `-wal`/`-shm` beside the source file. Source gained no `h1_*` tables and no review rows. Same class as prior H1 reviews.
- `grounded_review_current` is mutable by design (no append-only trigger). Integrity is the SAVEPOINT + pointer match, not an immutable tip table.
- Waiver `_review_matches` still accepts any nonempty `scoped_defects` once cites/grounding/time match. Discrimination of two same-cite scopes is the pointer (or unique historical fallback). Ambiguity without a pointer quarantines rather than minting.

## Protected-boundary cleanup

- No read/write of `~/Library/Application Support/ontologylab/`.
- No external network. Loopback only to disposable `127.0.0.1:18447`; listen gone after `should_exit` + join.
- Port 8799 / PID 55560 observe-only: DEVICE `0x1ff51c806b197195`.
- No 9C. Denylist unread.
- Disposable probe root and `/private/tmp/ontologylab-wave21-task7-sec-final.py` removed.
- No leftover product edits (freeze MATCH). No commit/push.

## Stop

Strict verdict: **PASSED**.
