# Wave 2.1 Step 8 evidence index

Date: 2026-08-24
Status: COMPLETE on committed fixture/disposable surfaces. Production
cutover has not occurred.

## Product commits

- `d740a646574b843e3bb8958823c20fa0e883499f`
  — `feat(pack): complete verified v2 publication boundary`
- `081d8554f814645517a29a0cef1c0e32af3d84df`
  — `test(pack): include evidence mode in signature contract`
- `0120c0515020615f9cbeea23c875f04b6da50cab`
  — `fix(pack): close verified v2 publication boundary`
- `cc3fd42513db4eaabff1a78a996fa5339f70615e`
  — `test(mcp): expect verified legacy provenance`

## Core implementation evidence

- `task-8-executor.md`
- `task-9-executor.md`
- `task-10-executor.md`
- `task-10-11-repair-executor.md`
- `task-11-executor.md`
- `task-12-review-repair-executor.md`
- `task-12-review-repair-2-executor.md`
- `task-12-review-repair-3-executor.md`
- `task-12-review-repair-4-executor.md`
- `task-12-review-repair-4-manual-qa.md`
- `task-12-review-repair-4-security.md`
- `task-12-review-code.md`
- `task-12-review-final-code.md`
- `task-12-review-repair-5-executor.md`
- `task-12-review-repair-6-executor.md`

## Independent review and gate evidence

Historical pre-repair reviews:

- `task-12-review-goal.md`
- `task-12-review-code.md`
- `task-12-review-security.md`
- `task-12-review-manual-qa.md`
- `task-12-review-context.md`

Repair and final reviews:

- `task-12-review-repair-goal.md`
- `task-12-review-repair-security.md`
- `task-12-review-repair-manual-qa.md`
- `task-12-review-repair-2-code.md`
- `task-12-review-repair-2-security.md`
- `task-12-review-repair-2-manual-qa.md`
- `task-12-review-repair-3-code.md`
- `task-12-review-repair-3-security.md`
- `task-12-review-repair-3-manual-qa.md`
- `task-12-review-repair-4-executor.md`
- `task-12-review-repair-4-security.md`
- `task-12-review-repair-4-security-bypass-qa.md`
- `task-12-review-final-code.md`
- `task-12-review-final-security.md`
- `task-12-review-final-manual-qa.md`
- `task-12-review-round6-code.md`
- `task-12-review-round6-security.md`
- `task-12-review-round6-manual-qa.md`
- `task-12-review-final-gate-after-repair.md` — APPROVED

## Commit and suite evidence

- `task-12-product-commit-verifier.md`
- `task-12-signature-repair-commit-verifier.md`
- `task-12-repair-commit-verifier.md`
- `task-12-full-suite-repair-commit-verifier.md`
- `task-12-final-full-suite.md`
- `task-12-repair-full-suite-failure.md`
- `task-12-repair-final-full-suite.md`

Final committed-state result:

`2816 passed, 1 skipped, 2 xfailed, 1 warning`

HEAD/tree/perimeter stayed identical across the successful run:

- `cc3fd42513db4eaabff1a78a996fa5339f70615e`
- `2278180afad39b1eb2903a91cd6739774496f689`
- `47aa97763afad2b921bd0d1ee6867bf25ed3d650137611cf3b663c6b4f1aea07`

## Closed claims

- One-snapshot v2 closure and source-material policy.
- Dynamic strict inventory and standalone verifier.
- Verify-copy-reverify immutable reader snapshots.
- F11 readiness/C-036 publication refusal.
- Work/Representation/Citation provenance and immutable raw-text access.
- Derived counts, verified counts, staleness, and exclusions catalog.
- Full-live receipt and document witnesses without widening packed closure.
- Packed semantic closure validation before every serving surface.
- Evidence capability requires a complete typed v2 closure contract.
- Strict v1/v2 parser boundary prevents authority-label laundering.
- v1 and synthetic graph-only compatibility remain verified.

## Boundary

All evidence used disposable roots. PID 55560 / port 8799 and live
Application Support data were untouched. No external network or push.
Step 9C production execution is not authorized and has not run.
