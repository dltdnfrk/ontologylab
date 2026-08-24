# Task 12 dependent final gate — after R1–R6 repair

Date: 2026-08-24
Reviewer: omo senpi-task `st_01a03292`
Lane: dependent FINAL GATE on uncommitted Step 8 Task 12 R1–R6 bytes.
Predecessor `st_01a03291` failed `resource_exhausted` before tools;
`bytes_changed=false`. This receipt is the recovered full gate.

Mode: product / test / plan / authority **read-only**. This file is the
only write. No commit, push, network, Application Support contents,
8799 / PID 55560 mutation, full suite, or Step 9C. At most one
in-process `parse_manifest` probe (no pytest).

## Verdict

**APPROVED**

**Confidence:** 0.93

No residual on the current dirty tree undermines canonical Step 8
authority, `evidence-self-contained-v2`, or `reviewed` /
`sourced-answer-v2`. Every original and discovered blocker maps to
current closed evidence. Round 6 code / security / manual-QA are
independent **PASS** on these exact bytes.

This is **not** Task 12 loop-close. Product/test remain uncommitted.
No Step 8 evidence index, aggregate completion, or Step 9 kickoff
exists. Plan Todo 12 is still `- [ ]`. `FULL_V2_AUTHORITY` is
`False`. Step 9C has not executed and is not authorized.

## Binding identity

| Fact | Observed |
|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged) |
| Tree | `8677230e75080e5fae606b8dfac568619bfd569c` |
| Subject | `test(pack): include evidence mode in signature contract` |
| Index | empty (`git diff --cached --quiet` exit 0) |
| Repair | uncommitted working tree vs HEAD: 9 modified + 4 owned untracked |
| `FULL_V2_AUTHORITY` | `False` (`ontologylab/ingestion_shadow.py:33`) |
| PID 55560 | still `127.0.0.1:8799` DEVICE `0x1ff51c806b197195` |
| Application Support `ontologylab` | ino `102434596` mtime_ns `1785487752937707432` size `192` (stat only) |

Authority read-only (unread as write targets):

| Path | SHA-256 | size |
|---|---|---:|
| analysis | `d903bab4a526cb21dc8473d471040fde940761573f3f579d22b86d91c7c42b19` | 43015 |
| blueprint | `8598d3a374c6badc65c481116745e482191dc39117813501dac5372d6092125c` | 40995 |
| pack-contract | `2fd39f1d6dce72fb4cb73b58afe03a018f949399c8565aab2fc2e33ff49c5372` | 19872 |
| plan | `41ff74f52a0752d135b129bccdeff273ab07c28d055fec4e4c6e983a45e873fc` | 45752 |
| Step 8 kickoff | `564dfd414503072125970964a1e2defa9b0e55c79dde6eaab23248f838ef4873` | 6800 |

### Entry = exit product/test SHA-256

Rehashed at gate start and after the parse probe. MATCH Round 6 freeze
and R6 executor table.

| Path | SHA-256 |
|---|---|
| `ontologylab/mcp_server.py` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` |
| `ontologylab/pack_readiness.py` | `550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21` |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` |
| `ontologylab/pack_verifier.py` | `2b64a110fa3789de3a53245e950f73cb8dccc9bdb78025394fbe3316b55130ed` |
| `ontologylab/pack_v2_derive.py` | `7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577` |
| `ontologylab/pack_source_fingerprint.py` | `a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7` |
| `ontologylab/pack_v2_validate.py` | `ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6` |
| `ontologylab/verified_pack_reader.py` | `6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1` |
| `tests/test_pack_v2_review_repair.py` | `622c7602c2f961c4dca98711d409c87123c257227d0610046e6e11a2ba417b76` |
| `tests/test_pack_v2_closure.py` | `96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff` |
| `tests/test_pack_v2_verifier.py` | `78ae23f199897c87841a9dc908bcd168dbfc93162ee4beaa1735a045b80c8ce5` |
| `tests/test_packdiff.py` | `296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6` |

Unrelated dirty (`ontologylab/graphify-out/`, `.gjc/`, `.sisyphus/`,
`artifacts/`, untracked docs, `uv.lock`) is out of perimeter.

## Authority used

- Step 8 kickoff (section 0 / blueprint wins on conflict)
- pack-contract §§7–8
- plan Todos 8–12
- Original five reviews; R1–R6 executors; Round 6 code / security /
  manual-QA PASS; repair-goal PASS
- Ledger `.omo/ulw-loop/wave21-step8-pack-publication-20260824/ledger.jsonl`
  through `review_repair_dependent_final_gate_recovered`

