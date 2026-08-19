# Isolated trial Slice A — HTTP / MCP

Recorded: 2026-08-17
Server: `127.0.0.1:18765` PID 90523
Data: `/private/tmp/ontologylab-cs-trial/data`
Packs: `/private/tmp/ontologylab-cs-trial/packs`
Protected (untouched): PID 55560 / `127.0.0.1:8799`

## Verdicts

| Probe | Surface | Result |
|---|---|---|
| F5 pack name `../outside` | HTTP + live UI | HTTP 422 field `name`; UI `#pack-build-result` = `name: Value error, invalid pack name '../outside': use only letters, digits, '.', '_', '-' (no path separators)`. `[object Object]` count = 0 |
| F7 unusable packs | HTTP + live UI | API `unusable` = 3 distinct reasons. Packs tab: "열 수 없는 팩 폴더 3개" lists `bad-array`, `bad-counts`, `bad-sqlite`. Diff selects empty (no phantom options) |
| F6 lock | HTTP only | `BEGIN IMMEDIATE` + `POST /api/edges/729b2bf9a50a49648453b0f9d50b1657/invalidate` → **503** `error_kind=busy`, `Retry-After: 2`. UI click still open (Slice B) |
| F3 MCP schema | product `McpApp` + `run_stdio` | three bad calls → JSON-RPC **-32602**, no signature leak, subsequent `ping` still `{result:{}}` |
| F4 tampered pack | `_verified_pack` + `PackSession.load_pack` | built `cs-trial-pack-20260817-222159` (override+intent). Flipped sqlite byte → **REJECTED** hash mismatch. Original pack still verifies |
| F1/F2 secret | live HTTP | `POST /api/sources` with `key=sk-cs-trial-SECRET-9f3c2a1b` → 200, `key_present=true`, secret absent from create/list/jobs/settings and from rejected-id body |

Raw JSON: `/private/tmp/cs-slice-a.json`, `/private/tmp/cs-slice-a2.json`

## Next session (Slice B only)

1. Confirm 18765 still listening; do not restart unless dead.
2. Tiny Aside: open review → `자세히: RateLimiter` → hold `BEGIN IMMEDIATE` → click `무효화` → expect visible busy, no silent success → release lock → one retry succeeds.
3. F1-UI partial-failure banner, then stop. Do not start cleanup in the same turn.
