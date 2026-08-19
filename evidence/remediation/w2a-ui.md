# W2A — UI failure-honesty fix: real-browser QA evidence

Scope: **evidence capture only.** The implementation (`web/app.js`) was already
written and independently verified before this session. No source file was
modified here — `web/app.js` was confirmed byte-identical to the prior worker's
capture (`diff -q web/app.js /private/tmp/w2a-app-fixed.js` → identical) and
`git status` shows no new modifications attributable to this run. The only file
created by this task is this artifact.

Defects under confirmation:

- **F6** — a busy 503 envelope `{ok:false, error_kind:"busy", detail:…}` must
  surface an error and must NOT silently reload as success (invalidateEdge,
  mergeAct, mergeDismiss).
- **F5** — a 422 validation body `{detail:[{type,loc,msg}]}` must render field +
  message, NEVER the literal `[object Object]`.
- **F1-UI** — a partially-failed extraction must state that results from
  successful chunks survived and offer review/retry; a TOTAL failure must not
  invent results.
- **F7-UI** — `/api/packs` and `/api/mcp/status` return
  `unusable: [{pack_dir, reason}]`; those entries must render as an advisory,
  NEVER as a pack row, NEVER as a pack-diff dropdown option, and must never get
  a copyable serve command.

---

## 1. Established mutation evidence (verbatim, captured by root)

Root ran the mutation check independently:

- `cp web/app.js /private/tmp/w2a_app.js && git checkout HEAD -- web/app.js`
- `.venv/bin/python -m pytest tests/test_ui_failure_honesty.py` -> `7 failed, 15 passed in 0.79s`
  Failures spanned all four defects, including:
  `test_a_busy_refusal_is_surfaced_and_not_reloaded_as_success[mergeDismiss-...]`,
  `test_no_call_site_interpolates_a_raw_detail`,
  `test_a_partial_extraction_failure_says_results_survived`,
  `test_an_unusable_directory_is_reported_somewhere_the_operator_looks`,
  `test_the_connect_screen_does_not_offer_a_command_for_a_broken_pack`
- restore -> `diff -q` byte-identical -> `22 passed in 0.70s`

The prior worker's own failing-first capture independently agreed:
`7 failed, 15 passed in 0.84s`.

Two independent runs of the same mutation (revert → fail, restore → pass) agree
on the same counts, so the test file is pinned to the fix rather than to the
repo's ambient state.

---

## 2. QA environment

Fresh server, ephemeral port, disposable data + packs dirs. The real data dir
(`~/Library/Application Support/ontologylab/data`) was never used, and port 8799
was never touched.

```
PORT=63235          (ephemeral, allocated by binding :0)
SERVER PID=80734
data-dir  = /private/tmp/w2a-qa2/data
packs-dir = /private/tmp/w2a-qa2/packs

.venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 63235 \
  --data-dir /private/tmp/w2a-qa2/data --packs-dir /private/tmp/w2a-qa2/packs
```

### Fixtures

| dir | shape | expected rejection branch |
|---|---|---|
| `good-pack` | valid manifest + sqlite with `nodes`/`edges`/`documents` | usable pack |
| `bad-a-no-packid` | manifest `{"counts":{}}` + dummy (non-sqlite) `pack.sqlite` | no usable `pack_id` |
| `bad-b-array-manifest` | manifest `[]` | manifest not a JSON object |
| `bad-c-broken-sqlite` | valid `pack_id`, truncated 120-byte `pack.sqlite` | sqlite not a usable pack DB |

`scan_packs` dry run confirmed each fixture lands in a *distinct* branch, so the
advisory is exercised across all three rejection paths rather than three copies
of one:

```json
PACKS ["good-pack"]
UNUSABLE [
 {"pack_dir": "bad-a-no-packid", "reason": "manifest.json has no usable 'pack_id'"},
 {"pack_dir": "bad-b-array-manifest", "reason": "manifest.json must be a JSON object, got list"},
 {"pack_dir": "bad-c-broken-sqlite", "reason": "pack.sqlite is not a usable pack database: database disk image is malformed"}
]
```

