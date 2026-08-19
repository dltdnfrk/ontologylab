# Gate review — OntologyLab ulw-loop close

Adversarial audit of `evidence/ulw-loop/gate/code-review.md` and
`evidence/ulw-loop/gate/qa-verify.md`, sampled against the 12 goal
artifacts, `.omo/ulw-loop/goals.json`, the live process/tmp inventory,
and `git diff` of the three intended files. Read-only except this
report. Port 8799 was not bound. PID 55560 was not signalled.

This is an attack, not a recap. Holes that do not block close are
listed under residual risks.

---

## 1. Code-review APPROVE — inspected, not an ack

The reviewer read the working-tree delta and cited live lines that
still match the files.

- Binding they judged (`code-review.md` §1, citation `routes.py:499-504`)
  is exactly the current handler: decorator at 499, `body: InvalidateAction`
  at 500, `store.invalidate_edge(edge_id, by=body.by, reason=body.note)`
  at 504. Verified against `ontologylab/server/routes.py`.
- They quoted the dashboard contract at `web/app.js:3359-3360`
  (`{ note: "invalidated via dashboard" }`). That pair is still there.
- They quoted `ProposalAction` as byte-identical at `schemas.py:202-208`
  and the new `InvalidateAction` fields at `schemas.py:218-219`. Both
  match. `ProposalAction` consumers remain at `approve_proposal` 482,
  `reject_proposal` 515, `reopen_proposal` 529 — they cited 481-486 /
  514-518 / 528-537; off-by-one on the decorator, right functions.
- Store write they cited (`kgstore.py:2826-2831`, `2854-2858`) is still
  the parameterized `UPDATE edges … WHERE id = ?`.
- They named the *other* dirty hunks in `routes.py` (`list_packs` →
  `scan_packs` / `unusable`) as out of scope instead of pretending the
  file only contains the invalidate fix. That is the opposite of an ack.
- They ran `.venv/bin/python -m pytest tests/test_bitemporal.py -v`
  (10 passed) and imported the module to confirm the annotation.

Not a rubber stamp. The APPROVE is earned for the scoped delta.

## 2. QA mutation — independently reproduced

`qa-verify.md` §2 is a first-person cycle, not a restatement of
`g002-mutation.txt`.

- Pre-mutation sha256 `b9640a525bfedecf5b9db668f21ca2003f28fef28dae0f5713f685ed67ac2107`
  with `body: InvalidateAction`.
- Snapshot to `/private/tmp/gate-verify.py` (worker used
  `/private/tmp/g002-routes.py` — different path).
- `git checkout HEAD` → sha256 `f689be95…`, signature
  `body: ProposalAction`.
- Pytest of the two contract tests: both 422, same assertion lines
  (`test_bitemporal.py:233` / `:260`) and the same
  `loc:["body","id"]` detail.
- Restore via `cp`; `diff -q` RC 0; sha256 restored.
- Post-restore: 7 invalidate tests passed (worker restored to 2).
- Live curl on a *fresh* KG (`EDGE_ID=7aa9478a…`, port 53284, PID 86198)
  returned 200 `ok:true` with note `gate-verify`. That is not the
  worker's `g004-curl.txt` (port 54231, id `34ee5772…`).

Independent reproduction of revert → 422 → byte-identical restore →
green. Plus a second real-surface POST.

## 3. Twelve goal artifacts — present; no PASS/status lie

All of `g001-red.txt` … `g012-newprobes.json` exist and are non-empty.
The five JSON files parse. Extra `g003-fullsuite.log` is present.

| artifact | recorded PASS claim | captured status / body | consistent? |
|---|---|---|---|
| g001-red.txt | both tests 422 on missing `body.id` | `assert (422 == 200)` + `Field required` | yes |
| g002-green.txt | invalidate 7 passed; focused 56 passed | those two summaries | yes |
| g002-mutation.txt | revert 422; `diff -q` identical; restore 2 passed | all three sections present | yes |
| g003-fullsuite.log | 2288 passed, 0 failed | `2288 passed, 6 skipped, 1 warning in 960.84s` | yes |
| g004-curl.txt | POST `{note}` → 200 + sqlite | `HTTP/1.1 200 OK`, `ok:true`, reason `superseded`; 400/404/200 battery | yes |
| g005-f6.json | three busy clicks → 503, unlocked → 200 | raw `httpStatus` 503 then 200; `durableRowUnchanged` then invalidated/merged/dismissed | yes |
| g006-f1ui.json | terminal `.badge.st-failed`, no `추출 완료!` | badge class captured; success string count in artifact = 0; job 200/`failed` | yes |
| g007-f5.json | two 422 surfaces, `[object Object]` zero | both `httpStatus` 422; three `object_object_*_zero` flags true | yes |
| g008-f7ui.json | 200 + 3 unusable + no phantoms | packs/mcp 200; `phantom_pack_rows_empty` true | yes |
| g009-f4.md | tampered A refused; B hash unchanged | `isError:true` hash mismatch `a43aec…` vs `5937c6…`; B stays `71de399a…` | yes |
| g010-f3.md | 7× `-32602`, then valid calls | all 7 error code `-32602`; post-battery lookup/graph succeed | yes |
| g011-f1f2.txt | jobs 200/`failed`, secret count 0, provenance has secret | jobs body has neither `SYNTHETIC_SECRET` nor `example.invalid`; provenance excerpt has both | yes |
| g012-newprobes.json | ≥3 probes | (a) 200 then 400; (b) 503; (d) `.badge.st-complete`. All PASS | yes |

