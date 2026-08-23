# Task 1 code review — Step 6 `eab47a6..e3bca45`

Reviewer: omo senpi-task `st_01a02e69`
Date: 2026-08-23
Lane: independent code review (correctness, minimality, transaction / file-lifecycle / outbox / shadow boundaries, compatibility, test nondeterminism, maintainability).
Constraint: no product/test/plan/canonical edits; no commit/push; no network; no live Application Support; no 8799 / PID 55560 mutation.

Prior G007/G006/G008/G009/start-work receipts were treated as claims. This review is bound to current committed bytes.

## Bind

| Fact | Required | Observed |
|---|---|---|
| HEAD | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` | match |
| Tree | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` | match |
| Subject | `feat(ingestion): complete transactional v2 shadow service` | match |
| Perimeter SHA-256 | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` | match (23 committed paths, working tree = `HEAD:` blobs) |
| Full suite | 2521 passed / 1 skipped / 2 xfailed | bound to `task-1-full-suite.md` after identity proof; not re-run |

Parent: `eab47a615cc5f309c05a48875c6e6877096783dd`. Diff: 23 files, +5556 / −102.

## Verdict

**PASS**

**Confidence:** 0.91

**BLOCKERS:** none

No CRITICAL or MAJOR defect reproduced on committed bytes. Focused Step 6 suites and basedpyright were re-run once and exited 0. Remaining issues are honesty / residual-compatibility MINORs that do not tear domain+outbox, do not expose staged or escaped bytes, and do not weaken v2 hash enforcement.

## Method

Read: canonical Step 6 (`docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md` §6 / invariants 5–12; blueprint Step 6; loop `brief.md` Goals 1–5), Task 1 plan text, start-work receipts, G006/G008/G009 RED-GREEN/mutation claims, and the full `eab47a6..e3bca45` product+test bytes.

G007 reviewed an uncommitted freeze whose `kgstore.py` still treated synthetic `sha256:`+64 hex as an oracle (`ae0422d7…`). Committed `kgstore.py` is the Task 1 repair (`2226e9bf…`). All other G007 production hashes match HEAD.

## Focused checks (reproduced)

CWD `/Users/hyunjun/Documents/MUNI/ontologylab`. Interpreter `.venv/bin/python` (3.12.12). Each command once; no retry-to-pass.

```
git rev-parse HEAD                          # e3bca459c27f6d2cbcabb1a0a9bc37230d38316f
git rev-parse HEAD^{tree}                   # 47e5964457c46f6a769ff074ed20f3619e1b9c0c
perimeter SHA-256 over 23 HEAD: blobs       # abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e
```

```
.venv/bin/python -m pytest \
  tests/test_document_view.py \
  tests/test_ingestion_service.py \
  tests/test_file_lifecycle.py \
  tests/test_ingestion_surfaces.py \
  tests/test_ingestion_shadow_entrypoints.py \
  tests/test_provenance_outbox.py \
  tests/test_ingest_concurrency.py \
  tests/test_provenance_api.py \
  tests/test_provenance.py -q --tb=no
