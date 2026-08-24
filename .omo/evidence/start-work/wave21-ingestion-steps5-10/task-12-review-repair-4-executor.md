# DoneClaim — Task 12 review repair round 4

Executor: omo senpi-task child `st_01a0323f`
Date: 2026-08-24
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit/push)
Authority: `task-12-review-repair-3-security.md` residual packed-row
deletion (citation / document) after hash rematerialize.

## Verdict

DONE. A hash-refreshed pack that drops a citation, document, review,
run, chunk, policy, or evidence member — or that claims a dangling
closure ID — is refused as typed `invalid_manifest` on `verify_pack`,
verifier CLI, `list_packs`, `activate_pack`, and MCP load/resource
before serve. Honest combined extra-run + unpublished-doc packs, v1,
and unreviewed v2 still verify. Prior loaded session survives a
sibling incomplete pack. Nine named mutants died and restored.

## Design

New read-only `ontologylab/pack_v2_validate.py` exposes
`validate_packed_v2_closure(pack_dir, conn, manifest)`. The standalone
verifier calls it after artifact/sqlite hash, count, and capability
checks and before returning success.

The seam:

- runs only when the pack claims reviewed/sourced labels or a v2
  `evidence_mode`+`closure` (inventory-only fixtures stay valid)
- requires `PRAGMA foreign_key_check` clean
- uses `resolve_v2_closure` so manifest families equal packed
  SQL/evidence IDs and required families are nonempty (counts unused)
- re-derives citation, review, source-document/work, run/chunk,
  policy, and evidence-path completeness from packed bytes

Raises `PackedV2ClosureRefused`; the verifier converts to
`PackVerifyRefused(INVALID_MANIFEST, member)` in-module so
`python -m ontologylab.pack_verifier` cannot dual-import the
exception. CLI stays typed JSON, exit 2, no traceback.

## Changed hashes

| Path | SHA-256 |
| --- | --- |
| `ontologylab/pack_v2_validate.py` | `d6e83fdda3eff5b58e433a6d6d0c840e80ac5efe1f6ca22aec344ac8ca587dcd` |
| `ontologylab/pack_verifier.py` | `ac2d55740ea1e7e6df4aaa2155ad8ca331f3b6447d86015a0bddc9e9bbf6907c` |
| `tests/test_pack_v2_review_repair.py` | `0b6371c91c5a35679d58439762ee174cddb06441ec6a32e206c1fc43fd871df4` |

Frozen Round-3 production (not required this round):

| Path | SHA-256 |
| --- | --- |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |
| `ontologylab/pack_v2_derive.py` | `7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577` |
| `ontologylab/pack_source_fingerprint.py` | `a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7` |

Pure LOC: validate 175 (healthy). Verifier remains SIZE_OK. Closure
untouched. No commit.

## RED (lead, before this production)

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py \
  -k 'deleted_packed or deleted_required or dangling_packed or missing_required_evidence or prior_loaded_session' \
  --override-ini addopts= -v --tb=line
13 failed
EXIT:1
```

Named reason for every incomplete-closure case: `DID NOT RAISE
PackVerifyRefused` after hashes + closure/count rewrite. Positive
combined / unreviewed / v1 already passed.

## GREEN

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py --override-ini addopts= -q
35 passed in 4.01s
```

Focused Task 12 + prior 10-file set (now 170):

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py \
  tests/test_pack_v2_closure.py tests/test_pack_v2_verifier.py \
  tests/test_pack_v2_publication_surface.py tests/test_pack_readiness_refusal.py \
  tests/test_verified_pack_reader.py tests/test_mcp_pack_integrity.py \
  tests/test_packdiff.py tests/test_ontology_pack_publication.py \
  tests/test_staleness.py --override-ini addopts= -q
