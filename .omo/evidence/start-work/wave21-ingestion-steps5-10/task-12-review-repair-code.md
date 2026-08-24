# Task 12 repair code review — R1–R6 (uncommitted)

Reviewer: omo senpi-task `st_01a031ef`
Date: 2026-08-24
Lane: independent re-review of the uncommitted Task 12 review repair.
Constraint: this report is the only write. Original
`task-12-review-code.md` left untouched. Product/test read-only. No
commit/push; no network; no Application Support; no 8799 / PID 55560;
no authority / plan edits. No full suite.

Executor `task-12-review-repair-executor.md` treated as a claim.
Review is bound to the current worktree against HEAD
`081d8554f814645517a29a0cef1c0e32af3d84df`.

## Verdict

**NEEDS-FIX**

**Confidence:** 0.90

The four original MAJOR holes are actually closed: counts come from
the packed v2 tables and keep `nodes_verified` for staleness; FULL
bytes are read from the process-owned snapshot via
`resolve_pack_evidence`; the publish CLI emits typed JSON for closure
and build refusals; MCP fact rows carry pack/work/representation/
citation receipts. Forged `reviewed` / `sourced-answer-v2` labels
die.

The new C-036 capability derivation is not authoritative. Finalize
overwrites live-authorized capabilities by resealing the **packed
subset** against a C-036 row still bound to the **live** inventory
root. A legal second run receipt that is not in the shipped closure
makes `authorize_publication` grant reviewed/sourced and the disk
manifest drop both labels. Reproduced on disposable bytes (see
probe). That is a blocking publish defect, fail-closed but wrong.

No CRITICAL (no BaseException swallow, no live-path evidence
fallback, no opener bypass, no v1 default-path regression).

## Findings

### CRITICAL

None.

### MAJOR

1. **Packed C-036 re-derivation silently strips live-authorized
   reviewed/sourced labels**
   (`ontologylab/pack_v2_derive.py:87-121`,
   `ontologylab/pack_v2_manifest.py:45-47`,
   `ontologylab/pack_v2_closure.py:333-345`).
   Live `authorize_publication` binds C-036 to
   `seal_receipt_inventory(live)` + `compute_source_fingerprint(live)`.
   `copy_v2_tables` copies only claimed receipt ids, then copies the
   live C-036 row unchanged. `finalize_v2_manifest` then **replaces**
   `capabilities` with `derive_capabilities(pack)` which reseals the
   packed subset and recomputes the packed document fingerprint.
   Extra live documents are already refused as `FINGERPRINT_MISMATCH`
   at the gate. Extra **valid** receipts on the same documents are
   not: a second `extraction_run_receipts` row with a distinct
   `config_identity` and a real `run_receipt_id()` stays in the live
   seal, is omitted from the pack (runs are copied from shipped
   citations only), and packed rebind fails →
   `UNREVIEWED_CAPABILITIES`.
   Probe (tempdir, then removed): granted
   `['knowledge-graph-v2','evidence-self-contained-v2','reviewed','sourced-answer-v2']`;
   disk `['knowledge-graph-v2','evidence-self-contained-v2']`.
   Fixtures that plant C-036 on a minimal one-run store hide this.
   Repair: rebind the packed C-036 row to the packed seal/fingerprint
   after copy (or write the already-granted live capabilities and
   verify against that rebound row). Do not compare a live root to a
   subset seal.

### MINOR

2. **`find_path` is still a fact-bearing response without citation
   receipts.** Lookup/search/graph/traverse/get_entity are enriched.
   `find_path` only attaches `_provenance()`.

3. **`PackSession.document_raw_text` is not an MCP tool.** The
   15-tool pin is preserved on purpose. Stdio clients cannot ask for
   FULL bytes except by reading inventory files. In-process session
   and pack tree are enough for the stated resolver contract.

