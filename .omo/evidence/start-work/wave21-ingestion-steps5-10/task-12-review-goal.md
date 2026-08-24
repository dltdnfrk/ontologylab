# Task 12 goal review — committed Wave 2.1 Step 8

Date: 2026-08-24
Reviewer: omo senpi-task `st_01a031ee` (alternate-route recovery after
architect pre-tool failure)
Lane: independent product / canonical goal audit on committed HEAD.
Mode: read-only except this file. No product/test/plan/canonical edits.
No commit. No push. No full-suite rerun. No network. No live Application
Support open. Port 8799 / PID 55560 observed only.

Authority (section 0 / report §§6-9 win on conflict):
- `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md` §§6-9
- `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md` §0 and Step 8
- `.omo/mass-ulw/20260820-ingestion-integration/06-pack-contract.md` §§1,6-8,11
- Plan Todos 8-12 in `.omo/plans/wave21-ingestion-steps5-10.md`
- Step 8 kickoff: `.omo/ulw-loop/wave21-step7-representation-grounding-20260824/step8-kickoff.md`

Prior Task 8-12 executor / verifier / commit / suite receipts are claims.
This lane re-read committed bytes and recomputed identities. Suite / mutant
/ stdio numbers are bound to named receipts whose freeze hashes MATCH
current `HEAD:` blobs (except the noted hygiene drift on one test file).
Not re-executed here.

## Verdict

**NEEDS-FIX**

**Confidence:** 0.91

Committed HEAD `081d8554f814645517a29a0cef1c0e32af3d84df` (product
`d740a646574b843e3bb8958823c20fa0e883499f` + signature-sentinel repair)
implements the Step 8 *skeleton*: one-snapshot `full|excerpt` closure,
strict inventory verifier, process-owned immutable opener, F11 readiness,
and C-036 fail-closed labels. That is not enough to satisfy canonical
Step 8.

Three product requirements are not covered on the committed bytes:

1. MCP fact-bearing responses still do not carry Work / Representation /
   Citation receipts. Blueprint Step 8 surface and pack-contract §8 are
   explicit. Stdio tests only assert `result` exists.
2. Published v2 `counts` are overwritten from the wrong SQLite table map.
   `review_decisions` and `observations` systematically become `0` while
   `grounded_review_decisions` / `document_observations` hold the shipped
   closure. The GREEN test only asserts those two *keys exist*.
3. Pack-contract §7 `exclusions={...}` is absent. Finalize also drops
   `nodes_verified` / `edges_verified`, so `get_staleness` reports
   `pack_verified_count=0` for a valid v2 pack.

Step 9C has **not** executed. `FULL_V2_AUTHORITY` is still `False`.
PID 55560 still owns `127.0.0.1:8799` inode `0x1ff51c806b197195`.
This lane does not claim Wave 2.1 GO, production cutover, or Task 12
loop-close (reviews / index / Step 9 kickoff / evidence commit).

Blockers: G1, G2, G3 below. Repair the product; do not close Step 8.

## Binding identity (independently recomputed)

