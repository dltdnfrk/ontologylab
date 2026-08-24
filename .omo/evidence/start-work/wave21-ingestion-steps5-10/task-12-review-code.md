# Task 12 code review — Wave 2.1 Step 8

Reviewer: omo senpi-task `st_01a031ef`
Date: 2026-08-24
Lane: independent code / architecture review of committed Step 8
(closure, inventory/verifier, immutable opener, F11/C-036, v1/v2
seam). Constraint: this report is the only write. No product/test
edits; no commit/push; no network; no Application Support; no 8799 /
PID 55560; no Step 9+ / authority / plan edits. No full suite.

Prior Task 8–11 executor/verifier receipts and
`task-12-final-full-suite.md` were treated as claims. This review is
bound to committed bytes at HEAD
`081d8554f814645517a29a0cef1c0e32af3d84df`.

## Verdict

**NEEDS-FIX**

**Confidence:** 0.91

The opener, F11/C-036 refuse-before-visible, v1 default path, and
named Task 8–11 mutants are real. Publication still ships a v2
manifest whose advertised counts are the wrong tables, drops the
staleness keys every reader already consumes, and writes
Representation paths the store reader cannot open. Tests stay green
by asserting key presence, not values, and by never calling
`document_raw_text` on a v2 pack.

No CRITICAL defect (no BaseException swallow, no live-store resolve,
no opener bypass, no source-byte mutation, no untyped success on the
named F11/C-036 cases).

## Findings

### CRITICAL

None.

### MAJOR

1. **Published v2 counts are re-derived from tables that do not
   exist, then overwrite the correct closure counts**
   (`ontologylab/pack_v2_manifest.py:22-34,53` and the identical map
   at `ontologylab/pack_verifier.py:27-39`).
   `collect_v2_closure` computes semantic counts from claimed
   Observation / Citation-receipt / grounded-review / run-receipt
   members (`pack_v2_closure.py:204-224`). `build_pack` copies those
   onto the in-memory `PackManifest` (`packbuilder.py:759`) and then
   `finalize_v2_manifest` **replaces** `payload["counts"]` with
   `SELECT COUNT(*)` over `observations`, `citations`,
   `review_decisions`, `extraction_runs`, `extraction_chunks`.
   There is no `observations` table in this repo (only
   `document_observations`). Pack install never creates
   `review_decisions` (only `grounded_review_decisions`). `citations`
   / `extraction_runs` / `extraction_chunks` are the v1 graph/stream
   tables, not the receipt families the closure claims.
   Disk `manifest.json` therefore reports `observations=0` and
   `review_decisions=0` on every successful v2 pack that ships those
   members, and `citations` / `extraction_*` can disagree with
   `closure.*`. Builder and verifier agree with each other, so
   `FORGED_COUNTS` never fires. Authority `06-pack-contract.md` §7
   requires those keys to be re-derived from the verified v2
   payload. `test_full_pack_resolves_every_closure_member_from_pack_bytes`
   asserts `>= 1` for the keys that happen to hit v1 tables and only
   `"observations" in counts` / `"review_decisions" in counts`
   (`tests/test_pack_v2_closure.py:441-453`).

2. **Count replace drops `nodes_verified` / `edges_verified`, so
   every v2 pack looks empty to staleness**
   (`ontologylab/pack_v2_manifest.py:53`,
   `ontologylab/mcp_server.py:299-303`).
   `get_staleness` still does
   `counts.nodes_verified + counts.edges_verified`. v1 packs keep
   those keys. v2 finalize writes only the ten remapped keys. A
   verified v2 pack therefore yields `pack_verified_count=0` and a
   pending count equal to the entire live store. Discovery/MCP list
   serve the same disk manifest. Task 10 C-045 tests only forge v1
   packs.

3. **v2 remaps `raw_text_path` to inventory paths the store reader
   rejects**
   (`ontologylab/pack_v2_closure.py:290-305`,
   `ontologylab/file_lifecycle.py:106-121`,
   `ontologylab/kgstore.py:2209-2217`).
   FULL writes `evidence/<id>/full.txt`; EXCERPT writes `''`.
   `document_raw_text` sees `work_id` (always set by the same UPDATE)
   and calls `read_ready_text` → `contained_documents_path`, which
   refuses anything outside `documents/` and refuses empty paths.
   Independent `resolve_v2_closure` still reads the evidence tree,
   so Task 8's "resolve after deleting the live DB" holds. Any store
   path that loads Representation bytes does not: `KGStore.provenance`
   excerpts (`kgstore.py:4907`) raise; review/extract/critic helpers
   that call `document_raw_text` cannot open a published v2 snapshot.
   Pack contract §6 wants a pack-relative inventory path **or NULL**,
   not an empty string, and a consumer must be able to open that
   path from the verified snapshot. No test calls `document_raw_text`
   on a v2 pack.

