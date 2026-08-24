# Task 12 Round 6 code review — uncommitted v1-disguise refuse

Reviewer: omo senpi-task `st_01a03287`
Date: 2026-08-24
Lane: independent CODE review of the final uncommitted Task 12
R1–R6 bytes, with R6 (`_parse_v1` allowlist + v2-field refuse) as
the increment under test. Constraint: this report is the only write.
Product/test read-only. No commit/push; no network; no Application
Support contents; no 8799 / PID 55560 mutation; no authority / plan
edits. No full suite.

Authority: `task-12-review-final-security.md` MEDIUM (v1-disguise
authority bypass); `task-12-review-final-code.md` MAJOR 1 / v1
gating residual; `task-12-review-repair-6-executor.md` (claim);
R1–R5 executors; pack-contract §§7–8. Bound to the worktree against
HEAD `081d8554f814645517a29a0cef1c0e32af3d84df`.

Prior receipts treated as claims and not rewritten. SHA-256 of the
ones read this turn:

| Receipt | SHA-256 |
|---|---|
| `task-12-review-repair-6-executor.md` | `6209b4aee7e31b49607a46d78aa1e9fb3fa16c69654da01795b78d0f450160aa` |
| `task-12-review-final-security.md` | `76e328c42529cf0451b4c259d9cd95ca2ab22546e581a5c4ca9d732362babb41` |
| `task-12-review-final-code.md` | `b53d03c8ecb7dfea948371c6ae8d8782e5c9b32b53f3f7c45f7225b038fa4b15` |
| `task-12-review-repair-executor.md` | `6283eb19b2e23bba8ef29584a69a986bea6b0294dc27f1127ddc859d612d1329` |

## Verdict

**PASS**

**Confidence:** 0.93

No blocking code defect. The named R6 MEDIUM is closed on the
real serve path: an explicit-`1` or omitted-schema rewrite that
keeps raw `reviewed` / `sourced-answer-v2` / `evidence-self-contained-v2`
/ `knowledge-graph-v2` dies in `_parse_v1` as typed
`invalid_manifest:capabilities` before `_verify_v1`,
`list_packs`, `activate_pack`, MCP `load_pack`, or
`resource_manifest` can emit those strings or switch a session.
v2-only contract fields on a v1-shaped manifest are the same
refuse class. Builder v1, historical no-cap v1, methodology-v1,
tree / no-tree / writable / extra-file, inventory-only `_write_v2`,
and the R1–R5 surfaces stay green.

No CRITICAL (no BaseException swallow in the increment, no
live-store resolve, no opener bypass, no source-byte mutation).

## Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

None new that this increment introduced. Carried residuals are
listed at the bottom and do not reopen the named disguise.

## Why the named R6 hole is closed

`parse_manifest` still defaults missing/`null` schema to v1
(`match raw.get("pack_schema_version", 1)` → `case 1 | None`).
That default is the legitimate builder/historical path (PackManifest
has no `pack_schema_version`; default `build_pack` omits it). R6
does not close omitted schema; it makes omitted schema a **strict
v1 parse**:

1. `_refuse_v2_only_fields` rejects any of
   `artifact_inventory`, `pack_content_hash`, `sqlite_hash`,
   `integrity_model`, `evidence_mode`, `closure`,
   `receipt_inventory`, `receipt_inventory_root`,
   `source_fingerprint`, `source_fingerprint_entries`.
2. `_parse_v1_capabilities` accepts only absence/`null`, or the
   exact tuples `()`, `("knowledge-graph-v1",)`,
   `("knowledge-graph-v1", "methodology-v1")`. Unknown strings,
   `reviewed`, every v2-only capability, `methodology-v1` alone,
   wrong order, duplicates, and non-list shapes refuse
   `invalid_manifest:capabilities`.
3. `ManifestV1` still carries only `pack_id` / `content_hash` /
   `tree_hash`. `_verify_v1` never re-reads raw capabilities.

Independent parse probe (in-process, no pack tree):

| Input | Result |
|---|---|
| historical absent caps | ACCEPTED `ManifestV1` |
| `[]` / `["knowledge-graph-v1"]` / pair + methodology | ACCEPTED |
| explicit `pack_schema_version=1` + graph-v1 | ACCEPTED |
| explicit `1` + `["reviewed"]` | `invalid_manifest:capabilities` |
| omitted schema + four v2/reviewed strings | `invalid_manifest:capabilities` |
| graph-v1 + `evidence_mode` | `invalid_manifest:evidence_mode` |
| graph-v1 + `artifact_inventory` | `invalid_manifest:artifact_inventory` |
| `["methodology-v1"]` alone | `invalid_manifest:capabilities` |
| `pack_schema_version="1"` (string) | `invalid_manifest:pack_schema_version` |

