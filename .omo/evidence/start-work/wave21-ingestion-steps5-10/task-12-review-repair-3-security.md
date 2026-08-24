# Task 12 repair-3 security recheck — receipt + source-fingerprint witnesses

Date: 2026-08-24
Rechecker: omo senpi-task `st_01a031f0`
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit)
Claim: `task-12-review-repair-3-executor.md` (hashes treated as claims; surfaces re-measured)
Prior receipts preserved:
- `task-12-review-security.md` `44c8199d2955ae7eeec2bd56106ca9fc41348dd598602d39d7729bb34e22a70f`
- `task-12-review-repair-security.md` `9c289c27496d2a2ce778ec2e753fb96c0d1d502277863fdab13bff50bd94cef1`
- `task-12-review-repair-2-security.md` `85bfe07b366887e5080eb73e48f3fd75fb71d6f760444fd75564ba2a6bd234dc`
Constraint: product/test read-only; artifact tampers only in disposable roots; no Application Support, network, 8799, PID 55560, full suite, authority, or plan edits.

## Verdict

**PASS**

An authorized live snapshot that also holds an extra unshipped run **and** an unpublished document stays `reviewed` + `sourced-answer-v2`. Both extra row classes are absent from packed sqlite; unpublished bytes are absent from `evidence/` and from MCP lookup/`document_raw_text`. Both `receipt-inventory.json` and `source-fingerprint.json` are inventoried `0444` and bind packed C-036 (`receipt_inventory_root` / `source_fingerprint`). Fingerprint witness delete / substitute / symlink / extra-key / duplicate / reorder / wrong-type / empty-id / non-string digest / content-hash edit / C-036 fingerprint edit, packed document add / hash change, receipt-witness delete / digest edit, and manifest-only or fully rehashed label forgery all refuse typed on `verify_pack`, verifier CLI, `list_packs`, `activate_pack`, and MCP `resource_manifest` / `load_pack`. Honest unreviewed and reviewed packs and a prior loaded session hold.

No capability mint and no unpublished-evidence leak. Round-2 packed-row deletion is **not closed**: verify still uses subset membership, so a hash-refreshed sqlite that drops a citation or even the packed document row can keep the labels. That is post-publish mutilation (new `pack_content_hash`), not a way to gain labels or query extra live rows. It is not treated as a bypass of the R3 witness gates.

## Bound freeze (entry = exit)

Working-tree SHA-256 MATCH the repair-3 executor table (rehashed after probes; no product/test write):

| Path | SHA-256 |
|---|---|
| `ontologylab/pack_source_fingerprint.py` | `a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7` |
| `ontologylab/pack_v2_derive.py` | `7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577` |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |
| `tests/test_pack_v2_review_repair.py` | `d2088b1e863a29b69866a645754561874fe136ad0c09eebdc32e71c3a486914c` |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` |
| `ontologylab/pack_verifier.py` | `9fa11d41aeda3677725fa222697e98c710e1e0c474d720913eefd3d353bb1273` |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` |
| `ontologylab/mcp_server.py` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` |

HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`.

## Independent probes

Disposable `/private/tmp/ontologylab-wave21-t12-r3sec` (deleted). Library + verifier CLI. MCP via `PackSession`. Artifact chmod/edit only under that root.

### Combined extra run + unpublished document

Live plant: extra `put_extraction_receipts` run + `insert_document` (`Unpublished extra document bytes.`), then C-036 on live fingerprint + receipt root. Pack `both-extra-*`.

| Check | Observed |
|---|---|
| capabilities | v2 + evidence-self-contained + reviewed + sourced-answer-v2 |
| extra run / extra doc in packed sqlite | absent |
| extra evidence dir | absent |
| both witnesses inventoried | `receipt-inventory.json`, `source-fingerprint.json` |
| C-036 binds | `source_fingerprint == fingerprint_from_entries(fp)`; `receipt_inventory_root == source_inventory_root(receipts)` |
| verify / CLI / list / activate / resource / load | ok, labels served |
| MCP lookup / `document_raw_text(extra)` | extra ids and unpublished text absent; `available=False` |

### Fingerprint-witness and packed-document tampers

Clones rematerialized inventory hashes where noted. Verify + CLI + list + activate + MCP refused unless stated.

