# Task 12 repair-2 security recheck — live-inventory witness

Date: 2026-08-24
Rechecker: omo senpi-task `st_01a031f0`
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit)
Claim: `task-12-review-repair-2-executor.md` (hashes treated as claims; surfaces re-measured)
Prior receipts preserved:
- `task-12-review-security.md` SHA-256 `44c8199d2955ae7eeec2bd56106ca9fc41348dd598602d39d7729bb34e22a70f`
- `task-12-review-repair-security.md` SHA-256 `9c289c27496d2a2ce778ec2e753fb96c0d1d502277863fdab13bff50bd94cef1`
Constraint: product/test read-only; artifact tampers only in disposable roots; no Application Support, network, 8799, PID 55560, full suite, authority, or plan edits.

## Verdict

**PASS**

An authorized live snapshot that also holds an extra valid run stays `reviewed` + `sourced-answer-v2`. That extra receipt is absent from every packed receipt table and from MCP/SQL, present only in inventoried `receipt-inventory.json`, and the packed C-036 root equals `source_inventory_root(witness)`. Packed triples must be a subset of the witness (`family`, `receipt_id`, `body_digest`). Witness delete / path substitute / symlink / duplicate / reorder / digest edit / C-036 root edit, packed addition / body change, and manifest-only or fully rehashed label forgery all refuse typed on `verify_pack`, verifier CLI, `list_packs`, `activate_pack`, and MCP `resource_manifest` / `load_pack`. Honest unreviewed and reviewed packs and a prior loaded session hold. No integrity or capability bypass.

## Bound freeze (entry = exit)

Working-tree SHA-256 MATCH the repair-2 executor table (rehashed after probes; no product/test write):

| Path | SHA-256 |
|---|---|
| `ontologylab/pack_v2_derive.py` | `e5ee3cc0b4be2c987d368d72bb9d6d0ee998d1b2156163c357ad83577e3c5946` |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` |
| `ontologylab/pack_v2_closure.py` | `24d2e2f31671d988b8a28aec409b360df057d0e12ca57d2820d46c4b6503cba2` |
| `ontologylab/pack_verifier.py` | `9fa11d41aeda3677725fa222697e98c710e1e0c474d720913eefd3d353bb1273` |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` |
| `ontologylab/mcp_server.py` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` |
| `ontologylab/pack_readiness.py` | `550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21` |
| `ontologylab/packbuilder.py` | `e903936ec8df14e37396d2c3db579713840cd64f82df8aeb83d4e012e81867b7` |
| `ontologylab/packdiff.py` | `cc148c3d4bd444f2f0cae1e4764ed03b28f6194472c5893d22e2edf5addb0292` |
| `ontologylab/verified_pack_reader.py` | `6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1` |
| `tests/test_pack_v2_review_repair.py` | `97cdaaa515ac295de105cdbfc3686feec048b2b69236e10b4969fba039bf1cad` |
| `tests/test_pack_v2_closure.py` | `96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff` |
| `tests/test_pack_v2_verifier.py` | `5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b` |
| `tests/test_packdiff.py` | `296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6` |

HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`.

## Independent probes

Disposable `/private/tmp/ontologylab-wave21-t12-r2sec` (deleted). Library + verifier CLI. MCP via `PackSession`. Artifact chmod/edit only under that root.

### Authorized extra live run

`_authorized_extra_run` + `build_pack(..., evidence_mode="full")`. Extra run id `sha256:691e608d…`.

| Check | Observed |
|---|---|
| capabilities | `knowledge-graph-v2`, `evidence-self-contained-v2`, `reviewed`, `sourced-answer-v2` |
| extra in packed run/chunk/cite/review tables | absent |
| extra in `receipt-inventory.json` | present |
| witness inventoried | `receipt-inventory.json` in `artifact_inventory` |
| C-036 `receipt_inventory_root` | equals `source_inventory_root(witness)` |
| verify / CLI / list / activate / resource / load | ok, labels served |

### Queryable extra / metadata leakage

| Surface | Extra receipt id |
|---|---|
| `entity_lookup` / `get_entity` JSON | absent |
| `resource_manifest` JSON | absent |
| packed sqlite `WHERE receipt_id = extra` | 0 rows |
| published `receipt-inventory.json` | present (`[family, receipt_id, body_digest]`) |

