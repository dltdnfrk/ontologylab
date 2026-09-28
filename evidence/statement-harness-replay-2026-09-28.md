# Statement-harness plumbing replay

**Development-only.** development-only plumbing replay; scripted slot engine; not an accuracy claim.

Copied `/private/tmp/ol-polarity6-20260927T125639Z-r{1,2,3}` to `/private/tmp/eh-replay-r{1,2,3}` and ran `scripts/statement_harness_replay.py` on each copy's `kg.sqlite`. The original stores were not opened for write; their file hashes were unchanged after the runs.

The engine answers only when a unit has exactly one explicit arm slot and one explicit result slot, and builds that reply from those slots' exact quotes. Every other unit is an abstention. No model or network call. This is not an accuracy claim.

| run | documents | status | calls | receipts | harness edges written | harness edges verified |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| r1 | 5 | complete | 709 | 27 | 26 | 0 |
| r2 | 5 | complete | 709 | 27 | 26 | 0 |
| r3 | 5 | complete | 709 | 27 | 26 | 0 |

Each copy holds the same five documents (PMC11298438, PMC12546283, PMC12563837, PMC12632097, PMC12713700). Rejection reasons: none. Unprocessed units: none. Hash keys: rules, cue, prompt, schema, qualifier, normalization, completion.

27 receipts wrote 26 proposed edges because one triple was cited twice. No harness edge is verified. Verified edges in each copy remain 0.
