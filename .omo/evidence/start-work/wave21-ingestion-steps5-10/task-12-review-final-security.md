# Task 12 final independent security review — uncommitted R5 bytes

Date: 2026-08-24
Reviewer: omo senpi-task `st_01a03271`
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit)
Claim: `task-12-review-repair-5-executor.md` (hashes, suites, and mutants treated as claims; surfaces re-measured)
Prior receipts preserved (SHA-256, not rewritten):

| Receipt | SHA-256 |
|---|---|
| `task-12-review-security.md` | `44c8199d2955ae7eeec2bd56106ca9fc41348dd598602d39d7729bb34e22a70f` |
| `task-12-review-repair-security.md` | `9c289c27496d2a2ce778ec2e753fb96c0d1d502277863fdab13bff50bd94cef1` |
| `task-12-review-repair-2-security.md` | `85bfe07b366887e5080eb73e48f3fd75fb71d6f760444fd75564ba2a6bd234dc` |
| `task-12-review-repair-3-security.md` | `b2965a54cea6d9ec48a702087c1a71c3976f1f25abcf4ec2ea2e68c910b9e55c` |
| `task-12-review-repair-4-security.md` | `1cddbed376a77116f09f899004502119320f7d008bae5063d0efa163e020e326` |
| `task-12-review-repair-4-security-bypass-qa.md` | `6914408d2db6c726e09c87feab684cd4c1be36573ac8847ad3730786b70df428` |
| `task-12-review-repair-5-executor.md` | `a4568a3e7d37b4ce59b23bb6582f9486ae43b8c94ab9d935773e32de030890b9` |

Constraint: product/test read-only; artifact tampers only in disposable roots; no Application Support, network, 8799, PID 55560, full suite, authority, or plan edits.

## Verdict

**NEEDS-FIX** — maximum severity **MEDIUM**.

R5 closed the named H-SKIP-UNREV-KEEP-EV evidence-closure skip: deleting one citation, dropping C-036, stripping `evidence_mode`+`closure`, keeping `knowledge-graph-v2`+`evidence-self-contained-v2`, and rematerializing hashes is typed `invalid_manifest:closure` on `verify_pack`, verifier CLI (exit 2, JSON, no traceback), `list_packs`, `activate_pack`, and in-process MCP `load_pack`. The prior honest combined session holds.

The v1 parse path was not closed. Rewriting a published reviewed+sourced v2 pack as a four-field v1 manifest (`pack_id`, `pack_schema_version=1` or omitted, `content_hash` of `pack.sqlite`, **kept** `reviewed` / `sourced-answer-v2` / `evidence-self-contained-v2` strings) verifies as `legacy-graph-only` and then **serves those labels** from the raw JSON on `list_packs`, `activate_pack`, and MCP `resource_manifest` / `load_pack`. Dropping packed `c036_capability_receipts` and refreshing only `content_hash` still serves the same labels and **switches** a live MCP session off the honest pack. That is the original M1 authority class, now via a parser that never calls `derive_capabilities` or `validate_packed_v2_closure`.

No CRITICAL. No HIGH. Source DB/files stay immutable. No secret exfil. No network / live Application Support / 8799 / PID 55560 / 9C contact.

## Bound freeze (entry = exit)

Working-tree SHA-256 MATCH the R5 executor table (rehashed after probes; no product/test write):

| Path | SHA-256 |
|---|---|
| `ontologylab/pack_v2_validate.py` | `ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6` |
| `tests/test_pack_v2_review_repair.py` | `483ce682f024d7462503c530d45c4bcd536750582a055f9c49952a9c93383015` |
| `ontologylab/pack_verifier.py` | `ac2d55740ea1e7e6df4aaa2155ad8ca331f3b6447d86015a0bddc9e9bbf6907c` |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |
| `ontologylab/pack_v2_derive.py` | `7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577` |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` |
| `ontologylab/mcp_server.py` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` |
| `ontologylab/pack_readiness.py` | `550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21` |
| `ontologylab/pack_source_fingerprint.py` | `a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7` |
| `tests/test_pack_v2_closure.py` | `96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff` |
| `tests/test_pack_v2_verifier.py` | `5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b` |
| `tests/test_packdiff.py` | `296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6` |

HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`. Repair is uncommitted working-tree only.

## Independent probes

Disposable `/private/tmp/ontologylab-wave21-t12-finalsec` (deleted after). Library + `python -m ontologylab.pack_verifier`. MCP via in-process `PackSession` (no bind). Artifact chmod/edit only under that root. No pytest / full suite.

Honest baseline: `_authorized_combined` (extra live run + unpublished document) → `honest-final-20260824-153301`. Clones rematerialized inventory hashes where a v2 inventory still applied.

### Positives

| Pack | Result |
|---|---|
| combined extra-run + unpublished-doc | verify/CLI/list/activate/MCP ok; caps include `reviewed`+`sourced-answer-v2`; extra run/doc absent from packed sqlite and `evidence/`; extra run present only in `receipt-inventory.json`; extra doc present only in `source-fingerprint.json`; MCP `document_raw_text(extra)` `available=False` / `unknown_representation`; lookup hits 0 |
| honest unreviewed v2 | verify/load ok; caps `knowledge-graph-v2` + `evidence-self-contained-v2` only |
| `_write_v1` | `legacy-graph-only`; listed caps `knowledge-graph-v1`. MCP `DatabaseError` on the fixture's non-sqlite payload bytes (not a product pack) |
| inventory-only `_write_v2` | verify ok, `evidence-self-contained-v2` (R5 still allows this fixture class) |

### R5 named skip (HOLD)

| ID | Attack | verify / CLI / list / activate / MCP |
|---|---|---|
| H-SKIP-UNREV-KEEP-EV | delete one citation; `DROP` C-036; pop `evidence_mode`+`closure`; claim unreviewed evidence caps; rewrite counts; rematerialize | **HOLD.** `invalid_manifest:closure`. CLI exit 2 `{"code":"invalid_manifest","ok":false,"path":"closure"}`; stderr empty. Not listed. `PackIntegrityError` before serve |
| H-SKIP-KEEP-REVIEWED | same cite delete; strip contract; keep reviewed labels | **HOLD.** `forged_counts` (counts not rewritten); never served |
| H-SKIP-MALFORMED | `closure` is a string | **HOLD.** `invalid_manifest:closure` |
| H-EVIDENCE-MODE-NONE | `evidence_mode="none"` on a real reviewed pack | **HOLD.** `invalid_manifest:closure` |
| H-PRIOR-SESSION | load honest; `load_pack(bypass-skip-ev)` | **HOLD.** `PackIntegrityError`; lookup id and `pack_id` unchanged |

### Historical integrity / authority / witness (HOLD)

| ID | Attack | Result |
|---|---|---|
| H-CAP-FORGE | add reviewed/sourced on unreviewed; hashes untouched | `invalid_manifest:capabilities` all surfaces |
| H-CAP-FORGE-REHASH | same after inventory rehash | `invalid_manifest:capabilities` |
| H-EXTRA-CAP | append `admin-override` | `invalid_manifest:capabilities` |
| H-DEL-CITE-REHASH | delete one citation; rewrite closure+counts; rematerialize; keep contract | `invalid_manifest:citation` |
| H-WIT-REC-DELETE | unlink `receipt-inventory.json` | `missing_artifact:receipt-inventory.json` |
| H-WIT-REC-DIGEST | zero first `body_digest` + rehash | `invalid_manifest:capabilities` |
| H-WIT-FP-DELETE | unlink `source-fingerprint.json` | `missing_artifact:source-fingerprint.json` |
| H-WIT-FP-SUBSTITUTE | `{"entries":[]}` + rehash | `invalid_manifest:capabilities` |
| H-WIT-FP-SYMLINK | symlink witness to outside copy | `symlink:source-fingerprint.json` |
| H-C036-ROOT / DENY / FP | wrong root / `decision=deny` / fingerprint `deadbeef*8` + rehash | `invalid_manifest:capabilities` |
| H-PACKED-ADD | insert run not in witness + rematerialize counts/hashes | `invalid_manifest:capabilities` |
| H-SAMEID-PACKED | `selected_text+='X'` keep id + rehash | `invalid_manifest:capabilities` |
| H-SAMEID-LIVE-TEXT | live text-only cite edit, then `build_pack` | `PackReadinessRefused` `c036_stale:c036`; visible `[]` |
| H-SAMEID-LIVE-BOTH | live text+hash cite edit, then `build_pack` | `PackReadinessRefused` `stale_receipt:citation`; visible `[]` |
| H-PATH | inventory `../escape.txt` | `path_mismatch:../escape.txt` |
| H-SYM-FILE | extra `alias.sqlite` → `pack.sqlite` | `symlink:alias.sqlite` |
| H-HARD-FILE | extra hardlink of `pack.sqlite` | `hardlink:pack.sqlite` |
| H-TOCTOU-CAP | monkeypatch first `verify_pack` inside `activate_pack` to append reviewed/sourced | second verify `invalid_manifest:capabilities`; activate refused |
| H-V1-DISGUISE | rewrite as v1 with `knowledge-graph-v1` only | **HOLD as honesty.** `legacy-graph-only`; listed caps `knowledge-graph-v1` only |

CLI refusals are typed JSON, exit 2, no `Traceback`, no `PackedV2ClosureRefused` leak.

### MEDIUM — v1 disguise keeps C-036 labels (CONFIRMED)

`parse_manifest` defaults missing/`1` to `_parse_v1`, which never inspects `capabilities`. `_verify_v1` binds only `pack.sqlite` `content_hash` (optional `tree_hash`). `activate_pack` then `_load_manifest`s the **raw** JSON. `list_packs` → `inspect_verified_manifest` → same raw JSON.

Operator path, measured on a real combined reviewed pack. Manifest rewritten to:

```json
{"pack_id":"v1-keep-labels","pack_schema_version":1,
 "capabilities":["knowledge-graph-v2","evidence-self-contained-v2","reviewed","sourced-answer-v2"],
 "content_hash":"<sha256 of unchanged pack.sqlite>"}