| ID | Tamper | Result |
|---|---|---|
| H-FP-DELETE | unlink `source-fingerprint.json` | `missing_artifact:source-fingerprint.json` |
| H-FP-DELETE-REHASH | unlink + rewrite inventory | `invalid_manifest:capabilities` |
| H-FP-SUBSTITUTE | `{"entries":[]}` | `invalid_manifest:capabilities` |
| H-FP-SYMLINK | symlink to outside copy | `symlink:source-fingerprint.json` |
| H-FP-EXTRA-KEY | `{"note":…}` (strict `set(raw)=={entries}`) | `invalid_manifest:capabilities` |
| H-FP-DUP / REORDER | duplicate / reverse | `invalid_manifest:capabilities` |
| H-FP-WRONG-TYPE | object rows | `invalid_manifest:capabilities` |
| H-FP-EMPTY-ID | `id=""` | `invalid_manifest:capabilities` |
| H-FP-DIGEST-TYPE | hash is `123` | `invalid_manifest:capabilities` |
| H-FP-CONTENT-HASH | replace pair hash | `invalid_manifest:capabilities` |
| H-C036-FP | C-036 fingerprint `deadbeef*8` | `invalid_manifest:capabilities` |
| H-DOC-ADD | insert `doc-attacker` not in witness | `invalid_manifest:capabilities` |
| H-DOC-HASH | `content_hash += '-X'` | `invalid_manifest:capabilities` |
| H-REC-DELETE | unlink receipt witness | `missing_artifact:receipt-inventory.json` |
| H-REC-DIGEST | zero first receipt `body_digest` | `invalid_manifest:capabilities` |
| H-CAP-FORGE-MANIFEST | add labels on unreviewed | `invalid_manifest:capabilities` |
| H-CAP-FORGE-REHASH | same after full inventory rehash | `invalid_manifest:capabilities` |

CLI bodies are typed `{"ok":false,"code":…,"path":…}` with no traceback.

### Positive packs and prior session

Unreviewed full: no reviewed/sourced. `_reviewed_pack`: both labels. Load combined pack, unlink sibling fingerprint witness, `activate_pack(sibling)` → `PackIntegrityError`; prior lookup still 1 match.

## Round-2 residual reassessed (packed-row deletion)

Not closed. Membership is still **subset**, not equality, on both witnesses.

| Tamper (FK off / trigger dropped) + rematerialize | verify / labels | Closure |
|---|---|---|
| Delete one of three packed citations | ok / still reviewed+sourced | 3 verified facts, 2 cites; one fact id uncited in sqlite |
| Delete the packed document row | ok / still reviewed+sourced | empty `documents`; empty set ⊆ fingerprint witness |

This does **not** mint labels, leak unpublished bytes, or make extra live rows queryable. It requires rewriting `pack.sqlite` and refreshing inventory hashes (new `pack_content_hash`). Verify does not re-run collect `_CITE_GAP` / non-empty representation closure. Same class as Round 2; document deletion makes the empty-subset case visible. Follow-up would be re-deriving closure completeness at `verify_pack`, not loosening R3 binds.

## Focused corroboration (once; not the suite)

```
.venv/bin/python -m pytest \
  tests/test_pack_v2_review_repair.py::test_unpublished_live_document_keeps_reviewed_labels_and_stays_unshipped \
  tests/test_pack_v2_review_repair.py::test_tampered_source_fingerprint_witness_is_refused \
  tests/test_pack_v2_review_repair.py::test_wrong_c036_source_fingerprint_is_refused \
  tests/test_pack_v2_review_repair.py::test_extra_live_run_keeps_reviewed_labels_and_stays_unshipped \
  tests/test_pack_v2_review_repair.py::test_unreviewed_forged_labels_with_fingerprint_witness_are_refused \
  --override-ini addopts= -q --tb=line
```

`5 passed in 0.87s` EXIT 0. No full suite.

## Protected-boundary cleanup

- No read/write of `~/Library/Application Support/ontologylab/` contents. Directory mtime still `2026-07-31 17:49:12`.
- No external network.
- Port 8799 / PID 55560 observe-only: DEVICE `0x1ff51c806b197195`, still `127.0.0.1:8799`.
- Disposable probe root removed. No leftover listeners.
- Product/test bytes MATCH entry freeze. Prior security receipts not rewritten.
- No commit/push. This file is the only durable write.

## Stop

Strict verdict: **PASS**.
