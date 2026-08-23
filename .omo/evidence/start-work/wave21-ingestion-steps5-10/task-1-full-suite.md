# Task 1 full-suite receipt (committed Step 6 product/test state)

Date: 2026-08-23
Worker: omo senpi-task `st_01a02e51`
Mode: read-only committed-state verification. No product/test edits. No commit. No push. No Git ref mutation.

## Verdict

`PASS`

Exact command `.venv/bin/python -m pytest` ran once against the required committed Step 6 product/test perimeter. Exit code 0. Terminal summary has zero failed, zero errors, and zero xpass. Before/after HEAD, tree, and perimeter SHA-256 are byte-identical.

## Gate (before run)

Required by task / `task-1-product-commit.md`. All three matched; no uncommitted product/test path existed; no pytest process existed. Suite was therefore allowed to start.

| Fact | Required | Observed before |
|---|---|---|
| HEAD | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` |
| Tree | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` |
| Committed perimeter SHA-256 | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` |
| Working-tree perimeter SHA-256 | same as committed | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` |
| Staged index | empty | empty |
| Uncommitted product/test paths | none | none (`git diff --stat -- ontologylab tests` empty; porcelain product/test clean except pre-existing `?? ontologylab/graphify-out/`) |
| Parallel pytest at start | none | none |

Perimeter recipe (same as product-commit): SHA-256 of sorted `path<TAB>file-sha256\n` over the 23 committed Step 6 paths. Working-tree bytes of those 23 paths matched `HEAD:` blobs before the run.

## Command

```
cwd=/Users/hyunjun/Documents/MUNI/ontologylab
interpreter=/Users/hyunjun/Documents/MUNI/ontologylab/.venv/bin/python
python=3.12.12
command=.venv/bin/python -m pytest
```

Invocation was exactly that command once. No extra flags, no subset, no rerun, no retry-to-pass. Repo pytest config (`pyproject.toml` `[tool.pytest.ini_options]`) supplies `addopts = "-q"`, `testpaths = ["tests"]`, `pythonpath = ["."]`. No `xfail_strict`. Ambient env had no `PYTHONPATH` / `PYTHONHOME` / `PYTEST_*` / `ONTOLOGYLAB_*` / `DATA_DIR` overrides.

## Timestamps

| | UTC | Local (+0900) | epoch |
|---|---|---|---|
| Start | `2026-08-23T11:13:39Z` | `2026-08-23T20:13:39+0900` | `1787483619` |
| End | `2026-08-23T11:33:15Z` | `2026-08-23T20:33:15+0900` | `1787484795` |

Wall duration: `1176` s. Pytest-reported duration: `1166.19s` (`0:19:26`).

## Exit and terminal summary

Authoritative last line of the captured terminal (not a progress-dot recount):

```
2521 passed, 1 skipped, 2 xfailed, 1 warning in 1166.19s (0:19:26)
```

| Field | Value |
|---|---|
| Exit code | `0` |
| passed | `2521` |
| skipped | `1` |
| xfailed | `2` |
| failed | `0` (absent from summary) |
| errors | `0` (absent from summary) |
| xpass | `0` (absent from summary) |
| warnings | `1` |

Project-strict success rule applied here: exit 0 and zero failed / error / xpass. `xfailed` is allowed because `xfail_strict` is not set. Skip/xfail node IDs are not named in `-q` output; they were not re-queried.

Warning (verbatim, third-party Starlette/FastAPI, not a product file):

```
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/hyunjun/Documents/MUNI/ontologylab/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa
```

## Complete captured output

Raw log: 3446 bytes, 43 lines, SHA-256 `888cc7257f7e5bba4548d38b2f228be71b55a41c7f34156bba61fe87f28dc3e2`. Embedded in full:

```
........................................................................ [  2%]
........................................................................ [  5%]
........................................................................ [  8%]
........................................................................ [ 11%]
........................................................................ [ 14%]
........................................................................ [ 17%]
........................................................................ [ 19%]
........................................................................ [ 22%]
........................................................................ [ 25%]
........................................................................ [ 28%]
........................................................................ [ 31%]
........................................................................ [ 34%]
........................................................................ [ 37%]
........................................................................ [ 39%]
........................................................................ [ 42%]
........................................................................ [ 45%]
........................................................................ [ 48%]
........................................................................ [ 51%]
........................................................................ [ 54%]
........................................................................ [ 57%]
........................................................................ [ 59%]
........................................................................ [ 62%]
........................................................................ [ 65%]
........................................................................ [ 68%]
........................................................................ [ 71%]
........................................................................ [ 74%]
........................................................................ [ 77%]
........................................................................ [ 79%]
........................................................................ [ 82%]
........................................................................ [ 85%]
........................................................................ [ 88%]
...................................................................s.... [ 91%]
........................................................................ [ 94%]
........................................................................ [ 96%]
...........x...x........................................................ [ 99%]
....                                                                     [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/hyunjun/Documents/MUNI/ontologylab/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
2521 passed, 1 skipped, 2 xfailed, 1 warning in 1166.19s (0:19:26)
```

## After-run identity (must equal before)

| Fact | After |
|---|---|
| HEAD | `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` |
| Tree | `47e5964457c46f6a769ff074ed20f3619e1b9c0c` |
| Subject | `feat(ingestion): complete transactional v2 shadow service` |
| Committed perimeter SHA-256 | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` |
| Working-tree perimeter SHA-256 | `abe543be4ca635c219ddda465a13c7ca223ee92a2b727f1a83650af7ddd6371e` |
| Per-path HEAD vs working-tree mismatches | none |
| Staged index | empty |

Before/after HEAD, tree, and both perimeter hashes are byte-identical to the required values.

## Dirty / staged classification

`git status --short` after the run (directory-level, same 11 entries as `task-1-product-commit.md` residual):

```
?? .sisyphus/
?? artifacts/
?? docs/CONANSSAM-PROMPT-2026-08-08.bak
?? docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md
?? docs/OMO-INGESTION-WAVE-2.1-IMPLEMENTATION-HANDOFF-2026-08-20.md
?? docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md
?? "docs/ONTOLOGYLAB-DETAILED-SMOKE-RESULT-2026-08-08 2.md"
?? docs/WAVE-2.1-DEEP-RESEARCH-REMEDIATION-GJC-2026-08-20.md
?? graphify-out/
?? ontologylab/graphify-out/
?? uv.lock
```

Classification: all pre-existing / orchestration / unrelated. None are Step 6 product or test sources. No new untracked top-level path appeared relative to the product-commit residual. `ontologylab/graphify-out/` remains generated/unrelated, not a product module.

Ignored orchestration (not shown by `git status --short`, not staged):

- `.omo/plans/`
- `.omo/evidence/start-work/wave21-ingestion-steps5-10/` (this receipt)
- `.omo/ulw-loop/` and other `.omo/` evidence

New path created by this worker: this receipt only (gitignored). No product/test path was created or modified.

## Protected-boundary / cleanup

- Did not read or write `~/Library/Application Support/ontologylab/`.
- Did not use external network.
- Did not bind, kill, or retarget port 8799 or PID 55560.
- Did not modify Git refs.

Port 8799 / PID 55560 (read-only, before and after; DEVICE unchanged):

```
COMMAND     PID    USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
python3.1 55560 hyunjun   10u  IPv4 0x1ff51c806b197195      0t0  TCP 127.0.0.1:8799 (LISTEN)
```

PID 55560 still owns `127.0.0.1:8799`, same listen socket DEVICE `0x1ff51c806b197195`, same command started `Thu Aug 6 13:51:44 2026`:

`/Users/hyunjun/Documents/MUNI/ontologylab/.venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 8799 --data-dir /Users/hyunjun/Library/Application Support/ontologylab/data --packs-dir /Users/hyunjun/Library/Application Support/ontologylab/packs`

Cleanup:

- No leftover pytest child process after the run.
- No pytest temp root created in `/private/tmp/pytest-of-hyunjun` during `20:13–20:33 +0900` (`in_window_count=0`). Historical `pytest-of-hyunjun` tree (mtime 2026-08-15) and `/tmp/.pytest_cache` (mtime 2026-08-20) were not touched and were not deleted.
- Temporary capture files `task-1-full-suite.raw.log` and `task-1-full-suite.meta.txt` are removed after this receipt embedded the required output. No lock file was left by this run.

## Recovery / non-actions

HEAD `e3bca459c27f6d2cbcabb1a0a9bc37230d38316f` is untouched. No commit, amend, rebase, reset, checkout, stash, or push. Product and test bytes are unchanged.