4. **EXCERPT still writes `raw_text_path=''` rather than SQL NULL**
   (`pack_v2_closure.py:320-322`). The resolver treats empty /
   `window.txt` as `excerpt_only`. Pack contract §6 wanted NULL.

5. **`derive_capabilities` assigns `conn.row_factory = sqlite3.Row`**
   on the caller connection. Current call sites use throwaway
   connections. A later call on `store.conn` would mutate it.

6. **`_with_fact_receipts(conn: Any, ...)`** and
   `fact_receipts(... LIMIT 1)`: `Any` is a changed-line typing
   slip; multiple citations collapse to `ORDER BY receipt_id`.
   Compact contract allows one id; it is not “citation_id(s)”.

7. **`test_forged_reviewed_labels_are_refused_after_publish` ends
   with `pytest.raises((PackIntegrityError, Exception))`.** Any
   exception satisfies the last load. The earlier `activate_pack`
   assertion is the real kill.

8. **Size.** `pack_v2_derive.py` 213 (healthy). `pack_readiness.py`
   283 and `pack_v2_closure.py` 680 remain over the 250-LOC house
   ceiling (closure already `SIZE_OK`). Split itself is the right
   abstraction; the C-036 bind is the weak one.

## Prior MAJOR status

| # | Original defect | Repair | Status |
|---|---|---|---|
| 1 | Counts from missing/`citations`/`extraction_runs` tables | `_COUNT_SQL` → `document_observations`, `citation_receipts`, `grounded_review_decisions`, `extraction_*_receipts` | **FIXED** |
| 2 | Replace dropped `nodes_verified` / staleness = 0 | derived counts include verified node/edge keys; `get_staleness` matches | **FIXED** |
| 3 | `contained_documents_path` cannot open `evidence/` | `resolve_pack_evidence` + `PackSession.document_raw_text` read the serving copy only; excerpt is typed `excerpt_only`; `_relpath` allows `sha256:` citation segments | **FIXED** (store `document_raw_text` still cannot; accepted alternate) |
| 4 | `--publish` only caught `PackReadinessRefused` | also `PackV2ClosureRefused` / `IncompleteExtractionError` / `PackBuildError`; `--evidence-mode none` is exit 2 JSON, no traceback | **FIXED** |

MCP `_provenance` now carries `pack_schema_version` / `integrity_level`
/ `evidence_mode`. Manifest `exclusions` are collected from the live
snapshot (ungrounded/waived/legacy/identity) and written through
`v2_manifest_fields`. Forged reviewed labels fail `verify_pack` /
`list_packs` / `activate_pack`.

## Bind

| Fact | Observed |
|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged) |
| Tree | worktree dirty; 8 tracked + 2 untracked owned paths |
| Original review | preserved at `task-12-review-code.md` (278 lines) |
| Executor hashes | all 10 claimed SHA-256 values MATCH current bytes |

Uncommitted owned paths: `pack_v2_derive.py` (new),
`pack_v2_manifest.py`, `pack_v2_closure.py`, `pack_verifier.py`,
`pack_readiness.py`, `mcp_server.py`,
`tests/test_pack_v2_review_repair.py` (new),
`tests/test_pack_v2_closure.py`, `tests/test_pack_v2_verifier.py`,
`tests/test_packdiff.py`.

## Method

Read the executor receipt, original `task-12-review-code.md`, the
full `git diff HEAD` on the eight tracked files, and the new derive
+ repair-test modules. Callers checked: `finalize_v2_manifest`,
`verify_pack`, `PackSession` lookup/search/graph/traverse/get_entity/
`document_raw_text`, `pack_readiness.main`, `_copy_c036`.
`compute_source_fingerprint` confirmed DB-only (id, content_hash).

Reproduced (once):

- basedpyright on derive/manifest/closure/verifier/readiness/packdiff:
  0/0/0
