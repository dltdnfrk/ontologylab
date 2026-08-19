# Aside CLI adversarial trial — 2026-08-14

## Verdict

**RED — do not call the browser acceptance fully green yet.**

The core pipeline is green: an isolated real server was driven through Aside
Chromium, a sample was collected and extracted, a human approved evidence,
immutable packs were built, and a sequential MCP stdio client discovered and
used the read-only tool surface. Host, cross-site, invalid-ID, path, and pack
immutability attacks did not alter accepted knowledge.

The release verdict is still red because a rejected pack name is rendered as
the literal string `[object Object]`. That fails the existing requirement that
an operator can diagnose a failed action from the product surface. The sample
collection screen also leaves its document list stale until the user navigates
away and back.

## Scope and topology

- Project: `/Users/hyunjun/Documents/MUNI/ontologylab`
- Branch/head tested: `fix/product-status-evidence` /
  `0108c370908ac1463e08c4063ec54e3dac37e2b3`
- Aside CLI: `1.26.717.1619` (update `1.26.810.1915` advertised)
- Isolated web server: `127.0.0.1:8801`
- Isolated data/packs root:
  `/private/tmp/ontologylab-aside-qa-c54f5d5f`
- Protected server: PID `55560`, port `8799`; not signalled or reused

`aside repl` was used as the deterministic real-Chromium driver. `aside mcp`
exposes the browser as an MCP server; it is not an MCP client for OntologyLab.
Accordingly, the trial verified both honest surfaces:

1. Aside Chromium drove OntologyLab's web UI.
2. The MCP command shown by that UI was exercised through an ordered stdio
   client against the generated immutable pack.

## Scenario matrix

| ID | Scenario and observable gate | Result | Evidence |
|---|---|---|---|
| A01 | Aside opens the isolated app | GREEN | URL `http://127.0.0.1:8801/`, title/H1 `온톨로지랩`, 11 tabs, 15 initial API resources |
| A02 | Clean sample insertion from the UI | GREEN | Initial document count `0`; success text names `샘플 — 우리 가게 주문 시스템`; reopening Sources shows one document |
| A03 | Inserted document appears without navigation | **RED** | Immediately after the success message, Sources still contained `0` rows; navigating Home → Sources revealed the row |
| A04 | Mock extraction completes through the UI | GREEN | Job `extract-2026`, status `완료`, concepts `+8`, relations `+7`, review badge `15` |
| A05 | Review exposes evidence and stable IDs | GREEN | 15 proposals; first relation `OrderApp → KitchenDisplay`, source excerpt visible; all 12 remaining proposal IDs and evidence links were present after approval |
| A06 | Human approval is authoritative | GREEN | Approving the relation reported `끝점 포함 3건`; stable state became concepts verified `2`, relations verified `1`, pending `6 + 6` |
| A07 | Packs contain only approved knowledge | GREEN | Both generated packs contain one document, two verified concepts, and one verified relation; the 12 pending proposals were excluded |
| A08 | MCP connection information is visible | GREEN | Aside Connection tab showed pack IDs, packs directory, and exact `python -m ontologylab.mcp_server --packs-dir … --pack …` commands |
| A09 | Real MCP initialize and read call | GREEN | Protocol `2024-11-05`; server `ontologylab/1`; 15 tools; `semantic_search("OrderApp")` returned one verified entity |
| A10 | Methodology compiler/MCP real-document proof | GREEN | 15 tools, four Method tools, zero forbidden tools, accepted-assumption bridge, source hash verified, pack bytes unchanged, no sidecars, process exited, cleanup absent |
| A11 | Forbidden actuation surface is absent | GREEN | `execute_method` was not listed; an explicit call returned JSON-RPC `-32602 unknown MCP tool` |
| A12 | Invalid proposal approval is atomic | GREEN | `does-not-exist` returned 404; proposal counts and both pack hashes remained identical |
| A13 | Host and cross-site mutations are refused | GREEN | Host `evil.example` returned 421; hostile origin returned 403 `cross_site`; Aside Chromium observed `Failed to fetch` |
| A14 | Pack path traversal cannot escape | GREEN | `../outside-aside` returned 422; no escaped pack or path was created |
| A15 | Path validation error is understandable | **RED** | Aside rendered the 422 response as `[object Object]` instead of the server's validation message |
| A16 | Published pack bytes are immutable | GREEN | Every post-attack SHA-256 matched its pre-attack SHA-256; no `.sqlite-wal` or `.sqlite-shm` sidecar existed |

## Exact immutable receipts

### Browser-generated graph pack

- Pack: `aside-trial-pack-20260814-235347`
- `pack.sqlite` SHA-256:
  `cd940042369b853a991014bef1ebb1d65a077749935d026571760b6e191c32ca`
- Counts: documents `1`, verified concepts `2`, verified relations `1`
- MCP search: `OrderApp`, status `verified`, result count `1`

### Real methodology proof