## list / activate / MCP cannot serve raw unvalidated caps

Serve still returns the **raw disk JSON** after a successful
verify (`activate_pack` → `_load_manifest`; `list_packs` →
`scan_packs` → `inspect_verified_manifest`; MCP
`resource_manifest` is that same dict). That is unchanged and
intentional. It is now safe for the named labels because every
list/activate/MCP path verifies first:

- `scan_packs` json.loads only to bind `pack_id` / directory
  name, then `inspect_verified_manifest`. Failures go to
  `unusable`, never into `list_packs`.
- MCP `list_packs` is `packbuilder.list_packs` (alias
  `discover_packs`).
- `activate_pack` / `load_pack` / inactive `resource_manifest`
  all call `verify_pack` (activate verifies source **and** the
  process-owned copy).
- `try_autoload` only sees the verified list.

A four-field disguise therefore cannot appear in `list_packs`,
cannot `activate_pack`, cannot `load_pack` (session held), and
cannot `resource_manifest`. Focused test
`test_reviewed_v2_disguised_as_v1_is_refused_before_session_switch`
covers explicit `1`, omitted schema, and omitted + DROP C-036;
CLI exit 2 `{"ok":false,"code":"invalid_manifest","path":"capabilities"}`
with no traceback.

Honest reviewed v2 still lists/activates/serves `reviewed` +
`sourced-answer-v2` because it stays on `_parse_v2` +
`_refuse_forged_capabilities` + `validate_packed_v2_closure`.

## Compatibility (must stay green)

| Surface | Why it still works |
|---|---|
| Builder v1 (`build_pack` without `evidence_mode`) | emits `["knowledge-graph-v1"]` or `["knowledge-graph-v1","methodology-v1"]` in that order; omits schema; writes `counts` / `tree_hash` / `methodology` (none of those are `_V2_ONLY_FIELDS`). `test_v1_pack_still_verifies` lists/activates/MCP-serves caps ⊆ `{knowledge-graph-v1, methodology-v1}` |
| Historical no-cap v1 | missing `capabilities` → `None` → accept. `test_legacy_v1_without_capabilities_verifies` |
| methodology-v1 | exact pair, graph first. `test_legacy_v1_with_methodology_capability_verifies` + parse parametrize |
| tree / no-tree | `_verify_v1` still optional `tree_hash`. Existing tests green |
| writable + extra file | v1 still `strict_mode=False` on sqlite; extra files ignored. Existing test green |
| Synthetic `_write_v2` | still schema 2; R5 inventory-only skip unchanged (`pack_v2_validate.py` bytes frozen) |

## Prior defects

| Defect | Authority | Status |
|---|---|---|
| MCP fact receipts + pack schema 2 | original code | **CLOSED** |
| Counts from missing / v1 tables | original MAJOR 1 | **CLOSED** |
| Dropped `nodes_verified` / staleness = 0 | original MAJOR 2 | **CLOSED** |
| `contained_documents_path` cannot open `evidence/` | original MAJOR 3 | **CLOSED** |
| `--publish` traceback on closure/build | original MAJOR 4 | **CLOSED** |
| Packed C-036 vs live extra run | repair-1 MAJOR 1 | **CLOSED** |
| Packed fingerprint vs unpublished live docs | repair-2 MAJOR 1 | **CLOSED** |
| Packed-row deletion after rematerialize | R4 | **CLOSED** |
| H-SKIP-UNREV-KEEP-EV (evidence cap, no contract) | R4 security MEDIUM / R5 | **CLOSED** — validate bytes still `ca3c138c…` |
| V1 parse-path disguise keeping raw v2 labels | final security MEDIUM / final code MAJOR 1 | **CLOSED** this round |

## R1–R5 integration (re-audit)

R6 touched only `pack_verifier.py` + the two test files vs the R5
freeze. `pack_v2_validate.py` / `pack_v2_closure.py` /
`verified_pack_reader.py` / derive / fingerprint / manifest /
readiness / seal / mcp_server hashes MATCH the final-code R5
table. `_verify_v2` still re-derives counts, `_refuse_forged_capabilities`,
then `_validate_packed_v2`. R5 `needs_closure = reviewed or
_claims_v2_closure or (advertised and _packed_v2_graph_present)`
is untouched. `document_raw_text` remains a `PackSession` method
(not a 16th `@mcp.tool`). 15 `@mcp.tool()` wrappers. CLI
`--evidence-mode none` still typed JSON exit 2.

