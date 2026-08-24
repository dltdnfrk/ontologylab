# Task 12 final code review — uncommitted R1–R5 repair

Reviewer: omo senpi-task `st_01a03270`
Date: 2026-08-24
Lane: independent CODE review of the final uncommitted Task 12
repair bytes. Constraint: this report is the only write. Product/test
read-only. No commit/push; no network; no Application Support
contents; no 8799 / PID 55560 mutation; no authority / plan edits.
No full suite.

Authority: Step 8 brief / kickoff, blueprint §0, pack-contract
§§6–8, original `task-12-review-code.md`, repair executors R1–R5.
Executor receipts treated as claims. Bound to worktree against HEAD
`081d8554f814645517a29a0cef1c0e32af3d84df`.

## Verdict

**NEEDS-FIX**

**Confidence:** 0.93

Maximum severity **MAJOR** (security lane: MEDIUM). Prior named
R1–R5 defects and H-SKIP-UNREV-KEEP-EV remain closed. A published
reviewed v2 pack rewritten onto the v1 parse path still verifies
as `legacy-graph-only`, is listed/activated, and **switches** a
real MCP session while `list_packs`, `activate_pack.manifest`,
and `resource_manifest` keep serving raw `reviewed` /
`sourced-answer-v2` / `evidence-self-contained-v2` strings.
`_verify_v1` never rejects v2-only fields, capabilities,
artifacts, or sqlite schema. Served capabilities are the raw
manifest list, not a derived/normalized receipt.

No CRITICAL (no BaseException swallow, no live-store resolve, no
opener bypass of verify-copy, no source-byte mutation).

## Findings

### CRITICAL

None.

### MAJOR

1. **V1 parse-path disguise serves raw v2 capability strings and
   switches the session**
   (`ontologylab/pack_verifier.py:194-201,244-247,371-389`,
   `ontologylab/verified_pack_reader.py:178-206`,
   `ontologylab/mcp_server.py:386-396,490-522`).
   `parse_manifest` treats missing/`1` `pack_schema_version` as
   v1. `_parse_v1` only requires `pack_id` + `content_hash`
   (optional `tree_hash`). It does not refuse `capabilities`
   containing `knowledge-graph-v2` / `evidence-self-contained-v2`
   / `reviewed` / `sourced-answer-v2`, nor `evidence_mode`,
   `closure`, `artifact_inventory`, `pack_content_hash`, an
   `evidence/` tree, or a packed v2 sqlite (receipt tables +
   `nodes.status`). `_verify_v1` then returns
   `integrity_level=legacy-graph-only` after a sqlite-byte match.
   `inspect_verified_manifest` / `activate_pack` hand callers the
   **raw disk manifest**, so discovery and MCP resources emit the
   un-normalized labels. MCP `load_pack` activates and **replaces**
   the prior session; lookup serves PaymentGateway with a citation
   id. Provenance `integrity_level` is the derived v1 string, but
   `evidence_mode` (when left on disk) and resource `capabilities`
   stay v2.
   Independent probe (tempdir, removed):
   - set `pack_schema_version=1` + `content_hash=sha256(pack.sqlite)`,
     keep all v2 fields and reviewed/sourced/evidence caps →
     verify/CLI 0 / list caps include reviewed+sourced+ev-v2 /
     activate ok / `load_pack` switched / resource same caps
   - omit `pack_schema_version` (default 1): same serve/switch
   - strip `evidence_mode`/`closure`/`artifact_inventory` but keep
     the four raw cap strings: same serve/switch
   - also DROP `c036_capability_receipts` without rewriting the
     leftover v2 `tree_hash`: **HOLD** `tampered_artifact:tree_hash`;
     honest session held. Refreshing or dropping `tree_hash` would
     re-open this path.
   Root cause / repair: the v1 path must strictly reject v2-only
   fields, v2 capability strings, v2 artifacts (`evidence/`,
   receipt tables / `nodes.status`), and leftover v2 inventory
   keys. Served `capabilities` on list/activate/MCP must be
   derived or normalized from the verifier receipt (v1 →
   `knowledge-graph-v1` only), never trusted raw manifest
   strings. Prior R4 H-V1-DISGUISE HOLD was a different recipe
   (caps rewritten to `knowledge-graph-v1`). This recipe keeps
   the v2 labels.

### MINOR

