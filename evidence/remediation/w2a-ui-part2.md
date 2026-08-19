# W2A part 2 — real-browser evidence for the two behaviors QA could not reproduce

Scope: **evidence capture only.** No source file, no test file, and no
`ontologylab/*.py` was modified by this task. The only file this task wrote
inside the repo is this artifact. Everything else it created lives under
`/private/tmp/w2b-qa` and was removed (receipts in §6).

A prior QA pass (`evidence/remediation/w2a-ui.md`) confirmed **F5** and **F7-UI**
in a real browser but explicitly declined to claim **F6** and **F1-UI**, because
both need server state that an empty data dir does not produce. This task builds
that state and drives the real UI.

| Behavior | Verdict |
|---|---|
| **F6** — busy write must not render as success (`mergeDismiss`) | **PASS** (browser-confirmed) |
| **F6** — same, via `invalidateEdge` | **NOT-REPRODUCIBLE — blocked by a separate genuine defect (§3)** |
| **F1-UI** — partial extraction failure must say survivors exist | **PASS** (browser-confirmed) |
| **NEW DEFECT** — `invalidateEdge` omits the required `id`; invalidation can never succeed | **GENUINE DEFECT (§3)** |

---

## 1. Environment

Two fresh servers, both on ephemeral ports with disposable data dirs under
`/private/tmp`. The real data dir (`~/Library/Application Support/ontologylab/data`)
was never opened. Port 8799 was never bound (each ephemeral port was asserted
`!= 8799` at allocation). PID 55560 and PID 70970 were never signalled.

```
Server A (F6)      PORT=64123  PID=98030
                   --data-dir /private/tmp/w2b-qa/data
                   --packs-dir /private/tmp/w2b-qa/packs
                   .venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 64123 …

Server B (F1-UI)   PORT=49645  PID=32221
                   data-dir /private/tmp/w2b-qa/data2, packs /private/tmp/w2b-qa/packs2
                   /private/tmp/w2b-qa/serve_partial.py  (shipped create_app; only
                   jobs_module.get_engine patched — see §4)

Lock coordinator   PORT=64909  PID=10230   /private/tmp/w2b-qa/coord.py
```

### Seeding (project's own factories, no hand-written SQL for graph objects)

`/private/tmp/w2b-qa/seed.py` uses `tests.factories.make_entity/make_relation`
plus `KGStore.insert_document` / `insert_proposed` / `approve` — the same
sequence as `tests/test_bitemporal.py::_seed_verified_edge`:

```json
{"doc_id": "bd88c5afcb5c48a283565f0169cb5a2c",
 "entity_id": "b1a86ef2bee54c1695c85e632c3f0c62",
 "other_id": "c1421431e661416d8a223d42d9893ea0",
 "edge_id": "95a458b50b714ee9ba70bfb63ff3aa3d",
 "edge_status": "verified", "edge_invalidated_ts": null}
```

A pending merge candidate was seeded with `KGStore.record_merge_candidate`
(`a2879eeae9f142dabd32edb8be08e9ba`, score 0.91).

### How the write lock was held

`coord.py` opens a **separate** sqlite3 connection to the same file, runs
`BEGIN IMMEDIATE` plus a real (no-op-row) `UPDATE`, and holds it until released
over HTTP. It is driven over loopback because the browser cannot touch the
filesystem, and the lock must be taken **after** the panel has loaded:
`KGStore.open` takes `BEGIN IMMEDIATE` for migrations even on read paths, so a
lock held during load blocks `/api/search` itself. Measured directly:

```
$ time curl -s -m 40 "http://127.0.0.1:64123/api/search?q=ApiGateway&limit=8"
{"ok":false,"error_kind":"busy","detail":"The knowledge base is busy — …"}
real  0m31.877s
```

That is why the first locked attempt returned `no-palette-hit`: the read that
populates the palette was itself waiting out the busy timeout. The final scripts
therefore sequence: **load unlocked → acquire lock → click → observe → release.**

### Waiting discipline

Every wait is a `MutationObserver` predicate (`window.__qaWait`) with a bounded
timeout. No fixed sleep gates any assertion. No assertion is read off the
`불러오는 중…` placeholder — `loading-placeholder-gone` is an explicit predicate
in the F6 runs, and the F1-UI terminal predicate requires a terminal
`.badge.st-(failed|complete|cancelled)`, never a substring that the running
badge could satisfy. (An earlier draft matched the substring `실패`/`중단` and
falsely settled on the running badge `실행 중`; that draft's output is *not*
used as evidence and the predicate was tightened before the recorded run.)