Focused 10-file set (repair + closure + verifier + publication +
readiness + reader + mcp integrity + packdiff + ontology pub +
staleness): **209 passed**, 1 pre-existing Starlette warning,
13.93s, EXIT 0. Method surface + two-tier: **22 passed**.

## Parser exhaustiveness / types / cycles / CLI

**Parser.** Schema match is `1 | None` / `2` / `_` refuse
(`MATCH_OK`). `verify_pack` matches `ManifestV1` / `ManifestV2` /
`assert_never`. Capability membership is a closed frozenset of
tuples, not `if/elif` on tags. `_parse_v2` still requires
`knowledge-graph-v2` and evidence-cap when `evidence/` is
inventoried.

**Types.** R6 helpers are `JsonValue` / `Mapping[str, JsonValue]`.
No `Any`, `cast`, `# type: ignore`, or `unwrap` on the increment.
basedpyright on verifier + validate + derive + closure + manifest
+ reader + both test files: **0/0/0**. LSP clean on those three
edited files. `mcp_server.py`: same **10** pre-existing FastMCP
`reportReturnType` wrappers (1056–1219). none on `_provenance` /
`load_pack` / `document_raw_text`. `python3.11 -m py_compile`
verifier: EXIT 0. no-excuse on 7 owned modules: 0 violations.

**Cycles.** `pack_v2_validate` top-level-imports `ManifestV2`;
`pack_verifier` still lazy-imports validate/derive inside
`_verify_v2`. Runtime import of verifier + validate + derive +
reader + manifest succeeds.

**CLI identity.** `python -m ontologylab.pack_verifier` still
catches only `PackVerifyRefused` →
`{"ok":false,"code":...,"path":...}`, exit 2. Disguise CLI
path is `capabilities`. stderr has no `Traceback`.

**v1 gating.** Honest default `build_pack` remains
`legacy-graph-only` / schema 1 / v1 caps. Completeness override
still cannot enter the v2 seam. The previous silent escape
(default/`1` skipping every v2 check **while keeping v2 labels**)
is gone.

## Dimension checks

| Dimension | Result |
|---|---|
| Explicit v1 disguise (`schema=1` + raw v2/reviewed caps) | PASS — refused before serve/switch |
| Omitted-schema disguise (+ optional C-036 drop) | PASS — same refuse |
| Strict v1 allowlist / v2-field rejection | PASS |
| Builder v1 / historical no-cap / methodology-v1 | PASS |
| tree / no-tree / writable / extra-file | PASS |
| list / activate / MCP cannot serve unvalidated caps | PASS (verify-gated; raw JSON only after allowlist or v2 re-derive) |
| H-SKIP-UNREV-KEEP-EV + incomplete cite/doc/review | PASS (R5 bytes frozen; focused suite green) |
| Honest reviewed v2 labels still served | PASS |
| Synthetic `_write_v2` / honest unreviewed | PASS on those fixtures |
| Types / changed-line LSP | PASS |
| Cycles | PASS |
| CLI exception identity | PASS |
| 15 MCP tools | PASS |
| No source reopen / no increment BaseException / no test `sleep` | PASS |
| Focused tests | 209 passed + 22 method/two-tier |

## Bind

| Fact | Observed |
|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged) |
| Tree | `8677230e75080e5fae606b8dfac568619bfd569c` |
| Subject | `test(pack): include evidence mode in signature contract` |
| Index | empty |
| PID 55560 | still `127.0.0.1:8799` DEVICE `0x1ff51c806b197195` (observe-only) |
| Application Support `ontologylab` | ino `102434596` mtime_ns `1785487752937707432` size `192` (stat only; no contents) |
| `pack_verifier.py` inode | `274739540` (bytes **changed** this round vs R5 `ac2d5574…`) |
| `pack_v2_validate.py` inode | `278314796` (R5 freeze) |
| `pack_v2_closure.py` inode | `274892112` (R5 freeze) |

### Exact SHA-256 (current worktree; MATCH R6 executor + R5 freeze)