| Fact | Required / claimed | Observed now |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match |
| Tree | `8677230e75080e5fae606b8dfac568619bfd569c` | match |
| Subject | `test(pack): include evidence mode in signature contract` | match |
| Parent / product | `d740a646574b843e3bb8958823c20fa0e883499f` | match |
| Product tree | `3ff4a69d910df6deea70e9bb26f6fa5924e6482d` | match |
| Product subject | plan Todo 12 `feat(pack): complete verified v2 publication boundary` | match |
| Product parent | Step 7 evidence `1c06fef63451c836e3d9366b707e89d34e8ff037` | match |
| Product paths | 23 (15 product + 8 tests, including 6 newly tracked `review_decision*` modules) | `git diff-tree` exact |
| Signature path | only `tests/test_methodology_foundation_baseline.py` | `M` that file |
| 23-path content perimeter | `LC_ALL=C` sorted `path<TAB>content-sha256\n` of `d740a64` | `4d00b6a6140696ec1d36c838e2a7c865e9554e9ce812bfb4251619c71944d08a` |
| Product tree perimeter | `git ls-tree -r d740a64 -- ontologylab tests scripts pyproject.toml` | `40aa6d5af0054ed89d24ee4f9a2e5bd71a394d3644ac7c7c9966291583b08ca8` (404 paths) |
| HEAD tree perimeter | same command on `081d855` | `5bfc7bbd2dcd61ceddc43c31ba5afc2c8590fa36007d6af6748fa8b15f8850e6` (404 paths). Matches assigned perimeter. |
| Tracked `ontologylab` / `tests` vs HEAD | clean | `git diff --quiet HEAD -- ontologylab tests scripts pyproject.toml` exit 0 |
| Staged index | empty | `git diff --cached --quiet` exit 0 |
| `origin/main` | unpushed | still `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`; `main` ahead 55; no remote contains HEAD |
| Full-suite receipt | `.venv/bin/python -m pytest` once on HEAD | `task-12-final-full-suite.md`: `2740 passed, 1 skipped, 2 xfailed`, exit 0, perimeter unchanged. Not re-run. |
| First committed-state suite | `d740a64` | 2739 / 1 fail (`test_build_pack_signature_has_explicit_method_selection`); sentinel then updated, assertion kept |
| `FULL_V2_AUTHORITY` | false | `ontologylab/ingestion_shadow.py:33` is `False` |
| Step 5 baseline SHA-256 | `019a986f878bcba5b2ba8c67a1451d8fc19af021988e28bdd9f7e2287f82f0b1` | still the pin in `tests/test_wave21_perf_baseline.py:29` |
| 8799 / PID 55560 | observe-only, unchanged | `python3.1 55560` `TCP 127.0.0.1:8799 (LISTEN)` DEVICE `0x1ff51c806b197195` |

HEAD blob SHA-256 (this lane, `git show HEAD:path | shasum -a 256`):

```
ontologylab/pack_v2_closure.py	3c82878de02f385584ee3d60970407a362e37d338727f695065eee4e831006e2
ontologylab/pack_verifier.py	052ec3d12ece21b4afd31485357a8082b131a55ec19f82527fc02ebc7037872c
ontologylab/pack_readiness.py	c2c4b13f673f8e46ad2bcd985234e947b184f4d3edbfb2a7a4cfb5b1ce92e0e5
ontologylab/pack_receipt_seal.py	93a51a1e0d32f558da3e6ee4c960e400bd4191849690b57198f2f733dea17751
ontologylab/pack_v2_manifest.py	f1f629c9b6e492285eaa1ac4e78b6c523fef22275546af80fa419f92332267a4
ontologylab/verified_pack_reader.py	6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1
ontologylab/packbuilder.py	e903936ec8df14e37396d2c3db579713840cd64f82df8aeb83d4e012e81867b7
ontologylab/packdiff.py	cc148c3d4bd444f2f0cae1e4764ed03b28f6194472c5893d22e2edf5addb0292
ontologylab/mcp_server.py	a0767807ea3cd3c44b57edb438f598b34bc99ef55ba4d204dde4321c915f262d
tests/test_pack_v2_closure.py	105f97fb4979abcf640e1318dfaac515171466beba96a7e5df39443d5cb1895d
tests/test_pack_v2_verifier.py	9bb61f372a09efdac483a04c0b7996ac7a60a369eb9e018e11575d8f819d3660
tests/test_pack_readiness_refusal.py	fc3985fe9d04a31e92d71dbae0cc69d142019d025f498c1e789bfea42868e8e7
tests/test_pack_v2_publication_surface.py	5ae476936ccc00ae2ad2a3c2576513abb1f3946fbd136ae87bb742500dc5d9ba
tests/test_verified_pack_reader.py	7bdfa1c4a2da2fbb472c77d7e629525762eeaa0cd0509fae0ba614d79e7ec095
tests/test_mcp_pack_integrity.py	25e109033875766b5a24a20b81984e241274341b6eff1b10b204f005e2d7e322
tests/test_packdiff.py	daae25385e55492289dafd662bb8a5a4a6bc51c4e3ebcd9a9fcca646e74281bc
tests/test_methodology_foundation_baseline.py	60bdd4c07ad1b386a9eeb9f61714e9c604e7b52246b99916e4275016db849048
```

Hygiene drift (not a mutant-table bind): repair-verifier freeze of
`tests/test_pack_readiness_refusal.py` was `71939bec…`. HEAD is
`fc3985fe…`. Ledger hygiene removed an unused `family` parameter from
`test_new_c036_cannot_bless_invalid_receipt_id`. Production files above
match the repair freeze. Same-ID / new-C036 refusals remain in the file.

