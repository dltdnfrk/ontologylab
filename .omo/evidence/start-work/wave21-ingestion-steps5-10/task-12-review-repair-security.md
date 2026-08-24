# Task 12 repair security recheck — Wave 2.1 Step 8 R1–R6

Date: 2026-08-24
Rechecker: omo senpi-task `st_01a031f0`
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit)
Claim: `task-12-review-repair-executor.md` (hashes, suites, and mutants treated as claims; surfaces re-measured)
Original review preserved: `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-12-review-security.md` SHA-256 `44c8199d2955ae7eeec2bd56106ca9fc41348dd598602d39d7729bb34e22a70f`
Constraint: product/test read-only; artifact tampers only in disposable roots; no Application Support, network, 8799, PID 55560, full suite, authority, or plan edits.

## Verdict

**PASS**

The original M1 post-publish capability laundering is closed on every named surface. Adding `reviewed` / `sourced-answer-v2` to an unreviewed pack — with payload hashes untouched, and again after recomputing `pack_content_hash` from the unchanged inventory — is `invalid_manifest:capabilities` for `verify_pack`, standalone CLI, `list_packs` (unusable, not advertised), `activate_pack`, MCP `resource_manifest`, and `load_pack`. Labels appear only when packed `c036_capability_receipts` binds the packed ledger generation, `compute_source_fingerprint`, `seal_receipt_inventory` root, `decision=authorize`, and scope ∈ {reviewed, sourced}. Honest unreviewed and reviewed/sourced packs still verify, activate, and serve. Path / symlink / hardlink / raw-text escape / source-reopen / failed-switch-class TOCTOU hold. No capability or count-authorization gap remains.

## Bound freeze (entry = exit)

Working-tree SHA-256 MATCH the repair-executor table (rehashed after probes; no product/test write):

| Path | SHA-256 |
|---|---|
| `ontologylab/pack_v2_derive.py` | `53ff5ac530e2e62a5cf069c4a54eca0332a427a3e2c6f245119c5cd5debe0a55` |
| `ontologylab/pack_v2_manifest.py` | `6e87c1075e327942ce6ef4ab118350345efa675b5045984dda23ef91d8f34675` |
| `ontologylab/pack_v2_closure.py` | `2db1454ae6517d29a038e1c94c6ee47f4f614659e68801f4f9ce90843dd14d55` |
| `ontologylab/pack_verifier.py` | `e9ad5467f6a5cba3d658a21613819fef22b6a1f79d56180f36ceb4395f81cc53` |
| `ontologylab/pack_readiness.py` | `550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21` |
| `ontologylab/mcp_server.py` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` |
| `ontologylab/pack_receipt_seal.py` | `93a51a1e0d32f558da3e6ee4c960e400bd4191849690b57198f2f733dea17751` |
| `ontologylab/packbuilder.py` | `e903936ec8df14e37396d2c3db579713840cd64f82df8aeb83d4e012e81867b7` |
| `ontologylab/packdiff.py` | `cc148c3d4bd444f2f0cae1e4764ed03b28f6194472c5893d22e2edf5addb0292` |
| `ontologylab/verified_pack_reader.py` | `6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1` |
| `tests/test_pack_v2_review_repair.py` | `5594956f904017e4ac1ca50bde019b2632afc157966e6a5db9ed1d8d10662276` |
| `tests/test_pack_v2_closure.py` | `96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff` |
| `tests/test_pack_v2_verifier.py` | `5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b` |
| `tests/test_packdiff.py` | `296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6` |
| `tests/test_pack_v2_publication_surface.py` | `5ae476936ccc00ae2ad2a3c2576513abb1f3946fbd136ae87bb742500dc5d9ba` |
| `tests/test_pack_readiness_refusal.py` | `fc3985fe9d04a31e92d71dbae0cc69d142019d025f498c1e789bfea42868e8e7` |
| `tests/test_verified_pack_reader.py` | `7bdfa1c4a2da2fbb472c77d7e629525762eeaa0cd0509fae0ba614d79e7ec095` |
| `tests/test_mcp_pack_integrity.py` | `25e109033875766b5a24a20b81984e241274341b6eff1b10b204f005e2d7e322` |
| `tests/test_ontology_pack_publication.py` | `cfa25516f0a1fa7aacf03698ad5f5dc29ab9235d736a6b631138f58e8a01f7d2` |

HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`. Repair is uncommitted working-tree only.

## Independent probes

Disposable `/private/tmp/ontologylab-wave21-t12-rsec` (deleted after). Library + installed verifier/readiness CLI. MCP via in-process `PackSession` (no bind). Artifact chmod/edit only under that root.

### Original M1 — forged labels, hashes untouched

Ready unreviewed `evidence_mode=full` pack. `chmod` `manifest.json`, append `reviewed` + `sourced-answer-v2`, restore `0444`. `pack_content_hash` and `sqlite_hash` unchanged.

| Surface | Observed |
|---|---|
| `verify_pack` | `invalid_manifest:capabilities` |
| `python -m ontologylab.pack_verifier` | EXIT 2 `{"ok":false,"code":"invalid_manifest","path":"capabilities"}` |
| `list_packs` | `[]` (unusable; forged labels not advertised) |
| `activate_pack` | `PackIntegrityError` unverifiable / rebuild |
| `resource_manifest` / `load_pack` | same `PackIntegrityError` |

