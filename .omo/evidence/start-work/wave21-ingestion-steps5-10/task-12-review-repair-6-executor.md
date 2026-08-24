# DoneClaim — Task 12 review repair round 6

Executor: omo senpi-task child `st_01a0327c`
Date: 2026-08-24
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit/push)
Authority: `task-12-review-final-security.md` MEDIUM v1-disguise
authority bypass; `task-12-review-final-code.md` v1 gating residual.

## Verdict

DONE. A published reviewed+sourced v2 pack rewritten as a four-field
v1 manifest (`pack_id`, `pack_schema_version=1` or omitted,
`content_hash` of `pack.sqlite`, raw `reviewed` /
`sourced-answer-v2` / `evidence-self-contained-v2` /
`knowledge-graph-v2`) is refused as typed `invalid_manifest:capabilities`
on `verify_pack`, verifier CLI (JSON, exit 2, no traceback),
`list_packs`, `activate_pack`, and real stdio MCP `load_pack` before
any session switch. Dropping packed C-036 and refreshing only
`content_hash` is the same refusal. The prior honest combined session
holds. Five named mutants died and restored. Legitimate builder v1,
historical no-capability v1, methodology-v1, tree/no-tree/writable/
extra-file, synthetic `_write_v2`, and all Round 1–5 surfaces stay
green. 15 MCP tools unchanged.

## Design

`_parse_v1` is now the v1 trust boundary. It refuses every v2-only
manifest contract field (`artifact_inventory`, `pack_content_hash`,
`sqlite_hash`, `integrity_model`, `evidence_mode`, `closure`, receipt/
fingerprint witness claims) and accepts capabilities only when absent
or exactly `()`, `("knowledge-graph-v1",)`, or
`("knowledge-graph-v1", "methodology-v1")`. Unknown strings,
duplicates, invalid order/shape, `methodology-v1` without
`knowledge-graph-v1`, and every v2-only capability die at parse —
before `_verify_v1` or any reader sees raw JSON. `list_packs` /
`activate_pack` / MCP still return the raw manifest after verify;
parser rejection makes arbitrary strings unlistable. A graph-only v1
with only legitimate v1 claims may still verify even if sqlite is
modern. `verified_pack_reader.py` and `packbuilder.py` were not
required.

## Changed hashes

| Path | SHA-256 |
| --- | --- |
| `ontologylab/pack_verifier.py` | `2b64a110fa3789de3a53245e950f73cb8dccc9bdb78025394fbe3316b55130ed` |
| `tests/test_pack_v2_review_repair.py` | `622c7602c2f961c4dca98711d409c87123c257227d0610046e6e11a2ba417b76` |
| `tests/test_pack_v2_verifier.py` | `78ae23f199897c87841a9dc908bcd168dbfc93162ee4beaa1735a045b80c8ce5` |

Unchanged this round (frozen R5 bytes):

| Path | SHA-256 |
| --- | --- |
| `ontologylab/pack_v2_validate.py` | `ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6` |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |
| `ontologylab/verified_pack_reader.py` | `6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1` |

Pure LOC: verifier 460 (SIZE_OK, parse/inventory/CLI stay in this
module). Repair tests 1329 SIZE_OK. Verifier tests 564 SIZE_OK.
No commit.

## RED (lead, before this production)

```
.venv/bin/python -m pytest \
  tests/test_pack_v2_verifier.py::test_parse_v1_rejects_capability_outside_allowlist \
  tests/test_pack_v2_verifier.py::test_parse_v1_rejects_v2_contract_field \
  tests/test_pack_v2_verifier.py::test_parse_v1_omitted_schema_rejects_v2_capabilities \
  tests/test_pack_v2_verifier.py::test_legacy_v1_unknown_capability_is_refused \
  tests/test_pack_v2_verifier.py::test_legacy_v1_reviewed_capability_is_refused \
  tests/test_pack_v2_verifier.py::test_legacy_v1_v2_contract_field_is_refused \
  tests/test_pack_v2_review_repair.py::test_reviewed_v2_disguised_as_v1_is_refused_before_session_switch \
  --override-ini addopts= -v --tb=line
31 failed in 1.11s
EXIT:1
```

Named reason: `_parse_v1` ignored capabilities and v2 contract fields,
so `verify_pack` did not raise `PackVerifyRefused`.

## GREEN

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py --override-ini addopts= -q
41 passed in 5.27s
```

Focused Task 12 + prior 10-file set (once on final bytes):

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py \
  tests/test_pack_v2_closure.py tests/test_pack_v2_verifier.py \
  tests/test_pack_v2_publication_surface.py tests/test_pack_readiness_refusal.py \
  tests/test_verified_pack_reader.py tests/test_mcp_pack_integrity.py \
  tests/test_packdiff.py tests/test_ontology_pack_publication.py \
  tests/test_staleness.py --override-ini addopts= -q
209 passed, 1 warning in 11.70s
EXIT:0
```

