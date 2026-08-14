# Task 1 - KG-only lifecycle baseline

Date: 2026-08-11 (repaired)
Scope: characterization tests only; no Methodology IR, store, compiler, pack, or MCP implementation.

> This file is the user-facing compatibility summary only. It does not satisfy
> any acceptance gate. The canonical, machine-checkable receipts live in
> `.omo/evidence/methodology-compiler-foundation/` (`baseline.md`,
> `task-1-red.md`, `task-1-green.md`, `task-1-manual.md`,
> `task-1-adversarial.md`, `task-1-cleanup.md`), plus the durable exact
> failure-ID arrays `baseline-normal-failure-ids.json` and
> `baseline-ci-failure-ids.json`.

## Repository boundary

- Physical working directory: `/Users/hyunjun/Documents/MUNI/ontologylab`
- Git top-level: `/Users/hyunjun/Documents/MUNI/ontologylab`
- Origin: `https://github.com/dltdnfrk/ontologylab.git`
- Existing modified and untracked files were not intentionally edited.

## Frozen pre-Methodology contract

`tests/test_methodology_foundation_baseline.py` (renamed from
`tests/test_methodology_baseline.py`; 248 pure LOC, 6 tests) records six
current guarantees:

1. The exact current `build_pack` signature is frozen by string equality, so
   any added parameter - including `method_release_ids` - breaks the test.
   (`summary_method` is pre-existing and unrelated to release selection.)
2. A real graph-only immutable pack has an exact 26-table inventory, shares no
   name with any of 21 Method/compiled-method table variants, and its
   `manifest.json` has no methodology section and no `capabilities` key.
3. MCP exposes exactly the current 11 tools and five `pack://` resource
   templates, read from the live tool/resource listing.
4. `documents.content_hash` equals SHA-256 of the exact raw bytes on disk, and
   a Unicode span is proven against decoded text - character offsets are
   explicitly shown not to be byte offsets.
5. A successful extraction chunk commits proposal rows and its success marker
   atomically, proven through an independent SQLite observer connection.
6. A failed extraction chunk rolls proposal rows back before persisting its
   failure marker, with exact failure identity `("failed",
   "baseline_failure")` and run status `failed`.

## Automated verification

### Canonical acceptance set

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/pytest -p no:cacheprovider \
  tests/test_methodology_foundation_baseline.py tests/test_packbuilder.py \
  tests/test_mcp_two_tier.py tests/test_extraction_lifecycle.py
```

Result: `30 passed, 2 warnings in 1.24s`.

### Full-suite baseline (normal)

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/pytest -p no:cacheprovider \
  --junitxml=/tmp/ontologylab-method-baseline.junit.xml
```

Result (re-capture): `269 failed, 1587 passed, 6 skipped, 5 warnings in
106.51s`. Parsed from the JUnit XML with `ElementTree`: 1862 tests, 269 unique
failure node IDs, **all** in `tests/test_product_status.py`, zero in any Task 1
module. The 269 exact IDs are stored in `baseline-normal-failure-ids.json`.

### Full-suite baseline (CI-equivalent)

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPATH='' .venv/bin/python -m pytest -p no:cacheprovider -q -c /dev/null \
  --rootdir . --junitxml=/tmp/ontologylab-method-ci-baseline.junit.xml
```

Result (re-capture): `269 failed, 1587 passed, 6 skipped, 5 warnings in
109.19s`. The CI failure-ID set is identical to the normal set (0 in each
direction); the IDs are stored in `baseline-ci-failure-ids.json`.

Both owned JUnit XMLs were parsed and then removed. Later checkpoints must
satisfy `current_failure_ids - baseline_failure_ids = empty` per command,
evaluated against the matching recorded JSON array. Counts alone cannot
execute that gate: `tests/test_product_status.py` collects 332 tests, of which
269 fail and 63 pass, so a count never identifies which tests failed. Note that
35 of the recorded IDs contain a literal two-character `\n` inside pytest
parameter ids, so the arrays must be read with a JSON parser, never by line
splitting.

## Mutation proof

Two temporary mutations were applied separately to
`ontologylab/extraction_state.py`, tested, and immediately reverted:

1. Removing `ExtractionState.failed()` proposal rollback made
   `test_chunk_failure_rolls_back_proposals_before_failure_marker` fail on the
   intended assertion (`assert (1,) is None` - the rolled-back node was still
   visible to the independent observer).
2. Removing `ExtractionState.succeeded()` commit made
   `test_chunk_success_commits_proposals_and_marker_atomically` fail because
   the observer could not see the node after success. The manual QA script
   independently caught the same mutation with exit 1 and exactly two false
   checks.

Restoration is proven by hash, not by inspection: the post-task SHA-256 of
`ontologylab/extraction_state.py` is
`210bcdd9bc7f2422263699a3a3bb8f49fe620c23585bc12e7afdf7d79d965f62`, identical
to the pre-task value, with clean `git status` and no `git diff`.

## Manual QA

`scripts/qa_methodology_baseline.py` drives real `KGStore` / `ExtractionState`
surfaces against a disposable database:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python \
  scripts/qa_methodology_baseline.py --database /tmp/ontologylab-method-baseline.sqlite
-> EXIT=0, status PASS, 13/13 checks true, residue [], leaked [],
   table_count 27 with the full sorted inventory printed
```

The script refuses to run (exit 2, `"mutated": false`) when the target or any
declared sidecar already exists; both refusal paths were exercised against
planted sentinels and left them byte-identical. It removes only the paths it
created - its database and sidecars, its own raw-document files and
per-document directories, and the `documents/` root only when that root did not
exist before the run and is empty afterwards. A pre-existing or non-empty
`documents/` root is never touched; both cases were verified, including one
with an unowned sentinel that survived byte-identical.

No `.pytest_cache` or `*.pyc` entry was created by Task 1: pre/post inventories
are identical (6 cache files, 427 `.pyc`).

## Pre-existing blocker noted

`git diff --check` could not complete because the repository already has a
corrupt Git pack object:

```text
.git/objects/pack/pack-6fe04754274d21ea1ad1c088b29b178438a6204e.pack
is far too short to be a packfile
fatal: unable to read 49042a5c527a685abf8838cc56a5113d786fcce2
```

This was not repaired because Git repair is outside Task 1 and could affect
shared work. It also explains the `git archive` subprocess failures seen in
the pre-existing product-status test failures - all 269 baseline failures in
both the normal and CI-equivalent runs belong to that one module.
