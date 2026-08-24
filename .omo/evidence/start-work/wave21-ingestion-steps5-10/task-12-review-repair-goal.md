# Task 12 repair goal review — uncommitted R1–R6

Date: 2026-08-24
Reviewer: omo senpi-task `st_01a031ee`
Lane: independent goal re-audit of the uncommitted Task 12 review
repair against prior `task-12-review-goal.md` G1–G3 and the R1–R6
surfaces named by the repair executor.
Mode: product/test **read-only**. Only this file is written. Original
`task-12-review-goal.md` preserved
(SHA-256 `b3cfab4b3dd5d02577a537af0a232e4402f81a5ddbfa025c92680d2a024009be`,
verdict still **NEEDS-FIX** on committed HEAD).
No commit. No push. No full suite. No network. No Application Support
open. Port 8799 / PID 55560 observed only. No authority / plan edits.

Authority (section 0 / report §§6-9 win):
- `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md` §§6-9
- `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md` §0 / Step 8
- `.omo/mass-ulw/20260820-ingestion-integration/06-pack-contract.md` §§7-8
- Plan Todos 8-12; Step 8 kickoff
- Prior goal G1–G3; code MAJORS 1–4; security MEDIUM C-036 label forge

Executor `task-12-review-repair-executor.md` is a claim. Hashes, suites,
and probes below were re-measured on the current dirty tree.

## Verdict

**PASS**

**Confidence:** 0.90

The uncommitted R1–R6 repair closes every prior goal blocker on the
current bytes. Independently: MCP fact surfaces now carry Work /
Representation / Citation receipts plus pack schema/integrity/mode;
published v2 counts match packed `document_observations` /
`grounded_review_decisions` / receipt tables and
`nodes_verified`/`edges_verified`, so staleness is nonzero; required
exclusion keys are snapshot-derived; FULL raw text reads
`evidence/<rep>/full.txt` from the serving tree; excerpt is a typed
limitation; CLI `--evidence-mode none` is exit 2 machine JSON with no
traceback; capabilities are re-derived from packed C-036 and
post-publish reviewed/sourced forgery is `invalid_manifest`.

v1 (`evidence_mode` omitted) still has no v2 inventory. Step 9C has
not executed. `FULL_V2_AUTHORITY` is `False`. PID 55560 still owns
`127.0.0.1:8799` inode `0x1ff51c806b197195`.

This is **not** Task 12 loop-close (reviews-as-a-set, evidence index,
Step 9 kickoff, product commit of this repair). It is not Wave 2.1 GO.

## Binding identity (this tree)

| Fact | Observed |
|---|---|
| HEAD (unchanged) | `081d8554f814645517a29a0cef1c0e32af3d84df` |
| Index | empty (`git diff --cached --quiet`) |
| Product/test vs HEAD | dirty: 8 modified + 2 new owned files (plus unrelated `ontologylab/graphify-out/`) |
| Origin | `4ee5465b…`; not pushed |
| `FULL_V2_AUTHORITY` | `False` |
| 8799 / PID 55560 | LISTEN inode `0x1ff51c806b197195` before and after probes |
| Original goal review | still **NEEDS-FIX**; not edited |

Working-tree SHA-256 (this lane; match executor):

```
ontologylab/pack_v2_derive.py	53ff5ac530e2e62a5cf069c4a54eca0332a427a3e2c6f245119c5cd5debe0a55
ontologylab/pack_v2_manifest.py	6e87c1075e327942ce6ef4ab118350345efa675b5045984dda23ef91d8f34675
ontologylab/pack_v2_closure.py	2db1454ae6517d29a038e1c94c6ee47f4f614659e68801f4f9ce90843dd14d55
ontologylab/pack_verifier.py	e9ad5467f6a5cba3d658a21613819fef22b6a1f79d56180f36ceb4395f81cc53
ontologylab/pack_readiness.py	550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21
ontologylab/mcp_server.py	137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89
tests/test_pack_v2_review_repair.py	5594956f904017e4ac1ca50bde019b2632afc157966e6a5db9ed1d8d10662276
tests/test_pack_v2_closure.py	96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff
tests/test_pack_v2_verifier.py	5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b
tests/test_packdiff.py	296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6
```