4. **Publication CLI is not a closed typed surface**
   (`ontologylab/pack_readiness.py:168-176`).
   `--publish` only catches `PackReadinessRefused`.
   `PackV2ClosureRefused` (`none`, dangling, hash mismatch, v1
   rewrite), `PackBuildError`, and `IncompleteExtractionError` dump
   a traceback instead of the machine JSON Task 11 required.
   Default `--evidence-mode full` hides this on the happy path;
   `--evidence-mode none` is a supported flag.

### MINOR

5. **`rewrite_existing_pack` only refuses v1.**
   `refuse_v1_rewrite` treats missing/`pack_schema_version!=2` as
   `V1_REWRITE` and returns on v2 (`pack_v2_closure.py:127-131`).
   Authority: published v2 is immutable. Production `build_pack`
   allocates a new id, so this is an unlocked helper, not a current
   write path.

6. **`resolve_v2_closure` hardcodes unreviewed capabilities**
   (`pack_v2_closure.py:384`). A C-036 sourced pack resolves as
   `knowledge-graph-v2` + `evidence-self-contained-v2` only.
   Member equality still holds; capability/readiness must be read
   from the manifest.

7. **Standalone verifier does not re-derive closure or citation
   windows.** Inventory/hash/mode/link/inode/count checks are
   strict. Pack contract §8 steps 4–6 (closure, window/selected-text
   hash, full Representation rehash) live only in
   `resolve_v2_closure` / `_seal_citations` at build time, not in
   `verify_pack`. A post-publish SQLite row edit that keeps
   `COUNT(*)` and file bytes would still verify.

8. **C-036 is keyed off the older `review_publication` table, not
   `grounded_review_decisions`.** Unreviewed v2 packs still ship
   every pack-eligible grounded review (`_REVIEW_GAP`). Labeling
   fail-closes (no `reviewed` / `sourced-answer-v2` without C-036).
   Two review schemas remain in the commit (clean-checkout
   `review_decision*` plus Step 7 grounded review).

9. **`review_decision._with_savepoint` only rolls back
   `ReviewRefused` / `sqlite3.Error`.** `KeyError` from
   `classify_member` leaves the savepoint open. These modules are
   the Step 7 checkout deps; C-036 tests plant SQL directly.

10. **`_method_reader` re-activates the published directory** on
    every method tool (`mcp_server.py:367-385`) while graph tools
    serve the frozen snapshot. Fail-closed for deleted-source tests;
    inconsistent with C-044 "loaded snapshot is the authority" and
    leaks a temp tree if `close()` fails after a successful pin.

11. **Module size.** `pack_v2_closure.py` 647 and `pack_verifier.py`
    487 carry `# noqa: SIZE_OK` as tasked. `pack_receipt_seal.py`
    281 and `pack_readiness.py` 269 sit over the 250-LOC house
    ceiling without a waiver. Duplicated `_COUNTS` /
    `_canonical` / `_digest` between manifest and verifier is how
    finding 1 survived.

12. **`seal_receipt_inventory._json_strings`** returns `()` on a
    non-list payload instead of refusing. A malformed waiver JSON
    becomes an empty tuple and can flip the review id to STALE
    (fail-closed) or, if the stored id already matches the empty
    projection, accept it.

## Bind

| Fact | Required | Observed |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match |
| Tree | `8677230e75080e5fae606b8dfac568619bfd569c` | match |
| Subject | `test(pack): include evidence mode in signature contract` | match |
| Product commit | `d740a646574b843e3bb8958823c20fa0e883499f` | parent of HEAD |
| Product tree | `3ff4a69d910df6deea70e9bb26f6fa5924e6482d` | match |
| Perimeter | `5bfc7bbd2dcd61ceddc43c31ba5afc2c8590fa36007d6af6748fa8b15f8850e6` | `git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml \| LC_ALL=C sort \| shasum -a 256` |
| Diff | 24 paths, +5797 / −318 | match |

Content SHA-256 of each committed path at HEAD matches
`task-12-product-commit-verifier.md` / the signature-repair blob
`60bdd4c07ad1b386a9eeb9f61714e9c604e7b52246b99916e4275016db849048`.

## Method

Read AGENTS.md / CLAUDE.md, plan Task 8–12, authority Step 8 /
`06-pack-contract.md` §§6–8, Task 8–11 receipts (as claims), and
every line of the 24-path increment plus callers
(`packbuilder.build_pack` / `scan_packs`, `mcp_server.PackSession`,
`packdiff.diff_packs`, `main.cmd_build_pack`,
`server.routes.packs_build`, `kgstore.document_raw_text`,
`file_lifecycle.contained_documents_path`). Did not open live
Application Support, denylist servers, or Step 9+ writers.

Static checks: `except BaseException` / bare `except` / `except
Exception`, `INSERT OR IGNORE`/`OR REPLACE`, `time.sleep`, `Any` /
`cast` / `type: ignore`, count-table names vs `CREATE TABLE`,
opener call sites, chmod/inode/hash canonicalization. Targeted
`basedpyright` on the 13 new/owned product modules: 0 errors, 0
warnings, 0 notes. Did not re-run pytest; suite claim is bound to
`task-12-final-full-suite.md` (2740 passed / 1 skipped / 2 xfailed
on this perimeter).