- Runtime pack:
  `real-proof-20260814-235005`
- Pack SHA-256:
  `b9b7317fd698c0e9fc4cc38705bce8f72bbbee1f5b266f747e02b70f562179b9`
- Release content hash:
  `sha256:1a2bfce1005a5378dc51716362b8756577b2e8be02467d5e01fd6f98bb5193bb`
- Publication receipt hash:
  `sha256:f94457135815a2083edfb9f0eb39c7a267c875466da77aa3c8996ad8873bf373`
- Method tools:
  `list_methods`, `get_method`, `trace_method`, `list_method_gaps`
- Forbidden tools: none
- MCP process exited: true
- Pack bytes unchanged: true
- Cleanup: absent

## Findings

### P1 — Pack validation errors are rendered as `[object Object]`

**Observed:** Entering `../outside-aside` in the real pack form produced a red
result box containing only `[object Object]`.

**Server truth:** The same request returned 422 with:

```text
invalid pack name '../outside-aside': use only letters, digits, '.', '_', '-'
(no path separators)
```

**Root cause:** `apiSend` returns any parsed object before checking
`res.ok` (`web/app.js:1684`). The pack handler then passes the structured
`detail` list directly through `escapeHtml` (`web/app.js:3010`), coercing it
to `[object Object]`.

**Required fix:** Make the shared request boundary reject non-2xx responses
before returning the body, and normalize FastAPI string/list/object `detail`
values into one readable message. Verify through the real pack form, not only
an API test.

### P2 — Sample insertion leaves the active document list stale

**Observed:** The success message appeared and the document was persisted, but
the active Sources list remained empty. Home → Sources navigation displayed
the document.

**Root cause:** The sample handler refreshes `loadHome()` only
(`web/app.js:5004`); it does not refresh the active Sources list.

**Required fix:** Refresh Sources after successful insertion, while preserving
the existing home-count refresh.

### P3 — Aside CLI update is available

The installed CLI advertised `1.26.810.1915` while the tested command version
was `1.26.717.1619`. This did not block the deterministic REPL run and is not
an OntologyLab defect.

## Ship decision

- Knowledge integrity, security boundaries, pack immutability, and MCP
  read-only behavior: **GREEN**
- Full Aside browser acceptance: **RED**
- Minimum path to GREEN: fix P1, fix P2, then rerun A02/A03/A14/A15 through
  `aside repl` against a fresh disposable data directory.

## Joint Herdr wave — prime-agent + Aside

The user requested a second adversarial wave coordinated with the existing
adjacent `prime-agent` pane. Herdr identified:

- This pane: `wD:pR`
- Adjacent prime-agent: `wD:pS`
- Shared tab/workspace: `wD:t1` / `wD`
- Prime-agent cwd: `/Users/hyunjun/Documents/MUNI/ontologylab`

The role split was explicit:

- This pane alone drove Aside CLI and Chromium.
- Prime-agent did backend/API/MCP and source-observation work without Aside.
- Both panes preserved the dirty worktree and protected PID 55560/port 8799.
- Neither pane edited product code.

### Joint Aside matrix

| ID | Scenario | Result | Exact observation |
|---|---|---|---|
| J01 | Repeat the same extraction | GREEN | First run `+8 concepts/+7 relations`; second run used a distinct job ID but returned `+0/+0`; proposal count stayed 15 with 15 unique IDs |
| J02 | Retry UI settles consistently | GREEN | The completion-transition badge briefly read 0, but a stable fresh Aside tab showed badge 15 and API count 15; classified as capture transient |
| J03 | Missing local file diagnosis | GREEN | Aside displayed `FETCH FAILED [Errno 2] No such file or directory`; document count remained 1 and no failed job row was fabricated |
| J04 | Pack A → Pack B growth | GREEN | Pack A contained 2 concepts/1 relation; a second evidence-backed approval produced Pack B with 3 concepts/2 relations |
| J05 | Pack diff through Aside | GREEN | UI reported exactly `concepts +1/-0/~0`, `relations +1/-0/~0`, adding `SalesReport` and `CouponEngine -[part_of]-> SalesReport` |
| J06 | Two-pack connection cards | GREEN | Connection tab showed exactly two commands with matching IDs and 2/1 versus 3/2 counts |
| J07 | Malformed manifest consistency | **RED** | Packs rendered two phantom `—000—.mcpb` rows and blank diff options while Connection returned `Internal Server Error` and left `불러오는 중…` visible |
| J08 | Malformed fixture removal | GREEN | Removing only the injected fixtures restored exactly two pack rows, two nonblank diff options, two MCP cards, and no error |

Joint pack receipts:

```text
joint-pack-a-20260815-002121
pack.sqlite sha256:596172e558c1836809d20a05fd35e86bf9bef6b179d93709843969d2783136b0

joint-pack-b-20260815-002257
pack.sqlite sha256:3be2f94d85592e00c9554895cd2992c8b9ed85a22cd85919ae2df252ecce40a6
```

