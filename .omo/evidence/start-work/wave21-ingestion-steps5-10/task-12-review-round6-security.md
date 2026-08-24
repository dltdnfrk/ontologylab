# Task 12 Round 6 independent security review — v1 parse trust boundary

Date: 2026-08-24
Reviewer: omo senpi-task `st_01a03288`
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df` (unchanged; no commit)
Claim: `task-12-review-repair-6-executor.md` (hashes, suites, and mutants treated as claims; surfaces re-measured)
Prior receipts preserved (SHA-256, not rewritten):

| Receipt | SHA-256 |
|---|---|
| `task-12-review-security.md` | `44c8199d2955ae7eeec2bd56106ca9fc41348dd598602d39d7729bb34e22a70f` |
| `task-12-review-repair-security.md` | `9c289c27496d2a2ce778ec2e753fb96c0d1d502277863fdab13bff50bd94cef1` |
| `task-12-review-repair-2-security.md` | `85bfe07b366887e5080eb73e48f3fd75fb71d6f760444fd75564ba2a6bd234dc` |
| `task-12-review-repair-3-security.md` | `b2965a54cea6d9ec48a702087c1a71c3976f1f25abcf4ec2ea2e68c910b9e55c` |
| `task-12-review-repair-4-security.md` | `1cddbed376a77116f09f899004502119320f7d008bae5063d0efa163e020e326` |
| `task-12-review-repair-4-security-bypass-qa.md` | `6914408d2db6c726e09c87feab684cd4c1be36573ac8847ad3730786b70df428` |
| `task-12-review-final-security.md` | `76e328c42529cf0451b4c259d9cd95ca2ab22546e581a5c4ca9d732362babb41` |
| `task-12-review-repair-6-executor.md` | `6209b4aee7e31b49607a46d78aa1e9fb3fa16c69654da01795b78d0f450160aa` |

Constraint: product/test read-only; artifact tampers only in disposable roots; no Application Support, network, 8799, PID 55560, full suite, authority, or plan edits.

## Verdict

**PASS**

R6 closed the named MEDIUM v1-disguise authority bypass. A published reviewed+sourced v2 pack rewritten as a four-field v1 manifest (`pack_id`, `pack_schema_version` explicit `1` / omitted / `null` / `true` / `1.0`, `content_hash` of `pack.sqlite`, raw `reviewed` / `sourced-answer-v2` / `evidence-self-contained-v2` / `knowledge-graph-v2`) is typed `invalid_manifest:capabilities` on `verify_pack`, verifier CLI (exit 2, JSON, no traceback), `list_packs`, `activate_pack`, and in-process MCP `resource_manifest` / `load_pack` before any session switch. Dropping packed C-036 and refreshing only `content_hash` is the same refusal. Each v2-only capability, unknown/duplicate/reordered v1 capabilities, and every v2-only contract field (individually and combined) die at `_parse_v1`. Legitimate builder v1 and honest v1 disguises with only allowlisted labels still verify as `legacy-graph-only`. Highest-risk R1–R5 bypasses and the prior honest session hold.

No CRITICAL. No HIGH. No MEDIUM. Source DB/files stay immutable. No secret exfil. No network / live Application Support / 8799 / PID 55560 / 9C contact.

## Bound freeze (entry = exit)

Working-tree SHA-256 MATCH the R6 executor table (rehashed after probes; no product/test write):

| Path | SHA-256 |
|---|---|
| `ontologylab/pack_verifier.py` | `2b64a110fa3789de3a53245e950f73cb8dccc9bdb78025394fbe3316b55130ed` |
| `tests/test_pack_v2_review_repair.py` | `622c7602c2f961c4dca98711d409c87123c257227d0610046e6e11a2ba417b76` |
| `tests/test_pack_v2_verifier.py` | `78ae23f199897c87841a9dc908bcd168dbfc93162ee4beaa1735a045b80c8ce5` |
| `ontologylab/pack_v2_validate.py` | `ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6` |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` |
| `ontologylab/pack_v2_derive.py` | `7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577` |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` |
| `ontologylab/mcp_server.py` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` |
| `ontologylab/pack_readiness.py` | `550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21` |
| `ontologylab/pack_source_fingerprint.py` | `a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7` |
| `tests/test_pack_v2_closure.py` | `96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff` |
| `tests/test_packdiff.py` | `296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6` |

HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df`. Repair is uncommitted working-tree only.

## Independent probes

Disposable `/private/tmp/ontologylab-wave21-t12-r6sec` (deleted after). Library + `python -m ontologylab.pack_verifier`. MCP via in-process `PackSession` (no bind). Artifact chmod/edit only under that root. No pytest / full suite.

Honest baseline: `_authorized_combined` (extra live run + unpublished document) → `honest-v2-20260824-155552` plus builder v1 `honest-v1-20260824-155552` and unreviewed v2 `honest-unrev-20260824-155552`. Sibling clones rematerialized inventory hashes where a v2 inventory still applied.

### Positives

| Pack | Result |
|---|---|
| combined extra-run + unpublished-doc | verify/CLI/list/activate/MCP ok; caps `knowledge-graph-v2` + `evidence-self-contained-v2` + `reviewed` + `sourced-answer-v2`; extra run/doc absent from packed sqlite; MCP `document_raw_text(extra)` `available=False` / `unknown_representation`; lookup hits 1 |
| honest builder v1 | `legacy-graph-only`; listed/activated/resource caps `["knowledge-graph-v1"]` only; schema omitted in raw JSON (builder v1 has no `pack_schema_version`) |
| honest unreviewed v2 | verify/load ok; caps `knowledge-graph-v2` + `evidence-self-contained-v2` only |
| v1 disguise with only `knowledge-graph-v1` (omit / explicit / +`methodology-v1` / no `tree_hash` / C-036 dropped) | **honesty.** `legacy-graph-only`; served caps ⊆ `{knowledge-graph-v1, methodology-v1}` |

### Schema-version confusion (HOLD)

`parse_manifest` uses `raw.get("pack_schema_version", 1)` then `match` `case 1 \| None`. Omitted, `null`, JSON `true` (`True == 1`), and `1.0` all enter `_parse_v1`. String `"1"` / `"2"`, JSON `false`, and unknown versions refuse `invalid_manifest:pack_schema_version`. Float `2.0` enters `_parse_v2` and dies on missing inventory.

Operator path, measured on a real combined reviewed pack rewritten to four fields (or the same plus C-036 `DROP` + refreshed `content_hash`):

| ID | `pack_schema_version` | capabilities | verify / CLI / list / activate / MCP |
|---|---|---|---|
| H-V1-EXPLICIT | `1` | four v2/reviewed strings | **HOLD.** `invalid_manifest:capabilities`. CLI exit 2 `{"code":"invalid_manifest","ok":false,"path":"capabilities"}`; stderr empty. Not listed. `PackIntegrityError` before serve |
| H-V1-OMIT | omitted | same | **HOLD.** same |
| H-V1-NULL | `null` | same | **HOLD.** same |
| H-V1-TRUE | `true` | same | **HOLD.** routed to v1, then `invalid_manifest:capabilities` |
| H-V1-FALSE | `false` | same | **HOLD.** `invalid_manifest:pack_schema_version` |
| H-V1-STR1 / STR2 | `"1"` / `"2"` | same | **HOLD.** `invalid_manifest:pack_schema_version` |
| H-V1-FLOAT | `1.0` | same | **HOLD.** `invalid_manifest:capabilities` |
| H-V1-OMIT-DROP-C036 | omitted | same, C-036 dropped | **HOLD.** `invalid_manifest:capabilities` |
| H-V1-EXPLICIT-DROP-C036 | `1` | same, C-036 dropped | **HOLD.** `invalid_manifest:capabilities` |

`True`/`1.0`/`null` are type-loose v1 routing, not a label bypass: `_parse_v1_capabilities` still runs before `_verify_v1` or any reader.

### Capability allowlist (HOLD)

Exact tuple membership in `{(), ("knowledge-graph-v1",), ("knowledge-graph-v1", "methodology-v1")}`. `None` / omitted / `[]` are historical absence.

| ID | Attack | Result |
|---|---|---|
| H-CAP-REVIEWED / SOURCED / EV / KGV2 | each string alone | `invalid_manifest:capabilities` all surfaces |
| H-CAP-V1PLUS-* | `knowledge-graph-v1` + each v2/reviewed string | same |
| H-CAP-ALL-V2 | four authority strings combined | same |
| H-CAP-UNKNOWN | `admin-override` | same |
| H-CAP-DUP | `["knowledge-graph-v1","knowledge-graph-v1"]` | same |
| H-CAP-REORDER | `["methodology-v1","knowledge-graph-v1"]` | same |
| H-CAP-METHOD-ONLY | `["methodology-v1"]` | same |
| H-CAP-FALSE / STR | `false` / `"knowledge-graph-v1"` | same |

### v2-only fields (HOLD)

Each of `artifact_inventory`, `pack_content_hash`, `sqlite_hash`, `integrity_model`, `evidence_mode`, `closure`, `receipt_inventory`, `receipt_inventory_root`, `source_fingerprint`, `source_fingerprint_entries` on an otherwise honest v1 disguise: `invalid_manifest:<field>`. Combined: first listed field (`artifact_inventory`). Presence is enough; value shape is not consulted.

### tree-hash / C-036 stripping

| ID | Attack | Result |
|---|---|---|
| H-TREE-STRIP | honest v1 caps, no `tree_hash` | **honesty.** verifies `legacy-graph-only` |
| H-TREE-BAD | honest v1 caps, wrong `tree_hash` | `tampered_artifact:tree_hash`; not listed |
| H-C036-STRIP-HONEST | `DROP` C-036; v1 caps + matching `content_hash` | **honesty.** `legacy-graph-only`; served caps `["knowledge-graph-v1"]` |
| H-C036-STRIP-KEEP-LABELS | `DROP` C-036; keep four v2/reviewed strings | **HOLD.** `invalid_manifest:capabilities` |

v1 verify still ignores extra payload files (`evidence/`, witnesses). Labels cannot be laundered through that hole because they never enter `ManifestV1`.

### Raw labels through list / activate / resource / MCP

`list_packs` → `inspect_verified_manifest` → `activate_pack` → `_load_manifest` still returns **raw** JSON after verify. Parser rejection makes non-allowlisted capability strings unlistable. Measured: every refused disguise is absent from `list_packs` ids; activate/resource/load raise `PackIntegrityError`; CLI never prints `Traceback` or `PackedV2ClosureRefused`.

Named R6 recipe `v1-keep-labels` (`schema=1`, four authority strings, sqlite digest unchanged): `load_pack` fails; session stays on `honest-v2-20260824-155552`.

### R1–R5 highest-risk re-runs (HOLD)

| ID | Attack | Result |
|---|---|---|
| H-CAP-FORGE | add reviewed/sourced on unreviewed; hashes untouched | `invalid_manifest:capabilities` |
| H-CAP-FORGE-REHASH | same after inventory rehash | `invalid_manifest:capabilities` |
| H-WIT-REC-DELETE | unlink `receipt-inventory.json` | `missing_artifact:receipt-inventory.json` |
| H-WIT-FP-DELETE | unlink `source-fingerprint.json` | `missing_artifact:source-fingerprint.json` |
| H-WIT-FP-SUBSTITUTE | `{"entries":[]}` + rehash | `invalid_manifest:capabilities` |
| H-WIT-REC-DIGEST | zero first `body_digest` + rehash | `invalid_manifest:capabilities` |
| H-INCOMPLETE-KEEP-REVIEWED | delete one citation; rewrite closure+counts; rematerialize; keep reviewed | `invalid_manifest:closure` |
| H-SKIP-UNREV-KEEP-EV | delete one citation; `DROP` C-036; pop `evidence_mode`+`closure`; claim unreviewed evidence caps; rematerialize | `invalid_manifest:closure`. `load_pack` fails; session unchanged |
| H-SKIP-KEEP-REVIEWED | cite delete; strip contract; keep reviewed labels; hashes not rematerialized | `tampered_artifact:pack.sqlite` (fails before serve) |
| H-SAMEID-PACKED | packed `selected_text+='X'` keep id + rehash | `invalid_manifest:capabilities` |
| H-SAMEID-PACKED-BOTH | packed text+hash edit + rehash | `invalid_manifest:capabilities` |
| H-SAMEID-LIVE-TEXT | live text-only cite edit, then `build_pack` | `PackReadinessRefused` `c036_stale:c036`; no pack |
| H-SAMEID-LIVE-BOTH | live text+hash cite edit, then `build_pack` | `PackReadinessRefused` `stale_receipt:citation`; no pack |
| H-PRIOR-SESSION | load honest; `load_pack` of closure-strip and of `v1-keep-labels` | **HOLD.** both `PackIntegrityError`; lookup id and `pack_id` unchanged |

## Residuals (non-blocking)

### L1 — extra sibling keys on a verifying v1 pack are still raw-served

`_parse_v1` does not close the JSON object. A legitimate v1 allowlist plus `"reviewed": true` or `"integrity_level": "evidence-self-contained-v2"` verifies as `legacy-graph-only`. `list_packs` / `activate_pack.manifest` / `resource_manifest` echo those sibling keys. Product authority is the `capabilities` array (still only `knowledge-graph-v1`). MCP `_provenance` uses the verifier receipt `integrity_level` (`legacy-graph-only`), not the raw sibling. Same unsigned-extra-field class as historical v1 `created_ts` / owner. Not a C-036 or capability mint.

### L2 — `True` / `1.0` / `null` schema values route as v1

Python `match` equality. Fail-safe: v1 allowlist still applies. String / `false` refuse. Not an authority path.

### L3 — inventory-only / knowledge-graph-v2-only incomplete packs

Unchanged from the R5 final review. No reviewed/sourced mint. Not re-run as a named R6 vector.

## Why R6 is enough for the named bypass

```
match raw.get("pack_schema_version", 1):
    case 1 | None:
        return _parse_v1(raw)   # refuse v2 fields + non-allowlisted caps