Prior receipts treated as claims except where this lane re-read bytes
or re-probed parse. Suite numbers are bound to named receipts whose
freeze hashes MATCH the table above. Not re-executed here.

## Independent checks this lane

- Rehashed every owned product/test path; MATCH Round 6 / R6 executor.
- Read `_parse_v1` / `_V1_CAPABILITIES` / `_V2_ONLY_FIELDS`,
  `_refuse_forged_capabilities`, `_verify_v2` →
  `validate_packed_v2_closure`, `derive_v2_counts` /
  `derive_capabilities` / `derive_exclusions`,
  `_provenance` / `_with_fact_receipts` / `document_raw_text`,
  `--publish` typed catches, `_copy_c036`, 15 `@mcp.tool()` wrappers.
- In-process `parse_manifest` (`.venv/bin/python`, no pack tree):

  | Input | Result |
  |---|---|
  | historical no-cap / graph-v1 / graph+methodology | `ManifestV1` |
  | explicit `1` + four v2/reviewed strings | `invalid_manifest:capabilities` |
  | omitted schema + same four strings | `invalid_manifest:capabilities` |
  | `true` / `1.0` / `null` + `reviewed` | `invalid_manifest:capabilities` |
  | string `"1"` / `false` | `invalid_manifest:pack_schema_version` |
  | `methodology-v1` alone | `invalid_manifest:capabilities` |
  | schema `1` + `closure` | `invalid_manifest:closure` |
  | graph-v1 + sibling `"reviewed": true` | `ManifestV1` (residual L1) |

- 15 MCP tools: `list_packs`, `get_staleness`, `load_pack`,
  `get_schema`, `entity_lookup`, `get_communities`, `get_entity`,
  `semantic_search`, `graph_query`, `traverse_relations`, `find_path`,
  `list_methods`, `get_method`, `trace_method`, `list_method_gaps`.
  `document_raw_text` is a `PackSession` method, not a 16th tool.
- `rg` over `ontologylab/` + `tests/` finds no `authorization_required`
  / Step 9C implementation and no `FULL_V2_AUTHORITY = True`.
- No pytest / full suite. Last committed-state suite claim remains
  `task-12-final-full-suite.md` (`2740 passed / 1 skipped / 2 xfailed`)
  on HEAD, not on these dirty bytes.

Lead verification (claim, bound to these hashes): R6 executor +
Round 6 code review — focused 10-file set **209 passed**; affected +
methodology 15-file set **139 passed**; basedpyright 0/0/0;
`python3.11 -m py_compile` EXIT 0; LSP clean.

## Blocker map

Every original / discovered blocker → current evidence. Status is
**CLOSED** unless named residual.

