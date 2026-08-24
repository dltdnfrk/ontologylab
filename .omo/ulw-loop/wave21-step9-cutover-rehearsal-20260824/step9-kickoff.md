# Wave 2.1 Step 9 kickoff — 9A rehearsal and 9B runbook only

Date: 2026-08-24
Authority: integrated report §§6–9 and synthesis blueprint §0.

## Hard stop

Step 9C production execution is OUT OF SCOPE. It requires a separately
named maintenance window and explicit user approval. This loop must stop
after 9A and 9B evidence.

## Goal

On disposable SQLite backup-API copies, execute the production-equivalent
sequence:

`expand -> legacy-compatible shadow write -> backfill -> generation-bound
catch-up -> old-writer drain/join -> fence/exclusive lock -> constraint
rebuild -> full-v2 enable -> data-neutral authority flip`

Then exercise all supported readers and forward-only rollback.

## RED before implementation

- F3: old and shadow writers can produce one-sided commit or unaccounted
  generation drift.
- F7: authority flag can flip with non-zero drift or change canonical data.
- F8: backup restore remains possible after `post_cutover_write`.
- F10 integration: retraction moves old citation or false merge cannot be
  compensated additively.
- H1: historical extraction/chunk/citation/review catch-up can leave an
  unmigrated or guessed anchor.
- Any old writer mutation after fence, missing outbox event, failed pack
  verifier, or missing rollback receipt does not abort.

## GREEN criteria

- Two transactionally measured zero-drift passes bind writer generation and
  transaction high-water mark; no sleeps or timed polling.
- Every supported reader’s canonical dump is generation-bound and identical,
  or returns typed unavailable for unrepresentable v2 state.
- Old writers drain/join; fenced mutation count is zero under exclusive lock.
- Constraint rebuild and full-v2 enable occur only after zero unmigrated rows,
  zero blocking collision, clean hash/FK/Citation checks, and outbox closure.
- Authority flip is data-neutral.
- Before first v2 authority mutation, restore requires marker absence,
  quiescence, exclusive lock, and fresh file-inventory equality.
- First irreversible v2 write sets `post_cutover_write` in the same
  transaction; afterward restore/schema contraction/old-writer re-enable are
  refused and rollback is forward-only.
- Retraction/compensation preserves rows/files/spans/events and creates a new
  pack without changing the old pack hash.

## Mutation decisions

Kill mutants that skip generation accounting, accept one zero-drift pass,
reopen an old writer, flip authority with drift, omit the marker, restore
after marker, omit outbox closure, rewrite FK on compensation, guess H1
anchors, or mutate a published pack.

## Deliverables

1. Disposable cutover rehearsal state machine.
2. All-reader generation-bound zero-drift proof.
3. Forward rollback and additive compensation proof.
4. Step 9B operator runbook with backup receipt, abort gates, and named 9C
   approval placeholder.
5. Independent code, security, manual-QA, context, and final-gate receipts.

No live Application Support data, external network, PID 55560/8799, or
production writer may be used.