### QA method

Every capture drove the shipped page in a real browser via the Aside CLI:

```
TERM=dumb NO_COLOR=1 aside repl "const p=await openTab('http://127.0.0.1:63235/'); …"
```

All waits are **MutationObserver-based predicates** — no fixed sleeps. Each
predicate explicitly requires the loading placeholder `불러오는 중…` to be
**absent** before any assertion is read, and every capture reports
`loading_placeholder_present` so the reading cannot be a loading-state false
pass (the exact mistake that produced a false reading earlier in this project).

---

## 3. Raw Aside captures

### Observable 1 — Packs screen (advisory / phantom rows / dropdown)

```json
OBS1 {"loading_placeholder_present":false,"advisory_hidden":false,"advisory_headline":"열 수 없는 팩 폴더 3개","advisory_items":[{"pack_dir":"bad-a-no-packid","reason":"manifest.json has no usable 'pack_id'"},{"pack_dir":"bad-b-array-manifest","reason":"manifest.json must be a JSON object, got list"},{"pack_dir":"bad-c-broken-sqlite","reason":"pack.sqlite is not a usable pack database: database disk image is malformed"}],"pack_row_count":1,"pack_row_ids":["good-pack"],"phantom_pack_rows":[],"diff_a_options":[{"value":"good-pack","text":"good-pack"}],"diff_b_options":[{"value":"good-pack","text":"good-pack"}],"blank_dropdown_options":[],"unusable_in_dropdown":[],"advisory_text_snapshot":"열 수 없는 팩 폴더 3개아래 폴더는 팩으로 읽힐 수 없어서 목록과 비교에서 빠졌어요. 다시 빌드하거나 폴더를 치우면 이 안내도 사라져요.bad-a-no-packid — manifest.json has no usable 'pack_id'bad-b-array-manifest — manifest.json must be a JSON object, got listbad-c-broken-sqlite — pack.sqlite is not a usable pack database: database disk image is malformed"}
```

### Observable 2 — Connection / MCP screen (no serve command, no 500)

```json
OBS2 {"mcp_status_http":200,"mcp_status_ok":true,"server_unusable":[{"pack_dir":"bad-a-no-packid","reason":"manifest.json has no usable 'pack_id'"},{"pack_dir":"bad-b-array-manifest","reason":"manifest.json must be a JSON object, got list"},{"pack_dir":"bad-c-broken-sqlite","reason":"pack.sqlite is not a usable pack database: database disk image is malformed"}],"server_pack_ids":["good-pack"],"server_serve_commands":["python -m ontologylab.mcp_server --packs-dir /private/tmp/w2a-qa2/packs --pack good-pack"],"server_unusable_with_serve_command":[],"loading_placeholder_present":false,"mcp_error_hidden":true,"mcp_card_count":1,"mcp_card_pack_ids":["good-pack"],"advisory_hidden":false,"advisory_items":[{"pack_dir":"bad-a-no-packid","reason":"manifest.json has no usable 'pack_id'"},{"pack_dir":"bad-b-array-manifest","reason":"manifest.json must be a JSON object, got list"},{"pack_dir":"bad-c-broken-sqlite","reason":"pack.sqlite is not a usable pack database: database disk image is malformed"}],"advisory_copyable_controls":[{"tag":"CODE","text":"bad-a-no-packid"},{"tag":"CODE","text":"bad-b-array-manifest"},{"tag":"CODE","text":"bad-c-broken-sqlite"}],"advisory_buttons":[],"serve_command_text_mentions_unusable":[],"all_serve_command_code_blocks":["python -m ontologylab.mcp_server --packs-dir /private/tmp/w2a-qa2/packs --pack good-pack"]}
```

Supporting server-side check (same server, curl):

```
$ curl -s -o mcp.json -w "%{http_code}\n" http://127.0.0.1:63235/api/mcp/status
200
```

### Observable 3 — Pack name validation (`../outside`, F5)

The name was typed into the real `#pack-name` field and the real
`#pack-build-form` was submitted; the assertion reads the settled
`#pack-build-result` box after the in-flight `팩 빌드 중…` state is gone.