1. **Graph-only disguise after closure-key strip still verifies.**
   A real packed v2 graph (receipt tables + `nodes.status` still
   present) that deletes one citation, drops C-036, pops
   `evidence_mode`+`closure`, **removes `evidence/`**, and claims
   only `knowledge-graph-v2` verifies, lists, activates, and MCP-
   serves. Independent probe: 3 verified facts / 2 citations;
   `PaymentGateway` returned with `citation_id=None`,
   `pack_schema_version=2`, `integrity_level=knowledge-graph-v2`.
   Same honesty class as the prior v1-disguise HOLD (no
   evidence-self-contained / reviewed / sourced claim). There is
   no honest builder path for graph-only v2 (omitting
   `evidence_mode` still builds v1). Residual of
   `needs_closure = reviewed or claims_keys or (advertised and
   packed_graph)` — dropping the evidence advertisement skips
   SQL completeness. Not the tasked H-SKIP (that path still
   advertises `evidence-self-contained-v2` and is refused).

2. **Schema-signal destruction re-enters the synthetic fixture
   skip.** Dropping every receipt table and recreating `nodes`
   without `status`, then applying the H-SKIP manifest strip,
   makes `_packed_v2_graph_present` false. `verify_pack` /
   `list_packs` / `activate_pack` succeed with
   `integrity_level=evidence-self-contained-v2`. MCP `load_pack`
   then raises untyped `sqlite3.OperationalError: no such column:
   status` from `store.counts()` / `get_schema()` **before**
   session switch; prior honest lookup held. Same skip class as
   inventory-only `_write_v2` (no receipt tables, `nodes` has
   only `id`). No facts served.

3. **Carried residuals from R1–R3 (unchanged, not regressions).**
   `find_path` still has no citation receipts. EXCERPT still
   writes `raw_text_path=''` rather than SQL NULL (resolver types
   `excerpt_only`). `_with_fact_receipts(conn: Any, ...)`. MCP
   `_provenance` still omits `capabilities`.
   `resolve_v2_closure` still hardcodes `V2_CAPABILITIES`.
   `pack_v2_derive.py` 245 and `pack_v2_validate.py` 217 sit in
   the house warning band (no `SIZE_OK`; next edit should split).

## Prior defects

| Defect | Authority | Status |
|---|---|---|
| MCP fact receipts (work / representation / citation + pack schema 2) | original code #MCP / contract §8 | **CLOSED** — lookup/search/entity carry receipts; focused test green |
| Counts from missing/`citations`/`extraction_*` tables | original MAJOR 1 | **CLOSED** — `_COUNT_SQL` → `document_observations`, `citation_receipts`, `grounded_review_decisions`, `extraction_*_receipts` |
| Replace dropped `nodes_verified` / staleness = 0 | original MAJOR 2 | **CLOSED** — derived counts keep verified keys; staleness matches |
| `contained_documents_path` cannot open `evidence/` | original MAJOR 3 | **CLOSED** — `resolve_pack_evidence` + `PackSession.document_raw_text` on serving copy |
| `--publish` only caught `PackReadinessRefused` | original MAJOR 4 | **CLOSED** — `PackV2ClosureRefused` / `IncompleteExtractionError` / `PackBuildError`; `--evidence-mode none` is exit 2 `sourced_none`, no traceback |
| Packed C-036 vs live subset seal | repair-1 MAJOR 1 | **CLOSED** — inventoried `receipt-inventory.json` witness |
| Packed fingerprint vs unpublished live docs | repair-2 MAJOR 1 | **CLOSED** — inventoried `source-fingerprint.json`; no packed `compute_source_fingerprint` compare |
| Packed-row deletion after hash rematerialize | repair-3 residual / R4 | **CLOSED** — `validate_packed_v2_closure` on reviewed/sourced or typed closure |
| H-SKIP-UNREV-KEEP-EV (evidence cap without contract) | repair-4 security MEDIUM | **CLOSED** — advertised `evidence-self-contained-v2` **and** packed v2 graph requires complete typed contract |
| V1 parse-path disguise keeping raw v2 labels | final security MEDIUM / this recheck | **OPEN** — finding 1 |

## Attacks (reproduced on disposable `/tmp`, removed)

Honest combined extra-run + unpublished-doc used as the parent
where a sibling is required. Full rematerialize = counts from
remaining SQL + inventory / `sqlite_hash` / `pack_content_hash`
refresh.

### Named / tasked