## Blockers

### G1 — MCP does not report Work / Representation / Citation receipts

Canonical: pack-contract §8; blueprint Step 8 surface; pack-contract §11
row “Independent MCP receipt” was a baseline GAP Step 8 owns.

`PackSession._provenance` (`mcp_server.py:318-321`) returns only
`{"pack_id", "content_hash"}`. `compact_node` keeps `id` / `name` /
`source_doc_id` and drops span/citation. No `work_id`,
`representation_id`, `representation_content_hash`, `citation_id`,
`selected_text_hash`, `evidence_mode`, `pack_schema_version`, or
`integrity_level` on fact-bearing tools.

`tests/test_pack_v2_publication_surface.py` stdio path asserts
`initialized/result`, `list_packs` in tools, and `entity_lookup` has a
`result`. It never compares those receipts to packed rows.

Task 10 / 10-11-repair stdio claims are the same pack-id / hash /
`PaymentGateway` lookup class. They do not close §8 step 7.

### G2 — Published counts do not re-derive the shipped ReviewDecision / Observation closure

Canonical: report Step 8 GREEN “counts/capabilities derive from verified
payload”; pack-contract §7 count catalog; F11/C-045 “re-derive counts
from verified SQLite”.

`collect_v2_closure` computes honest counts from member lists
(`pack_v2_closure.py:239-254`, including `observations=len(observations)`
and `review_decisions=len(reviews)`). `packbuilder.py:758` copies those
onto `PackManifest.counts`. `finalize_v2_manifest` then **replaces**
`payload["counts"]` with `_rederive_counts` (`pack_v2_manifest.py:50`,
`116-135`).

That map is:

| Manifest key | Table used | Actual v2 table |
|---|---|---|
| `observations` | `observations` | `document_observations` |
| `review_decisions` | `review_decisions` | `grounded_review_decisions` |
| `citations` | `citations` (graph) | also `citation_receipts` |
| `extraction_runs` | `extraction_runs` | also `extraction_run_receipts` |

Missing tables become `0`. `authority.py` creates
`document_observations`, not `observations`. Shipped reviews live in
`grounded_review_decisions`.

`test_full_pack_resolves_every_closure_member_from_pack_bytes` asserts
`counts[k] >= 1` for works/representations/identifiers/citations/runs/
chunks/nodes/edges, and only `"observations" in payload["counts"]` /
`"review_decisions" in payload["counts"]`. That pins the hole.

Repair-verifier text that this “is the Task 9 re-derivation contract, not
a reopening of Gap 2” is an overclaim against pack-contract §7.

`packbuilder.py:630-631` still writes `nodes_verified` / `edges_verified`
before finalize. Finalize drops them. `get_staleness` then does
`counts.get("nodes_verified", 0) + counts.get("edges_verified", 0)`
(`mcp_server.py:301-304`) → `pack_verified_count=0` on a valid v2 pack.

### G3 — Pack-contract §7 exclusions catalog is not shipped

Normative manifest “at least” includes
`exclusions={ungrounded,waived,invalid_legacy_evidence,identity_conflicts,...}`.
`rg` over `pack_v2_closure.py` / `pack_v2_manifest.py` / the v2 finalize
path finds no `exclusions` key. Proposed / waived rows are omitted from
copy (G2-adjacent HOLD on *membership*), but the required exclusion
counts never appear.

## Per-requirement matrix

Independent reads of HEAD sources/tests. Suite / mutant / QA numbers are
bound to named receipts whose freeze hashes MATCH current `HEAD:` blobs.
Not re-executed here.