The witness is pack payload by design: filesystem readers of the published directory can see unshipped receipt ids and body digests (hashes, not selected text / actor / reason). MCP and the serving store cannot query those rows. That is audit metadata, not a capability or query bypass.

### Witness and membership tampers

Each clone rematerialized inventory hashes where noted. Verify + CLI + list + activate + MCP all refused unless stated.

| ID | Tamper | Result |
|---|---|---|
| H-WIT-DELETE | unlink witness | `missing_artifact:receipt-inventory.json` |
| H-WIT-DELETE-REHASH | unlink + rewrite inventory | `invalid_manifest:capabilities` |
| H-WIT-SUBSTITUTE | empty `{"entries":[]}` at the path | `invalid_manifest:capabilities` |
| H-WIT-SYMLINK | symlink to outside copy | `symlink:receipt-inventory.json` |
| H-WIT-DUP | duplicate first entry + rehash | `invalid_manifest:capabilities` |
| H-WIT-REORDER | reverse entries + rehash | `invalid_manifest:capabilities` |
| H-WIT-DIGEST | zero first `body_digest` + rehash | `invalid_manifest:capabilities` |
| H-C036-ROOT-EDIT | C-036 root `0*64` + rehash | `invalid_manifest:capabilities` |
| H-PACKED-ADD | insert extra run row not in witness + rehash | `invalid_manifest:capabilities` |
| H-PACKED-BODY | `selected_text+='X'` keep id + rehash | `invalid_manifest:capabilities` |
| H-CAP-FORGE-MANIFEST | add reviewed/sourced on unreviewed, hashes untouched | `invalid_manifest:capabilities` |
| H-CAP-FORGE-REHASH | same after full inventory rehash | `invalid_manifest:capabilities` |

CLI bodies are typed `{"ok":false,"code":…,"path":…}` with no traceback.

### Positive packs and prior session

| Case | Result |
|---|---|
| unreviewed full | verify/load ok; no reviewed/sourced |
| `_reviewed_pack` | verify/load/resource ok with both labels |
| load extra-run pack; unlink sibling witness; `activate_pack(sibling)` | `PackIntegrityError`; prior lookup still 1 match, same `pack_id` |

## Residuals (non-blocking)

- **Ignored extra JSON keys** on the witness (`{"note":"attacker"}`) after honest inventory rehash still verify. `load_source_receipt_inventory` only reads `entries`; C-036 root and packed ⊆ witness are unchanged. Not a label bypass. File bytes change `pack_content_hash`.
- **Packed-row deletion is subset, not equality.** Deleting one packed citation and rematerializing counts/hashes still authorizes: remaining triples ⊆ witness and C-036 still binds the live inventory. New content hash. Extra live rows were already allowed in the witness; shrinking the shipped subset is the same rule. Not a way to mint labels or resurrect the extra run in SQL.
- **Witness filesystem disclosure** of unshipped `receipt_id` + `body_digest` (see above).

## Focused corroboration (once; not the suite)

```
.venv/bin/python -m pytest \
  tests/test_pack_v2_review_repair.py::test_extra_live_run_keeps_reviewed_labels_and_stays_unshipped \
  tests/test_pack_v2_review_repair.py::test_tampered_source_inventory_witness_is_refused \
  tests/test_pack_v2_review_repair.py::test_packed_receipt_absent_from_witness_is_refused \
  tests/test_pack_v2_review_repair.py::test_forged_reviewed_labels_are_refused_after_publish \
  --override-ini addopts= -q --tb=line
```

`4 passed in 0.59s` EXIT 0. No full suite.

## Protected-boundary cleanup

- No read/write of `~/Library/Application Support/ontologylab/` contents. Directory mtime still `2026-07-31 17:49:12`.
- No external network.
- Port 8799 / PID 55560 observe-only: DEVICE `0x1ff51c806b197195`, still `127.0.0.1:8799`.
- Disposable probe root removed. No leftover listeners.
- Product/test bytes MATCH entry freeze. Prior security receipts not rewritten.
- No commit/push. This file is the only durable write.

## Stop

Strict verdict: **PASS**.