| ID | Tamper | verify / CLI | list / activate / MCP |
|---|---|---|---|
| H-SKIP-UNREV-KEEP-EV | delete 1 cite; drop C-036; pop `evidence_mode`+`closure`; keep unreviewed evidence caps; rewrite counts | `invalid_manifest:closure`; CLI exit 2 `{"ok":false,"code":"invalid_manifest","path":"closure"}`; stderr empty | omitted; `PackIntegrityError`; prior honest session held |
| INCOMPLETE-citation | delete 1 cite; rewrite closure+counts | `invalid_manifest:citation` | refuse |
| INCOMPLETE-document | delete packed document | `invalid_manifest:foreign_keys` | refuse |
| INCOMPLETE-review | delete grounded review | `invalid_manifest:review_decision` | refuse |
| INCOMPLETE-run | delete packed run (FK off) | `invalid_manifest:capabilities` (derive no longer matches claimed reviewed) | refuse |
| INCOMPLETE-chunk | replace/delete required chunk | `invalid_manifest:foreign_keys` | refuse |
| INCOMPLETE-policy | delete primary policy receipt | `invalid_manifest:policy` | refuse |
| STRIP-ONLY-evidence_mode | cite+C-036 drop; pop only `evidence_mode`; keep evidence cap | `invalid_manifest:closure` | — |
| STRIP-ONLY-closure | same; pop only `closure` | `invalid_manifest:closure` | — |
| MALFORMED-CLOSURE | `closure` is a string | `invalid_manifest:closure` | — |
| KEEP-REVIEWED-STRIP | pop both keys; keep reviewed/sourced | `invalid_manifest:closure` | — |
| MISSING-CLOSURE-MEMBER-KEY | drop `closure.citation` key | typed contract false; `invalid_manifest:closure` | — |
| H-V1-DISGUISE-KEEP-CAPS | set `pack_schema_version=1`; `content_hash=sha256(pack.sqlite)`; keep reviewed/sourced/ev-v2 + v2 fields | verify ok `legacy-graph-only`; CLI exit 0 | listed with raw v2 caps; activate ok; MCP **switched**; resource serves same caps |
| H-V1-OMIT-VERSION | omit `pack_schema_version` (defaults 1); same hash/caps | same | same switch |
| H-V1-STRIP-FIELDS-KEEP-CAPS | drop `evidence_mode`/`closure`/`artifact_inventory`; keep four raw cap strings; schema=1 + content_hash | same | same switch; provenance `evidence_mode=null` |
| H-V1-DROP-C036 | above + DROP `c036_capability_receipts` without rewriting leftover `tree_hash` | `tampered_artifact:tree_hash`; CLI exit 2 | omitted; activate/load refuse; honest held |

### Honesty / fixture class (not blocking)

| ID | Result |
|---|---|
| GRAPH-ONLY-DISGUISE | verify ok `knowledge-graph-v2`; serves citation-less verified node (MINOR 1) |
| DESTROY-GRAPH-SIGNAL | verify/list/activate ok `evidence-self-contained-v2`; `load_pack` `OperationalError` before switch; honest lookup held (MINOR 2) |
| SYNTHETIC `_write_v2` | verify ok; `_packed_v2_graph_present=false`; `nodes` cols `["id"]` |
| `_write_v1` / default `build_pack` without `evidence_mode` | `legacy-graph-only`, schema 1, caps `knowledge-graph-v1` |
| HONEST-UNREVIEWED | verify ok; has `evidence_mode`+`closure`; no reviewed/sourced |

## Bind

| Fact | Observed |
|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged) |
| Tree | `8677230e75080e5fae606b8dfac568619bfd569c` |
| Subject | `test(pack): include evidence mode in signature contract` |
| Index | empty |
| PID 55560 | still `127.0.0.1:8799` DEVICE `0x1ff51c806b197195` (observe-only) |
| Application Support `OntologyLab` / `ontologylab` | ino `102434596` mtime_ns `1785487752937707432` size `192` (stat only; no contents) |
| `pack_v2_validate.py` inode | `278314796` |
| `pack_verifier.py` inode | `274739540` |
| `pack_v2_closure.py` inode | `274892112` |

### Exact SHA-256 (current worktree; MATCH R1–R5 executor tables)

| Path | SHA-256 |
|---|---|
| `ontologylab/pack_v2_validate.py` | `ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6` |
| `ontologylab/pack_verifier.py` | `ac2d55740ea1e7e6df4aaa2155ad8ca331f3b6447d86015a0bddc9e9bbf6907c` |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |
| `ontologylab/pack_v2_derive.py` | `7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577` |
| `ontologylab/pack_source_fingerprint.py` | `a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7` |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` |
| `ontologylab/pack_readiness.py` | `550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21` |
| `ontologylab/mcp_server.py` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` |
| `tests/test_pack_v2_review_repair.py` | `483ce682f024d7462503c530d45c4bcd536750582a055f9c49952a9c93383015` |
| `tests/test_pack_v2_closure.py` | `96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff` |
| `tests/test_pack_v2_verifier.py` | `5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b` |
| `tests/test_packdiff.py` | `296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6` |