| ID | Criterion | Result | Evidence on `081d855` |
|---|---|---|---|
| 8A closure | One snapshot; Work/identifier/redirect/decision/Observation/Representation/source/run/chunk/Citation/ReviewDecision/policy/provenance; `full\|excerpt`; sourced `none` / dangling / cross-generation / missing receipt / incomplete stream / v1 rewrite fail before visible staging | **HOLD (membership)** | `CLOSURE_MEMBERS` + `OPTIONAL_FAMILIES={redirect,decision}`. `parse_evidence_mode` only `full`/`excerpt`. Tests: `test_sourced_none_*`, `test_dangling_member_*`, `test_cross_generation_*`, `test_missing_receipt_*`, `test_incomplete_stream_*`, `test_v1_rewrite_*`, `test_missing_generation_*`, `test_empty_optional_redirect_and_decision_publish`. `resolve_v2_closure` opens pack sqlite `mode=ro` only. |
| D15 / no `none` | Sourced fact cannot ship `none` | **HOLD** | Unknown mode → `SOURCED_NONE`. Unreviewed caps omit `sourced-answer-v2`. |
| D16 / v1 | Never rewrite / promote v1 | **HOLD** | `refuse_v1_rewrite`; `test_v1_rewrite_refused_and_preserves_bytes`; `test_v1_pack_omits_v2_inventory_when_evidence_mode_absent`; v1 verifier still `legacy-graph-only`. |
| D17 inventory | Dynamic inventory, owner-read-only, process-owned snapshot; hash is integrity | **HOLD** | `pack_v2_manifest.finalize_v2_manifest` inventories every non-manifest regular file, `0444`, `integrity_model=sha256-receipt-not-signature`. `activate_pack` verify → copy → reverify(`working=source`) → `KGStore.open(..., immutable=True)` (`mode=ro&immutable=1`). |
| Evidence reproduce | Every sourced fact from full bytes or sealed excerpt; hash compared at copy | **HOLD (builder)** | `write_v2_evidence` hashes `full.txt` vs Representation `content_hash` and excerpt vs `selected_text_hash`. Tests: `test_full_evidence_hash_mismatch_*`, `test_source_file_hash_drift_*`, `test_tampered_selected_text_*`. Standalone verifier does **not** recheck window/text hashes (residual). |
| Subset copy | Unrelated / unverified / `pack_ineligible` rows stay out | **HOLD** | Claimed-ID `copy_v2_tables`. `test_unrelated_and_ineligible_rows_are_absent_from_pack`. |
| Method closure | Selected Method source closure from the same snapshot | **HOLD (optional path)** | `copy_method_releases` still runs on the v2 snapshot. Not a required `CLOSURE_MEMBERS` family when `method_release_ids` is empty. |
| 8B verifier | Inventory every relative artifact; no self-ref; rederive claims/counts/closure; refuse missing/extra/tamper/symlink/hardlink/`0644`/path/original inode/forged hash/count | **PARTIAL** | Inventory/mode/link/inode/hash mutants and CLI matrix exist (`test_pack_v2_verifier.py`, repair-verifier `CONFIRMED` on `052ec3d1…`). Count rederive uses G2 map, so “rederive closure counts” is not honest. Verifier does not re-derive citation/window hashes (pack-contract §8 steps 4-6). |
| Manifest `lstat` | v2 `manifest.json` type/mode/nlink before bytes | **HOLD** | `_manifest_lstat` then `read_text`. Tests: writable / hardlink / symlink manifest. |
| C-044 | Same-inode mutation cannot change served snapshot under loaded receipt | **HOLD** | Detached copy + `working=source` kills hardlink. Tests: `test_load_pack_opens_detached_immutable_snapshot`, `test_activate_pack_ignores_source_mutation_after_load`, `test_resource_manifest_refuses_source_rewrite_after_load`. |
| C-045 / C-060 | Forged/malformed latest unusable before sort/count/policy | **HOLD (forged path)** | `scan_packs` only appends `inspect_verified_manifest` successes; failures → `unusable`. `test_staleness_refuses_forged_latest_manifest`, `test_list_packs_refuses_raw_unverified_path`. Pre-verify `json.loads` is pack_id / dirname only. **Not** HOLD for honest v2 count consumption (G2). |
| Shared opener | `load_pack`, `_store_for`, resources, schema, staleness, discovery, diff | **HOLD** | `activate_pack` / `inspect_verified_manifest` / `opened_verified_pack`. `packdiff.py:98-99` uses `opened_verified_pack`. Failed switch: `test_failed_switch_keeps_prior_session_byte_identical`. |
| F11 | Non-ready / incomplete / ambiguous / generation-drift / fingerprint / missing-as-ready / phase-only cannot publish; ready binds one generation; no visible dir | **HOLD** | `authorize_publication` + `_bound_ledger`. Tests in `test_pack_readiness_refusal.py` covering migrating / incomplete / ambiguous / drift / fingerprint / missing ledger / phase-named-ready / failed-attempt-preserves. Absence is typed refusal, not generation `0`. |
| C-036 | No reviewed/sourced publish or label without a bound C-036 receipt | **HOLD** | Missing table/row → unreviewed caps only. Requested sourced without receipt → `c036_required`. Binding is generation + fingerprint + inventory root + scope + `authorize`. Tests: `test_ready_unreviewed_publishes_without_c036`, `test_reviewed_without_c036_*`, `test_reviewed_with_valid_c036_*`, `test_stale_c036_*`. |
| Same-ID tamper | Body mutation keeping `receipt_id` cannot keep a valid C-036 / publish | **HOLD (bound)** | `seal_receipt_inventory` root is `[family, receipt_id, body_digest]`; IDs re-derived from public Step 7 constructors. Tests: `test_same_id_body_mutation_refuses_reused_c036`, `test_new_c036_cannot_bless_invalid_receipt_id`. Matches repair-verifier Gap 1 close on production freeze `93a51a1e…`. |
| MCP §8 receipts | Every fact-bearing response includes pack + Work + Representation + Citation receipts; stdio matches independent rows | **MISS — G1** | See blockers. |
| Counts / exclusions | Counts and exclusions re-derived from verified payload | **MISS — G2, G3** | See blockers. |
| Task 8 AC | RED invalid fixtures; GREEN resolve after source delete; named mutants die | **HOLD (bound)** | Executor + `task-8-repair-verifier.md` `CONFIRMED` on `3c82878d…` / `e903936e…` / `105f97fb…`. Focused 19 then later 121 with Tasks 9-11. Not re-mutated. |
| Task 9 AC | Legacy pin; standalone deterministic receipt; named inventory mutants | **HOLD (bound)** | `task-9-repair-verifier.md` `CONFIRMED` on `052ec3d1…` / `9bb61f37…`. 31 tests. CLI matrix bound. Count *honesty* is G2, not a Task 9 named mutant miss. |
| Task 10 AC | Tampered resource/staleness/diff/raw-path/writable/failed-switch refuse; prior session byte-identical | **HOLD (bound)** | `task-10-executor.md` + joint repair on opener freeze `6607a552…` / `a0767807…` / `cc148c3d…`. Original Task 10 stdio used v1 packs; Gap 2 repair re-ran stdio on a real v2 pack for load/list/lookup only. |
| Task 11 AC | Typed F11/C-036 refusals; no visible output; ready unreviewed publishes; reviewed/sourced needs C-036 | **HOLD (bound)** | Production `c2c4b13f…`. CLI matrix in executor. |
| Task 12 one complete pack | One valid v2 pack independently complete | **MISS** | Inventory + member IDs resolve after source delete. Counts / exclusions / MCP receipts do not meet pack-contract completeness. |
| Task 12 mutants | Every artifact/closure/mode/path/receipt/readiness/opener mutant dies | **HOLD (bound)** | Named Task 8-11 + ten repair mutants recorded kill/restore. Not re-run. |
| Task 12 opener / F11 | All readers share opener; F11 binary GREEN | **HOLD** | As above. |
| Task 12 same snapshot | Stdio + verifier receipt on the same snapshot | **PARTIAL** | Same `pack_id` / `pack_content_hash` on build → `verify_pack` → `activate_pack` → stdio load. Not Work/Representation/Citation receipts. |
| Task 12 suite | Exact suite, no perimeter drift | **HOLD (bound)** | `2740 passed, 1 skipped, 2 xfailed`, exit 0, HEAD/perimeter identical. First `d740a64` run failed only the signature sentinel; `081d855` kept equality. |
| Task 12 reviews / index / kickoff / evidence commit | All independent reviews confirmed; index/kickoff/commits consistent | **N/A this lane** | Reviews are in flight. No Step 8 evidence index or Step 9 kickoff yet. Not used as a product defect. |
| RED before change | Named RED then GREEN | **HOLD (historical, documented)** | Task 8-11 executors record module-missing / DID NOT RAISE RED, then GREEN. Joint verifier first `NEEDS-FIX` (same-ID + missing inventory) then repair `CONFIRMED`. |
| Compatibility | v1 graph-only preserved; `evidence_mode` omitted keeps v1; no authority flip | **HOLD** | `FULL_V2_AUTHORITY is False`. Signature sentinel now includes `evidence_mode: 'str \| None' = None`. |
| Step 9C stop | No 9C, no production cutover, no live data, no 8799 mutation | **HOLD** | No `authorization_required` / 9C implementation in `ontologylab/` / `tests/`. `FULL_V2_AUTHORITY = False`. Observe-only PID/port/inode unchanged. Canonical docs untracked and unread as write targets. |
| Protection | No network, no Application Support open, no denylist-as-authority, no plan/authority edits | **HOLD** | This lane wrote only this file. `review_decision*` are now tracked clean-checkout deps; pack product modules do not import them. |