| ID | Blocker | Provenance | Closed by | Current evidence |
|---|---|---|---|---|
| G1 | MCP fact responses omit Work / Representation / Citation receipts | original goal | R1 `mcp_server` + `fact_receipts` | `_with_fact_receipts` on lookup / get_entity / semantic_search / graph_query / traverse. `_provenance` adds schema / integrity / evidence_mode. Repair-goal HOLD; Round 6 code CLOSED |
| G2 | Published counts from missing / v1 tables; `nodes_verified` dropped; staleness 0 | original goal + code MAJOR 1–2 | R1 `derive_v2_counts` | Counts from `document_observations`, `grounded_review_decisions`, `citation_receipts`, `extraction_*_receipts`, plus verified node/edge filters. Finalize + verify share the map. `FORGED_COUNTS` if they disagree |
| G3 | Pack-contract §7 `exclusions` catalog absent | original goal | R1 `derive_exclusions` + `v2_manifest_fields` | Four required keys shipped. **Advisory residual** (not a verify pin; cannot mint labels) |
| C3 | `contained_documents_path` cannot open `evidence/` | original code MAJOR 3 | R1 `resolve_pack_evidence` | `PackSession.document_raw_text` reads `evidence/<id>/full.txt` from the serving tree. Excerpt → typed `excerpt_only` |
| C4 | `--publish` traceback on closure / build | original code MAJOR 4 | R1 `pack_readiness` | Catches `PackV2ClosureRefused` / `IncompleteExtractionError` / `PackBuildError` → `{ok:false,code,member}` exit 2. Probe: `sourced_none` |
| S-M1 | Post-publish `reviewed` / `sourced-answer-v2` forge; labels not re-derived | original security MEDIUM | R1 packed C-036 + `_refuse_forged_capabilities` | Claimed caps must equal `derive_capabilities` (packed C-036 + witness). Forge → `invalid_manifest:capabilities` |
| R1-C | Live C-036 full inventory root ≠ valid shipped subset | repair-1 code MAJOR | R2 inventoried `receipt-inventory.json` | Live witness bound by `pack_content_hash`. Packed triples ⊆ witness. Extra live run unshipped |
| R2-C | Live full-document fingerprint ≠ valid packed document subset | repair-2 code MAJOR | R3 inventoried `source-fingerprint.json` | Packed document pairs must be witness members. Extra unpublished doc unshipped |
| R3-S | Hash-refreshed incomplete packed closure still verifies | repair-3 security residual | R4 `validate_packed_v2_closure` | Deleted citation / document / review / run / chunk / policy / evidence or dangling closure ID → `invalid_manifest:<member>` before serve |
| R4-S | `evidence-self-contained-v2` survives after stripping `evidence_mode`+`closure` | repair-4 security MEDIUM | R5 evidence-cap ⇒ typed contract | `needs_closure = reviewed or claims_contract or (advertised and packed_v2_graph)`. Missing keys → `invalid_manifest:closure` |
| R4-Q | Real stdio MCP switched onto closure-stripped pack | repair-4 bypass QA | R5 + opener | `load_pack` `isError`; prior honest session held (R5/R6 QA) |
| R5-S / FC | v2 / reviewed labels laundered through v1 parse (`schema=1` or omitted) | final security MEDIUM + final code MAJOR | R6 `_parse_v1` allowlist + `_V2_ONLY_FIELDS` | This lane’s parse probe: four-field disguise → `invalid_manifest:capabilities` before `_verify_v1`. Round 6 list / activate / MCP refuse; session held |
| CTX | Scope / Git / evidence fidelity | original context | n/a (PASS) | Still HOLD: Step 8-only, no 9C slip, unrelated dirty preserved |
| MQA-0 | Original manual QA PASS not dispositive over G1–G3 / S-M1 | original manual | R1–R6 + Round 6 MQA | Round 6 real stdio 15 tools; disguises `isError`; honest `6b6aafae…` held |

## Required-claim map

| Claim | Status | Why it does not reopen |
|---|---|---|
| Provenance on fact tools | **HOLD** | G1 closed on lookup / entity / search / graph / traverse. `find_path` still pack-only (residual; does not mint sourced) |
| Counts / staleness | **HOLD** | Honest v2 tables; `nodes_verified` / `edges_verified` survive finalize |
| Exclusions catalog | **HOLD (advisory)** | Shipped; not re-compared at verify; not an authorization input |
| Raw text | **HOLD** | FULL from packed `evidence/`; excerpt typed limitation |
| Typed CLI | **HOLD** | Closure / sourced-none / invalid_manifest JSON exit 2, no traceback |
| C-036 labels | **HOLD** | Re-derived from packed C-036 + witnesses; v1 cannot carry them |
| Live receipt / document witnesses | **HOLD** | Extra live rows stay out of sqlite/MCP; witnesses inventoried |
| Packed closure semantics | **HOLD** | Validator refuses incomplete rematerialized packs before serve |
| Evidence-cap closure requirement | **HOLD** | Advertising `evidence-self-contained-v2` on a real v2 graph requires the typed contract |
| Strict v1 / v2 parser / served labels | **HOLD** | v1 allowlist; v2-only fields refuse; raw JSON served only after verify |
| v1 / synthetic-v2 compatibility | **HOLD** | Builder v1, historical no-cap, methodology-v1, tree / no-tree / writable / extra-file, inventory-only `_write_v2` stay valid |
| Prior session | **HOLD** | Failed disguise / strip / cite / witness loads leave honest session byte-identical (Round 6 MQA) |
| 15 MCP tools | **HOLD** | Counted 15 `@mcp.tool()`; no 16th |
| Step 9C stop / protected state | **HOLD** | No 9C impl; authority `False`; 8799 / AS / canonical docs unchanged |

## Residual classification

None of these mint `reviewed`, `sourced-answer-v2`, or
`evidence-self-contained-v2`, or rewrite canonical authority.

1. **Advisory exclusions.** `exclusions={ungrounded,waived,invalid_legacy_evidence,identity_conflicts}`
   is a shipped catalog of rows *not* in default closure. Verify does
   not pin it. Forging the catalog cannot add members or labels.