- basedpyright `mcp_server.py`: 10 `reportReturnType` errors, all on
  pre-existing FastMCP wrappers (`list_packs`…`find_path`,
  lines 1056–1219). None on `_provenance`, `_with_fact_receipts`,
  `document_raw_text`, or `compact_*`. LSP `mcp_server.py` /
  `pack_v2_derive.py` / repair test / other owned modules: clean
- focused pytest: `tests/test_pack_v2_review_repair.py` + Task 8–11
  surfaces 128 passed; `tests/test_staleness.py` 12 passed
- C-036 extra-run probe (tempdir, removed): label drop as above

Did not re-run the executor’s ten source mutants or the full suite.

## What holds

- No `except BaseException` in the repair. CLI catches the four
  typed build refusals and re-emits JSON. `IncompleteExtractionError.code`
  is the class attribute `"incomplete_extraction"`.
- Evidence resolver refuses `..` / `/` / `\` in the id, requires
  `claimed == evidence/<id>/full.txt`, and `is_relative_to(pack_root)`.
  No working-store fallback. Serving copy is
  `_snapshot.sqlite_path.parent`.
- Verifier `_relpath` no longer treats `:` as escape, so
  `evidence/sha256:…/window.txt` excerpt packs activate. Drive
  letters and `://` still refuse.
- `document_raw_text` is a `PackSession` method, not a 16th FastMCP
  tool. v1 `fact_receipts` hits `OperationalError` and returns `{}`.
- Inventory hash canonicalization, opener, and refuse-before-visible
  staging are unchanged. New tests have no `time.sleep`.
- Count/exclusion/capability maps live in one module. Builder and
  verifier no longer duplicate the wrong table names.

## Mutant coverage (tests exist; not re-mutated)

| Claimed mutant | Kill test | Would still die? |
|---|---|---|
| wrong count table | `test_v2_counts_use_packed_observation_and_review_tables` | yes (`observations` == packed `document_observations`) |
| dropping verified counts | same | yes (`nodes_verified` + staleness) |
| constant-zero exclusions | `test_v2_manifest_emits_required_exclusion_counts` | yes |
| raw live-path fallback | `test_full_v2_document_raw_text_*` | yes (`evidence/` path, not `documents/`) |
| missing citation provenance | `test_mcp_fact_results_*` | yes |
| pack-only provenance | same (`pack_schema_version == 2`) | yes |
| CLI catches only readiness | `test_cli_publish_emits_json_*` | yes |
| manifest capability trust | `test_forged_reviewed_labels_*` | yes |
| capability comparison removed | same | yes |
| C-036 derivation skipped (always reviewed) | same first assertion + unreviewed fixture | yes |

No mutant for “live-authorized C-036 vs packed subset seal” (finding 1).

## Dimension checks

| Dimension | Result |
|---|---|
| Prior four MAJORS | FIXED |
| MCP provenance | FIXED on lookup/search/entity/graph/traverse |
| Exclusions | FIXED as collect-time snapshot counts |
| Authoritative C-036 caps | **NEEDS-FIX** — finding 1 |
| No source reopen | PASS |
| No BaseException swallow | PASS |
| v1 regression | PASS on default `evidence_mode=None` and v1 verify |
| Typing | PASS on new module; `Any` on `_with_fact_receipts` is MINOR; FastMCP wrappers pre-existing |
| Oversized / weak abstraction | derive split is right; C-036 rebind is weak |
| Focused tests | 140 passed (128 + 12 staleness), 1 pre-existing Starlette warning |

## Repair that would flip this to PASS

After `copy_v2_tables`, rewrite the packed `c036_capability_receipts`
row to the packed `compute_source_fingerprint` + packed
`seal_receipt_inventory` root (only when live `authorize_publication`
already granted reviewed/sourced). Then `derive_capabilities` on pack
bytes will agree with the grant. Add a test that plants a valid extra
unshipped run receipt, authorizes C-036, publishes, and asserts disk
capabilities still include `reviewed` and `sourced-answer-v2`. Keep
the forged-label refusal.