```

| Surface | Observed |
|---|---|
| `verify_pack` | ok, `integrity_level=legacy-graph-only`, schema 1 |
| verifier CLI | EXIT 0, `ok=true`, `legacy-graph-only` |
| `list_packs` | advertised; capabilities include `reviewed` + `sourced-answer-v2` + `evidence-self-contained-v2` |
| `activate_pack` | ok; snapshot.manifest carries the same four strings |
| MCP `load_pack` | `ok`; `entity_lookup PaymentGateway` hits=1 on the disguised pack |
| MCP `resource_manifest` | same forged labels; `pack_schema_version=1` |

Omitting `pack_schema_version` (defaults to 1) is identical (`H-V1-OMIT-SCHEMA`).

Follow-up A: `DROP TABLE c036_capability_receipts`, set `content_hash` to the new sqlite digest, keep the four labels.

- verify still `legacy-graph-only`
- list/activate/MCP still serve `reviewed` + `sourced-answer-v2`
- MCP session started on honest: `load_pack(v1-keep-noc036)` **succeeds** and subsequent lookup `pack_id` is the disguised pack
- unpublished extra doc still not readable (`unknown_representation`) — not an unpublished-text leak

This is not a remote unauth path. It is the same local `0444` rewrite the inventory verifier exists for. R1–R5 re-derive and closure gates never run, because the pack is no longer parsed as v2. R4's `H-V1-DISGUISE` only rewrote capabilities to `knowledge-graph-v1` and called that honesty; keeping the v2 authority strings was not measured.

Do not “fix” this by hashing the whole v1 manifest or by trusting `integrity_level=legacy-graph-only` while readers still consume `capabilities`. Either (a) refuse `reviewed` / `sourced-answer-v2` / `evidence-self-contained-v2` / `knowledge-graph-v2` on the v1 path, or (b) re-derive capabilities from packed C-036 + witnesses before any reader sees the list, including after a v1 parse. A directory that still holds v2 payload (receipt tables, `artifact_inventory`, `evidence/`) must not be allowed to launder labels by dropping `pack_schema_version` to 1.

## Residuals (non-blocking)

### L1 — Synthetic / hidden-table disguise still advertises `evidence-self-contained-v2`

Dropping every `_V2_RECEIPT_TABLES` table (or renaming them to `*__hidden`) and recreating `nodes` without `status`, then stripping the contract and claiming unreviewed evidence caps, makes `_packed_v2_graph_present` false. `verify_pack` returns ok with `integrity_level=evidence-self-contained-v2`. MCP `load_pack` is `OperationalError` (not a served graph). Same shape as the allowed inventory-only `_write_v2` fixture. No reviewed/sourced mint. Case-rename of receipt tables is infeasible here (`ALTER TABLE citation_receipts RENAME TO CITATION_RECEIPTS` → SQLite case-fold).

### L2 — knowledge-graph-v2-only incomplete pack is served

Delete one citation, drop C-036 and all `evidence/` files, strip `evidence_mode`+`closure`, claim only `knowledge-graph-v2`, rematerialize. Validator skips (not reviewed, no contract keys, not advertising `evidence-self-contained-v2`). Served as `knowledge-graph-v2` with `citations=2` vs `nodes_verified=2`+`edges_verified=1`. MCP lookup succeeds. This is a capability-honest downgrade, not a C-036 or evidence-self-contained claim. New `pack_content_hash`.

### L3 — exclusions / `created_ts` / inventory owner still not re-derived

Unchanged from R0/R1. Advisory. Nothing authorizes on them.

## Why R5 is not enough

```
needs_closure = reviewed or _claims_v2_closure(pack_dir) or (
    advertised and _packed_v2_graph_present(conn)
)
```

That gate lives in `_verify_v2` only. `_verify_v1` never reaches it. `activate_pack` identity-pins `pack_id` + `pack_content_hash` (v1 hash is the sqlite digest) and then serves unsigned capability strings.

## What was not re-run

- Full `.venv/bin/python -m pytest`.
- Bound-socket uvicorn / real stdio MCP (`PackSession` is the same load/list/resource path; follow-up A observed a real session switch).
- Multi-process writers against one packs dir.

## Confidence

`0.94`

Not 0.95: HTTP/MCP was in-process `PackSession`, not a bound stdio server. The authority bypass does not depend on that — `list_packs` and `activate_pack` already serve the labels.

## Blockers

`verify_pack` / `activate_pack` / discovery / MCP must not report `reviewed` or `sourced-answer-v2` (or `evidence-self-contained-v2`) unless those labels are re-derived from pack-resident sealed evidence. A v1-shaped manifest that still carries those strings, including after C-036 is dropped, is an authority bypass. Until that is closed, Task 12 final is **NEEDS-FIX**.

## Protected-boundary cleanup

- No read/write of `~/Library/Application Support/ontologylab/` contents. Directory `ino=102434596` `mtime_ns=1785487752937707432` `size=192` unchanged.
- No external network.
- Port 8799 / PID 55560 observe-only: DEVICE `0x1ff51c806b197195`, still `127.0.0.1:8799`.
- Disposable probe root `/private/tmp/ontologylab-wave21-t12-finalsec` and probe script removed. No leftover listeners. Pre-existing `/var/folders/.../ontologylab-pack-*` dirs (empty ~7.5d or unrelated PID 49885) were not touched.
- Product/test bytes MATCH entry freeze. Prior security receipts not rewritten.
- No commit/push. This file is the only durable write.

## Stop

Strict verdict: **NEEDS-FIX**. Maximum severity: **MEDIUM**.
