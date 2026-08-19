# Adversarial re-trial — invalidate 422 fix + F1–F7 remediation (2026-08-17)

- Repo: `/Users/hyunjun/Documents/MUNI/ontologylab`
- Base: `0108c370` ("ci: allow executable audit runner variance")
- No commit made. Port 8799 / PID 55560 untouched (verified LISTEN, not signalled).
- Real Application Support data dir untouched; every run used a disposable
  `/private/tmp/olab-cs-*` root.
- Aside CLI `1.26.717.1619` located at `/Users/hyunjun/.local/bin/aside`
  (symlink → `~/.aside/cli/Aside CLI.app/Contents/MacOS/aside`).

## Verdict

**AMBER — the invalidate fix is real and F1–F7 hold on every gate I could
execute, but two new defects were found and one gate class is unverified.**

| Item | Verdict | Basis |
|---|---|---|
| Task 1 invalidate `{note}`-only | **GREEN** | red→green→mutation, `g00` |
| F6 busy-write honesty | **GREEN** | real `BEGIN IMMEDIATE`, `g01` |
| F5 422 field+message | **GREEN** | real 422 replayed into real app.js, `g07` |
| F7 malformed pack advisory-only | **GREEN** | `g07` |
| F4 tampered pack refused | **GREEN** | real byte tamper over real stdio, `g03` |
| F3 malformed MCP args → −32602 | **GREEN** | real subprocess JSON-RPC, `g03` |
| F1/F2 job↔durable, secret containment | **GREEN** | `g04` |
| F1-UI survivors named | **GREEN** | real `applyJobs` transition, `g07` |
| **N1 read starvation under write lock** | **RED (new)** | `g02` |
| **N2 `/api/engines` bare 500** | **RED (new)** | `g05` P8 |
| **N3 unbounded invalidation note** | **AMBER (new)** | `g05` P6 |
| Real-browser click path | **UNVERIFIED** | sandbox blocks all sockets |

## Method and its one hard limit

`aside repl` could not be used. The Aside daemon is genuinely running
(`127.0.0.1:21420 LISTEN`, browser PID 44555), but this execution sandbox
denies **every** socket operation — TCP loopback `connect`, `bind`, and even
`AF_UNIX` — all `PermissionError: Operation not permitted`. That also makes
binding an isolated server on `127.0.0.1:8803` impossible. I did not attempt
to tunnel around it.

What was used instead, and why it is not a fixture test:

- **Server/durable gates**: the real `create_app()` ASGI app over real
  sqlite, with durable state re-read on a **separate read-only connection**
  after every refusal — so a "refused" that nonetheless wrote would be caught.
- **MCP gates**: `python -m ontologylab.mcp_server` spawned as a **real
  subprocess** driven over **real stdio pipes** with newline-delimited
  JSON-RPC — the surface an agent actually connects to.
- **UI gates**: the real `web/index.html` + `ui-utils.js` + `localize.js` +
  `chat-session.js` + `app.js` loaded into a real DOM (jsdom 22/node
  v22.17.1), answering `fetch()` with **responses captured verbatim from the
  live server** (`g06`). `web/app.js` was never modified.

Discipline held throughout: **no fixed sleeps** (a `MutationObserver` +
deadline settles every UI assertion, and the sqlite lock is proven held by
making an independent contender's `BEGIN IMMEDIATE` fail *before* any request
is issued), and **no loading placeholder accepted as success** (assertions
require terminal text).

## Task 1 — the 422

At base the route bound `ProposalAction`, whose `id` is required, while
`web/app.js` posted `{note}` only. Every dashboard invalidation was a 422 and
no invalidation ever landed.

- **RED/mutation**: reverting the binding to `ProposalAction` reproduces
  `422 {"loc":["body","id"],"msg":"Field required"}` and fails both tests.
- **GREEN**: with `InvalidateAction` (no `id`), the `{note}`-only request is
  200 and `invalidated_ts` / `invalidation_reason` are durably set.
- **Scope**: `ProposalAction` remains bound on `/proposals/approve|reject|reopen`;
  `web/app.js` untouched (mtime `2026-08-15 09:01:29`, predates this session).

## New findings

### N1 — RED: reads starve for 31s under a write lock, then advise "retry in 2"

`KGStore.open()` runs `BEGIN IMMEDIATE` to apply migrations even for read
paths, so read-only screens contend with any writer. Measured under a held
lock (`g02`):

| endpoint | status | elapsed |
|---|---|---|
| `/api/proposals` | 503 | **31.0 s** |
| `/api/merge/candidates` | 503 | **31.1 s** |
| `/api/packs` | 200 | 0.17 s |
| `/api/jobs` | 200 | 0.002 s |

The refusal is honest and leaks nothing, but the operator waits ~31 s (sqlite
`timeout=30.0`) for a screen that then says "try again in 2 seconds". The
Review and Merge screens are exactly the ones F6's controls live on. F6's own
contract is unaffected — writes still refuse correctly and never partially
apply, including under five rapid repeat clicks.