## Overclaim register

Treat as **not proven** even if a receipt says DONE / CONFIRMED / complete:

- “Evidence-self-contained / independently complete” in the pack-contract
  sense, while MCP omits Work/Representation/Citation receipts and
  published `review_decisions` / `observations` counts are not the
  shipped families.
- “Stdio/verifier receipt same snapshot” if read as pack-contract §8
  step 7 (compare returned Work/Representation/Citation rows). Proven
  only as pack id/hash.
- Repair-verifier “Gap 2 closed” as anything more than: v2 manifest now
  has inventory/hashes, `verify_pack` / `activate_pack` / stdio
  initialize+lookup succeed. It explicitly waived G2 counts.
- Task 10 executor “DONE” stdio QA (v1 incomplete-extraction packs) as
  Task 12 same-snapshot v2 proof. Later repair replaced that QA class.
- `evidence-self-contained-v2` on an unreviewed fixture as a reviewed /
  sourced release. Unreviewed publish without C-036 is allowed; those
  caps must not be called reviewed/sourced. Current code keeps
  `sourced-answer-v2` off that path.
- “Hash authenticates the builder.” `integrity_model` correctly says
  `sha256-receipt-not-signature`.
- “Wave 2.1 / R10 complete”, “lossless ingestion”, “production cutover”,
  “DOI migration complete”, “tests GREEN ⇒ product GREEN”.
