# Step 8 kickoff prompt

Use this prompt verbatim to start Wave 2.1 Step 8.

```text
Continue OntologyLab Wave 2.1 from Step 7's completed
Representation-grounded extraction, Citation, ReviewDecision and H1 receipt
boundary. Read these first and treat them as execution authority; section 0 of
the blueprint wins on conflict:

- docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md
- .omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md
- .omo/plans/wave21-ingestion-steps5-10.md Tasks 8-12
- .omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/step7-evidence-index.md

Product baseline:
commit 362b0a679483139e51d8e37748674a867d6a9b2f
tree dce1386961684e924108ded625e56dab4031384d
21-path repair perimeter
1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b
full-suite perimeter
9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867
suite 2650 passed / 1 skipped / 2 xfailed, exit 0.

An evidence-only Step 7 closure commit may be HEAD after this product baseline;
it must leave ontologylab/, tests/, scripts/ and pyproject.toml byte-identical
to the baseline above.

Implement Step 8 only: evidence-self-contained pack v2, strict dynamic
inventory and standalone verification, a common immutable verified reader
snapshot, F11 readiness refusal, and C-036 reviewed/sourced capability gating.
Do not implement Step 9A/9B/9C, authority flip, production migration or any
cutover. Do not enable FULL_V2_AUTHORITY. Do not touch live Application Support
data, port 8799/PID 55560, external network or canonical planning docs.

Required scope:

1. Build one-snapshot pack v2 closure. In a dedicated v2 closure module plus
   the packbuilder seam, manifest v2 must close Work, identifier, redirect,
   decision, Observation, Representation, source bytes or sealed excerpt,
   extraction run/chunk, Citation, ReviewDecision, policy and provenance
   inside one generation-bound snapshot. Evidence mode is exactly full or
   excerpt. Sourced none, dangling, cross-generation, missing receipt,
   incomplete stream or a v1 rewrite must fail before visible staging.

2. Implement a strict dynamic inventory and standalone verifier. Inventory
   every relative artifact with size, content hash, type, mode and ownership;
   bind the manifest without self-reference ambiguity; rederive claims, counts
   and closure from packed bytes. Refuse missing, extra or tampered files,
   symlink/hardlink, writable 0644, path mismatch, original working inode and
   forged hashes/counts. Keep legacy v1 verification compatibility; never
   rewrite a v1 pack.

3. Route load_pack, _store_for, all MCP resources/tools, discovery, schema,
   staleness and diff through one verified opener. Verify then copy into a
   process-owned immutable serving snapshot and open SQLite with
   mode=ro&immutable=1. Include pack id/hash provenance. A failed replacement
   preserves the prior loaded session byte-identically. No raw path, direct
   KGStore, raw manifest or independent diff bypass.

4. Enforce F11 from Step 5 ledger/generation/fingerprint plus the Step 7
   receipt inventory. Refuse non-ready, incomplete/ambiguous,
   check-vs-snapshot generation drift, stale/missing receipts and every
   reviewed/sourced label or publication without a valid C-036 capability
   receipt. Step 5 truth is read-only. Absence is typed refusal, not a warning.
   Failed publication exposes no staging and never replaces a prior pack.
   A ready complete unreviewed fixture may publish.

5. Close Step 8 by running the full mutation/closure matrix, standalone
   verifier and real stdio MCP on the same snapshot, affected suite, atomic
   product/test commits, one exact full suite on final committed code/test
   perimeter, independent goal/code/manual-QA/security/context/gate reviews,
   cleanup, Step 8 evidence index, verbatim Step 9 kickoff, aggregate
   completion and an evidence-only closure commit.

Named implementation mutants that must die and restore byte-identically:

- omitted closure member
- live-store lookup from a packed claim
- sourced evidence mode none
- missing run/chunk/Citation/ReviewDecision/policy receipt
- v1 replacement/rewrite
- SQLite-only inventory
- skipped mode or extra-file checks
- trusted manifest counts
- root-only content hash
- original-inode use
- direct KGStore or raw-path open
- MCP resource/tool verification bypass
- mutable SQLite open
- session switch before successful verification
- raw-manifest staleness/discovery
- independent unverified diff
- missing readiness check
- missing-as-ready or phase-only readiness
- stale receipt acceptance
- C-036 warning-only behavior
- early visible publication

Evidence discipline:

- Before every production edit, capture one RED that fails for the named
  decision. After the minimal change, capture GREEN.
- Kill each real implementation mutant in isolation, restore exact source
  bytes and record before/after hashes. No source-text-only mutation claims.
- Tests assert machine-consumed manifest fields, binary receipts, hashes,
  inventories, capability ids and typed refusal codes, never prose wording.
- Use disposable fixtures only. No fixed sleeps, timing luck, retry-to-pass or
  unbounded polling. Subscribe before triggering async work.
- Drive direct builder, installed CLI standalone verifier, real stdio MCP
  initialize/list/load/query, failed replacement and prior-session query.
- Delete or mutate the source store after a valid full/excerpt build and prove
  every receipt resolves from packed bytes alone.
- Tamper bytes, add/delete a file, change mode, plant a link, forge manifest,
  race generation, omit a receipt and omit C-036; every case must refuse with
  no visible output and no prior-session drift.
- Run basedpyright on every changed Python file and the focused/affected
  pytest sets once. Run the exact full suite only at the final committed-state
  gate with unchanged before/after perimeter.
- Preserve unrelated dirty work. Stage only exact owned paths. Never amend,
  rebase, reset, push, use destructive checkout/restore, or edit the authority
  docs.

Completion:

- Tasks 8-12 receipts show RED/GREEN, isolated mutation kills, direct/CLI/
  verifier/stdio-MCP QA, deterministic inventories/roots, F11/C-036 refusals,
  typing and focused/affected suites.
- Product/test commits are conventional and independently verified.
- One exact final suite passes on committed bytes with unchanged perimeter.
- Independent goal/code/manual-QA/security/context/gate reviews all approve.
- Step 8 evidence index, aggregate state and verbatim Step 9 kickoff exist and
  are evidence-only committed without product/test drift.
- Explicitly report that Step 9C remains unauthorized. Do not execute or
  imply production cutover.
```
