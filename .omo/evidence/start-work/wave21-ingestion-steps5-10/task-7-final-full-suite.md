# Task 7 final committed-state full-suite receipt

Date: 2026-08-24
Mode: exact serial project suite, one run
Command: `.venv/bin/python -m pytest`

## Verdict

`PASSED`

The exact full suite passed on the final committed Task 7 repair state.

## Frozen state

- Commit before/after:
  `362b0a679483139e51d8e37748674a867d6a9b2f`
- Commit subject:
  `fix(extraction): preserve exact receipt identity`
- Product/test tree perimeter recipe:
  SHA-256 of `git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml`
  sorted with `LC_ALL=C`.
- Perimeter before/after:
  `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867`
- Tracked `ontologylab`, `tests`, `scripts`, and `pyproject.toml` worktree
  matched `HEAD` before and after.
- No concurrent project pytest process existed before launch.
- No product/test edit, commit, stage, push, or retry occurred during the run.

## Result

```text
2650 passed, 1 skipped, 2 xfailed, 1 warning in 1274.66s (0:21:14)
PYTEST_STATUS=0
HEAD_AFTER=362b0a679483139e51d8e37748674a867d6a9b2f
PERIMETER_AFTER=9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867
WORKTREE_CODE_TEST_CLEAN_AFTER=true
```

The warning is the existing Starlette `httpx`/`httpx2` deprecation warning.
The suite's declared skip and xfails remained non-failing.

## Prior-run supersession

This receipt supersedes the interrupted full-suite attempts in
`task-7-full-suite.md` and `task-7-full-suite-2.md`. Those attempts reached the
same integration boundary and were stopped after confirming an inherited SSE
iterator teardown stall. Commit
`5a6378964bfc41fe2a679453a88235c548a59f4b`
(`test(server): synchronize jobs stream change`) repaired that deterministic
test seam. The final run above traversed the same boundary and completed.

## Protected boundaries

- No live Application Support data was used.
- Port `8799` / PID `55560` was not touched.
- No external network action was performed.
- No planning document was edited.
