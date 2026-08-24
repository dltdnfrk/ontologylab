# Task 12 repair-3 code review — document-fingerprint witness (uncommitted)

Reviewer: omo senpi-task `st_01a031ef`
Date: 2026-08-24
Lane: independent round-3 re-review of the uncommitted source-fingerprint
witness repair. Constraint: this report is the only write. Prior
`task-12-review-repair-code.md` and `task-12-review-repair-2-code.md`
(**NEEDS-FIX**) left untouched. Product/test read-only. No commit/push;
no network; no Application Support; no 8799 / PID 55560; no authority /
plan edits. No full suite.

Executor `task-12-review-repair-3-executor.md` treated as a claim.
Review is bound to the current worktree against HEAD
`081d8554f814645517a29a0cef1c0e32af3d84df`.

## Verdict

**PASS**

**Confidence:** 0.92

The unpublished-document RED is closed. Live C-036 over the full
document set stays authorized; the extra document (and an extra valid
run) stay out of pack sqlite / works / observations / receipts /
provenance / evidence / MCP query; `source-fingerprint.json` is
inventoried, `0444`, exact `{entries:[[id,hash],...]}` in sorted unique
string pairs; its hash equals packed C-036 `source_fingerprint` and the
live `compute_source_fingerprint`; every packed document pair is an
exact witness member; receipt-inventory witness still binds the extra
run. verify / list / activate / MCP pass with `reviewed` +
`sourced-answer-v2`. Missing, tampered, reordered, duplicate,
extra-key, wrong-shape, packed-doc-missing, wrong-C-036, and forged
unreviewed labels all refuse `INVALID_MANIFEST`. R1–R6 and the extra-run
witness remain GREEN. No CRITICAL or MAJOR. No new changed-line
diagnostics.

## Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

1. **`pack_v2_derive.py` remains 276 file LOC** (executor claimed 245)
   over the 250-LOC house ceiling. The fingerprint logic correctly
   moved to `pack_source_fingerprint.py` (99 LOC, healthy). Not a
   bind defect.

2. **MCP `_provenance` still omits `capabilities`.** Surfaces that
   read the verified manifest (list/activate/disk) carry the labels.
   Lookup still falls back to disk in one extra-run assertion.

3. **EXCERPT `raw_text_path=''`** is unchanged. Resolver still types
   `excerpt_only`. Pack contract wanted NULL.

## Unpublished-document case (reproduced)

Independent disposable `_plant_v2` → extra `insert_document` → extra
valid `put_extraction_receipts` → `_seal_ready` → sourced + C-036 →
`authorize_publication` granted reviewed/sourced →
`build_pack(..., evidence_mode="full")`:

| Check | Result |
|---|---|
| Disk capabilities | kg-v2, evidence-self-contained-v2, reviewed, sourced-answer-v2 |
| Extra doc in pack sqlite / works / obs / runs / provenance | absent (0) |
| Extra run in pack sqlite | False |
| Extra evidence dir / MCP name / unpublished text | absent |
| `document_raw_text(extra_id).available` | False |
| `source-fingerprint.json` in `artifact_inventory` | True, sha256 bound |
| Receipt witness in inventory | True |
| Both witnesses mode | `0444` |
| Fingerprint JSON keys | exactly `{entries}` |
| Entries all `str,str` length-2, unique, id-sorted | True |
| Extra `(id,hash)` in fingerprint witness | True |
| Packed docs ⊆ witness (exact pairs) | True |
| `fingerprint_from_entries` == packed C-036 == live fingerprint | True |
| Receipt root == packed C-036 == live inventory root | True |
| Packed receipt triples ⊆ receipt witness; extra run present | True |
| `verify_pack` / `list_packs` / `activate_pack` / MCP schema 2 | ok |

## Attacks (reproduced)

