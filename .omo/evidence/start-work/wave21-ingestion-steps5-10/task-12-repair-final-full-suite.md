# Task 12 repaired committed-state full suite — PASS

Date: 2026-08-24
Command: `uv run --all-extras pytest`
Background session: `bash_448`

## Result

`2816 passed, 1 skipped, 2 xfailed, 1 warning in 1234.36s`

Exit: `0`

The sole deterministic failure from the preceding committed run was a
stale machine-consumed expected value in
`tests/test_communities.py::test_legacy_pack_without_communities_degrades`.
It was repaired and committed separately as
`cc3fd42513db4eaabff1a78a996fa5339f70615e`; the focused test passed
before this exact rerun.

## Byte identity

Before and after:

- HEAD: `cc3fd42513db4eaabff1a78a996fa5339f70615e`
- tree: `2278180afad39b1eb2903a91cd6739774496f689`
- product/test perimeter:
  `47aa97763afad2b921bd0d1ee6867bf25ed3d650137611cf3b663c6b4f1aea07`

The product repair remains commit
`0120c0515020615f9cbeea23c875f04b6da50cab`, independently verified
at exact 13-path perimeter
`c6f799fceb7dd18cf4a390574e07a28ae896d09b0339bb61930bf7fb3fb63b2a`.

No push, production cutover, Application Support access, or mutation of
PID 55560 / port 8799 occurred.
