# Task 12 repair-2 code review — C-036 witness (uncommitted)

Reviewer: omo senpi-task `st_01a031ef`
Date: 2026-08-24
Lane: independent round-2 re-review of the uncommitted C-036
inventory-witness repair. Constraint: this report is the only write.
Prior `task-12-review-repair-code.md` (**NEEDS-FIX**) left untouched.
Product/test read-only. No commit/push; no network; no Application
Support; no 8799 / PID 55560; no authority / plan edits. No full suite.

Executor `task-12-review-repair-2-executor.md` treated as a claim.
Review is bound to the current worktree against HEAD
`081d8554f814645517a29a0cef1c0e32af3d84df`.

## Verdict

**NEEDS-FIX**

**Confidence:** 0.89

The tasked extra-valid-unshipped-**run** case is actually closed.
Live C-036 stays authorized; the extra run is absent from pack
sqlite; `receipt-inventory.json` carries its canonical
`[family, id, body_digest]` triple; that file is inventoried and
hash-bound; recomputed witness root equals packed C-036 root; every
packed receipt triple is a witness member; verify / list / activate /
MCP lookup succeed with `reviewed` + `sourced-answer-v2`. Missing
witness, wrong C-036 root, tampered witness, packed-not-in-witness,
and unreviewed capability forge all refuse.

The same bind class is not closed for **documents**.
`derive_capabilities` still requires packed
`compute_source_fingerprint(pack)` == live-authorized C-036
fingerprint. Unpublished documents that were in the generation
snapshot (ledger + C-036) are not shipped, so the packed fingerprint
differs and finalize silently writes unreviewed capabilities.
Reproduced: granted reviewed/sourced; disk
`['knowledge-graph-v2','evidence-self-contained-v2']`. That is the
normal store (a second ingested paper with no verified facts). R1–R6
and the extra-run witness otherwise hold. No CRITICAL.

## Findings

### CRITICAL

None.

### MAJOR

1. **Packed fingerprint still compared to the live C-036
   source-fingerprint bind**
   (`ontologylab/pack_v2_derive.py:160-178`).
   After the witness fix, inventory-root compare uses the inventoried
   live entries (correct). Fingerprint compare still does
   `str(row[1]) != compute_source_fingerprint(conn)` on the **pack**
   connection. `compute_source_fingerprint` hashes every
   `documents(id, content_hash)`. The pack only copies shipped
   verified sources. A document that existed when the ledger/C-036
   was sealed, but has no verified facts, is in the authorized
   fingerprint and not in the pack.
   Probe (tempdir, removed): `_plant_v2` → extra `insert_document`
   → `_seal_ready` → sourced + C-036 → `authorize_publication`
   granted reviewed/sourced → disk capabilities unreviewed.
   Extra documents added *after* the ledger still fail closed at
   F11 (`FINGERPRINT_MISMATCH`). The hole is documents present at
   bind time and omitted by publication, which is the usual working
   store.
   Repair: do not re-hash packed documents against the live C-036
   fingerprint. Authorize on live fingerprint as today; at verify,
   check generation + witness root + packed entries ⊆ witness +
   decision/scope. Or write the live fingerprint into the packed
   C-036 row as an opaque bind and stop recomputing it from the
   subset. Add a test that plants an unpublished document before
   `_seal_ready`, authorizes C-036, and asserts disk still has
   `reviewed` / `sourced-answer-v2`.

### MINOR

2. **`pack_v2_derive.py` is 276 file LOC** (executor claimed 245)
   with no `SIZE_OK`. House ceiling is 250. The witness helpers
   belong here; split load/hash from evidence/facts if it grows.

3. **MCP `_provenance` still has no `capabilities`.**
   `test_extra_live_run_*` asserts
   `_REVIEWED in (lookup["pack"].get("capabilities") or payload["capabilities"])`,
   so it passes via the disk fallback even when the session pack
   envelope omits the label.

4. **EXCERPT `raw_text_path=''` and `find_path` without citation
   receipts** are unchanged residuals from R1. Not regressions.

## Extra-run case (reproduced)

Disposable `_ready_fixture` + valid extra `put_extraction_receipts`
(distinct `config_identity`) + sourced + C-036 + `build_pack(...,
evidence_mode="full")`:

| Check | Result |
|---|---|
| Live `authorize_publication` reviewed | True |
| Disk capabilities | kg-v2, evidence-self-contained-v2, reviewed, sourced-answer-v2 |
| Extra run in pack sqlite | False (1 packed run) |
| Extra run in witness `entries` | True |
| `receipt-inventory.json` in `artifact_inventory` | True |
| Inventory sha256 == file bytes | True |
| Witness mode | `0444` |
| Recomputed `source_inventory_root` == packed C-036 root | True |
| Packed (family, id) ⊆ witness | True |
| `verify_pack` | ok |
| `list_packs` carries reviewed | True |
| `activate_pack` manifest reviewed | True |
| MCP `entity_lookup` matches / `pack_schema_version==2` | True |