- Step 9C / maintenance-window execution inferred from F11 GREEN, suite
  GREEN, or 9B/10 success. 9C remains unauthorized. This increment must
  not be described as cutover.

Allowed staged wording (canonical §9 / blueprint §8):

> The v2 publication path passes fixture gates for closure membership,
> inventory, immutable open, F11, and C-036 labels. Production cutover
> has not occurred. MCP identity receipts, honest count/exclusion
> re-derivation, and Step 8 loop-close artifacts are not GREEN.

## Residuals (not additional blockers)

- Standalone verifier does not recompute Representation / selected-text /
  window hashes. Builder seals them; pack-contract §8 steps 5-6 are not
  the verifier’s current job.
- `scan_packs` still `json.loads` unverified `pack_id` before
  `inspect_verified_manifest`. Counts/policy are not consumed from that
  parse.
- `resolve_v2_closure` hard-codes `capabilities=V2_CAPABILITIES`
  (unreviewed pair) even when the manifest also has `reviewed` /
  `sourced-answer-v2`.
- Excerpt mode writes `documents.raw_text_path = ''` rather than SQL
  `NULL`.
- Six `review_decision*` modules are newly tracked so
  `test_pack_readiness_refusal.py` can plant `review_publication` /
  `review_decisions`. Live approve/review remains `grounded_review_*`.
  Dual schema is unused by the pack product path.
- `mcp_server.py` FastMCP `reportReturnType` diagnostics pre-exist.
- Task 12 index / Step 9 kickoff / evidence-only commit are not present.
  That is loop-close work after this review wave, not G1-G3.

## What this review is not

- Not a code, security, QA, context, or gate review.
- Not a claim that mutants, stdio, or the 2740-test suite were re-run.
- Not a rebound after a product repair of G1-G3.
- Not authorization for Step 9A/9B/9C.

## Protected boundaries (this lane)

- PID `55560` still
  `.venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 8799 --data-dir ~/Library/Application Support/ontologylab/data`.
- `127.0.0.1:8799` still LISTEN on that PID, inode `0x1ff51c806b197195`.
- Did not read Application Support contents.
- No network. No commit / push. No full suite. No product/test/plan/
  authority edits.
- Canonical analysis / blueprint / pack-contract / plan unread as write
  targets (SHA-256 of those files as read:
  analysis `d903bab4…`, blueprint `8598d3a3…`, pack-contract `2fd39f1d…`,
  plan `41ff74f5…`).
