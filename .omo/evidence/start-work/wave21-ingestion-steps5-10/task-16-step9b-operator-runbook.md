# Wave 2.1 Step 9B operator runbook

Date: 2026-08-24
Scope: Step 9A backup-API rehearsal and Step 9B operator evidence only
Hard stop: `STOP_BEFORE_STEP_9C`

## Purpose

This runbook proves that an operator can rehearse cutover on a disposable
backup-API copy, observe every reader at one generation/high-water binding,
exercise the pre/post-write rollback boundary, and produce auditable pack
evidence. It does **not** authorize or describe production cutover.

Step 9C is absent by design. It requires a separately named maintenance
window and an explicit approval receipt not present in this runbook.

## Roles

| Role | Responsibility |
|---|---|
| operator | runs the disposable rehearsal and records receipts |
| observer | independently checks hashes, phases, and protected boundaries |
| approver | accepts or rejects Step 9A/9B evidence; cannot authorize 9C here |

One person may not sign both operator and observer fields for the same
rehearsal.

## Required inputs

- canonical repository root:
  `/Users/hyunjun/Documents/MUNI/ontologylab`
- a backup made through SQLite's backup API
- a new disposable work directory outside Application Support
- expected source fingerprint, generation, high-water, file inventory hash,
  and backup receipt
- an evidence directory unique to the rehearsal
- protected server identity recorded observe-only:
  PID `55560`, `127.0.0.1:8799`, device `0x1ff51c806b197195`

Forbidden inputs:

- `~/Library/Application Support/ontologylab/`
- repository `data/` or `packs/` as authority
- port `8799` or PID `55560` as a rehearsal process
- external network sources
- any production path

## Preflight

Record every value before opening the disposable copy:

```text
physical cwd
Git top-level
origin URL
HEAD commit
source fingerprint
backup receipt and backup SHA-256
generation and high-water
file inventory SHA-256
operator, observer, UTC timestamp, rehearsal ID
```

Abort if the physical cwd, Git top-level, or origin differs from
`PROJECTS.md`; if any input is missing; if the disposable root aliases a
protected path; or if the protected process identity changes.

## Rehearsal sequence

### 1. Prove the backup

1. Create the source backup only through `snapshot_db`.
2. Open the backup read-only and record its source fingerprint.
3. Create the work copy from that backup through the backup API.
4. Hash the complete non-database file inventory.
5. Verify the source backup and protected paths remain byte-identical.

Required receipt: backup path identity, backup SHA-256, source fingerprint,
generation, high-water, and file inventory hash.

### 2. Walk the disposable cutover state

Advance only in this order:

```text
expand
shadow_write
backfill
catch_up
drained
fenced
constraints_rebuilt
full_v2
authority_flipped
```

Each transition must be inside its caller-owned transaction. Any failpoint
must roll back the phase row, receipt, and domain mutation together.

At `catch_up`, run every registered reader twice at the same
generation/high-water:

```text
kg_store
cli_graph
http_query
verified_pack
mcp_session
method_graph
```

Each available reader hashes its returned machine payload. A genuinely
unrepresentable method graph records typed
`unrepresentable_v2_state`. Missing, duplicate, stale, divergent, failed,
or non-allowlisted readers reset or refuse the proof. Drain requires two
complete consecutive bundle receipts.

### 3. Prove the authority flip

Before flip:

- verify the latest bundle row against the state-bound bundle hash
- verify integrity, outbox, pack, fence, and constraint gates
- record the canonical data hash

After flip:

- recompute the canonical data hash; it must be unchanged
- verify no caller-supplied bundle pin was trusted
- keep old writers fenced

### 4. Prove the rollback boundary

Before `post_cutover_write`, authorize backup restore only when:

- writes are refused
- writers are drained
- an exclusive lock is held
- zero drift is current
- the live file inventory independently matches the bound inventory

For each first irreversible mutation class—ingestion, identity,
extraction/review, and publication—prove the domain mutation, rollback
receipt, and `post_cutover_write` marker share one SAVEPOINT.

After the marker:

- backup restore must return `post_cutover_restore`
- old-writer reopen must return `old_writer_forbidden`
- ordinary v2 writes must return `v2_writes_disabled`
- forward rollback must fence writes and disable v2 preferred selection and
  general publication
- compatibility may return faithful read-only data or typed unavailable;
  it must not fabricate representability

### 5. Prove additive recovery

On the disposable work copy:

1. append a compensation decision that supersedes a false merge
2. append a grounded retraction for one verified fact
3. verify Work/Representation/Citation rows, spans, file bytes, and FKs were
   not moved, deleted, or rewritten
4. build and independently verify a new v2 pack
5. verify the retracted fact is absent from the new pack
6. verify the old pack tree is byte-identical to its pre-recovery hash
7. append a recovery-pack receipt containing verifier-derived old/new pack
   hashes

Rollback and compensation receipts must refuse UPDATE and DELETE.

## Exact bounded validation

Run from the canonical repository root:

```bash
UV_NO_SYNC=1 uv run pytest \
  tests/test_cutover_rehearsal.py \
  tests/test_cutover_readers.py \
  tests/test_cutover_rollback.py \
  --override-ini addopts= -q

/Users/hyunjun/.local/bin/basedpyright \
  ontologylab/cutover_rehearsal.py \
  ontologylab/cutover_readers.py \
  ontologylab/cutover_rollback.py \
  ontologylab/cutover_compensation.py \
  ontologylab/cutover_rollback_store.py \
  ontologylab/cutover_rollback_types.py

python3.11 -m py_compile \
  ontologylab/cutover_rehearsal.py \
  ontologylab/cutover_readers.py \
  ontologylab/cutover_rollback.py \
  ontologylab/cutover_compensation.py \
  ontologylab/cutover_rollback_store.py \
  ontologylab/cutover_rollback_types.py
```

The exact full suite is deliberately deferred to Step 9 closure, where it
must run against the committed Step 9 state.

## Mandatory abort table

| Observation | Operator action |
|---|---|
| source, backup, generation, high-water, or inventory mismatch | abort |
| any protected-path alias or port/PID conflict | abort |
| any reader missing, duplicated, stale, divergent, or failed | reset proof; abort drain |
| fewer than two complete zero-drift bundles | abort drain |
| bundle row differs from state-bound hash | abort flip |
| data hash changes across authority flip | abort |
| first mutation lacks atomic marker and rollback receipt | roll back; abort |
| restore accepted after marker | abort |
| old writer or ordinary v2 writer reopens after forward rollback | abort |
| compensation moves Citation/FK/file anchors | roll back; abort |
| old pack bytes change | abort |
| new pack does not independently verify | abort |
| any request to proceed into Step 9C | emit `STOP_BEFORE_STEP_9C`; stop |

## Evidence packet

The operator hands the observer:

- preflight identities and hashes
- ordered phase receipts
- two complete reader-bundle receipts
- pre/post-flip data hashes
- restore permit and post-marker refusal receipts
- forward rollback state and fence receipt
- merge-compensation and grounded-retraction receipts
- old/new standalone pack verification receipts
- anchor and immutable-tree hashes
- bounded validation outputs
- protected-boundary before/after identity
- `task-16-step9b-runbook.json`
- `task-16-step9c-stop.md`

The observer signs only Step 9A/9B completeness. A PASS does not authorize
Step 9C.

## Stop

When the Step 9A/9B evidence packet is complete, record:

```text
STEP_9B_COMPLETE
STOP_BEFORE_STEP_9C
```

Do not translate that stop into a production command, deployment action,
service restart, live-data open, or maintenance-window assumption.
