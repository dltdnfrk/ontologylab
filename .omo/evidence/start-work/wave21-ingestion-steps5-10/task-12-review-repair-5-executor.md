# DoneClaim — Task 12 review repair round 5

Executor: omo senpi-task child `st_01a03261`
Date: 2026-08-24
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit/push)
Authority: `task-12-review-repair-4-security.md` and
`task-12-review-repair-4-security-bypass-qa.md` (H-SKIP-UNREV-KEEP-EV).

## Verdict

DONE. A reviewed+sourced v2 pack that deletes one citation, drops
C-036, strips manifest `evidence_mode`+`closure`, keeps
`knowledge-graph-v2`+`evidence-self-contained-v2`, rewrites counts to
the remaining SQL, and rematerializes hashes is refused as typed
`invalid_manifest` on `verify_pack`, verifier CLI (JSON, exit 2, no
traceback), `list_packs`, `activate_pack`, and real stdio MCP
`load_pack` before any session switch. The prior honest combined
session holds. Three named mutants died and restored. Inventory-only
`_write_v2`, honest unreviewed v2, v1, and all Round 1–4 surfaces
stay green. 15 MCP tools unchanged.

## Design

`ontologylab/pack_v2_validate.py` `_validate` now requires a complete
typed v2 contract when any of:

- the pack claims `reviewed` / `sourced-answer-v2` (existing)
- the pack claims both `evidence_mode` and `closure` (existing)
- the pack advertises `evidence-self-contained-v2` **and** the sqlite
  is a real packed v2 graph (receipt tables or `nodes.status`)

Missing or malformed contract keys refuse `closure` before serve.
Capability advertisement can never skip the validator on a real
graph. Synthetic inventory-only `_write_v2` fixtures have neither
receipt tables nor `nodes.status`, so they remain allowed. v1 is
untouched. `pack_verifier.py` bytes unchanged.

## Changed hashes

| Path | SHA-256 |
| --- | --- |
| `ontologylab/pack_v2_validate.py` | `ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6` |
| `tests/test_pack_v2_review_repair.py` | `483ce682f024d7462503c530d45c4bcd536750582a055f9c49952a9c93383015` |

Unchanged this round (frozen Round-4 bytes):

| Path | SHA-256 |
| --- | --- |
| `ontologylab/pack_verifier.py` | `ac2d55740ea1e7e6df4aaa2155ad8ca331f3b6447d86015a0bddc9e9bbf6907c` |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |

Pure LOC: validate 217 (warning band; next edit should split gating
from SQL completeness). Verifier untouched. Test file SIZE_OK. No
commit.

## RED (lead, before this production)

```
.venv/bin/python -m pytest \
  tests/test_pack_v2_review_repair.py::test_stripped_closure_advertising_evidence_capability_is_refused \
  --override-ini addopts= -v --tb=short
FAILED  DID NOT RAISE PackVerifyRefused
EXIT:1
```

Named reason: the frozen H-SKIP-UNREV-KEEP-EV pack still verified
after hash rematerialize.

## GREEN

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py --override-ini addopts= -q
38 passed in 4.34s
```

Focused Task 12 + prior 10-file set (once on final bytes):

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py \
  tests/test_pack_v2_closure.py tests/test_pack_v2_verifier.py \
  tests/test_pack_v2_publication_surface.py tests/test_pack_readiness_refusal.py \
  tests/test_verified_pack_reader.py tests/test_mcp_pack_integrity.py \
  tests/test_packdiff.py tests/test_ontology_pack_publication.py \
  tests/test_staleness.py --override-ini addopts= -q
171 passed, 1 warning in 12.78s
EXIT:0
```

Affected + methodology 15-file set (once on final bytes):

```
139 passed, 1 warning in 8.84s
EXIT:0
```

basedpyright on validate/verifier/repair tests: 0/0/0.
`python3.11 -m py_compile` on changed production: EXIT 0.
LSP clean. no-excuse: 0 violations.

## Mutation (kill then gold restore)

Gold `/tmp/t12r5-gold`. Restores from those copies; post-restore SHA
matches gold
`ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6` /
`ac2d55740ea1e7e6df4aaa2155ad8ca331f3b6447d86015a0bddc9e9bbf6907c`.

| Mutant | File | Named test | Failure | Mutant SHA-256 | Restored |
| --- | --- | --- | --- | --- | --- |
| evidence capability ignored | `pack_v2_validate.py` | `test_stripped_closure_advertising_evidence_capability_is_refused` | DID NOT RAISE | `ba3d58717640d3bb07010c8d9ac19a4b43389aa86fb46e6f77796e9ee11f19bf` | yes |
| missing closure keys accepted | `pack_v2_validate.py` | same | DID NOT RAISE | `8681aec5092818a7b95c526e122abddda74e33df964230ad3a38c2117d87c0ca` | yes |
| validator call skipped after capability recognized | `pack_verifier.py` | same (+ `test_deleted_packed_citation_*`) | DID NOT RAISE | `58160b3d4d5b73b27c982a1dbcbd9a1285e1b2998d60c9e69c660c2bc2240de0` | yes |

## Manual QA (`ontologylab-t12r5-qa-*`, removed)

Authorized live extra run + unpublished document → packs
`honest-20260824-151949` and `bypass-20260824-151949`. Bypass applied
the exact frozen recipe (delete one citation, drop C-036, pop
`evidence_mode`+`closure`, keep unreviewed evidence caps, rewrite
counts `citations=2` vs `nodes_verified=2`, rematerialize hashes).

- honest: reviewed+sourced; standalone verifier EXIT 0;
  `integrity_level=evidence-self-contained-v2`
- bypass verify: `invalid_manifest:closure`
- CLI: EXIT 2 `{"code":"invalid_manifest","ok":false,"path":"closure"}`;
  stderr empty (no traceback)
- `list_packs` ids: only honest
- `activate_pack` honest ok; bypass `PackIntegrityError`
- stdio MCP `initialize.protocolVersion=2025-06-18`; 15 tools;
  `entity_lookup PaymentGateway` on honest; `load_pack bypass`
  `isError=true`; subsequent lookup still honest; MCP rc=0
- root removed; no leftover MCP

`QA_STATUS=0` `QA_CLEANED=True`

## Architectural self-review

1. Single responsibility: packed v2 closure completeness gating.
2. Boundary: untrusted manifest parsed into a typed contract
   (`pack_schema_version==2`, `evidence_mode` in EvidenceMode,
   closure exact `CLOSURE_MEMBERS` string lists) before SQL.
3. EvidenceMode membership is a set check; later evidence paths still
   `match` + `assert_never`.
4. No Any / ignore / unwrap.
5. Early return only for inventory-only fixtures that do not
   advertise a real packed v2 graph.
6. `_packed_v2_graph_present` and `_typed_v2_contract_complete` each
   have two callers conceptually (gate + mutants); not one-off noise.
7. Named bypass test fails if capability is ignored, missing keys are
   accepted, or the validator call is skipped.
8. Public seam still 3 parameters.
9. No post-delete verification.
10. Positive names (`_typed_v2_contract_complete`,
    `_packed_v2_graph_present`).
11. No new logging.

## Protected

- HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`
- pack_verifier inode `274739540` (bytes unchanged); validate inode
  `278314796`; closure inode unchanged
- PID 55560 still `127.0.0.1:8799` device `0x1ff51c806b197195`
- Application Support ino `102434596` mtime_ns
  `1785487752937707432` size `192`
- no Application Support / network / commit / push / full suite
- prior security receipts not rewritten

DONE
