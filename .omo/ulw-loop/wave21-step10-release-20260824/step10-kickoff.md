# Wave 2.1 Step 10 kickoff — release evidence before production cutover

Date: 2026-08-24
Authority:

1. `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md`
2. `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md` §0
3. `step9-evidence-index.md`

The synthesis blueprint §0 and the integrated analysis win on conflict.

## Entry gate

Do not start Step 10 until the Step 9 evidence-only closure commit has an
independent PASS verifier. Rebind the actual closure commit, tree, and
product/test perimeter at start.

Current product baseline before closure evidence:

```text
HEAD  42d3dcb3940d4d40697dac07bf28f4dbfcd28b81
tree  0a20eb1d587b5c7f6767d86eba1d55990ac65f50
full suite  2873 passed, 1 skipped, 2 xfailed
```

Performance baseline:

```text
fixture  wave21-perf-v1
manifest sha256  019a986f878bcba5b2ba8c67a1451d8fc19af021988e28bdd9f7e2287f82f0b1
```

Do not regenerate, relabel, or silently replace that frozen baseline.

## Scope

Step 10 has exactly three tasks:

1. `Execute consolidated release mutation matrix`
2. `Compare release performance determinism and claims`
3. `Close Step 10 before production cutover`

Step 10 is release evidence, not Step 9C. It cannot authorize production.

## Task 17 — consolidated release mutation matrix

### RED

- no single release receipt maps every Step 5–9 decision to its mutant,
  killer, restoration hash, and current committed test
- any historical required mutant is missing or survives
- a mutation result is inferred from a prior green suite rather than killed
  on current committed bytes
- mutation cleanup fails to restore exact source hashes

### Required work

- inventory the Step 5–9 mutation receipts from their evidence indexes
- group decisions by migration, authority identity, grounding/review,
  pack/verifier/MCP, cutover readers, rollback, and stop contract
- rerun one bounded current-byte killer for each materially distinct
  decision; reuse immutable receipts only where the exact committed bytes and
  checker identity are already proven
- restore every mutant before the next group and independently hash restored
  files
- produce a machine-readable matrix plus a human evidence report

### GREEN

- zero required survivors
- every mutation has one exact killer and restored hash
- affected suites and typing are green on restored bytes
- no mutation touches protected or user-owned state

## Task 18 — performance, determinism, and claim comparison

### RED

- current release has no measured comparison against frozen
  `wave21-perf-v1`
- repeated runs produce different semantic outputs, receipts, pack identity,
  or claim classifications
- a performance or capability claim exceeds measured evidence
- warm/cold, fixture identity, host, command, and sample count are omitted

### Required work

- run the existing measured baseline protocol on the same host and frozen
  fixture
- preserve the established thresholds; do not invent more favorable release
  thresholds
- compare migration throughput, peak resource use, deterministic receipts,
  pack hashes, reader agreement, and relevant query surfaces
- run enough identical samples to expose nondeterminism without timing sleeps
  or retry-to-pass
- classify every release claim as measured, bounded, unavailable, or
  forbidden; no aspirational claim may be presented as shipped behavior

### GREEN

- determinism holds for all machine-consumed outputs
- performance deltas are within the previously approved bounds or are
  explicitly blocking
- claim language exactly matches observed capability
- raw measurements, commands, hashes, and comparison tables are preserved

## Task 19 — Step 10 closure

### RED

- mutation or performance/claim task lacks independent review
- exact committed-state full suite is absent or red
- evidence index, final gate, commit verifier, or mandatory stop is absent

### Required work

- independent code/architecture/security review
- independent hands-on QA of each relevant public surface
- dependent release gate
- conventional commits at each clean gate
- exact committed-state full suite
- Step 10 evidence index and final completion audit
- preserve the production stop in every report and machine manifest

### GREEN

- all Step 10 tasks PASS
- exact committed-state suite and hashes are green
- evidence commit is independently verified
- all claims are bounded by measured evidence
- no open release blocker remains before the mandatory production stop

## Protected boundary

- disposable fixtures and backup-API copies only
- no Application Support contents
- no port `8799` or PID `55560` mutation
- no external network
- no planning-document edits
- no production command, deployment, activation, service restart, or writer
  reopen

## Mandatory stop

Step 10 completion ends here:

```text
STOP_BEFORE_STEP_9C
```

Production cutover requires a newer direct user request, a separately named
maintenance window, explicit approval, approval receipt identity, and fresh
operator/observer preflight. Step 10 success cannot supply those conditions.
