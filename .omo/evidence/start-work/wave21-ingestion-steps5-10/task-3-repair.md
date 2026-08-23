# Repair — wave21 steps 5–10 / task-3 isolated raw-path mutant

Executor: omo senpi-task `st_01a02eb5` (repair after `st_01a02ecf` needs-fix)
Date: 2026-08-23
HEAD: `49ac5249fbfaecf0e18a00d08392166ea79250d5` (unchanged; no commit)
Constraint: no Application Support / network / 8799 / PID 55560 mutation; no Citation/review/migration/pack edits.

## Verdict

Isolated `direct raw-path read` is now killed. New test
`test_research_refuses_when_selected_ready_bytes_are_tampered` plants a ready
selected PMC Representation, tampers backing bytes after ingest/finalize, and
requires `FileIntegrityError.reason == "hash_mismatch"` with zero run/chunk/node
rows. Replacing only `_bind_run_receipt`'s `read_ready_text` with
`Path(raw_text_path).read_text()` fails that test (`FileNotFoundError` on the
relative store path). Restored `research_extract.py` bytes match the pre-repair
hash. Product behavior otherwise unchanged.

## Test added

`tests/test_research_ready_boundary.py` (48 pure LOC)

Given a C-024 Work with ready PMC full text
When the selected file bytes are overwritten after metadata is sealed
Then `extract_research_documents` raises `FileIntegrityError("hash_mismatch")`
and `extraction_run_receipts` / `extraction_chunk_receipts` / `nodes` stay 0.
The leak token `TamperedRawPathLeak` never appears.

This is the fixture where the two readers disagree: `read_ready_text` rechecks
the sealed content hash; `Path(raw_text_path).read_text()` does not join the
store root and never consults the hash.

## Isolated mutant (not grouped)

File: `ontologylab/research_extract.py` lines 198–201.

Pre / post SHA-256 (byte-identical):

```
d2da049dd2c822a8ea2d9c1208d2ffec4010f104869489175b5b2c4ad33a20c3  ontologylab/research_extract.py
```

New test SHA-256:

```
7f037cc32caaa8cf20bb65589bf08a41b51e024c6163f9e6297feb27cb4657c3  tests/test_research_ready_boundary.py
```

GREEN (current `read_ready_text`):

```
.venv/bin/python -m pytest \
  tests/test_research_ready_boundary.py::test_research_refuses_when_selected_ready_bytes_are_tampered -q
.
EXIT:0
```

RED (isolated Path mutant only; `from pathlib import Path` added so the mutant
could execute; no ranking / ignore-ready / fallback changes):

```
text = Path(str(raw_text_path)).read_text()
```

```
.venv/bin/python -m pytest \
  tests/test_research_ready_boundary.py::test_research_refuses_when_selected_ready_bytes_are_tampered -q --tb=short
F
E   FileNotFoundError: [Errno 2] No such file or directory: 'documents/rep-8837fa5c1c3c/raw.txt'
EXIT:1
```

Correct reason: the consumer never called `read_ready_text`, so it never
produced `hash_mismatch`; it opened the raw relative path from CWD.

Restore: original `read_ready_text(...)` block put back. Hash match
`d2da049d…`. Same test `.` EXIT:0.

## Verify (each command once)

Focused Task 3 (now 34):

```
.venv/bin/python -m pytest tests/test_preferred_selection.py \
  tests/test_research_selection.py tests/test_research_ready_boundary.py \
  tests/test_document_view.py tests/test_extraction_receipts.py -q
..................................
EXIT:0
# 34 passed
```

Affected (unchanged 102):

```
.venv/bin/python -m pytest \
  tests/test_research_run.py tests/test_research_source_surface.py \
  tests/test_extractor.py tests/test_run_extraction.py \
  tests/test_work_view.py tests/test_ingestion_service.py \
  tests/test_file_lifecycle.py tests/test_v2_truth_table.py -q
......................................................................................................
EXIT:0
# 102 passed
```

Static (changed Python files; `jobs.py` omitted — pre-existing `engine: Any | None`):

```
/Users/hyunjun/.local/bin/basedpyright \
  ontologylab/selection_types.py ontologylab/selection_policy.py \
  ontologylab/selection_ids.py ontologylab/selection_schema.py \
  ontologylab/selection_store.py ontologylab/selection.py \
  ontologylab/research_extract.py ontologylab/work_view.py \
  ontologylab/ingestion_shadow.py ontologylab/connectors/base.py \
  tests/test_preferred_selection.py tests/test_research_selection.py \
  tests/test_research_ready_boundary.py
0 errors, 0 warnings, 0 notes
```

No full suite. No retry-to-pass.

## Manual QA

Disposable `/private/tmp/ontologylab-wave21-task3-repair.qa.py` against
`/private/tmp/ontologylab-wave21-task3-repair.qa` (deleted after). Direct
public library only (`plant_c024` + `extract_research_documents`). No HTTP,
no sleeps.

```
{"leaked": false, "names": [], "reason": "hash_mismatch", "run_count": 0}
EXIT:0
```

## Cleanup

- QA root and driver removed
- `research_extract.py` hash identical to Task 3 GREEN product
- PID 55560 / `127.0.0.1:8799` unchanged (`ELAPSED 17-08:57:32` → `17-08:58:02`)
- No commit

## Post-write review

1. Single responsibility: one test file owns the ready-boundary refuse.
2. Boundary purity: tamper is a store-file write; refuse is `FileIntegrityError`.
3. No new variant `if/elif`.
4. No escape hatches in product (product untouched after restore).
5. No extra defensive layer.
6. `_table_count` used for run/chunk/node absence after rollback.
7. Test fails if `read_ready_text` is replaced by `Path(raw_text_path).read_text()`.
8. No parameter bloat.
9. No post-delete re-query beyond counting remaining rows (absence is the Then).
10. Positive names.
11. No logging.