The one-second loop in the F1-UI/merge drivers polls a value the **page**
already resolved via MutationObserver; it exists only because a single CDP
`evaluate` call caps at ~30 s while SQLite's busy timeout is also ~30 s. It
gates nothing — the DOM verdict was decided by the observer.

---

## 2. F6 — busy write must not render as success

### 2a. `mergeDismiss` — **PASS**

The `중복 아님` button on the Merge screen was clicked with the exclusive write
transaction **verifiably held at click time and still held when the response
landed** (`statusBeforeClick`, `statusAfterClick`, `statusAtResponse` all
`{"held":true}`).

Raw Aside capture (`F6MERGE2`, verbatim):

```json
{"step1":{"loaded":{"label":"merge-cards-loaded","ok":true},"cardCount":1,"cardsTextHead":"점수 0.91이름 유사도PaymentGatewayAdapter 검토 대기타입: Component · 확신도: 0.90 · 인용: 1별칭: —속성: —1dfc9419856aPaymentGateway 검토 대기타입: Component · 확신도: 0.90 · 인용: 2별칭: —속성: —fda7a82c7fdf◀ “PaymentGatewayAdapter” 유지 “PaymentGateway” 유지 ▶ 중복 아님 ","buttonLabels":["◀ “PaymentGatewayAdapter” 유지","“PaymentGateway” 유지 ▶","중복 아님"],"foundDismissButton":true,"errHidden":true,"errText":""},"lock":{"acquire":{"held":true},"statusBeforeClick":{"held":true},"statusAfterClick":{"held":true},"statusAtResponse":{"held":true},"release":{"held":false}},"step3":{"clicked":true,"clickedAt":1786753205570},"pollRounds":{"settled":{"label":"dismiss-settled","ok":true},"netCount":1},"final":{"settled":{"label":"dismiss-settled","ok":true},"errHidden":false,"errVisibleComputed":true,"errText":"The knowledge base is busy — an extraction job is writing to it. Try again in a moment. — 2초 뒤에 다시 시도해주세요.","cardsChanged":false,"cardCount":1,"cardsTextHead":"점수 0.91이름 유사도PaymentGatewayAdapter 검토 대기타입: Component · 확신도: 0.90 · 인용: 1별칭: —속성: —1dfc9419856aPaymentGateway 검토 대기타입: Component · 확신도: 0.90 · 인용: 2별칭: —속성: —fda7a82c7fdf◀ “PaymentGatewayAdapter” 유지 “PaymentGateway” 유지 ▶ 중복 아님 ","emptyStateShown":false,"netCalls":[{"url":"/api/merge/candidates/a2879eeae9f142dabd32edb8be08e9ba/dismiss","method":"POST","requestBody":"{}","status":503,"retryAfter":"2","responseBody":{"ok":false,"error_kind":"busy","detail":"The knowledge base is busy — an extraction job is writing to it. Try again in a moment."}}]}}
```

Binary observables, all satisfied:

| Requirement | Observed |
|---|---|
| network status is the busy envelope | `status: 503`, `retryAfter: "2"`, `{"ok":false,"error_kind":"busy",…}` |
| a visible error/retry message is shown | `errHidden:false`, `errVisibleComputed:true` |
| the message names the cause **and** the wait | `"The knowledge base is busy — … — 2초 뒤에 다시 시도해주세요."` |
| **must NOT silently reload as success** | `cardsChanged:false`, `cardCount:1`, `emptyStateShown:false` — the candidate is still on screen |

The refused write also did not land in the database:

```
{'id': 'a2879eeae9f142dabd32edb8be08e9ba', 'status': 'proposed', 'decided_ts': None}
```

This is the exact old-bug shape (`ok === false` slipping past a
`res.ok === undefined` guard) confirmed fixed on the real surface: the 503
envelope produced an operator-visible refusal, the list did not refresh, and the
row did not change.

### 2b. `invalidateEdge` — **NOT-REPRODUCIBLE** (blocked by the §3 defect)

The busy path cannot be reached through the invalidate button, because the
request is rejected by FastAPI request validation **before** it ever touches
SQLite. With the lock verifiably held (`statusWhenClicked:{"held":true}`), the
real `무효화` click produced HTTP **422**, not 503:

