# Wave 2.1 Step 6 evidence index

Authoritative closer for the committed Step 6 product. This file is the G007
evidence index. It is not a product claim beyond the bindings below.

## Bindings (final authority)

| Fact | Value |
|---|---|
| Commit | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` |
| Subject | `feat(ingestion): complete transactional v2 shadow service` |
| Tree | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` |
| Parent | `eab47a615cc5f309c05a48875c6e6877096783dd` (Step 5) |
| Perimeter SHA-256 | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` |
| Perimeter recipe | SHA-256 of C-sorted `path<TAB>file-sha256\n` over the 23 committed Step 6 paths |
| Suite | `2521 passed, 1 skipped, 2 xfailed`, exit 0 |
| Suite receipt | `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-1-full-suite.md` SHA-256 `f51dbb65f1299fdbf8a64c7bea5dbbc4efe4e5a9e71b4fb4e597fd1db4ff791f` |
| Loop session | `wave21-step6-ingestion-service-20260821` |
| Closer goal | G007 (G005 remains blocked/superseded) |

Execution authority (section 0 of the blueprint wins on conflict):

- `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md`
- `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md`

Consumed baseline: Step 5 index
`.omo/evidence/ulw/wave21-step5-migration-core-20260821/G005-goal-5-close-step-5-run-the-exact-fu/a1/step5-evidence-index.md`
and commit `eab47a6`. Step 5 product/test bytes are unchanged by `e3bca45`.

Final start-work receipts (cite these, not the pre-commit G007/a1 reviews):

| Receipt | Worker | SHA-256 |
|---|---|---|
| `task-1-executor.md` | `st_01a02e39` | `39b12a5665fe66fae250c373f9329bf6f52ba8ccd460f721313766c20765ee1c` |
| `task-1-verifier.md` | `st_01a02e43` | `773ccbf2167ff08c541956a846c0fdfbd635e82a9265e2d55135aaecb2c0afe5` |
| `task-1-product-commit.md` | `st_01a02e4d` | `45421e33457f2e8c7c52801d05f3b62c1c8014377ce1dba19f1ab6fa0bfc6723` |
| `task-1-full-suite.md` | `st_01a02e51` | `f51dbb65f1299fdbf8a64c7bea5dbbc4efe4e5a9e71b4fb4e597fd1db4ff791f` |

Final review DAG (hashes from `task-1-reviews/gate.md`):

| Report | Worker | SHA-256 | Verdict |
|---|---|---|---|
| `goal.md` | `st_01a02e68` | `786ca27a04103c1ce6e9080b302702fe68a74903bf992d2803f576165a3f7999` | PASS (0.86) |
| `code.md` | `st_01a02e69` | `ac1a7013d0b0e3342995f9b2528989d6eb0f939d035d6d5b0088b0938519bd0a` | PASS (0.91); 0 CRITICAL, 0 MAJOR; 7 MINOR |
| `qa.md` | `st_01a02e6a` | `145b20cd6445a47304d0be7da31fb7c8f5838a10cec681b3f0fadd52ef99ea3d` | PASS (0.94); S1-S16 PASS |
| `security.md` | `st_01a02e6b` | `f528c25aa2ced84e06b2e82c75a746661d53009f7f383220202cbdfe53ec3c22` | PASS (0.90); max LOW; 6 LOW |
| `context.md` | `st_01a02e6c` | `f55f14c9fbaf63ac682e035fe2b21633edd60987156efa8c53a7c949a1a5ddd3` | PASS (0.93); 7/7 HOLD |
| `gate.md` | `st_01a02e73` | `f6c36527276dc79e602568935e6a69457a281ce96ce73e58018daccc727a9c3d` | PASS |

Do not cite superseded pre-fix or pre-commit reports as final authority. That
set includes G005 reviews, G007/a1 reviews bound to `eab47a6` / freeze
`f3aead6a…` / `kgstore.py` `ae0422d7…`, and any hash-oracle language that
treats synthetic `sha256:` + 64 hex on NULL-`work_id` rows as integrity.

`kgstore.py` on `e3bca45` is the Task 1 repair blob
`2226e9bf6b67952ccea38202203478a96fd5571bbb27b75045d53b8961eca22f`.

## Goal / evidence families

### G001 transactional service v2 core (6A): complete

Files: `ontologylab/ingestion_service.py`, `ontologylab/authority_repo.py`,
`tests/test_ingestion_service.py`.

RED: `tests/test_ingestion_service.py` collection `ModuleNotFoundError`, rc=2.
GREEN: 8 passed, rc=0. Typed `created` / `duplicate` / `conflict` / `failed`
receipts. Identifier reserve, one Work per family, Observation append, and
append-only assertion stay inside one caller-owned SAVEPOINT. No service
`commit` / `rollback`. Same-key retry reuses. Second-DOI attach is typed
conflict, never a merge.

Mutants killed and restored:

- m1 second-DOI conflict folded into a dedupe return
- m2 identifier reservation and Observation split across commits

Receipts: `G001-.../a1/{red-green,edge-mutation,regression}.txt`. Historical
bundle tag `@bundle:6c370785…` is a G001-G004 freeze, not the final perimeter.

### G002 authority write tool and HTTP seam (6A surfaces): complete

Files: `ontologylab/ingestion_surfaces.py`, `ontologylab/server/ingest_routes.py`,
`ontologylab/server/app.py`, `ontologylab/main.py`,
`tests/test_ingestion_surfaces.py`.

RED: missing `ingestion_surfaces`, rc=2.
GREEN: 8 passed, rc=0. CLI `ingest` and HTTP `POST /api/ingest` plus
`/api/ingest/sample` share the service core. Receipt ids and conflict class
names match (HTTP 409 / CLI exit 2). Queue mode writes nothing. Sample collect
returns typed per-item outcomes and cannot claim `ok` on a partial batch.

Mutants killed and restored:

- m1 swallows a batch failure and reports ok on partial
- m2 sample path writes directly instead of calling the service

### G003 citation-blob projection: SUPERSEDED historical receipts only

`tests/test_citation_projection.py` and `ontologylab/citation_projection.py`
are not in commit `e3bca45`. Section 0 remaps 6B to file lifecycle (G008).
G003 RED 4 failed / 3 passed then GREEN 7 passed, plus mutants m1 blob write
and m2 blob read fallback, remain on disk as superseded context. They are not
final product authority. Committed `work_view.py` has no title/citation
projection keys and there is no `citation_json` column, so there is also no
blob fallback on current bytes.

### G004 fixture-bound concurrent ingest (F2 ownership): complete

Files: `tests/test_ingest_concurrency.py`, `tests/wave21/ingest_concurrency.py`,
plus G001 service/authority hooks.

RED: missing harness, rc=2.
GREEN: 8 passed, rc=0. Barrier-synchronized threads, 5s bounded join, no
sleeps. Identical family: 1 Work / 1 identifier / 2 Observations / 2
assertions. Observed order changes only Observation identity. Concurrent
second-DOI is one typed conflict. Unrelated sentinel survives.

Mutants killed and restored:

- m1 reservation loser folded into a dedupe return
- m2 reservation and Observation commits split apart

Caption this as G004 / loop F2, not as `05-failure-analysis.md` F2 GREEN.
Writers are threads, not processes. `FAMILY_TRUTH` is metadata-only
(`documents: 0`). Same-hash / two-Work materialization stays queued or
`IdentityConflict` under the live global hash constraint.

### G005 original closer: blocked / superseded

Steering `mark_blocked_superseded` at `2026-08-23T08:47:06.465Z`. Premise
lacked F4, F5, production shadow, and authoritative 6B scope. Receipts under
`G005-.../a1/` are historical. Closure moved to G007.

### G008 staged file lifecycle and F4: complete

Files: `ontologylab/file_lifecycle.py` plus service/kgstore/work_view/surface
hooks and `tests/test_file_lifecycle.py`, `tests/test_document_view.py`.

RED: missing `file_lifecycle`, rc=2.
GREEN: 13 passed, rc=0. Operation-owned staging. Immutable final relative
`documents/{representation_id}/raw.txt` stored from the first DB write.
Atomic rename plus file/directory fsync. Readers consume ready only.

F4 truth table: absent, finalizable staged, valid ready, typed quarantine.
Historical G008 regression recorded 55 passed. Later characterization tests
grew the adjacent set (verifier collected 62). Count drift is added tests,
not a missing module.

Mutants killed and restored:

- m1 containment disabled
- m2 staged exposure
- m3 mutable final path
- m4 missing-file finalize
- m5 hash-mismatch acceptance
- m6 internal transaction control

Path-containment (absolute / `..` / symlink / `sources.json`) is proven on
`tmp_path` only.

### G006 transactional outbox and F5: complete

Files: `ontologylab/provenance_outbox.py` plus service/surface project hooks
and `tests/test_provenance_outbox.py`, `tests/test_provenance.py`.

RED: missing `provenance_outbox`, rc=2.
GREEN: 13 passed, rc=0. One deterministic outbox event in the same
caller-owned SAVEPOINT. `project_outbox` rebuilds canonical JSONL, then sets
`mirrored_ts`.

F5: rollback couples domain and outbox; replay is one logical/physical event;
torn mirror rebuilds from SQLite; failpoint after fsync stays unmarked;
failpoint before mirror leaves projected state unset; malformed payload fails
closed.

Mutants killed and restored:

- m1 outbox omission
- m2 mark-before-durable-mirror
- m3 duplicate append
- m4 nondeterministic ordering
- m5 internal transaction control

Historical regression: 63 passed, basedpyright 0/0/0.

### G009 production shadow entrypoint convergence (6D): complete

Files: `ontologylab/ingestion_shadow.py`, `ontologylab/ingestion.py`,
`ontologylab/server/routes.py`, plus service/surface/main hooks and
`tests/test_ingestion_shadow_entrypoints.py`.

RED: missing adapter, rc=2.
GREEN: 16 passed, rc=0. CLI collect, `POST /api/collect`, research
`ingest_documents`, and `POST /api/collect/sample` all traverse
`shadow_persist`. Legacy response shapes, sample URI, and operation keys
are preserved. Representable persists write matching Observation + outbox.
`FULL_V2_AUTHORITY = False`. Richer / conflict outcomes enter a durable
queue or typed not_ready.

Mutants killed and restored:

- m1 direct sample insertion
- m2 legacy `ingest_documents` detour
- m3 global content-hash authority
- m4 swallowed partial batch
- m5 raw identifier storage
- m6 exception leakage
- m7 unbounded batch
- m8 internal transaction control

Independent production-entrypoint regression: 97 passed, basedpyright 0/0/0.

### Task 1 compatibility repair (legacy provenance): confirmed

Executor `st_01a02e39`, verifier `st_01a02e43` verdict `confirmed`.
`document_raw_text` splits on `work_id is not None` -> `read_ready_text`
(hash + `documents/` containment). NULL-`work_id` ready rows decode without
using `content_hash` as an oracle. Absolute / traversal / `sources.json` /
`providers.json` / `.env` still raise typed escape. Staged/quarantined still
refused. Toggle restore of the oracle fails
`test_legacy_provenance_reads_when_hash_metadata_is_synthetic` and the
inverse restore returns blob
`2226e9bf6b67952ccea38202203478a96fd5571bbb27b75045d53b8961eca22f`.

### G007 closer: complete on this write

C001: suite bound to `task-1-full-suite.md` (`2521 passed, 1 skipped, 2 xfailed`,
exit 0) with no perimeter drift; five lanes plus gate PASS; this index and
`.omo/ulw-loop/wave21-step6-ingestion-service-20260821/step7-kickoff.md`.
C002: `scope-cleanup.txt`.
C003: `commit-boundary.txt` (product commit already `e3bca45`; this closer
does not amend or add a second product commit).

## Ownership map (honest)

| Concern | Owner on these bytes |
|---|---|
| F2 concurrent v2 writers | G004 fixture (threads, metadata-only). Not full `05` F2 GREEN. |
| F4 file recovery | G008. Absent / finalizable / valid-ready / quarantined. |
| F5 outbox | G006. One logical event. Mark never before durable mirror. |
| Entrypoint convergence | G009 four named collect/research/sample seams plus G002 authority CLI/HTTP. `competency.py` `insert_document` is not a named 6D collect entrypoint. |
| Compatibility repair | Task 1 `document_raw_text` split. v2 hash still enforced. |
| Real surfaces | QA S1-S16 on disposable roots and port 19173. |
| Product commit | `e3bca45`, 23 owned paths, perimeter `abe543be…`. |
| Suite | One exact `.venv/bin/python -m pytest`, exit 0. |
| Reviews | Six start-work reports, gate PASS. |

## Real surfaces (QA, disposable only)

Installed CLI ingest/collect, direct `ingest_item` staged then ready, research
`ingest_documents`, HTTP collect/sample, legacy synthetic-hash provenance 200,
v2 live tamper `hash_mismatch` then HTTP 400 quarantined, five unsafe legacy
paths 400 with `SECRET_LEAK=[]`, torn/malformed/failpoint outbox fail closed.
Listener 19173 and QA temps are gone. See `task-1-reviews/qa.md`.

## Protected cleanup

Port `127.0.0.1:8799` remains PID `55560`, DEVICE `0x1ff51c806b197195`,
started `Thu Aug 6 13:51:44 2026`, same argv
(`ontologylab.serve --port 8799 --data-dir …/Application Support/ontologylab/data`).
This closer did not read or write live Application Support. Leftover
`/private/tmp/ontologylab-wave21-t1qa*` and `*-task1*` roots are absent.

## Known MINOR / LOW residuals (do not void PASS)

`code.md` lists: silent `shadow_persist` `except Exception: continue`; unordered
`observations_by_rep`; authority-vs-shadow finalize split; rolled-back conflict
ids; eager-hash leftover `.part`; legacy store-root residual; pre-fence
`FULL_V2_AUTHORITY = False`.

`security.md` L1-L6: SQL-planted NULL-`work_id` store-root read;
case-sensitive denylist; `work_id IS NULL` skips v2 hash/reconcile; review
panel 200-empty; in-process receipt `Type: message`; leftover `.part`.

`goal.md` notes research still `collapse_duplicates` before persist (persist
seam is still `ingest_documents`). F2 caption residual as above.

None of these tear domain+outbox, expose staged or escaped bytes on ingest
or collect, or weaken v2 ready hash.

## Honest boundary (forbidden captions)

This index does **not** claim:

- lossless ingestion
- full semantic dual-write
- full v2 authority (`FULL_V2_AUTHORITY` stays false until Step 9)
- full `05-failure-analysis.md` F2 GREEN
- Step 7+ extraction / Citation / ReviewDecision / C-024 consumer GREEN
- pack v2 / F11
- production cutover / 9C
- G003 citation-projection product still in the tree
- pre-commit G007/a1 reviews as current-byte authority

Step 7 kickoff:
`.omo/ulw-loop/wave21-step6-ingestion-service-20260821/step7-kickoff.md`.