`G011` is the only goal still `pending` in `goals.json`; all three of
its criteria are already `pass`. That is the expected "waiting on this
gate" state, not a missing artifact.

No PASS artifact claims HTTP 200/503 and then captures something else.

## 4. Leftovers the receipts claimed gone — gone

Live check this gate:

- Claimed server/controller PIDs all absent: 61263, 72379, 84290,
  81607, 95530, 97457, 97511, 44138, 78950, 86198.
- Claimed ephemeral ports all free: 53284, 54231, 52122, 49607, 50122,
  64374.
- Claimed trial dirs gone: `/private/tmp/ulw-trial-1`, `-2`, `-3`,
  `-3b`, `/private/tmp/ulw-g004`, `/private/tmp/gate-verify*`,
  `/private/tmp/g002*`.
- Only `ontologylab.serve` still running is protected PID 55560.
- QA's own `/private/tmp/gate-verify.py` is gone.

Aside.app has many long-lived renderer processes (user session since
Wed). Cleanup receipts claimed *their* trial tabs closed (`after: 0`);
there is no leftover listener or serve process pointing at a trial
port that would make those tabs still drive a disposable server.

## 5. Protected 8799 / Application Support — not touched

- `lsof -nP -iTCP:8799 -sTCP:LISTEN` → only PID 55560.
- PID 55560 still the original command
  `--port 8799 --data-dir /Users/hyunjun/Library/Application Support/ontologylab/data`
  with elapsed 10+ days. Not restarted this run.
- PID 70970 (`uvicorn search_server` :8400) likewise untouched.
- `kg.sqlite` mtime 2026-08-08; no file under Application Support
  `ontologylab/` has mtime within the last two days.
- G011 `PROTECTED_BEFORE` / `PROTECTED_AFTER` blocks are identical.

No evidence anyone wrote the real data dir or rebound 8799.

## 6. Working-tree scope

This-run product delta is the three intended files:

- `ontologylab/server/schemas.py` (`+InvalidateAction` only)
- `ontologylab/server/routes.py` (import + `InvalidateAction` binding;
  file also still carries the older `scan_packs`/`unusable` hunks)
- `tests/test_bitemporal.py` (contract rewrite + new test)

`routes.py` mtime 2026-08-17 01:44 is the QA mutation restore, not a
new product edit. `schemas.py` / `test_bitemporal.py` mtimes are Aug 16.

Other dirty product files (`extractor.py`, `mcp_*.py`, `packbuilder.py`,
`jobs.py`, `web/app.js`, several tests) have Aug 15 mtimes and were
called out by the code reviewer as prior remediation. They are not
silent this-run edits. Untracked evidence under `evidence/ulw-loop/`
is expected.

---

## Holes that do **not** block close

1. **`g004-curl.txt` has no cleanup section.** C003 (non-essential)
   claims PID 78950 / `/private/tmp/ulw-g004` / port 54231 in
   `capturedEvidence`, but the 617-byte artifact stops at the 200/400/404
   battery. The claimed state is true *now* (PID gone, port free, dir
   gone). Missing receipt, not a live leftover.
2. **`g002-green.txt` has no LSP / `git diff --check` section** that
   G002-C003 (non-essential) said it would. Code review independently
   imported the module and ran the file.
3. **G003-C001 expected `g003-focused.txt`.** The 56-passed summary
   lives inside `g002-green.txt` instead. Content exists; the named
   file does not.
4. **Pre-existing `/private/tmp/ulw-*` scratch** still on disk
   (`ulw-ckpt.json`, `ulw-handoff.json`, `ulw-proposals-*.json`,
   `ulw-steer-out.json`, `ulw-g003-fullsuite.log`, empty `ulw-qa*`).
   QA recorded these and correctly refused to delete them under a
   read-only constraint. They are not the trial fixtures the cleanup
   receipts claimed removed.
5. **G005 `lockVerifyAfterRelease` was still locked**
   (`held:true`, `contender_error:"database is locked"`). The artifact
   documents this as transient connection unwind; `finalLockVerifyBeforeClose`
   and `cleanup.lock_final` both show released, and the unlocked retries
   are HTTP 200. Internally consistent, slightly sloppy lock sampling.
6. **G012 skipped example probe (c)** (pack-diff dropdown). Goal asked
   for ≥3 probes and listed (a)(b)(c)(d) as examples. (a)(b)(d) ran
   and passed. Not a shortfall.
7. **`routes.py` still mixes this fix with prior `scan_packs` hunks.**
   Reviewer scoped them out. A later commit that stages the whole file
   will ship both. That is a commit-hygiene risk, not a gate-close
   defect.
8. **Redundant-`id` test asserts only HTTP 200** (`test_bitemporal.py:307-308`),
   as the reviewer already noted. Persistence of `note` is covered on
   the first request.

None of these contradict a recorded PASS, leave a live serve/tmp/tab,
or show the protected server was touched.

---

VERDICT: PASS
QUALITY_GATE: passed