| Attack | Result |
|---|---|
| Delete `source-fingerprint.json` + rematerialize | `INVALID_MANIFEST` |
| Drop unpublished pair from witness + rematerialize | `INVALID_MANIFEST` |
| Reverse entry order | `INVALID_MANIFEST` (parser requires increasing ids) |
| Duplicate first pair | `INVALID_MANIFEST` |
| Extra top-level key | `INVALID_MANIFEST` |
| Object-shaped entries | `INVALID_MANIFEST` |
| Drop packed doc from witness | `INVALID_MANIFEST` |
| Rewrite packed C-036 fingerprint to `deadbeef*8` | `INVALID_MANIFEST` |
| Forge reviewed/sourced on unreviewed pack (test) | `INVALID_MANIFEST`; list/activate/load refuse |

## Prior rounds

| Item | Status |
|---|---|
| R1 counts / staleness / raw-text / CLI / MCP receipts / exclusions / forged labels | GREEN (focused 152) |
| R2 extra unshipped **run** + receipt-inventory witness | still GREEN (combined probe) |
| R2 extra unshipped **document** labels | **FIXED** this round |
| Prior NEEDS-FIX receipts | preserved, not rewritten |

## Bind

| Fact | Observed |
|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged) |
| Executor SHA-256 (4 changed + 3 frozen R2) | all MATCH |
| New module | `ontologylab/pack_source_fingerprint.py` |

`derive_capabilities` no longer imports or calls
`compute_source_fingerprint`. Packed compare is
`source_fingerprint_matches(conn, pack_root, claimed)` only.

## Method

Read the Round-3 executor, `pack_source_fingerprint.py`, derive /
closure diffs, and the unpublished-doc / parser / forge tests.
Independently rebuilt the prior RED (unpublished document before
`_seal_ready`) plus an extra valid run. Independently applied the
eight named attacks with rematerialized inventories.

Reproduced once:

- focused pytest (repair + Task 8–11 surfaces + staleness):
  **152 passed**, 1 pre-existing Starlette warning
- basedpyright on fingerprint / derive / closure / manifest / seal /
  readiness / verifier: 0/0/0
- LSP on `pack_source_fingerprint.py`, `pack_v2_derive.py`,
  `pack_v2_closure.py`: clean
- `mcp_server.py` basedpyright: same 10 pre-existing FastMCP
  `reportReturnType` wrappers (1056–1219). No new diagnostic on
  this round's files.

Did not re-run source mutants or the full suite.

## What holds

- Fingerprint formula matches `migration.compute_source_fingerprint`:
  `sha256(json.dumps([[id, IFNULL(hash,'')], ...], separators=(",",":"),
  ensure_ascii=False))`. Capture uses `ORDER BY id`.
- Parser is exact: object keys must be `{entries}`; each row a 2-list
  of non-empty unique strings in strictly increasing id order. Extra
  keys, objects, duplicates, and reorder return `None` → unreviewed
  derive → claimed reviewed fails verify.
- Packed membership is exact `(id, hash)` inclusion, so a packed hash
  edit or an unpublished packed row fails.
- Both witnesses are written in `write_v2_evidence` before
  `finalize_v2_manifest` chmods and inventories, so they enter
  `pack_content_hash`.
- Receipt witness / root / packed ⊆ witness / generation / decision /
  scope checks remain in `_derive_capabilities`.
- No `except BaseException`. v1 `evidence_mode=None` unchanged.
  Unreviewed packs still write a fingerprint witness but do not gain
  reviewed labels.
- `pack_source_fingerprint.py` is a dedicated 99-LOC module with no
  packbuilder/MCP imports. Architecture is the right split.

## Dimension checks

| Dimension | Result |
|---|---|
| Unpublished-doc C-036 labels | PASS |
| Fingerprint witness inventoried / 0444 / strict shape | PASS |
| Packed docs exact witness members; extra rows/bytes/query absent | PASS |
| Receipt witness still mandatory | PASS |
| Tamper / missing / forge attacks | PASS |
| R1–R6 + extra-run | PASS |
| v1 / unreviewed | PASS |
| Types / changed-line LSP | PASS |
| Size / architecture | acceptable (derive still oversized; new module healthy) |
| Blocking code defect | none |