```

`_verify_v1` never sees raw capabilities. Readers that still `_load_manifest` the JSON cannot advertise strings the parser already refused, because `verify_pack` fails first and discovery / activate / MCP all go through that verify.

## What was not re-run

- Full `.venv/bin/python -m pytest`.
- Bound-socket uvicorn / real stdio MCP (`PackSession` is the same load/list/resource path; session switch was attempted and refused).
- Multi-process writers against one packs dir.

## Confidence

`0.94`

Not 0.95: HTTP/MCP was in-process `PackSession`, not a bound stdio server. The closed authority path does not depend on that — `list_packs` and `activate_pack` already refuse the labels.

## Protected-boundary cleanup

- No read/write of `~/Library/Application Support/ontologylab/` contents. Directory `ino=102434596` `mtime_ns=1785487752937707432` `size=192` unchanged.
- No external network.
- Port 8799 / PID 55560 observe-only: DEVICE `0x1ff51c806b197195`, still `127.0.0.1:8799`.
- Disposable probe root `/private/tmp/ontologylab-wave21-t12-r6sec` and probe script removed. No leftover listeners.
- Product/test bytes MATCH entry freeze. Prior security receipts not rewritten.
- No commit/push. This file is the only durable write.

## Stop

Strict verdict: **PASS**. Maximum severity: none (LOW residuals only).