2. **Witness id / digest metadata.** Inventoried
   `receipt-inventory.json` / `source-fingerprint.json` expose
   unshipped `receipt_id` + `body_digest` / document id+hash to
   filesystem readers. MCP / serving sqlite cannot query those rows.
   Bytes are hash-bound. Audit payload, not a capability path.

3. **Subset / new-content vs internal completeness.** Extra live
   runs/docs staying unshipped is the R2/R3 contract (packed ⊆ live
   witness). Deleting a packed closure member and rematerializing
   hashes is a *new* identity and is refused as incomplete (R4/R5).
   Those are different predicates. Internal completeness is enforced;
   live-superset publication is allowed.

4. **Raw non-authoritative sibling keys.** `_parse_v1` does not close
   the JSON object. A v1-legal allowlist plus `"reviewed": true` or
   `"integrity_level": "evidence-self-contained-v2"` still verifies
   as `legacy-graph-only`. Served raw JSON may echo the sibling.
   Product authority is the `capabilities` array (allowlisted) or
   verifier `integrity_level` (`legacy-graph-only`). Confirmed by
   this lane’s sibling-key probe. Same unsigned-extra-field class as
   historical `created_ts`.

5. **Bool / float v1 routing still strict.** `True` / `1.0` / `null`
   enter `_parse_v1` via `match raw.get(..., 1)`. Allowlist still
   runs before `_verify_v1`. Strings / `false` refuse
   `pack_schema_version`. Not a label bypass. This lane reproduced
   every cell.

6. **217 LOC validator warning.** `pack_v2_validate.py` is in the
   house warning band (gate + SQL completeness). Next edit should
   split. Not a product hole. `pack_verifier.py` 460 is `SIZE_OK`.

Carried non-blockers (do not flip): `find_path` omits citation
receipts; EXCERPT still writes `raw_text_path=''`;
`resolve_v2_closure` hardcodes unreviewed caps (labels come from
manifest / derive); graph-only v2 without evidence cap can serve a
citation-less verified node without claiming evidence-self-contained;
destroying receipt tables **and** `nodes.status` re-enters the
inventory-only skip (`load_pack` errors before switch); standalone
verifier does not rehash citation windows (builder + C-036 body
digest still bind reviewed packs); `mcp_server.py` FastMCP
`reportReturnType` wrappers pre-exist.

## What this approval is not

- Not a committed-state gate. Dirty repair must be committed first.
- Not Wave 2.1 GO, production cutover, or DOI migration complete.
- Not authorization for Step 9A / 9B / 9C or `FULL_V2_AUTHORITY`.
- Not a claim that the 2740-test suite was re-run on these bytes.
- Not permission to edit authority / plan / live Application Support
  / 8799 / PID 55560.

Allowed staged wording:

> Uncommitted R1–R6 repair on HEAD `081d855` closes every Task 12
> review blocker for evidence-self-contained pack v2, C-036 labels,
> honest counts, MCP fact receipts, typed CLI, packed closure, and
> v1/v2 parse separation. Production cutover has not occurred.
> Step 9C remains unauthorized.

## Permit (exactly this sequence)

1. Commit **only** the exact repair product/test paths:

   ```
   ontologylab/mcp_server.py
   ontologylab/pack_readiness.py
   ontologylab/pack_receipt_seal.py
   ontologylab/pack_v2_closure.py
   ontologylab/pack_v2_manifest.py
   ontologylab/pack_verifier.py
   ontologylab/pack_source_fingerprint.py
   ontologylab/pack_v2_derive.py
   ontologylab/pack_v2_validate.py
   tests/test_pack_v2_closure.py
   tests/test_pack_v2_verifier.py
   tests/test_packdiff.py
   tests/test_pack_v2_review_repair.py
   ```

   Do not stage `ontologylab/graphify-out/`, `uv.lock`, docs,
   `.gjc/`, `.sisyphus/`, `artifacts/`, or this evidence file in
   that product commit.

2. Independent commit / perimeter verify on the new commit.
3. Exact committed-state full suite once on that perimeter
   (`.venv/bin/python -m pytest`), before/after perimeter hash
   unchanged, exit 0.
4. Then evidence index / aggregate / verbatim Step 9 kickoff as
   evidence-only work. Do not implement Step 9.

## Step 9C / protected

- Step 9C remains unauthorized. Do not execute or imply cutover.
- PID `55560` still
  `.venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 8799`
  DEVICE `0x1ff51c806b197195`.
- Application Support directory identity unchanged; contents unread.
- No network. No leftover `/tmp` trees from this gate.
- Prior review / executor receipts not rewritten.

## Stop

Strict verdict: **APPROVED**.