Both packs had no SQLite sidecars.

### Additional prime-agent P1 findings

#### P1 — Partial chunk failure is presented as a complete job

Prime-agent injected an `EngineError` into the second of four chunks.

```text
API job status       = complete
API job error        = null
extraction_run       = failed
chunk attempts       = succeeded, failed, succeeded, succeeded
```

The browser consequently has enough data to display `추출 완료!` while the
durable extraction run is failed.

References:

- `ontologylab/extractor.py:760`
- `ontologylab/extractor.py:836`
- `ontologylab/server/jobs.py:604`
- `web/app.js:2318`

#### P1 — Chunk EngineError content leaks through progress

A synthetic provider error containing
`https://example.invalid/?key=SYNTHETIC_SECRET` appeared verbatim in
`GET /api/jobs`, detail progress, and therefore the browser-readable job
surface. Top-level worker failures use redaction; chunk failures bypass it.

References:

- `ontologylab/extractor.py:769`
- `ontologylab/server/jobs.py:212`
- `ontologylab/server/jobs.py:608`
- `web/app.js:2075`
- `ontologylab/engines.py:135`

#### P1 — MCP input schemas are advertised but not enforced

The live registry accepted malformed values including:

```text
detail="false"      → treated as truthy
start_ids="n_rl"    → treated as a character iterable
top_k=-1            → accepted
min_score=2.0       → accepted
graph limit=-1      → unbounded SQLite result
max_hops=-1         → accepted
unknown argument    → raw Python signature error
```

References:

- `ontologylab/mcp_runtime.py:51`
- `ontologylab/mcp_runtime.py:138`
- `ontologylab/mcp_server.py:641`
- `ontologylab/mcp_server.py:1130`

#### P1 — Named non-active schema reads bypass pack integrity

After same-length SQLite tampering, `load_pack(A)` correctly raised
`PackIntegrityError`, but `get_schema(pack_id=A)` returned the tampered
`evil-schema-X`. The active Pack B remained selected.

References:

- integrity bypass: `ontologylab/mcp_server.py:626`
- validated load: `ontologylab/mcp_server.py:579`

#### P1 — Busy invalidation can look successful in the UI

The backend correctly returned HTTP 503, `Retry-After: 2`, and
`{"ok":false,"error_kind":"busy"}`. `invalidateEdge` only treats
`res.ok === undefined` as failure, so `ok:false` can pass through to a reload
without an operator-visible retry error.

References:

- `ontologylab/server/app.py:96`
- `web/app.js:3213`
- similar merge callers: `web/app.js:3518`

#### P1 — Malformed manifests disagree across product surfaces

Prime-agent first established the backend contract:

```text
manifest {"counts":{}}       /api/packs count=1, /api/mcp/status count=0
manifest []                  /api/packs 200, /api/mcp/status 500
invalid SQLite with pack_id  copyable MCP command still exposed
```

Aside then independently confirmed the user-visible contradiction in J07.

References:

- `ontologylab/packbuilder.py:800`
- `ontologylab/server/routes.py:2355`
- `ontologylab/server/routes.py:2510`
- `web/app.js:2713`
- `web/app.js:3074`
- `web/app.js:4207`

### Backend retry and session results that remained green

Prime-agent verified:

- Only the failed chunk reran; attempts changed from `[1,1,1,1]` to
  `[1,2,1,1]`.
- Successful chunks were not called again.
- The same run moved `failed → complete`.
- A third identical request made zero engine calls.
- Proposal and citation counts did not duplicate.
- A checkpoint failure left node/edge/citation at `0/0/0`; retry produced
  exactly `2/1/3`.
- A→B→A→B pack switching returned the correct entity, schema, hash, and
  provenance every time.
- Methodology state cleared when switching to a pack without methods.
- Previous stores were actually closed.
- Unknown, tampered, and traversal pack loads preserved the active pack.
- Malformed stdio requests did not kill the MCP process.
- Unknown tools returned JSON-RPC `-32602`; process exit was 0 with empty
  stderr.

The remaining P2 is product observability: JobStatus and the UI do not expose
the extraction run ID, failed/retryable chunk count, original document IDs,
seed, budgets, or a per-job retry action. A user therefore cannot prove that
a manual rerun is the same workload.

References:

- `ontologylab/extractor.py:814`
- `ontologylab/extraction_state.py:342`
- `ontologylab/server/jobs.py:108`
- `web/app.js:2247`

### Updated ship decision

**Overall verdict remains RED and is stronger than the first wave.**

The integrity-preserving retry implementation and ordinary pack switching are
green. Release acceptance is blocked by:

1. partial chunk failures being shown as complete,
2. provider error details leaking into browser-readable progress,
3. unenforced MCP schemas and unbounded negative limits,
4. named-pack integrity bypass,
5. structured validation errors rendered unreadably,
6. busy state changes that can look successful, and
7. malformed manifests causing contradictory or unusable pack/MCP surfaces.