Tracked increment vs HEAD: 9 files, +221 / −103. Untracked owned:
`pack_source_fingerprint.py`, `pack_v2_derive.py`,
`pack_v2_validate.py`, `tests/test_pack_v2_review_repair.py`.
Unrelated dirty `ontologylab/graphify-out/` left untouched.

## Method

Read Step 8 brief + kickoff, blueprint §0, pack-contract §§6–8,
original `task-12-review-code.md`, repair-1/2/3 code reviews, R1–R5
executors, R4 security + bypass QA. Read `pack_v2_validate.py`,
`pack_v2_derive.py`, `pack_verifier.py` `_verify_v2` /
`_validate_packed_v2` / `parse_manifest`, `pack_v2_manifest.py`,
`pack_readiness.main`, `pack_v2_closure` collect/copy/resolve,
MCP `_provenance` / `_with_fact_receipts` / `document_raw_text` /
`load_pack` / 15 `@mcp.tool` wrappers, and the repair-test matrix
including `_apply_unreviewed_evidence_capability_closure_strip`.
Independently reproduced the final-security v1 parse-path
disguise (set/omit schema version, keep raw v2 caps, optional
C-036 drop) on disposable roots, then removed them.

Reproduced once:

- focused pytest (repair + Task 8–11 surfaces + staleness):
  **171 passed**, 1 pre-existing Starlette warning, 11.02s, EXIT 0
- basedpyright on validate/derive/closure/manifest/verifier/
  readiness/seal/fingerprint + repair tests: **0/0/0**
- basedpyright `mcp_server.py`: same **10** pre-existing FastMCP
  `reportReturnType` wrappers (1056–1219). None on `_provenance`,
  `_with_fact_receipts`, `document_raw_text`, or `load_pack`
- LSP: owned modules + repair tests clean; `mcp_server.py` only
  those 10 wrapper errors
- `python3.11 -m py_compile` on changed production: EXIT 0
- no-excuse on validate/derive/manifest/fingerprint/readiness/seal:
  0 violations
- independent disposable attacks above, plus v1-disguise
  probe (roots and `/tmp/t12-v1-disguise-probe.py` removed)

Did not re-run source mutants or the full suite. Did not open
Application Support contents, denylist servers, or Step 9+.

## Types / architecture / cycles / CLI identity / gating

**Types.** New/owned modules have no `Any` / `cast` / `type:
ignore`. `EvidenceMode` is `match` + `assert_never`.
`PackedV2ClosureRefused` is a frozen slotted dataclass.
`validate_packed_v2_closure` is 3 public parameters. Manifest v2
is parsed once into `ManifestV2`; closure completeness re-reads
disk JSON (those keys are not on `ManifestV2`) and then
`resolve_v2_closure`.

**Architecture.** Split is honest: derive (counts/caps/evidence),
fingerprint witness, receipt-inventory witness, validate
(packed completeness), verifier (inventory/hash/CLI), closure
(collect/copy/resolve). `pack_v2_validate` 217 and
`pack_v2_derive` 245 are warning-band; closure 624 and verifier
429 remain `SIZE_OK`. Test file 1203 is `SIZE_OK` (single SUT
matrix).

**Cycles.** `pack_v2_validate` top-level-imports `ManifestV2`
from `pack_verifier`; `pack_verifier` lazy-imports validate
inside `_validate_packed_v2`. Runtime import of both modules
succeeds. `pack_v2_manifest` imports `ClaimedEntry` only. No
validate ↔ closure cycle. `pack_receipt_seal` and
`pack_source_fingerprint` have no pack-* imports.

**CLI exception identity.**

- `python -m ontologylab.pack_verifier`: only `PackVerifyRefused`
  → `{"ok":false,"code":...,"path":...}`, exit 2. In-module
  conversion `PackedV2ClosureRefused` → `INVALID_MANIFEST` +
  member. Probe stderr never contained `PackedV2ClosureRefused`
  or `Traceback`.
- `python -m ontologylab.pack_readiness --publish --evidence-mode
  none`: catches `PackV2ClosureRefused` and emits
  `{"ok":false,"code":"sourced_none","member":"source"}`, exit 2.
  `IncompleteExtractionError.code` is the class attribute
  `"incomplete_extraction"`. `PackBuildError` still uses
  `type(refused).__name__` (pre-existing weak identity, not the
  original CLI hole).