170 passed, 1 warning in 10.11s
EXIT:0
```

Affected + methodology 15-file set:

```
139 passed, 1 warning in 7.10s
EXIT:0
```

basedpyright on validate/verifier/repair tests: 0/0/0.
`python3.11 -m py_compile` on changed production: EXIT 0.
LSP clean. no-excuse: 0 violations.

## Mutation (kill then gold restore)

Gold `/tmp/t12r4-gold`. Restores from those copies; post-restore SHA
matches gold
`d6e83fdda3eff5b58e433a6d6d0c840e80ac5efe1f6ca22aec344ac8ca587dcd` /
`ac2d55740ea1e7e6df4aaa2155ad8ca331f3b6447d86015a0bddc9e9bbf6907c`.

| Mutant | File | Named test | Failure | Mutant SHA-256 | Restored |
| --- | --- | --- | --- | --- | --- |
| validator call skipped | `pack_verifier.py` | `test_deleted_packed_citation_*` | DID NOT RAISE | `ebcc30bfcb42db17709bd3cad5a067e01c5743114e963c24791b0cd595d24960` | yes |
| manifest-vs-SQL equality bypass | `pack_v2_validate.py` | `test_dangling_*[citation]` | DID NOT RAISE | `fc96224445e57528cc5b560530b5ef6702a707a742b3b869bd9c76fd868781e9` | yes |
| FK check bypass | `pack_v2_validate.py` | `test_foreign_key_orphan_*` | DID NOT RAISE | `7a8fee4319c033794b810853ccec57e763257b0965fc72f9264e387f30a8bea6` | yes |
| citation gap bypass | `pack_v2_validate.py` | `test_deleted_packed_citation_*` | DID NOT RAISE | `524979eba6502c738e050f19295327eb3d23b1c893fd4a07bad74659f049bcc1` | yes |
| review gap bypass | `pack_v2_validate.py` | `test_deleted_required_review_*` | DID NOT RAISE | `ff0b67e65d979464b170f1d4dc609300a6acb50654d41bab0b6e94f195e9b7cd` | yes |
| source document gap bypass | `pack_v2_validate.py` | `test_document_missing_work_*` | DID NOT RAISE | `c7c77ddf8ba6c4c5866e086b8a8a29a773aab13169005271341a18842b3c45c9` | yes |
| run/chunk dependency bypass | `pack_v2_validate.py` | `test_deleted_required_run_*` | DID NOT RAISE | `c319eab7e65c1c1e9a421b48b9ef8714d582ed142d6d3d92566c7dc5e3b5c01d` | yes |
| policy gap bypass | `pack_v2_validate.py` | `test_deleted_required_policy_*` | DID NOT RAISE | `2a813f6be0c925869f2b8d26a8c32c20e15a7dcb2cb9652c368dc11c33c42e1d` | yes |
| evidence gap bypass | `pack_v2_validate.py` | `test_missing_required_evidence_*` | DID NOT RAISE | `dee4942d5804075b49f4e766077e7ef2f3173f46bcc2b92338fb998f985a7771` | yes |

## Manual QA (`t12r4-qa-*`, removed)

Authorized live extra run + unpublished document → packs
`qa-honest-*`, `qa-sib-cite-*`, `qa-sib-doc-*`, plus
`pack_readiness --publish` `qa-ready-*`:

- capabilities include `reviewed` + `sourced-answer-v2`
- extra run/doc absent from packed sqlite
- readiness EXIT 0; standalone verifier EXIT 0
- `list_packs` / `activate_pack` reviewed
- stdio MCP `initialize.protocolVersion=2025-06-18`; lookup hits
  PaymentGateway; MCP rc=0
- citation sibling: `invalid_manifest:citation`; CLI
  `{"ok":false,"code":"invalid_manifest","path":"citation"}`; no
  traceback; list omits it; activate refuses
- document sibling: `invalid_manifest:foreign_keys`; same surfaces
- `load_pack(sibling)` refuses; prior honest lookup held
- root removed

`QA_STATUS=0` `QA_CLEANED=True`

## Architectural self-review

1. Single responsibility: packed v2 closure completeness.
2. Boundary: untrusted manifest already parsed; closure re-read via
   `resolve_v2_closure`; SQL re-derived, counts unused.
3. EvidenceMode matched with `assert_never`.
4. No Any / ignore / unwrap.
5. Early return only when the pack does not claim a v2 closure.
6. No one-off helpers beyond the shared `_refuse_if`.
7. Tests fail if the validator call is skipped.
8. Public seam has 3 parameters (`pack_dir`, `conn`, `manifest`).
9. No post-delete verification.
10. Positive names (`_claims_v2_closure`).
11. No new logging.

## Protected

- HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`
- pack_verifier inode `274739540`; new validate inode `278314796`;
  closure inode `274892112` unchanged
- PID 55560 still `127.0.0.1:8799` inode `0x1ff51c806b197195`
- Application Support mtime still `2026-07-31 17:49:12`
- no Application Support / network / commit / push / full suite

DONE
