# BYOK backend: OpenRouter OAuth connect + Keychain provider keys

Base: `4fd2091` + the frontend-recovery changes (uncommitted). This adds the
BYOK backend the user asked for after the frontend work completed.

## What was found

- OAuth connect exists for exactly one provider: **OpenRouter**, via its
  documented PKCE flow (no client_id registration). gptme, aider, goose,
  opencode, and others all implement the same flow.
- Anthropic and OpenAI do not offer third-party OAuth for API keys —
  Anthropic actively blocks it, OpenAI's Codex OAuth is subscription-bound.
  The standard pattern for them is key paste → secure store.
- The codebase already had the secure store: `keychain.py` (signed Swift
  helper, write-verified, never echoes) used by publisher sources.

## What was built

- `ontologylab/oauth_connect.py` — PKCE generation, pending-flow store
  (single-use state, 10-min TTL, bounded count), code→key exchange through
  the hardened `paper_api.urlopen` (no cross-origin redirects). The key is
  never in a response, log, or redirect.
- `ontologylab/server/oauth_routes.py` — `POST /api/providers/openrouter/connect`
  (session-authed, returns the auth URL) and `GET /oauth/openrouter/callback`
  (outside `/api/*` because the samesite=strict cookie is not sent on the
  cross-site navigation back; guarded by the single-use `state` instead).
  Both answer with 303 redirects carrying a typed code, never a message.
- `providers.py` — `Provider.keychain_account`, `resolve_api_key` now reads
  Keychain first then env (`resolve_key` order), `api_key_present` passive
  check for listings, `forget_api_key`, `canonical_keychain_account`.
- `routes.py` — `ProviderCreate.key` write-only field (same no-echo contract
  as `SourceCreate.key`), `DELETE /providers/{id}/key`, `key_retained` on
  provider delete, `key_location` in the public model.
- `Engines.tsx` — "OpenRouter 연결" button (redirects to the auth URL),
  `?connected=`/`?connect_error=` handling on /engines, optional API-key
  password field in the add dialog, "키 삭제" for Keychain-stored providers.
- Shipped bundle rebuilt: `assets/index-Bw9snlwz.js` (645856 bytes,
  sha256 419e8ac3…), manifest regenerated via `web_assets write-manifest`,
  `web_assets check` passes, asset pins updated.

## Verification

- `tests/test_provider_oauth.py` — 26 cases: PKCE correctness, single-use
  state, TTL expiry, exchange posts code+verifier, error never quotes the
  code, offline-mode block, callback needs no session cookie, bad/replayed
  state redirects typed errors, real-Keychain store round-trip, key never
  echoed on failure, forget-key clears the locator.
- Related suites: 158 passed (dashboard assets/routes/wheel, providers,
  provider security, sources routes/registry, server, security hardening,
  frontend provider security, keychain helper).
- Live smoke on 127.0.0.1:18899: `/` → session cookie → connect →
  `https://openrouter.ai/auth?callback_url=http://127.0.0.1:18899/oauth/…`;
  callback with bad state → `303 /engines?connect_error=state` (not 401).
- `test_frontend_provider_security.py` rewritten for the React source:
  password-type key input, key never rendered, sent exactly once, cleared
  on reset, connect uses redirect not key entry.

## Not done / boundaries

- No git commit (not authorized).
- Anthropic/OpenAI direct keys still use paste→Keychain or env var; there is
  no OAuth for them because the providers do not offer one.
- The OpenRouter flow was exercised up to the exchange boundary with a
  stubbed token endpoint; a real end-to-end browser consent was not run
  (requires a human's OpenRouter login).