This is the prior review CONFIRMED HIGH/MEDIUM. It does not reproduce as a serve.

### Manifest-only rehash

Same forged capabilities; recompute `pack_content_hash` from canonical inventory. Hash equals the original (capabilities are still outside the inventory digest). All five surfaces refuse identically.

### Packed C-036 / ledger / content-root

On a disposable unreviewed pack, plant `c036_capability_receipts` into `pack.sqlite`, refresh `sqlite_hash` + inventory entry + `pack_content_hash`, set claimed `REVIEWED_CAPABILITIES`:

| Plant | Result |
|---|---|
| matching generation / live packed fingerprint / `seal_receipt_inventory` root / `authorize` / `sourced` | **authorizes**: verify + CLI + list + activate + resource all serve reviewed/sourced |
| root `0*64` | `invalid_manifest:capabilities` on every surface |
| `decision=deny` | `invalid_manifest:capabilities` on every surface |

Authorization is the packed bind, not the unsigned string. Changing sqlite to insert a matching C-036 changes `pack_content_hash` (receipt-not-signature; a new pack, not silent relabel).

### Positive packs

| Pack | Capabilities | verify / activate / load / resource |
|---|---|---|
| unreviewed full | `knowledge-graph-v2`, `evidence-self-contained-v2` only | ok |
| `_reviewed_pack` | those plus `reviewed`, `sourced-answer-v2`; packed C-036 count=1; `derive_capabilities` matches | ok |

### Counts, exclusions, raw text, typed refusal

| ID | Hypothesis | Result |
|---|---|---|
| H-COUNT-FORGE | `counts.nodes_verified=99` verifies | **HOLD.** `forged_counts` |
| H-EXCL-FORGE | zeroed `exclusions` verifies and lists | **RESIDUAL.** verify accepts; listed exclusions all 0. Advisory only; not a capability gate. |
| H-RAW-POS | FULL text from snapshot `evidence/<rep>/full.txt` | **HOLD.** 44 bytes; no `documents/` |
| H-RAW-TRAV | `../etc/passwd`, `rep/../x`, `/etc/passwd` | **HOLD.** `available=False`, `invalid_representation_id`; no `/Users/`, Application Support, or traceback |
| H-RAW-REOPEN | mutate published `full.txt` + plant `documents/<rep>/raw.txt` after load | **HOLD.** served text unchanged |
| H-RAW-DB-ESCAPE | packed `raw_text_path=../../etc/passwd` | **HOLD.** `path_not_in_inventory` |
| H-RAW-SYMLINK | `evidence/<rep>/full.txt` → outside file | **HOLD.** `path_escapes_pack` |
| H-CLI-TYPED | `--evidence-mode none` | **HOLD.** EXIT 2 `{"code":"sourced_none","member":"source","ok":false}`; stderr empty |

### Prior inventory / TOCTOU

| ID | Result |
|---|---|
| extra symlink | `symlink:alias.sqlite` |
| extra hardlink | `hardlink:pack.sqlite` |
| `../escape.txt` inventory | `path_mismatch` |
| `evidence/sha256:deadbeef/window.txt` | parse allows `:`; refuse is `missing_artifact:pack.sqlite` (not traversal) |
| capability rewrite after first verify, before copy | `activate_pack` `invalid_manifest:capabilities` |

## Why M1 is closed

`finalize_v2_manifest` and `_verify_v2` both call `derive_capabilities` on packed sqlite: empty/missing/non-matching C-036 → `UNREVIEWED_CAPABILITIES`; exact bind → `REVIEWED_CAPABILITIES`. `_refuse_forged_capabilities` requires `claimed == derived`. C-036 rows are copied into the pack at build (`_copy_c036`). `list_packs` only returns `inspect_verified_manifest` successes.

## Residual (non-blocking)

- **Exclusions are not re-derived at verify.** Forged zeros still list after a passing verify. Contract §7’s re-derive list is counts / capabilities / source policy / schema IDs; exclusions are advisory. Nothing authorizes on them. Counts remain enforced.
- `derive_capabilities` assigns `conn.row_factory = sqlite3.Row` on the caller connection. Verifier/finalize open private connections. Not a label bypass.
- Self-issued C-036 inside a rewritten `pack.sqlite` with honest hash refresh is a new content hash (integrity receipt, not a signature). Same model as the pack contract.

## Focused corroboration (once; not the suite)

```
.venv/bin/python -m pytest tests/test_pack_v2_review_repair.py --override-ini addopts= -q --tb=line
```

`7 passed in 0.80s` EXIT 0. No full suite.

## Protected-boundary cleanup

- No read/write of `~/Library/Application Support/ontologylab/` contents. Directory mtime still `2026-07-31 17:49:12`.
- No external network.
- Port 8799 / PID 55560 observe-only: DEVICE `0x1ff51c806b197195`, still `127.0.0.1:8799`.
- Disposable probe root `/private/tmp/ontologylab-wave21-t12-rsec` removed. No leftover listeners.
- Product/test bytes MATCH entry freeze. Original `task-12-review-security.md` not rewritten.
- No commit/push. This file is the only durable write.

## Stop

Strict verdict: **PASS**.