**v1 gating.** Honest default `build_pack` without
`evidence_mode` still ships `knowledge-graph-v1` /
`legacy-graph-only`. Completeness override cannot enter the v2
seam. **Fail:** `parse_manifest` default/`1` is a silent escape
from every v2 check. `_parse_v1` / `_verify_v1` do not reject
v2-only fields, v2 capability strings, `evidence/` artifacts, or
a packed v2 sqlite schema. That is finding 1.

**Synthetic-v2 gating.** `_write_v2` seeds `CREATE TABLE nodes
(id TEXT)` plus non-receipt names (`citations`,
`review_decisions`, `extraction_runs` — not `*_receipts`).
`_packed_v2_graph_present` is false; `_claims_v2_closure` is
false; no reviewed label → validator returns. Intentional
fixture skip. A real pack still advertising
`evidence-self-contained-v2` cannot take that skip without
destroying receipt tables **and** `nodes.status` (MINOR 2).

**MCP.** 15 `@mcp.tool` wrappers. `document_raw_text` remains a
`PackSession` method, not a 16th tool. `load_pack` closes the
new snapshot on open/count/schema failure before replacing
`self.store` — DESTROY therefore cannot switch. V1-disguise
`load_pack` **does** switch because `_verify_v1` and
`KGStore.counts()` both succeed.

**BaseException / sleeps.** No `except BaseException` in the
repair increment. New tests have no `time.sleep`.

## Dimension checks

| Dimension | Result |
|---|---|
| Prior four MAJORs + MCP receipts + exclusions | PASS |
| C-036 live-run witness | PASS |
| C-036 unpublished-doc fingerprint witness | PASS |
| Packed semantic closure (keys kept) | PASS |
| Evidence capability mandatory contract (H-SKIP) | PASS |
| Closure-key strip while keeping evidence cap | PASS (refused) |
| Incomplete cite/doc/review/run/chunk/policy | PASS (refused) |
| Graph-only / schema-destroy disguise | MINOR residuals 1–2 |
| V1 parse-path + raw capability serve | **NEEDS-FIX** — finding 1 |
| Honest v1 builder / synthetic-v2 / unreviewed | PASS on those fixtures |
| CLI exception identity | PASS on the tasked codes |
| Types / changed-line LSP | PASS (FastMCP wrappers pre-existing) |
| Cycles | PASS (lazy verifier → validate) |
| No source reopen / no BaseException swallow | PASS |
| Focused tests | 171 passed, 1 pre-existing warning |

## Repair that would flip this to PASS

In `_parse_v1` / `_verify_v1`, refuse when any of: capability
string is not in the v1 set (`knowledge-graph-v1`); v2-only
keys are present (`evidence_mode`, `closure`,
`artifact_inventory`, `pack_content_hash`, `integrity_model`);
`evidence/` exists; sqlite has v2 receipt tables or
`nodes.status`. After a successful verify, list/activate/MCP
must emit capabilities from the verifier receipt (v1 →
`("knowledge-graph-v1",)`), never `snapshot.manifest["capabilities"]`.
Add a test that plants the frozen recipe (schema 1 or omitted +
legacy `content_hash` + kept reviewed/sourced/ev-v2 strings) and
asserts `PackVerifyRefused` plus no list/activate/session switch.
Keep honest `_write_v1` / default v1 `build_pack` green.

## Residuals (do not flip by themselves)

- MINOR 1: graph-only disguise serves a citation-less verified
  node as `pack_schema_version=2` / `knowledge-graph-v2`.
- MINOR 2: schema-signal destruction lists/activates as
  `evidence-self-contained-v2`; `load_pack` leaks
  `OperationalError` instead of `PackIntegrityError`. Session
  still held.
- Carried R1–R3 MINORs listed above.
- `mcp_server.py` FastMCP `reportReturnType` wrappers (pre-
  existing; not this increment).
- Full suite not re-run here; last committed-suite claim remains
  `task-12-final-full-suite.md` on HEAD, not on these dirty bytes.

## Protected

- HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`
- Product/test bytes MATCH the hash table (rehashed after probes)
- PID 55560 still `127.0.0.1:8799` DEVICE `0x1ff51c806b197195`
- Application Support ino/mtime/size unchanged (stat only)
- Disposable probe roots and `/tmp/t12-final-code-probe*.py` removed
- Prior review/security/QA receipts not rewritten
- No commit/push/network/full suite/plan/authority edits
