# Isolated trial Slice B — UI

Recorded: 2026-08-18
Server: `127.0.0.1:18765` PID 90523 (until cleanup)
Data: `/private/tmp/ontologylab-cs-trial/data`
Protected (untouched): PID 55560 / `127.0.0.1:8799`

## F6 lock click

1. Palette → 승인됨 RateLimiter → entity panel (`무효화` count = 1 after earlier edge already invalidated).
2. Hold `BEGIN IMMEDIATE` on trial `kg.sqlite` (`/private/tmp/cs-lock2.py`).
3. Real click on `무효화` (`window.confirm` stubbed true).
4. `#entity-panel-error` visible, not hidden:
   `The knowledge base is busy — an extraction job is writing to it. Try again in a moment. — 2초 뒤에 다시 시도해주세요.`
   `nInv` stayed 1. After lock release, `729b2bf9…` still had `invalidated_ts IS NULL`.
5. Unlocked retry: one click → `nInv` 0, panel relations “승인 0건”, sqlite `invalidated_ts` set once, reason `invalidated via dashboard`.

Aside long-evaluate WebSocket drops (~23s) are a driver flake, not a product 503 miss. Short click + DOM poll is the working capture path.

## F1-UI partial-failure banner

`api:cs-trial` (base `https://example.invalid/v1`, no key) through the real extract form (`#extract-form` inside `<details>`).

`#extract-result`:
`실패 extraction engine failed — 새로 나온 제안은 없어요. 위 추출 양식으로 다시 시도해주세요.`

`[object Object]` = 0. Jobs table independently listed the same job as 실패.
