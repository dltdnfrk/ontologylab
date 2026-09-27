# Extraction transport retries

`ApiEngine.generate` still issues exactly one request. It classifies
`RemoteDisconnected`, connection reset/abort, socket timeout/`TimeoutError`
(including a `URLError.reason` of those types), and HTTP 429/500/502/503/504
as `TransientEngineError`. Other failures are not transport-retried.
Malformed model output retains the existing single JSON-parse retry.

The extraction loop owns retries so every attempt, including a failed one,
passes the same `Caps` check and `Provenance.track_engine_call` boundary.
There are at most two transport retries **per chunk**, shared across the
initial response and its JSON retry. Configure this through the existing
extraction limits: CLI `extract --max-transport-retries N`, HTTP
`POST /api/extract` field `max_transport_retries`, or the shared job function
and `Caps.config.max_transport_retries`. CLI/HTTP accept 0-100; zero disables
transport retries. Research callers of the shared loop inherit the default.

Waits are 1, 2, 4, 8 seconds, capped at 8. A valid `Retry-After` delta or
HTTP date can increase the wait, also capped at 8. Invalid values fall back
to exponential backoff. The date clock and async sleeper are injectable.
Request/time caps and cancellation are checked before waiting and again
before the next attempt. A spent cap fails the current chunk as before;
successful recovery leaves it succeeded.

Retries consume the existing request reserve, never additional spend.
For the frozen 21-chunk, 60-request run, 21 initial requests plus 21 JSON
retries leave 18 slots for transport recovery. More failures can exhaust
the cap; completing every chunk in that worst case is not promised.
Automatic wall time uses `min((2 + N) * chunks, max_engine_calls)` request
slots (uncapped when the request cap is zero), each with the configured
request timeout, 10% local-work allowance, and an 8-second backoff allowance.
An explicit wall limit is never increased.

The retry event records document/chunk identity, retry ordinal, and delay.
Errors retain only provider identity, status or exception class. Neither
credentials, raw exception details, nor request bodies enter retry logs.