# collected 94 (5+10+15+8+16+14+8+16+2)
# EXIT:0
```

```
basedpyright <13 product + 9 test files above>
# 0 errors, 0 warnings, 0 notes
```

Disposable library probe under `/var/folders/…/ontologylab-wave21-task1-code-*` (deleted after):

| Probe | Result |
|---|---|
| Legacy `insert_document` row, `work_id=NULL`, `content_hash=sha256:`+`d*64` | reads exact body |
| v2 ready one-byte tamper | `KGStoreError: hash_mismatch` |
| Planted `sources.json` / `/etc/passwd` on NULL-`work_id` ready rows | `legacy raw_text_path escapes safe storage`; sentinel not in error |
| Caller SAVEPOINT + ingest + rollback | observation `op-rb` and its outbox event gone together |
| `_register_artifact` injected `RuntimeError` during `shadow_persist` | no raise; `created_count=0`; zero DOI rows; queue empty (item rolled back, outcome untyped) |

No sleeps, polling, or retry-to-pass in the new product modules or their tests. F2 uses a start barrier and a 5s bounded join.

## Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

1. **`shadow_persist` swallows unexpected item errors** (`ingestion_shadow.py` `except Exception: continue`). Domain+outbox are rolled back inside `shadow_item`, so this is not a torn write. It is silent omission: a mixed batch can return a short `IngestionResult` and HTTP `/api/collect` still answers `ok: true`. `ShadowIngestError` / `DocumentIdentityConflict` still propagate. Conflicts remain typed. This is a regression versus pre-Step-6 `ingest_documents`, which only continued on identity conflict.

2. **`work_view.observations_by_rep` has no `ORDER BY`** (`work_view.py`). Multiple Observations on one Representation collapse in SQLite scan order. That can flip `stage`/`kind`/`source`/`evidence_grade` used by `preferred-representation-v1` when a Work has more than one ready Representation. Collect duplicates usually share identical meta; the authority path can attach two sources to one Representation.

3. **Authority finalize is weaker than shadow finalize.** CLI/HTTP `/api/ingest` commit, then `reconcile_files` + `project_outbox`, and still return the pre-reconcile receipt (`staged`/`ok`). A post-commit missing `.part` can quarantine while the client already saw success. `finalize_shadow_writes` raises `FileIntegrityError` for current-batch quarantine. Same split: HTTP `/api/ingest` is 200 if any item succeeded; CLI `ingest` exits 2 unless every receipt is successful.

4. **Conflict receipts can name rolled-back ids.** `IdentifierOwnedConflict` / `SecondDoiAttachConflict` handlers return the in-flight `work_id` / `representation_id` after `ROLLBACK TO SAVEPOINT`. A follow-up that reuses those ids fails typed (`unknown representation_id`); it does not corrupt. Still a footgun.

5. **Eager hash-mismatch orphans a `.part`.** `ingestion_service.py` raises `FileIntegrityError` before `staged_paths.append`, so `_discard_staged` misses it. No document row is left; next `reconcile_files` `_cleanup_absent_staging` deletes the file.

6. **Legacy reader and review panel residuals.** NULL-`work_id` `document_raw_text` is store-root + `{sources.json, providers.json, .env}`, and does not use `content_hash` as an oracle (Task 1; pinned by `test_legacy_provenance_reads_when_hash_metadata_is_synthetic`). A SQL-planted ready row can still read other UTF-8 files under the data dir. `/api/ingest` and collect always assign `work_id` and cannot enter that branch. `document_review_context` still swallows `KGStoreError` into `text=""` (pre-existing; 200 + empty panel, not an exfil).

7. **Pre-fence residuals, not invariant breaks.** F2 `FAMILY_TRUTH` is metadata-only (`documents: 0`). `FULL_V2_AUTHORITY = False` is a tested constant, not a write gate. `shadow_ingest_queue` is `CREATE TABLE IF NOT EXISTS` at persist time, not in `authority._SCHEMA`. `insert_document` still exists for tests/`competency.py` and still `rollback()`s on `IntegrityError` (off the collect path). Canonical Goal 3 title/citation keys are absent from committed `work_view` (G007 freeze hash `33148026…` unchanged; `citation_projection` remains only as pycache). There is no `citation_json` column, so there is also no blob fallback.

## Boundaries

**Transactions.** `ingest_item` / `attach_identifier` / `insert_observation_event` / `project_outbox` / `shadow_persist` never `commit`/`rollback` the caller. They start `BEGIN IMMEDIATE` only when no transaction exists, then use named SAVEPOINTs. `RELEASE` is never the outermost savepoint. Item failure is `ROLLBACK TO` + `RELEASE`. Same-family reservation loser retries onto `existing_work_id` after the first savepoint is cleared. `file_lifecycle.quarantine_representation` / `_mark_ready` commit only when they *own* the connection (`not conn.in_transaction`); with a caller SAVEPOINT they do not. Tests pin this (`test_service_never_commits_callers_transaction`, `test_outbox_never_commits_or_rolls_back_caller_transaction`, `test_lifecycle_never_commits_or_rolls_back_caller_transaction`, `test_adapter_never_commits_or_rolls_back_caller_transaction`).

**File lifecycle.** DB stores immutable `documents/{representation_id}/raw.txt` from the first insert. Bytes live in `staging/{safe_operation_id}/{rep}.part` until `os.replace` + file/dir fsync + ready UPDATE. Readers require `representation_state=ready` and re-hash. Recovery classes are absent / finalizable / valid-ready / quarantined. Startup `reconcile_files` is scoped to `work_id IS NOT NULL` and (`staged` or `documents/%` + 71-char hash), so legacy `insert_document` rows are not rewritten. Containment refuses absolute / `..` / staging symlink escape / store-root secrets.

**Outbox.** Observation insert and `provenance_outbox` share the item SAVEPOINT. `event_id` is `sha256` of canonical `{observation_id, step}`. Projector atomically rebuilds `provenance.jsonl` *then* sets `mirrored_ts`. Replay is event-id deduped and seq-ordered. Torn JSONL is discarded. Malformed payload fails closed and leaves the existing mirror untouched. `KGStore.open` (writable only) projects unmirrored events.

**Shadow.** Production CLI collect, `POST /api/collect`, research `ingest_documents`, and `POST /api/collect/sample` all go through `shadow_persist`. Representable outcomes write the legacy document row (including `doi`) plus Work / Observation / outbox in one caller transaction, then `finalize_shadow_writes`. Same-DOI new bytes → existing row + `reason=richer` queue. Different-DOI same bytes → typed `IdentityConflict` + `reason=conflict` queue; siblings still persist. Sample URI and `SAMPLE_OPERATION_KEY` are preserved. Batch cap 100. This is not full v2 dual-write; two-Representation same-hash materialization stays refused by the live `UNIQUE(content_hash)` plus the adapter queue.

## Compatibility

- Legacy provenance tests that seed `insert_document` with placeholder `sha256:`+`d*64` now return `extraction` instead of `legacy raw text hash mismatch`.
- `/api/collect` response shape `{ok, documents, created, duplicates}` is unchanged; unexpected exceptions become `{ok:false, error_kind:failed, detail:internal_error}` with no `str(exc)` on the wire.
- `/api/collect/sample` no longer calls `insert_document`.
- v2 ready reads always go through `read_ready_text` (containment + hash). Task 1 did not weaken that branch.
- `insert_document` remains for older tests and competency; it still writes `work_id=NULL` and default `ready`.

## Nondeterminism / maintainability

No `time.sleep`, poll-until-green, or retry-to-pass in the Step 6 product or its tests. F2 writers share WAL + `BEGIN IMMEDIATE` and a barrier; observed order is allowed to change only Observation identity, and `stable_projection` drops volatile ids. `time.time()` / `uuid4` are used for timestamps and ids and are not asserted as exact values.

New modules are cohesive but large (`file_lifecycle` 531, `ingestion_service` 512, `ingestion_shadow` 499). `kgstore.py` remains far above the 250 LOC ceiling; this increment only replaced `document_raw_text` and hooked open-time reconcile/project. Acceptable for a first vertical slice; do not grow `kgstore.py` further.

## Protected-boundary cleanup

- Did not read or write `~/Library/Application Support/ontologylab/`.
- Did not use external network.
- Did not bind, kill, or retarget port 8799 or PID 55560.
- PID 55560 still listens on `127.0.0.1:8799`, DEVICE `0x1ff51c806b197195`, started `Thu Aug 6 13:51:44 2026`, same argv (`ontologylab.serve --port 8799 --data-dir …/Application Support/ontologylab/data`).
- Probe root deleted; `ls` of `ontologylab-wave21-task1-code-*` is empty.
- No leftover pytest or extra `ontologylab.serve` listener.
- `git status --short` is the same 11 unrelated untracked entries as the product-commit residual. No staged paths. This report is the only write.

## Recommendation

Approve the committed Step 6 increment. The caller-owned SAVEPOINT core, staged-ready-quarantine machine, outbox-as-truth projector, and four-entrypoint shadow adapter hold their invariants on current bytes. Fix MINOR 1 (typed per-item or batch failure instead of `continue`) when touching the adapter next; do not block close on it.

RECOMMENDATION: APPROVE
CODE_QUALITY_STATUS: PASS
BLOCKERS: none
COMMIT: e3bca459c27f6d2cbcabb1a0a9bc37230d38316f
TREE: 47e5964457c46f6a769ff074ed20f3619e1b9c0c
PERIMETER: abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e
SUITE_RECEIPT: 2521 passed, 1 skipped, 2 xfailed