### N2 — RED: `/api/engines` answers a bare 500 on an unreadable PATH dir

`engines.resolve_cli()` stats six fixed candidate directories
(`~/.npm-global/bin`, `~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`,
`~/.bun/bin`, `~/.volta/bin`) with an unguarded `Path.is_file()`. A candidate
directory that exists but is not traversable raises `PermissionError` straight
out of the route as `500 Internal Server Error`.

Confirmed reachable **without** the sandbox: with `HOME` pointed at a clean
tree and one candidate dir at mode `000`, the call raises
`PermissionError: [Errno 13] Permission denied`. Guarding the stat with
`OSError` would make availability report `False` instead of failing the screen.

### N3 — AMBER: a 200 KB invalidation note is stored whole

`POST /api/edges/{id}/invalidate` with a 200,000-character `note` returns 200
and writes all 200,000 characters into the durable `invalidation_reason` audit
column (`g05` P6). No crash and no corruption, but `InvalidateAction.note`
carries no `max_length` while comparable fields elsewhere in `schemas.py` are
bounded (e.g. `override_intent` at 500).

## New hostile probes (6, beyond the F1–F7 checklist)

| ID | Probe | Result |
|---|---|---|
| P4 | a body `id` cannot redirect a path-addressed invalidate (confused deputy) | PASS |
| P5 | double invalidation is a typed 400, not a fake success; reason not overwritten | PASS |
| P6 | 200 KB audit note | **FAIL** → N3 |
| P7 | NUL/CRLF log-forging chars in the audit reason keep the row readable | PASS |
| P8 | `/api/engines` under an unreadable PATH candidate dir | **FAIL** → N2 |
| P9 | swapping in a **valid but foreign** `pack.sqlite` is still refused | PASS |

P9 matters beyond F4: it shows the receipt binds *these bytes*, not merely
"a well-formed sqlite", so a substitution attack with a legitimate database
cannot satisfy the gate.

## Negative controls — every gate proven able to fail

A gate that cannot fail is not evidence. Each control reintroduced the
original defect and confirmed the gate flips to FAIL (`g08`):

- **NC1 (F5)**: old per-call-site interpolation renders the real 422 as
  `빌드 실패: [object Object]` — the original bug, reproduced from the same
  captured response.
- **NC2 (F6)**: old `res.ok === undefined` guard does **not** throw on the
  real 503 body — the silent-success path.
- **NC3 (F1-UI)**: removing the `failed` branch renders nothing, so survivors
  go unreported.
- **F4 integrity check**: mutating the good pack after the baseline hash flips
  `good_pack_bytes_unchanged` to FAIL (this check was itself a tautology on
  first write — `sha(x) == sha(x)` — and was corrected).

## Corrections made to my own harness

Recorded because they changed conclusions, not just code:

1. `good_pack_bytes_unchanged` compared a hash to itself. Fixed to capture a
   baseline before tampering, then proven to discriminate.
2. I first scored `entity_lookup {}` → `isError` as an F3 failure. The
   advertised schema has `required: []`, so `{}` **is** schema-valid and a
   typed `isError` is the correct contract; `-32602` would be wrong. My
   expectation was at fault, not the product — probe withdrawn.
3. An incidental discovery while building the F4 negative control: the MCP
   server **refuses to boot** when its `--pack` startup pack is tampered
   (child exits, broken pipe) rather than serving unverified bytes.

## Unverified — stated, not papered over

The real-browser click path (a human pressing 무효화 / 유지 / 중복 아님 in
Aside Chromium, and the resulting repaint) is **not** verified here. The
underlying contracts are: the server refuses with a shaped `{ok:false,
error_kind:"busy"}` 503 + `Retry-After`, the shipped `throwIfRefused` throws
on that exact body and passes the real 200, and the message reaches the
operator with the retry seconds appended. What remains unproven by me is
only that a real click reaches those functions and that the panel repaints
as expected. That gap needs an out-of-sandbox `aside repl` run.

## Artifacts

- `g00-task1-red-green-mutation.txt` — Task 1 defect / mutation / green / scope
- `g01-f6-busy.json` — F6 under a real `BEGIN IMMEDIATE` lock
- `g02-f6-readlatency.json` — N1 read-starvation measurement
- `g03-f4-f3-mcp.json` — F4 + F3 over a real MCP subprocess
- `g04-f1-f2.json` — F1 job↔durable, F2 secret containment
- `g05-new-probes.json` — the 6 new hostile probes
- `g06-ui-captured-server-responses.json` — verbatim live-server responses
- `g07-ui-trial-jsdom.json` — F5/F6/F7/F1-UI against the real dashboard
- `g08-ui-negative-controls.json` — defect-reintroduction controls
