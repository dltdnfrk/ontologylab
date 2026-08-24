# Task 12 round-4 security probe — C-036/closure-strip bypass

Date: 2026-08-24
Worker: omo senpi-task `st_01a031ec`
Mode: disposable real-surface add-on on the **frozen uncommitted**
round-4 bytes. Product/test/plan/authority **read-only**. Prior QA
receipts not rewritten. Bounded event-driven stdio I/O. No pytest,
full suite, commit, push, network, or 8799 / Application Support
touch.

## Verdict

`NEEDS-FIX`

After deleting one citation, dropping packed C-036, removing
`evidence_mode` + `closure` while keeping `evidence-self-contained-v2`,
rewriting counts, and rematerializing hashes, the incomplete pack
**was served**:

- standalone verifier EXIT 0 / `ok=true` /
  `integrity_level=evidence-self-contained-v2`
- `list_packs` advertised `bypass-20260824-150544`
- `activate_pack` succeeded
- stdio MCP `load_pack` succeeded (`isError=false`) and **switched**
  the active session off the honest pack

This is a pre-serve bypass of `validate_packed_v2_closure`: with
reviewed/sourced labels gone and no `evidence_mode`/`closure` claim,
the validator returns early.

## Recipe observed (not a product edit)

Published two reviewed+sourced combined packs from one disposable kg,
then mutated only the sibling:

1. `PRAGMA foreign_keys=OFF`
2. DELETE one `citation_receipts` row
   (`sha256:3bb232c98395814deab6b60cdb4a47fe64b8c342c5c3859b439349a30dbf77c8`)
3. `DROP TABLE c036_capability_receipts`
4. Manifest: pop `evidence_mode`, pop `closure`
5. Manifest capabilities kept `evidence-self-contained-v2` and
   `knowledge-graph-v2`; dropped `reviewed` / `sourced-answer-v2` so
   claimed labels match `derive_capabilities` after C-036 strip
   (otherwise the capability check refuses first and the skip is never
   reached)
6. Counts rewritten from remaining SQL (`citations=2`)
7. Inventory / `sqlite_hash` / `pack_content_hash` rematerialized

Leaving `reviewed`+`sourced-answer-v2` in place is **not** this bypass;
that path is already refused as `invalid_manifest:capabilities`.

## Observed surfaces

Honest pack `honest-20260824-150544` (untouched) still verified.

Bypass pack `bypass-20260824-150544`:

```text
ARGV: python -m ontologylab.pack_verifier .../bypass-20260824-150544
EXIT: 0
{"ok":true,
 "pack_id":"bypass-20260824-150544",
 "pack_schema_version":2,
 "integrity_level":"evidence-self-contained-v2",
 "pack_content_hash":"sha256:c49d142d6b859887fb5d476f2daf70d8ddf0a7e8301a5e1af9b90cfb4d0b71b4",
 "counts":{"citations":2,"review_decisions":3,"nodes_verified":2,...}}
stderr empty  (no Traceback)

list_packs ids: bypass-20260824-150544, honest-20260824-150544
bypass capabilities: ["knowledge-graph-v2","evidence-self-contained-v2"]

activate_pack: ok=true
  integrity_level=evidence-self-contained-v2
  content_hash=sha256:c49d142d6b859887…

MCP (started on honest):
  initialize.protocolVersion=2025-06-18
  entity_lookup PaymentGateway → id=6dfc61f1… pack=honest-20260824-150544
  load_pack bypass-20260824-150544 → isError=false
    sqlite_path=.../ontologylab-pack-1257-4ljsv0l6/bypass-20260824-150544/pack.sqlite
    nodes_verified=2 edges_verified=1
  entity_lookup after load → same node id, pack_id=bypass-20260824-150544
```

Prior session did **not** stay on honest: successful `load_pack`
replaced it.

## Why this serves

`pack_v2_validate._validate` skips when the pack is not
reviewed/sourced **and** `_claims_v2_closure` is false
(`evidence_mode` and `closure` both absent). Artifact hashes, counts,
and derived unreviewed capabilities all match after rematerialize, so
`_verify_v2` returns success and MCP activates a snapshot.

A citation-incomplete pack can therefore be advertised as
`evidence-self-contained-v2` without running the packed-closure
validator.

## Bound identity / cleanup

```text
HEAD before=after 081d8554f814645517a29a0cef1c0e32af3d84df
entry product hashes == exit product hashes
index empty; this probe wrote no product/test bytes
prior QA receipts byte-identical (including
  task-12-review-repair-4-manual-qa.md)
root gone; MCP pid 1257 exit=0; owned snapshots []
PID 55560 DEVICE 0x1ff51c806b197195 TCP 127.0.0.1:8799 (LISTEN)
AS ino=102434596 mtime_ns=1785487752937707432 size=192
plan.md ino=276402724 size=45752
```

Did not edit product, tests, plans, authority, or prior QA receipts.
Did not commit, push, use network, or run pytest / full suite.

## Stop

Strict verdict: **NEEDS-FIX**. Incomplete citation pack was served.