## Suites / typing (reproduced; no full suite)

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py --override-ini addopts= -v
7 passed in 1.02s
EXIT:0
```

Focused (same 10-file set as the executor, once):

```
… test_pack_v2_review_repair.py + Task 8–11 surfaces + test_staleness.py
140 passed, 1 warning in 7.02s
EXIT:0
```

Affected + methodology (same 15-file set, once):

```
139 passed, 1 warning in 7.18s
EXIT:0
```

`basedpyright` on derive/manifest/closure/verifier/readiness + the three
changed test files: `0 errors, 0 warnings, 0 notes`.
`python3.11 -m py_compile` on all six changed production files: EXIT 0.
Pre-existing FastMCP `reportReturnType` on unread `mcp_server.py`
wrappers not re-opened.

## Independent disposable probe

Root `/var/folders/…/t12-goal-reprobe-583fed2k` (removed). Ready
reviewed/sourced pack `probe-20260824-133522` plus excerpt / CLI /
unreviewed-forge / v1 fixtures.

| Probe | Observed |
|---|---|
| Packed counts vs SQL | `observations=1`, `review_decisions=3`, `citations` match `citation_receipts`, `nodes_verified=2`, `edges_verified=1` |
| Staleness | `pack_verified_count=3` (`2+1`), `latest_pack_id=probe-20260824-133522` |
| Caps | `knowledge-graph-v2`, `evidence-self-contained-v2`, `reviewed`, `sourced-answer-v2` |
| Packed C-036 | 1 row in `c036_capability_receipts` |
| Exclusions keys | `ungrounded`, `waived`, `invalid_legacy_evidence`, `identity_conflicts` |
| FULL `raw_text_path` | `evidence/<rep>/full.txt` |
| `verify_pack` | `integrity_level=evidence-self-contained-v2` |
| `entity_lookup` pack | schema `2`, `integrity_level`, `evidence_mode=full`, matching `content_hash` |
| `entity_lookup` fact | `work_id`, `representation_id`, `citation_id`, `selected_text_hash` equal packed rows |
| `get_entity` / `semantic_search` / `graph_query` / `traverse_relations` / `resource_entity` | each carries `citation_id` (edges: work/representation/citation) |
| `document_raw_text` FULL | `available=True`, path `evidence/<rep>/full.txt`, 44 bytes == plant text |
| excerpt | `raw_text_path=''`; session returns `available=False`, `limitation=excerpt_only`, `text=None` |
| CLI `--evidence-mode none` | exit 2, `{"code":"sourced_none","member":"source","ok":false}`, no traceback |
| Forge `reviewed`+`sourced-answer-v2` on unreviewed | `PackVerifyCode.INVALID_MANIFEST`; `list_packs` omits both labels |
| v1 `evidence_mode` omitted | `test_v1_pack_omits_v2_inventory_when_evidence_mode_absent` PASS; no `artifact_inventory` |
| 9C / authority flip | `FULL_V2_AUTHORITY is False`; no 9C symbols in the dirty pack modules |

## Prior findings → current

| ID | Prior miss | Result now | Evidence |
|---|---|---|---|
| G1 / R MCP | `_provenance` was only `pack_id`/`content_hash`; compact rows had no Work/Representation/Citation | **HOLD** | `_with_fact_receipts` + `fact_receipts()` on lookup, get_entity (and resource_entity via `_entity_detail`), semantic_search, graph_query, traverse. `compact_node` / `compact_edge` keep the eight receipt keys. `_provenance` adds schema / integrity / evidence_mode from the verified snapshot. Probe compared lookup receipts to packed `citation_receipts` / `documents`. |
| G2 / R counts | finalize counted missing `observations` / `review_decisions`; dropped `nodes_verified` | **HOLD** | `derive_v2_counts` uses `document_observations`, `grounded_review_decisions`, `citation_receipts`, `extraction_*_receipts`, plus verified node/edge filters. `finalize_v2_manifest` and `verify_pack` both call it. Closure test now asserts `observations` / `review_decisions` / `nodes_verified` `>= 1`. Probe: counts == packed SQL; staleness `3`. |
| G3 / R exclusions | no `exclusions` catalog | **HOLD** | `collect_v2_closure` stores `derive_exclusions(snapshot)`; `v2_manifest_fields` ships the four required keys. Repair test plants proposed / waived / collision / H1 quarantine and asserts each `>= 1`. Probe saw all four keys on a ready reviewed pack. |
| Code MAJOR 3 / R raw text | `document_raw_text` refused `evidence/…` via `documents/` containment | **HOLD** | New `PackSession.document_raw_text` → `resolve_pack_evidence` on the serving tree. FULL requires claimed path `evidence/<id>/full.txt` inside the pack. Excerpt (`''` or `window.txt`) is `excerpt_only`. Not added as a 16th FastMCP tool (15-tool contracts stayed GREEN in the 139-file run). |
| Code MAJOR 4 / R CLI | `--publish` only caught `PackReadinessRefused` | **HOLD** | Also catches `PackV2ClosureRefused`, `IncompleteExtractionError`, `PackBuildError` and emits `{ok:false,code,member}` exit 2. Probe: `sourced_none`. |
| Sec MEDIUM / R C-036 labels | post-publish capability edit verified and listed | **HOLD** | `_copy_c036` into pack sqlite. `derive_capabilities` rebinds ledger + fingerprint + inventory root + `authorize` + reviewed/sourced scope. `verify_pack` `_refuse_forged_capabilities`. Forge probe: `invalid_manifest`; discovery does not advertise forged labels. |
| v1 compatibility | must survive | **HOLD** | `evidence_mode` omitted still writes no v2 inventory / integrity model. Affected + methodology 139 including `test_methodology_foundation_baseline.py`. |
| Step 9C stop | must remain unauthorized | **HOLD** | `FULL_V2_AUTHORITY = False`. No 9C / live Application Support / 8799 mutation. Observe-only inode unchanged. |

## Residuals (not goal blockers)

- `find_path` attaches pack provenance only; the path payload is ids, not
  per-node citation rows. Fact tools/resources above do carry receipts.
- `fact_receipts` takes `ORDER BY receipt_id LIMIT 1`. Multi-citation
  facts expose one id, not the full set.
- Excerpt still stores SQL `raw_text_path=''` rather than `NULL`. The
  required consumer treats empty / window as `excerpt_only`.
- Verifier re-derives counts and capabilities, not exclusion integers.
  Forging exclusion counts without touching payload bytes would still
  verify. Pack-contract §7 “before use” names counts/capabilities/
  source policy/schema ids.
- Inventory `owner` / `redistribution` / `created_ts` remain outside
  `pack_content_hash` (prior security residual).
- `document_raw_text` is a `PackSession` method, not a FastMCP tool.
- Dual `review_decision*` / `grounded_review_*` schemas unchanged.

## Overclaim still forbidden

Do not claim Wave 2.1/R10 complete, production cutover, 9C, or
reviewed/sourced release as a general capability. Hashes remain
integrity, not authenticity. This PASS is the *repair goal* on the
dirty tree, not a committed-state Step 8 close.

Allowed wording:

> On the uncommitted R1–R6 bytes, fixture v2 publication now meets
> the prior goal blockers for MCP identity receipts, honest counts
> and staleness keys, required exclusions, FULL/excerpt raw-text
> consumption, typed CLI closure refusal, and C-036 label re-derivation.
> Production cutover has not occurred.

## Protected boundaries

- Wrote only this file. Did not touch `task-12-review-goal.md`.
- Did not edit product/test/plan/canonical files.
- Did not commit, push, open Application Support, or use the network.
- Disposable probe root removed. No leftover listeners.