| Path | SHA-256 | vs R5 final-code table |
|---|---|---|
| `ontologylab/pack_verifier.py` | `2b64a110fa3789de3a53245e950f73cb8dccc9bdb78025394fbe3316b55130ed` | R6 (was `ac2d5574…`) |
| `tests/test_pack_v2_review_repair.py` | `622c7602c2f961c4dca98711d409c87123c257227d0610046e6e11a2ba417b76` | R6 (was `483ce682…`) |
| `tests/test_pack_v2_verifier.py` | `78ae23f199897c87841a9dc908bcd168dbfc93162ee4beaa1735a045b80c8ce5` | R6 (was `5be208ea…`) |
| `ontologylab/pack_v2_validate.py` | `ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6` | MATCH freeze |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` | MATCH freeze |
| `ontologylab/verified_pack_reader.py` | `6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1` | MATCH R6 freeze |
| `ontologylab/pack_v2_derive.py` | `7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577` | MATCH |
| `ontologylab/pack_source_fingerprint.py` | `a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7` | MATCH |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` | MATCH |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` | MATCH |
| `ontologylab/pack_readiness.py` | `550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21` | MATCH |
| `ontologylab/mcp_server.py` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` | MATCH |
| `tests/test_pack_v2_closure.py` | `96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff` | MATCH |
| `tests/test_packdiff.py` | `296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6` | MATCH |

Tracked increment vs HEAD: 9 files, +455 / −103. Untracked owned:
`pack_source_fingerprint.py`, `pack_v2_derive.py`,
`pack_v2_validate.py`, `tests/test_pack_v2_review_repair.py`.
Unrelated dirty `ontologylab/graphify-out/` left untouched.

Pure LOC: verifier 460 (`SIZE_OK` header — parse/inventory/CLI).
Repair tests 1329 `SIZE_OK`. Verifier tests 564 `SIZE_OK`.
validate 217 / derive 245 remain in the house warning band.

## Method

Read R6 executor, R1–R6 rollup, final security + final code, R5
executor. Read `pack_verifier.py` parse/verify/CLI,
`verified_pack_reader.activate_pack` / `inspect_verified_manifest`,
`packbuilder.scan_packs` / `list_packs`, MCP `list_packs` /
`load_pack` / `resource_manifest` / `_provenance` / 15 tools,
`pack_v2_validate._validate` gate, `pack_v2_manifest.finalize`,
builder v1 capability emission, and the new parse + disguise
tests. Independently probed `parse_manifest` on the table above.
Did not re-run source mutants, stdio MCP, or the full suite.

Reproduced once:

- R6-named pytest (parse allowlist/fields/omitted + legacy
  tree/no-tree/writable + disguise + builder v1 surface):
  **42 passed**, 1.06s
- focused 10-file set: **209 passed**, 1 pre-existing warning
- `tests/test_method_mcp_surface.py` + `tests/test_mcp_two_tier.py`:
  **22 passed**
- basedpyright / LSP / py_compile / no-excuse as above

## Residuals (do not flip by themselves)

- list/activate/MCP still emit **raw** post-verify `capabilities`
  rather than a receipt field. After R6 those strings are either
  the v1 allowlist or v2 labels that `_refuse_forged_capabilities`
  already matched to packed C-036. Defense-in-depth only.
- Honesty class (R4 H-V1-DISGUISE): a modern sqlite + `evidence/`
  tree rewritten as v1 with **only** allowlisted caps still
  verifies as `legacy-graph-only`. Not the named label-laundering
  hole.
- Carried final-code MINOR 1: graph-only v2 (no evidence cap, no
  contract keys) can still serve a citation-less verified node.
- Carried final-code MINOR 2: destroying receipt tables +
  `nodes.status` re-enters the inventory-only `_write_v2` skip;
  `load_pack` may `OperationalError` before switch; honest session
  held.
- Carried R1–R3: `find_path` has no citation receipts; EXCERPT
  writes `raw_text_path=''`; `_with_fact_receipts(conn: Any)`;
  MCP `_provenance` omits `capabilities`; `resolve_v2_closure`
  hardcodes `V2_CAPABILITIES`.
- `pack_schema_version: true` matches `case 1` (`True == 1`).
  Caps are still allowlisted. String `"1"` is refused.
- Advisory v2 keys not in `_V2_ONLY_FIELDS` (`generation`,
  `exclusions`, `selection_policy_version`,
  `source_material_policy`) can ride along on a v1-legal pack.
  Nothing authorizes on them.
- `mcp_server.py` FastMCP `reportReturnType` wrappers
  (pre-existing).
- Full suite not re-run here; last committed-suite claim remains
  `task-12-final-full-suite.md` on HEAD, not on these dirty bytes.

## Protected

- HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`
- Product/test bytes MATCH the hash table (rehashed after probes)
- PID 55560 still `127.0.0.1:8799` DEVICE `0x1ff51c806b197195`
- Application Support ino/mtime/size unchanged (stat only)
- No leftover `/tmp` pack trees from this review
- Prior review/security/QA/executor receipts not rewritten
- No commit/push/network/full suite/plan/authority edits
