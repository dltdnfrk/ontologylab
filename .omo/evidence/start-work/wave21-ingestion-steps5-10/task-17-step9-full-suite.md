# Step 9 committed-state full suite

Date: 2026-08-24
Command:

```bash
UV_NO_SYNC=1 uv run --all-extras pytest
```

## Result

```text
2873 passed, 1 skipped, 2 xfailed, 1 warning in 1336.78s (0:22:16)
exit 0
```

The warning is the existing Starlette TestClient/httpx deprecation.

## Committed identity

Before and after the single serial suite:

```text
HEAD  42d3dcb3940d4d40697dac07bf28f4dbfcd28b81
tree  0a20eb1d587b5c7f6767d86eba1d55990ac65f50
```

Two product/test perimeter algorithms are recorded distinctly:

```text
commit-blob perimeter (independent verifier)
2ca26476278fb2ca25c35182505ed48c47f2f7571edcfb73084d14eb37aaf129

working-byte perimeter (lead before/after command)
6318ba4e39b2e7eb4b501090a66907cab09ae485ab3c6dcdc7c93c01f2bb69c2
```

The Step 9 preflight ledger initially labeled the commit-blob perimeter as
the generic product/test perimeter while the post-suite lead command emitted
the working-byte perimeter. This is an algorithm-label mismatch, not a byte
change. The hashes are preserved under their correct names; HEAD and tree are
identical.

## Isolation

- one pytest process only
- no rerun-to-pass
- no product/test/plan edit
- no push
- no external network
- no Application Support access
- no port 8799/PID 55560 mutation
- no Step 9C

```text
STEP_9B_COMPLETE
STOP_BEFORE_STEP_9C
```