```json
OBS3 {"submitted_name":"../outside","result_box_hidden":false,"result_box_text":"name: Value error, invalid pack name '../outside': use only letters, digits, '.', '_', '-' (no path separators)","result_box_html":"name: Value error, invalid pack name '../outside': use only letters, digits, '.', '_', '-' (no path separators)","mentions_field_name":true,"mentions_message":true,"object_object_in_result_box":false,"object_object_in_page_text":false,"object_object_in_page_html":false,"object_object_occurrences_in_html":0}
```

Underlying 422 envelope (the array shape that used to stringify to
`[object Object]`):

```
$ curl -s -o build422.json -w "%{http_code}\n" -X POST \
    http://127.0.0.1:63235/api/packs/build \
    -H 'Content-Type: application/json' -d '{"name":"../outside"}'
422
{"detail":[{"type":"value_error","loc":["body","name"],"msg":"Value error, invalid pack name '../outside': use only letters, digits, '.', '_', '-' (no path separators)"}]}
```

### Observable 4 — Stale state clears without a server restart

The three malformed dirs were deleted while the server kept running (PID 80734,
start time `Sat Aug 15 09:03:49 2026`, unchanged across the deletion), then the
page was reloaded.

```json
OBS4 {"server_unusable_now":[],"server_pack_ids_now":["good-pack"],"packs_advisory_exists":true,"packs_advisory_hidden":true,"packs_advisory_text":"","packs_advisory_li_count":0,"pack_row_count":1,"pack_row_ids":["good-pack"],"mcp_advisory_exists":true,"mcp_advisory_hidden":true,"mcp_advisory_text":"","mcp_advisory_li_count":0,"mcp_card_count":1,"stale_bad_dir_anywhere_on_page":[]}
```

---

## 4. PASS / FAIL per observable

- **Observable 1 — Packs screen advisory: PASS.** All three malformed dirs
  render in the advisory with both `pack_dir` and `reason`
  (`advisory_hidden:false`, headline `열 수 없는 팩 폴더 3개`, 3 items, each
  reason distinct). Phantom pack rows: **zero** (`pack_row_count:1`,
  `pack_row_ids:["good-pack"]`, `phantom_pack_rows:[]`). Pack-diff dropdowns
  contain only `good-pack` in both selects, with `blank_dropdown_options:[]` and
  `unusable_in_dropdown:[]`. Read against a settled DOM
  (`loading_placeholder_present:false`).

- **Observable 2 — Connection/MCP screen: PASS.** `/api/mcp/status` returned
  **200**, not 500 (`mcp_error_hidden:true`, no error path taken). Exactly one
  MCP card (`good-pack`), and the only serve command on the screen is
  `python -m ontologylab.mcp_server --packs-dir /private/tmp/w2a-qa2/packs --pack good-pack`.
  No unusable dir appears in any serve-command text
  (`serve_command_text_mentions_unusable:[]`), the advisory block contains
  **zero buttons** (`advisory_buttons:[]`), and its only copyable-looking
  elements are the three `<code>` pack_dir labels — no copy affordance, no
  stdio config, no serve command for a broken pack. Server-side,
  `server_unusable_with_serve_command:[]` confirms the envelope never carries
  one either.

- **Observable 3 — Pack name validation / `[object Object]`: PASS.** The form
  shows `name: Value error, invalid pack name '../outside': use only letters,
  digits, '.', '_', '-' (no path separators)` — field (`name`) **and** message,
  from a 422 whose `detail` is an array. The literal `[object Object]` appears
  **nowhere**: not in the result box, not in `document.body.innerText`, and not
  in `document.documentElement.innerHTML`
  (`object_object_occurrences_in_html:0`).

- **Observable 4 — Stale state clears on refresh, no restart: PASS.** After
  deleting the three fixtures and reloading with the *same* server process
  running, the server reports `unusable:[]` and both advisories collapse to
  hidden with zero items (`packs_advisory_hidden:true`,
  `packs_advisory_li_count:0`, `mcp_advisory_hidden:true`,
  `mcp_advisory_li_count:0`). No stale `bad-*` string survives anywhere on the
  page (`stale_bad_dir_anywhere_on_page:[]`), and the good pack still renders
  (1 row, 1 MCP card) — the advisory cleared without taking the real pack with
  it.