```json
{"phase":"clicked-under-lock","lock":{"acquire":{"held":true},"statusWhenClicked":{"held":true},"release":{"held":false}},"before":{"panelVisible":true,"bodyTextHead":"ApiGateway 승인됨 Component · 확신도 0.90멘션 (1)w2b seed…>>>The ApiGat<<<eway uses the RateLimiter to shed load.…관계 (검토 대기 0건 · 승인 1건)승인됨 —[uses]→ RateLimiter (상대: 승인됨)무효화온톨로지 제안 검토","foundInvalidateButton":true,"errHidden":true,"errText":""},"after":{"errHidden":false,"errVisibleComputed":true,"errText":"id: Field required","panelBodyChanged":false,"bodyTextHead":"ApiGateway 승인됨 Component · 확신도 0.90멘션 (1)w2b seed…>>>The ApiGat<<<eway uses the RateLimiter to shed load.…관계 (검토 대기 0건 · 승인 1건)승인됨 —[uses]→ RateLimiter (상대: 승인됨)무효화온톨로지 제안 검토","stillShowsInvalidateButton":true},"log":[{"label":"palette-open","ok":true,"immediate":true},{"label":"palette-entity-row","ok":true},{"label":"entity-panel-loaded","ok":true},{"label":"invalidate-settled","ok":true},{"label":"invalidate-response-seen","ok":true,"immediate":true},{"label":"loading-placeholder-gone","ok":true,"immediate":true}],"netCalls":[{"url":"/api/edges/95a458b50b714ee9ba70bfb63ff3aa3d/invalidate","method":"POST","requestBody":"{\"note\":\"invalidated via dashboard\"}","status":422,"retryAfter":null,"responseBody":{"detail":[{"type":"missing","loc":["body","id"],"msg":"Field required"}]}}],"confirmSeen":1}
```

**Exactly what blocked it:** `_sqlite_operational_error` (the 503 producer) is an
exception handler on the *route body*. A 422 is raised by request validation
before the route body runs, so no SQLite call is ever attempted and the busy
handler is unreachable from this control. This is a property of the §3 defect,
not of the F6 fix — and the same guard is proven correct on the identical code
path by §2a, which uses the same `apiSend` → `throwIfRefused` → `retryHint`
chain.

Worth stating plainly, because it is the honest half of the result: the F6
**failure-honesty** behavior is still visibly correct here. The refusal was
surfaced (`errHidden:false`, text `"id: Field required"`) and the panel did
**not** reload as success (`panelBodyChanged:false`). What could not be captured
is the *busy-specific* 503 + `Retry-After` rendering through this particular
button.

---

## 3. GENUINE DEFECT (new, pre-existing, NOT fixed here)

**`invalidateEdge` in `web/app.js` never sends the required `id` field, so
invalidating a verified edge from the dashboard always fails with 422.**

`web/app.js` (current working tree, ~line 3358):

```js
var res = await apiSend(
  "/api/edges/" + encodeURIComponent(edgeId) + "/invalidate",
  { note: "invalidated via dashboard" }      // <- no `id`
);
```

`POST /api/edges/{edge_id}/invalidate` binds `body: ProposalAction`
(`ontologylab/server/schemas.py:202`), whose `id: str` is **required**. The edge
id is in the path, but the schema still demands it in the body. Compare the
sibling call site `act()` (approve/reject), which does send
`JSON.stringify({ id: id, cascade: … })`.

Reproduced in the real browser **with no lock at all** (control run, so
contention is excluded as a cause) — `F6RESULT` baseline:

```json
{"phase":"clicked","before":{"lockHeld":false,…,"foundInvalidateButton":true,"errHidden":true,"errText":""},"after":{"errHidden":false,"errVisibleComputed":true,"errText":"id: Field required","panelBodyChanged":false,…,"stillShowsInvalidateButton":true},…,"netCalls":[{"url":"/api/edges/95a458b50b714ee9ba70bfb63ff3aa3d/invalidate","method":"POST","requestBody":"{\"note\":\"invalidated via dashboard\"}","status":422,"retryAfter":null,"responseBody":{"detail":[{"type":"missing","loc":["body","id"],"msg":"Field required"}]}}],"confirmSeen":1}
```

And at the API level:

```
$ curl -s -i -X POST ".../api/edges/95a458b50b714ee9ba70bfb63ff3aa3d/invalidate" \
    -H 'Content-Type: application/json' -d '{"note":"invalidated via dashboard"}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["body","id"],"msg":"Field required"}]}
```

The edge is provably never invalidated:

```
{'id': '95a458b50b714ee9ba70bfb63ff3aa3d', 'status': 'verified',
 'invalidated_ts': None, 'invalidation_reason': None}
```

**Pre-existing, and not introduced by the W2A fix.** The line is byte-identical
in `HEAD` (`git show HEAD:web/app.js` line 3215), and the W2A diff for this hunk
only replaces the guard, carrying `{ note: … }` through as unchanged context:

```diff
@@ -3214,10 +3359,10 @@
         "/api/edges/" + encodeURIComponent(edgeId) + "/invalidate",
         { note: "invalidated via dashboard" }
       );
-      if (res && res.ok === undefined && res.detail) throw new Error(res.detail);
+      throwIfRefused(res);
```

**Why the test suite did not catch it:**
`tests/test_ui_failure_honesty.py::test_a_busy_refusal_is_surfaced_and_not_reloaded_as_success`
stubs `apiSend` (`_send_stub(BUSY, status=503, …)`), so the request body is
never validated against the real schema and the endpoint is never reached. The
test pins the *guard*, which is genuinely fixed; it cannot see that the *request*
is malformed.

Not fixed here, per task scope. Two candidate remedies for whoever picks it up:
send `{ id: edgeId, note: … }` from `invalidateEdge`, or give the route a body
schema that does not require an `id` already present in the path. The second is
the better shape — the id is in the path, and `ProposalAction` is the wrong
schema for a path-addressed action — but that is a route change, so it needs its
own decision.

---

## 4. F1-UI — partial extraction failure must say survivors exist — **PASS**

Induced with the technique from `tests/test_partial_chunk_failure.py`
(`_FailSecondChunkOnce`) against a **live server**: `serve_partial.py` patches
only `jobs_module.get_engine` and otherwise runs the shipped `create_app`,
router, and `JobRegistry`. The document is the test's own 4-chunk
`"The PaymentGateway uses the DatabaseService. " * 800`
(`chunk_document` → 4 chunks, confirmed at seed time).

One deviation, stated explicitly: the mock engine sleeps 1.5 s per chunk.
`MockEngine` answers in microseconds, so the whole job finished in ~21 ms —
before the dashboard's first `/api/jobs` poll. The UI never observed `running`,
so the `running → failed` transition in `applyJobs` (which renders the verdict
banner) never fired. The sleep models per-chunk engine latency that any real
CLI/API engine has; it changes no outcome, only makes the already-produced
transition observable. Durable state below is identical to the unslowed run.

The **real extraction form** was driven: Sources tab → open the
`추출만 다시 돌릴래요` `<details>` → click `#extract-submit`.

Raw Aside capture (`F1UI`, verbatim):

```json
{"step1":{"engineReady":{"label":"engine-options","ok":true},"engineOptions":["mock","claude","codex","gemini"],"detailsOpen":true,"boxTextAtSubmit":"추출 시작 중…"},"poll":{"done":{"label":"extract-terminal-render","ok":true},"boxHidden":false,"boxText":"실패 extraction engine failed — 그래도 여기까지 나온 제안은 남아 있어요. 개념 +2/~4 · 관계 +2/~1. 위 추출 양식으로 나머지를 다시 돌릴 수 있어요. 검토 →"},"final":{"terminal":{"label":"extract-terminal-render","ok":true},"boxHidden":false,"boxText":"실패 extraction engine failed — 그래도 여기까지 나온 제안은 남아 있어요. 개념 +2/~4 · 관계 +2/~1. 위 추출 양식으로 나머지를 다시 돌릴 수 있어요. 검토 →","boxHtml":"<span class=\"badge st-failed\">실패</span> extraction engine failed — 그래도 여기까지 나온 제안은 남아 있어요. 개념 +2/~4 · 관계 +2/~1. 위 추출 양식으로 나머지를 다시 돌릴 수 있어요. <button type=\"button\" class=\"btn btn-primary\" data-goto=\"review\">검토 →</button>","saysSuccess":false,"saysFailed":true,"mentionsSurvivors":true,"saysNothingProduced":false,"offersReviewPath":true,"reviewButtonText":"검토 →","offersRetryHint":true}}
```

Rendered result box, verbatim:

> **실패** extraction engine failed — 그래도 여기까지 나온 제안은 남아 있어요.
> 개념 +2/~4 · 관계 +2/~1. 위 추출 양식으로 나머지를 다시 돌릴 수 있어요. **[검토 →]**

Binary observables, all satisfied:

| Requirement | Observed |
|---|---|
| must NOT show `추출 완료!` | `saysSuccess: false` |
| must not imply everything was lost | `saysNothingProduced: false`; `mentionsSurvivors: true` (`남아 있어요`) |
| must convey partial results survived | survivor counts rendered: `개념 +2/~4 · 관계 +2/~1` |
| must offer the review path | `offersReviewPath: true`, `[data-goto="review"]` → `검토 →` |
| must offer the retry path | `offersRetryHint: true` (`위 추출 양식으로 나머지를 다시 돌릴 수 있어요`) |
| status is honest | badge `st-failed` `실패` + `extraction engine failed` |

Durable state confirms this was a genuine **partial** failure, not a total one —
and that the banner's counts describe rows that really exist:

```
run:   [{'status': 'failed'}]
chunk  {'chunk_index': 0, 'status': 'succeeded', 'error_kind': None}
chunk  {'chunk_index': 1, 'status': 'failed',    'error_kind': 'engine_error'}
chunk  {'chunk_index': 2, 'status': 'succeeded', 'error_kind': None}
chunk  {'chunk_index': 3, 'status': 'succeeded', 'error_kind': None}
nodes 2
edges 2

/api/jobs → {'status': 'failed', 'error': 'extraction engine failed',
             'totals': {'nodes_new': 2, 'nodes_merged': 4,
                        'edges_new': 2, 'edges_merged': 1}}
```

Job status `failed` matches durable `extraction_runs.status` `failed`, the error
string matches the contract (`extraction engine failed`), and the 2 nodes / 2
edges written by chunks 0/2/3 survived the failure of chunk 1.

---

## 5. Files this task wrote

Inside the repo: **this artifact only.**

```
$ stat -f "%Sm %N" web/app.js ontologylab/server/app.py tests/test_ui_failure_honesty.py
2026-08-15 09:01:29 web/app.js                        (predates this session)
2026-08-14 19:58:19 ontologylab/server/app.py         (predates this session)
2026-08-15 08:45:20 tests/test_ui_failure_honesty.py  (predates this session)
```

This session began ~09:08; all three mtimes precede it. `ontologylab/graphify-out/`
was not touched, no pre-existing dirty file was modified, and no git commit was made.

---

## 6. Cleanup receipts

**DB lock released.** The coordinator reported `{"held": false}` after every run.
One intermediate run hit a CDP timeout and left the lock held; it was released
explicitly (`curl .../release` → `{"held": false}`) and re-verified before
continuing. Final state before teardown: `{"held": false}`.

**Aside tabs closed.** Every capture script ends with `await p.close()` and each
run printed `[system] last tab closed. page is now null.` +
`[system] no current open tabs in this session.` Independent final check below.

**Aside tabs — final independent check:**

```
$ aside repl "console.log('PAGE ' + JSON.stringify(page === null ? 'no-open-tabs' : page.url()));"
PAGE "no-open-tabs"
```

**Servers and coordinator terminated:**

```
$ curl -s http://127.0.0.1:64909/status
{"held": false}                      # lock released before teardown

$ kill 98030 ; kill 10230 ; kill 32221
SERVER_PID=98030  TERMINATED: YES    # ontologylab.serve, port 64123
COORD_PID=10230   TERMINATED: YES    # lock coordinator, port 64909
SERVER2_PID=32221 TERMINATED: YES    # serve_partial.py, port 49645

$ for p in 64123 64909 49329 49645; do lsof -nP -iTCP:$p -sTCP:LISTEN; done
port 64123: no listener
port 64909: no listener
port 49329: no listener              # first (unslowed) F1-UI server, killed earlier
port 49645: no listener
```

**Fixtures removed:**

```
$ rm -rf /private/tmp/w2b-qa
/private/tmp/w2b-qa REMOVED: YES
no w2b leftovers in /private/tmp
```

**Protected processes verified alive AFTER teardown:**

```
55560 .venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 8799 --data-dir ~/Library/Application Support/ontologylab/data …
70970 …/Python -m uvicorn search_server:app --host 127.0.0.1 --port 8400

$ lsof -nP -iTCP:8799 -sTCP:LISTEN
python3.1 55560 hyunjun 10u IPv4 … TCP 127.0.0.1:8799 (LISTEN)
```

**Protected processes untouched.** PID 55560 (port 8799) and PID 70970
(`uvicorn search_server:app`) were never signalled; no unrelated python process
was killed. Each ephemeral port was asserted `!= 8799` at allocation
(64123, 64909, 49329, 49645).