Affected + methodology 15-file set (once on final bytes):

```
139 passed, 1 warning in 7.75s
EXIT:0
```

basedpyright on verifier + both test files: 0/0/0.
`python3.11 -m py_compile` on changed production: EXIT 0.
LSP clean. no-excuse: 0 violations.

## Mutation (kill then gold restore)

Gold `/tmp/t12r6-gold`. Restores from those copies; post-restore SHA
matches gold
`2b64a110fa3789de3a53245e950f73cb8dccc9bdb78025394fbe3316b55130ed`.

| Mutant | File | Named test | Failure | Mutant SHA-256 | Restored |
| --- | --- | --- | --- | --- | --- |
| unknown cap accepted | `pack_verifier.py` | `test_parse_v1_rejects_capability_outside_allowlist[unknown]` | DID NOT RAISE | `f1ade2508e9da7af59e4ef5b59734422ecc98c55410fc89337babee51d673339` | yes |
| reviewed accepted | `pack_verifier.py` | `test_parse_v1_rejects_capability_outside_allowlist[reviewed]` | DID NOT RAISE | `911756cf6ddef8c321cede8c37bff8d1283252d27036444f80ad6760af3f2b06` | yes |
| v2 field accepted | `pack_verifier.py` | `test_legacy_v1_v2_contract_field_is_refused` | DID NOT RAISE | `b590369c8911c09610579de8e0d3fe85cb7aeb7d589f639e60224d647d3a3393` | yes |
| omitted-schema bypass | `pack_verifier.py` | `test_parse_v1_omitted_schema_rejects_v2_capabilities` | DID NOT RAISE | `990119ebfd41d88d74e3d3049cda9f5ea253e8e8b78f6e994b549c2344ccba0c` | yes |
| parser validation skipped before v1 verify/serve | `pack_verifier.py` | `test_legacy_v1_reviewed_capability_is_refused` | DID NOT RAISE | `8930a5d2352158317ca34f75ae79e2492fc56ba73200c4ffca1674ae79260335` | yes |

## Manual QA (`ontologylab-t12r6-qa-*`, removed)

Authorized live extra run + unpublished document → honest reviewed v2
plus two siblings disguised with the exact four-field recipe
(explicit `pack_schema_version=1` and omitted schema; raw v2/reviewed/
sourced caps; legacy `content_hash` of unchanged `pack.sqlite`).
Honest builder v1 built beside them.

- honest v2: standalone verifier EXIT 0; caps include reviewed+sourced
- honest v1: EXIT 0; listed/activated caps ⊆ `{knowledge-graph-v1, methodology-v1}`
- both disguises: `invalid_manifest:capabilities`; CLI EXIT 2
  `{"code":"invalid_manifest","ok":false,"path":"capabilities"}`;
  stderr empty; not listed; `activate_pack` `PackIntegrityError`
- stdio MCP `initialize.protocolVersion=2025-06-18`; 15 tools;
  `entity_lookup PaymentGateway` on honest; `load_pack` of each
  disguise `isError=true`; subsequent lookup still honest; MCP rc=0
- root and `/tmp/t12r6-qa.py` removed; no leftover MCP

`QA_STATUS=0` `QA_CLEANED=True`

## Architectural self-review

1. Single responsibility: v1 manifest parse contract (capabilities +
   v2-only fields). File still owns parse/inventory/CLI (SIZE_OK).
2. Boundary: untrusted JSON is parsed into `ManifestV1` only after
   the allowlist and v2-field refusal; interior `_verify_v1` never
   re-reads raw capabilities.
3. Schema version still `match` + refuse default. Capability
   membership is a closed frozenset, not `if/elif` on variants.
4. No Any / ignore / unwrap / `as`.
5. `None` capabilities means historical absence, not a defensive
   re-check of a proven value.
6. `_parse_v1_capabilities` and `_refuse_v2_only_fields` are the two
   independently mutated parse decisions, not one-off wrappers.
7. Named tests fail if unknown caps, reviewed, v2 fields, omitted
   schema, or a verify-path parse skip are accepted.
8. Public seams unchanged; new helpers take one parameter.
9. No post-delete verification.
10. Positive names (`_V1_CAPABILITIES`, `_V2_ONLY_FIELDS`).
11. No new logging.

## Protected

- HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`
- pack_verifier inode `274739540`; validate/closure/reader bytes
  MATCH the R5 freeze
- PID 55560 still `127.0.0.1:8799` device `0x1ff51c806b197195`
- Application Support ino `102434596` mtime_ns
  `1785487752937707432` size `192`
- no Application Support / network / commit / push / full suite
- prior security/code/QA receipts not rewritten

DONE