**Result: 4 / 4 PASS. No defect found.**

### Coverage note (honest scope limit)

Observables 1–4 exercise **F7-UI** (advisory / no phantom rows / no serve
command / stale clearing) and **F5** (`[object Object]`) on the real surface.
**F6** (busy-503 on invalidateEdge / mergeAct / mergeDismiss) and **F1-UI**
(partial extraction survivors) were *not* reproduced in the browser here: both
require a contended write and a partially-failed extraction job, neither of
which occurs against a freshly-seeded empty data dir without fabricating server
state. Their evidence remains the executed-function suite in
`tests/test_ui_failure_honesty.py` plus the mutation check in section 1, which
runs the shipped functions against a stub DOM rather than reading source text.
This artifact does not claim real-browser confirmation of F6 or F1-UI.

---

## 5. Cleanup receipts

**Aside tabs.** Each of the four capture scripts ended with `await p.close()`;
every run printed `[system] last tab closed. page is now null.` followed by
`[system] no current open tabs in this session.` Final independent check:

```
$ aside repl "console.log('PAGE ' + JSON.stringify(page === null ? 'no-open-tabs' : page.url()));"
PAGE "no-open-tabs"
```

**QA server.** PID **80734** on port **63235**, terminated:

```
$ kill 80734
$ ps -p 80734 -o pid,command
  PID COMMAND
TERMINATED: YES
$ lsof -nP -iTCP:63235 -sTCP:LISTEN
no listener on 63235
```

**Protected processes untouched.**

```
55560 /Users/hyunjun/Documents/MUNI/ontologylab/.venv/bin/python -m ontologylab.serve --ho…
70970 /opt/homebrew/Cellar/python@3.14/…/Python -m uvicorn search_server:app …
$ lsof -nP -iTCP:8799 -sTCP:LISTEN
python3.1 55560 hyunjun 10u IPv4 … TCP 127.0.0.1:8799 (LISTEN)
```

Port 8799 was never bound by this task; the ephemeral port was checked against
8799 before use.

**Fixtures and dead-worker leftovers removed.** `/private/tmp/w2a-qa2` (my
fixtures, data dir, packs dir, scripts, logs) plus the prior worker's leftovers:
`/private/tmp/w2a-app-fixed.js`, `/private/tmp/w2a-failing-first.txt`,
`/private/tmp/w2a-fullsuite.txt`, `/private/tmp/w2a-mutation-fixed.txt`,
`/private/tmp/w2a-mutation-unfixed.txt`, `/private/tmp/w2a-qa`. Everything
needed from them (the `7 failed, 15 passed in 0.84s` failing-first line, the
`22 passed` restored line, and the `app.js` byte-identity check) was copied into
this artifact before deletion. Removal receipt recorded in section 6.

**Source tree.** No source file modified, no git commit made. `web/app.js`,
`ontologylab/*.py`, and all test files carry only the pre-existing
modifications from the earlier remediation work.

---

## 6. Deletion receipt

```
$ ls -d /private/tmp/w2a-qa2 /private/tmp/w2a-qa /private/tmp/w2a-app-fixed.js \
        /private/tmp/w2a-failing-first.txt /private/tmp/w2a-fullsuite.txt \
        /private/tmp/w2a-mutation-fixed.txt /private/tmp/w2a-mutation-unfixed.txt
ls: /private/tmp/w2a-qa2: No such file or directory
ls: /private/tmp/w2a-qa: No such file or directory
ls: /private/tmp/w2a-app-fixed.js: No such file or directory
ls: /private/tmp/w2a-failing-first.txt: No such file or directory
ls: /private/tmp/w2a-fullsuite.txt: No such file or directory
ls: /private/tmp/w2a-mutation-fixed.txt: No such file or directory
ls: /private/tmp/w2a-mutation-unfixed.txt: No such file or directory
```