## What holds

- v1 is unchanged when `evidence_mode` is omitted. Completeness
  override still cannot enter the v2 seam; incomplete v2 is
  `INCOMPLETE_STREAM` before staging. `TemporaryDirectory` staging
  plus `try/finally` on the snapshot (no new `except BaseException`)
  leaves no visible pack on refusal. Pre-existing packbuilder
  `except BaseException` blocks (blame `1dd0cdaf`) re-raise after
  cleanup; they are not swallows and were not introduced here.
- `collect_v2_closure` binds one ledger generation via
  `authorize_publication`, reseals receipt ids, refuses
  none/dangling/cross-generation/missing/incomplete, copies only
  claimed ids, and re-hashes evidence after copy. Optional
  redirect/decision families may be empty. Unrelated works and
  `pack_ineligible=1` reviews stay out.
- `seal_receipt_inventory` re-derives ids with the public Step 7
  constructors and binds C-036 to `[family, id, body_digest]`.
  Same-id body mutants die as `STALE_RECEIPT` / `C036_STALE`.
- Verifier inventory is sorted, excludes `manifest.json`, uses
  `hmac.compare_digest`, rejects symlink/hardlink/0644/path
  traversal/self-reference/original inode, and is deterministic on
  the CLI (`sort_keys` + `separators`). v1 remains
  `legacy-graph-only` without tree_hash and with extra/writable
  files.
- Every pack reader in this increment goes through
  `activate_pack` / `inspect_verified_manifest` /
  `opened_verified_pack`: verify → `copyfile` (new inode) →
  reverify with `working=source` → `mode=ro&immutable=1`. Failed
  `load_pack` closes the new snapshot before switch. MCP `main()`
  closes the session on stdio EOF. New tests have no `time.sleep`.
- Typing on the new modules is strict: no `Any`, no `cast`, no
  `type: ignore`. Enums use `match` + `assert_never`.
- Signature repair (`081d855`) only appends the keyword-only
  `evidence_mode` sentinel; the equality assertion remains.

## Dimension checks

| Dimension | Result |
|---|---|
| Correctness | **NEEDS-FIX** — findings 1–3 ship wrong counts and unreadable Representation paths |
| Typing | PASS — basedpyright 0/0/0 on owned product modules |
| Ownership | PASS on the Step 8 split (closure / seal / readiness / verifier / opener). MINOR dual review schema and duplicated count maps |
| Cleanup | PASS — staging `TemporaryDirectory`, activate `finally` rmtree, session.close on stdio; tests assert no `.*-staging-*` |
| Exceptions | **NEEDS-FIX** on the publish CLI (finding 4). New library paths raise typed refused errors and do not swallow `BaseException` |
| v1/v2 separation | Mixed — default build stays v1; count keys and `raw_text_path` mix v1 tables/lifecycle with v2 names |
| Deterministic inventory/hash | PASS for artifact inventory / `pack_content_hash` / CLI receipt. FAIL for advertised `counts` (finding 1) |
| BaseException swallow | PASS in this increment |
| Immutable-source discipline | PASS for DB/files during verify-copy-serve. FAIL for store-level evidence open (finding 3) |
| Mutant coverage | Named Task 8–11 mutants have kill tests. No mutant for wrong count-table names or `documents/`-escaping `raw_text_path` |

## Mutant coverage (claimed vs this review)

Killed in-tree (tests exist; not re-executed here): omitted closure
member, live-store resolve, sourced `none`, missing receipt, v1
replacement, SQLite-only inventory, skipped mode/extra, trusted
manifest counts, root-only hash, original inode, direct KGStore
open, resource bypass, mutable open, early switch, raw manifest,
independent diff, missing readiness check, missing-as-ready,
phase-only ready, stale receipts, warning-only C-036, early
publication, same-id C-036 body tamper.

Not covered, and green today: map `observations` →
`document_observations` (or leave the map as-is) — suite still
passes; write `raw_text_path` under `documents/` — suite still
passes; merge instead of replace `counts` — suite still passes.

## Repair that would flip this to PASS

Point `_COUNT_TABLES` / `_COUNTS` at `document_observations`,
`citation_receipts`, `grounded_review_decisions`,
`extraction_run_receipts`, `extraction_chunk_receipts`. Merge those
derived values into the existing PackManifest counts instead of
replacing them, so `nodes_verified` survives. Persist FULL
`raw_text_path` as a path `contained_documents_path` will open (or
teach the pack snapshot reader to accept `evidence/`); persist
EXCERPT as SQL `NULL`. Catch `PackV2ClosureRefused` (and the other
build errors) on `--publish` and emit the same typed JSON. Add
assertions that disk `counts.observations` / `counts.review_decisions`
equal `len(closure.*)` and that `document_raw_text` on the activated
snapshot returns the shipped FULL bytes.
