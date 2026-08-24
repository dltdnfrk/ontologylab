# Task 12 repaired committed-state full suite — deterministic contract failure

Date: 2026-08-24
Command: `uv run --all-extras pytest`
Background session: `bash_443`

## Result

`1 failed, 2815 passed, 1 skipped, 2 xfailed, 1 warning in 1479.97s`

Failure:
`tests/test_communities.py::test_legacy_pack_without_communities_degrades`

The legacy communities fallback expected only `pack_id` and
`content_hash`. The shipped query provenance contract now also returns:

- `pack_schema_version: 1`
- `integrity_level: "legacy-graph-only"`
- `evidence_mode: null`

This is a deterministic stale machine-consumed expected value, not a
production failure. The focused test was updated to the verified public
response shape and then passed once:

`1 passed in 0.55s`

`basedpyright tests/test_communities.py`: 0 errors, 0 warnings, 0 notes.
LSP reported only pre-existing hints in the file.

## Committed-byte identity

Before and after the failed suite:

- HEAD: `0120c0515020615f9cbeea23c875f04b6da50cab`
- tree: `82be963d9ce7dc28d1467cc40ee5b03ac5f0d03f`
- product/test perimeter:
  `029d4ad6b5fd7b9551420fe453f4c55ab80d72104c33bdefc17c365235724f23`

No production bytes changed during the suite. The one-file test repair
is committed separately before one exact full-suite rerun.
