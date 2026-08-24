# Task 12 repair-4 security recheck — packed-closure validator

Date: 2026-08-24
Rechecker: omo senpi-task `st_01a031f0`
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit)
Claim: `task-12-review-repair-4-executor.md` (hashes treated as claims; surfaces re-measured)
Prior receipts preserved:
- `task-12-review-security.md` `44c8199d…e22a70f`
- `task-12-review-repair-security.md` `9c289c27…f1cef1`
- `task-12-review-repair-2-security.md` `85bfe07b…d234dc`
- `task-12-review-repair-3-security.md` `b2965a54…9e55c`
Constraint: product/test read-only; artifact tampers only in disposable roots; no Application Support, network, 8799, PID 55560, full suite, authority, or plan edits.

## Verdict

**NEEDS-FIX** — maximum severity **MEDIUM**.

Round-3 packed-row deletion is closed **while the pack still claims reviewed/sourced or keeps `evidence_mode`+`closure`**. Citation / document+evidence / review / run / chunk / policy deletion, FK-off parent delete, dangling closure IDs, and source_doc/work/policy mismatch all refuse typed `invalid_manifest` on `verify_pack`, verifier CLI (JSON, exit 2, no traceback, no `PackedV2ClosureRefused` leak), `list_packs`, `activate_pack`, and MCP load/resource. Honest combined-witness, unreviewed v2, and v1 still verify. Prior session holds.

The validator is skipped when the pack is neither reviewed/sourced **nor** carrying both `evidence_mode` and `closure`. After deleting a citation, rematerializing hashes/counts/closure, stripping C-036, dropping those two keys, and claiming only `UNREVIEWED_CAPABILITIES`, `verify_pack` returns **ok** with `integrity_level=evidence-self-contained-v2` and two citations against three verified facts. That is an evidence-closure bypass of the new seam: an internally incomplete pack still advertises evidence-self-contained. Reviewed/sourced cannot be kept on that path (capability re-derive refuses). v1 disguise of the same mutilation becomes `legacy-graph-only` (no v2 evidence claim).

## Bound freeze (entry = exit)

Working-tree SHA-256 MATCH the repair-4 executor table (rehashed after probes; no product/test write):

| Path | SHA-256 |
|---|---|
| `ontologylab/pack_v2_validate.py` | `d6e83fdda3eff5b58e433a6d6d0c840e80ac5efe1f6ca22aec344ac8ca587dcd` |
| `ontologylab/pack_verifier.py` | `ac2d55740ea1e7e6df4aaa2155ad8ca331f3b6447d86015a0bddc9e9bbf6907c` |
| `tests/test_pack_v2_review_repair.py` | `0b6371c91c5a35679d58439762ee174cddb06441ec6a32e206c1fc43fd871df4` |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |

HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`.

## Independent probes

Disposable `/private/tmp/ontologylab-wave21-t12-r4sec` (deleted). Library + `python -m ontologylab.pack_verifier`. MCP via `PackSession`. Full rematerialize = `_rewrite_closure_and_counts` + inventory hash refresh.

### Positive

| Pack | Result |
|---|---|
| combined extra-run + unpublished-doc, reviewed+sourced | verify/CLI/list/activate/load ok; extras absent from sqlite |
| honest unreviewed v2 | verify ok; no reviewed/sourced |
| `_write_v1` | `legacy-graph-only` |
| inventory-only `_write_v2` | verify ok, `evidence-self-contained-v2` (no `evidence_mode`/`closure`; skip is intentional for this fixture class) |

### Prior mutilations (keep v2 closure keys) — all HOLD

| ID | Tamper + rematerialize | verify / CLI |
|---|---|---|
| H-DEL-CITE | delete one citation | `invalid_manifest:citation` |
| H-DEL-DOCS-EV | delete all documents + `evidence/` | `invalid_manifest:capabilities` |
| H-DEL-REVIEW | delete reviews | `invalid_manifest:capabilities` |
| H-DEL-RUN | delete runs (FK off) | `invalid_manifest:capabilities` |
| H-DEL-CHUNK | delete chunks (FK off) | `invalid_manifest:capabilities` |
| H-DEL-POLICY | delete policies | `invalid_manifest:capabilities` |
| H-FK-PARENT | delete `works` (FK off) | `invalid_manifest:foreign_keys` |
| H-DANGLING | add `cite-ghost` to manifest closure | `invalid_manifest:citation` |
| H-MISMATCH-WORK | `documents.work_id='work-missing'` | `invalid_manifest:representation` |
| H-MISMATCH-SRCDOC | verified `source_doc_id='doc-missing'` | `invalid_manifest:foreign_keys` |
| H-MISMATCH-POLICY | policy selected rep missing | `invalid_manifest:capabilities` |

CLI: `{"ok":false,"code":"invalid_manifest","path":…}`, stderr empty. List omits the pack. Activate/MCP `PackIntegrityError` before serve.

### Validator-skip / disguise

| ID | Attack | Result |
|---|---|---|
| H-SKIP-OMIT-KEEP-REVIEWED | drop `evidence_mode`+`closure`, keep reviewed | **HOLD** `invalid_manifest:closure` (reviewed still forces validate) |
| H-SKIP-MALFORMED | `closure` is a string | **HOLD** `invalid_manifest:closure` |
| H-V1-DISGUISE | rewrite manifest as v1 + sqlite `content_hash` | **HOLD** as honesty: verifies `legacy-graph-only`; caps `knowledge-graph-v1`; no reviewed / evidence-self-contained |
| H-SKIP-UNREV-KEEP-EV | delete one cite; rematerialize; delete C-036; drop `evidence_mode`+`closure`; claim `UNREVIEWED_CAPABILITIES` | **CONFIRMED MEDIUM.** verify ok; CLI 0; list/activate/MCP serve; `integrity_level=evidence-self-contained-v2`; counts `citations=2` vs `nodes_verified=2`+`edges_verified=1` |
| H-CAP-FORGE-* | add reviewed/sourced on honest unreviewed | **HOLD** `invalid_manifest:capabilities` |
| H-PRIOR-SESSION | load honest; activate citation-mutilated sibling | **HOLD** sibling refused; prior lookup still 1 match |

Cause on committed repair bytes: `_validate` returns immediately when `reviewed` is false and `_claims_v2_closure` is false (`evidence_mode` and `closure` both required). Capability re-derive then accepts unreviewed labels whenever C-036 is gone and `evidence/` still exists. The new completeness SQL never runs. Same shape as the inventory-only `_write_v2` fixture, but here the sqlite is a **real** mutilated v2 graph.

Do not “fix” by trusting `integrity_level` from claimed caps after skip. If `evidence-self-contained-v2` is advertised, run `validate_packed_v2_closure` (or refuse the capability when `evidence_mode`/`closure` are absent). Inventory-only fixtures must stop claiming that string or grow a real closure.

## Remaining internally incomplete advertisement

- **Reviewed / sourced:** not observed after rematerialized mutilation.
- **evidence-self-contained-v2:** observed on H-SKIP-UNREV-KEEP-EV (mutilated real pack) and on synthetic `_write_v2` (fixture class). The first is the blocker.

## Focused corroboration (once; not the suite)

```
.venv/bin/python -m pytest \
  tests/test_pack_v2_review_repair.py::test_deleted_packed_citation_is_refused_after_rehash \
  tests/test_pack_v2_review_repair.py::test_deleted_packed_document_is_refused_after_rehash \
  tests/test_pack_v2_review_repair.py::test_foreign_key_orphan_is_refused_after_rehash \
  tests/test_pack_v2_review_repair.py::test_prior_loaded_session_survives_sibling_incomplete_pack \
  tests/test_pack_v2_review_repair.py::test_v1_pack_still_verifies \
  --override-ini addopts= -q --tb=line
```

`5 passed in 0.95s` EXIT 0. Those tests never strip `evidence_mode`/`closure` after a cite delete, so they stay green while H-SKIP-UNREV-KEEP-EV holds.

## Protected-boundary cleanup

- No read/write of `~/Library/Application Support/ontologylab/` contents. Directory mtime still `2026-07-31 17:49:12`.
- No external network.
- Port 8799 / PID 55560 observe-only: DEVICE `0x1ff51c806b197195`, still `127.0.0.1:8799`.
- Disposable probe root removed. No leftover listeners.
- Product/test bytes MATCH entry freeze. Prior security receipts not rewritten.
- No commit/push. This file is the only durable write.

## Stop

Strict verdict: **NEEDS-FIX**. Maximum severity: **MEDIUM**.