## Attacks (reproduced)

| Attack | Result |
|---|---|
| Delete witness + rematerialize inventory/hashes | `PackVerifyRefused.INVALID_MANIFEST` |
| Rewrite packed C-036 root to `deadbeef` + rematerialize | `INVALID_MANIFEST` |
| Drop extra-run triple from witness + rematerialize (test) | `INVALID_MANIFEST` |
| Drop packed-run triple, rewrite C-036 root to new witness, rematerialize (test) | `INVALID_MANIFEST` |
| Forge reviewed/sourced on unreviewed pack (test) | `INVALID_MANIFEST`; list omits; activate/load refuse |

## Prior R1–R6

| Item | Status |
|---|---|
| Count tables + `nodes_verified` / staleness | still GREEN (focused suite) |
| Snapshot `document_raw_text` / excerpt limitation | still GREEN |
| Typed CLI closure refusal | still GREEN |
| MCP work/representation/citation receipts | still GREEN |
| Manifest exclusions | still GREEN |
| Forged reviewed labels | still GREEN |
| Extra unshipped **run** labels | **FIXED** this round |
| Extra unshipped **document** labels | **still open** (finding 1) |

## Bind

| Fact | Observed |
|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged) |
| Prior repair-1 review | preserved, still **NEEDS-FIX** |
| Executor SHA-256 (6 claimed paths) | all MATCH current bytes |

New/changed vs repair-1: `pack_receipt_seal.py` exposes `entries`;
`write_source_receipt_inventory` / `load_source_receipt_inventory` /
`source_inventory_root`; `derive_capabilities(..., pack_root=)`;
`write_v2_evidence` emits the witness before finalize inventories it.

## Method

Read repair-2 executor, current diffs on seal / derive / closure /
manifest / verifier / readiness, and the new extra-run / tamper
tests. Independently rebuilt the extra-run store with
`put_extraction_receipts` (not a fake id). Independently planted an
unpublished document before `_seal_ready`. Independently deleted the
witness and rewrote C-036 root.

Reproduced once:

- focused pytest (repair + Task 8–11 surfaces + staleness):
  **143 passed**, 1 pre-existing Starlette warning
- basedpyright on derive/manifest/seal/readiness/closure/verifier:
  0/0/0
- LSP on `pack_v2_derive.py`, `pack_receipt_seal.py`,
  `pack_v2_closure.py`: clean
- `mcp_server.py` basedpyright: same 10 pre-existing FastMCP
  `reportReturnType` wrapper errors (1056–1219). No new diagnostic
  on `_provenance`, `_with_fact_receipts`, or `document_raw_text`.

Did not re-run source mutants or the full suite.

## What holds

- Witness bytes are pack payload: written in `write_v2_evidence`
  before `finalize_v2_manifest` walks the tree, so they enter
  `artifact_inventory` and `pack_content_hash`. Mode `0444` after
  `_chmod_payloads`.
- Root formula matches the seal: `sha256(json.dumps(list-of-triples,
  separators=(",", ":")))`. Live `sealed.entries` captured at
  collect become the file; packed C-036 root is that hash, not the
  packed subset seal.
- Packed membership is exact triple inclusion (`family, id,
  body_digest`), so a same-id body edit fails subset or
  `STALE_RECEIPT`.
- Extra live receipts are audit-only: not copied as sqlite rows
  (`_insert_claimed` still uses claimed ids).
- `derive_capabilities` now saves/restores `conn.row_factory`.
- No `except BaseException`. v1 default `evidence_mode=None` and
  v1 verify path unchanged. `SealedInventory` is only constructed
  in `seal_receipt_inventory`.
- Named repair-2 mutants have tests (extra-run labels, copy-all
  rows, witness not inventoried, root unchecked, subset unchecked,
  capability trust). Extra-unpublished-document has no test.

## Dimension checks

| Dimension | Result |
|---|---|
| Extra-run C-036 labels | PASS |
| Witness inventoried / hash-bound | PASS |
| Packed receipts ⊆ witness | PASS |
| Unrelated rows not queryable | PASS |
| Tamper / missing / forge attacks | PASS |
| Authoritative C-036 vs unpublished docs | **NEEDS-FIX** |
| R1–R6 regressions | none observed |
| v1 | PASS |
| Types / changed-line LSP | PASS (FastMCP wrappers pre-existing) |
| Abstraction | witness split is right; leftover packed-fingerprint compare is the weak bind |
| Size | derive 276, closure 686, seal 283 — derive now over 250 |

## Repair that would flip this to PASS

Stop comparing C-036 `source_fingerprint` to
`compute_source_fingerprint(pack)`. Keep generation, witness root,
packed ⊆ witness, and authorize/scope. Add one test that inserts an
unpublished document before `_seal_ready`, authorizes C-036, and
expects reviewed/sourced on disk. Keep the extra-run and tamper
tests.
