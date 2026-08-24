# Task 12 independent security review — Wave 2.1 Step 8

Date: 2026-08-24
Reviewer: omo senpi-task `st_01a031f0` (alternate-route recovery after deep provider failed before tools)
HEAD: `081d8554f814645517a29a0cef1c0e32af3d84df`
Lane: path traversal, symlink/hardlink/writable/inode identity, manifest self-reference, missing/extra/nested artifacts, hash canonicalization, SQLite `mode=ro&immutable=1`, verify-copy-reverify TOCTOU, failed switch, source mutation, same-ID receipt tamper, C-036 binding and capability wording.

## Verdict

**NEEDS-FIX** — maximum severity **MEDIUM**.

1 MEDIUM (C-036 `reviewed` / `sourced-answer-v2` labels are not bound into `pack_content_hash` and are not re-derived at verify/use). No CRITICAL. No HIGH. Source DB/files stay immutable. No secret exfil. No network / live Application Support / 8799 / PID 55560 / 9C contact.

Build-time C-036 still refuses reviewed/sourced publication without a matching receipt. The committed verifier and every reader that consumes `inspect_verified_manifest` / `resource_manifest` will then advertise those labels after a post-publish JSON edit that does not change a single payload byte.

## Bound identity

Prior receipts are claims. Current committed bytes:

| Fact | Required | Observed |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match |
| Tree | `8677230e75080e5fae606b8dfac568619bfd569c` | match |
| Product parent | `d740a646574b843e3bb8958823c20fa0e883499f` (`feat(pack): complete verified v2 publication boundary`) | match |
| Signature-repair tip | `081d8554` `test(pack): include evidence mode in signature contract` — `tests/test_methodology_foundation_baseline.py` only | match; product pack bytes unchanged |
| Product/test perimeter SHA-256 | `5bfc7bbd2dcd61ceddc43c31ba5afc2c8590fa36007d6af6748fa8b15f8850e6` | match (`git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml \| LC_ALL=C sort`) |

Entry = exit SHA-256 of the Step 8 product/test freeze (rehashed after probes):

| Path | SHA-256 |
|---|---|
| `ontologylab/mcp_server.py` | `a0767807ea3cd3c44b57edb438f598b34bc99ef55ba4d204dde4321c915f262d` |
| `ontologylab/pack_readiness.py` | `c2c4b13f673f8e46ad2bcd985234e947b184f4d3edbfb2a7a4cfb5b1ce92e0e5` |
| `ontologylab/pack_receipt_seal.py` | `93a51a1e0d32f558da3e6ee4c960e400bd4191849690b57198f2f733dea17751` |
| `ontologylab/pack_v2_closure.py` | `3c82878de02f385584ee3d60970407a362e37d338727f695065eee4e831006e2` |
| `ontologylab/pack_v2_manifest.py` | `f1f629c9b6e492285eaa1ac4e78b6c523fef22275546af80fa419f92332267a4` |
| `ontologylab/pack_verifier.py` | `052ec3d12ece21b4afd31485357a8082b131a55ec19f82527fc02ebc7037872c` |
| `ontologylab/packbuilder.py` | `e903936ec8df14e37396d2c3db579713840cd64f82df8aeb83d4e012e81867b7` |
| `ontologylab/packdiff.py` | `cc148c3d4bd444f2f0cae1e4764ed03b28f6194472c5893d22e2edf5addb0292` |
| `ontologylab/verified_pack_reader.py` | `6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1` |
| `tests/test_mcp_pack_integrity.py` | `25e109033875766b5a24a20b81984e241274341b6eff1b10b204f005e2d7e322` |
| `tests/test_ontology_pack_publication.py` | `cfa25516f0a1fa7aacf03698ad5f5dc29ab9235d736a6b631138f58e8a01f7d2` |
| `tests/test_pack_readiness_refusal.py` | `fc3985fe9d04a31e92d71dbae0cc69d142019d025f498c1e789bfea42868e8e7` |
| `tests/test_pack_v2_closure.py` | `105f97fb4979abcf640e1318dfaac515171466beba96a7e5df39443d5cb1895d` |
| `tests/test_pack_v2_publication_surface.py` | `5ae476936ccc00ae2ad2a3c2576513abb1f3946fbd136ae87bb742500dc5d9ba` |
| `tests/test_pack_v2_verifier.py` | `9bb61f372a09efdac483a04c0b7996ac7a60a369eb9e018e11575d8f819d3660` |
| `tests/test_packdiff.py` | `daae25385e55492289dafd662bb8a5a4a6bc51c4e3ebcd9a9fcca646e74281bc` |
| `tests/test_verified_pack_reader.py` | `7bdfa1c4a2da2fbb472c77d7e629525762eeaa0cd0509fae0ba614d79e7ec095` |

No full suite. No product/test/plan/authority edits. No commit/push. `git diff -- ontologylab tests scripts pyproject.toml` empty at exit.

Authority used (read-only): plan Task 8–11; `06-pack-contract.md` §§1,6–8,10; blueprint C-036 / prohibited sourced-answer claim; Task 8–11 receipts treated as claims and re-measured.

## Threat hypotheses and probes

Disposable roots only under `/private/tmp/ontologylab-wave21-task12-sec*` (removed). Library via `.venv/bin/python`. MCP via in-process `PackSession` (no bind). Real ready unreviewed v2 packs from `_plant_v2` + `_seal_ready` + `build_pack(..., evidence_mode="full")`. Handcrafted v2 inventory packs from `tests/test_pack_v2_verifier._write_v2`. No network.

| ID | Hypothesis | Probe | Result |
|---|---|---|---|
| H-PATH-* | Absolute / `..` / `.` / empty / `\` / `:` inventory paths verify | claimed paths in forged inventory | **REFUTED.** `path_mismatch` |
| H-PATH-SELF | Inventory may name `manifest.json` | `include_manifest_in_inventory` | **REFUTED.** `self_reference` |
| H-SYM-FILE | Extra symlink artifact verifies | `alias.sqlite` → `pack.sqlite` | **REFUTED.** `symlink:alias.sqlite` |
| H-SYM-ROOT | Symlinked pack directory verifies | `os.symlink(pack, root-link)` | **REFUTED.** `symlink` |
| H-SYM-DIR | Directory symlink under `evidence/` verifies | `evidence/rep-1` → outside | **REFUTED.** `symlink:evidence/rep-1` |
| H-HARD-FILE | Extra hardlink verifies | `os.link(pack.sqlite, dup.sqlite)` | **REFUTED.** `hardlink:pack.sqlite` (`nlink!=1`) |
| H-HARD-MAN | Hardlinked manifest verifies | `os.link(manifest, outside)` | **REFUTED.** `hardlink` before parse |
| H-WRITE-0644 | Writable payload verifies | `schema.json` `0644` | **REFUTED.** `writable:schema.json` |
| H-WRITE-MAN | Writable v2 manifest verifies | `manifest.json` `0644` | **REFUTED.** `writable:manifest.json` |
| H-INODE | Serving/copy may share the working sqlite inode | `verify_pack(..., working=pack.sqlite)` | **REFUTED.** `original_inode` |
| H-MISS-NEST | Missing nested evidence verifies | unlink `evidence/rep-1/full.txt` | **REFUTED.** `missing_artifact` |
| H-EXTRA | Extra root file verifies | `notes.txt` `0444` | **REFUTED.** `extra_artifact:notes.txt` |
| H-NEST-EXTRA | Nested extra evidence file verifies | `evidence/rep-1/extra.txt` | **REFUTED.** `extra_artifact` |
| H-CAP-FORGE | Add `reviewed` + `sourced-answer-v2` to an unreviewed pack without touching payload | chmod manifest, extend `capabilities`, chmod back | **CONFIRMED MEDIUM.** `pack_content_hash` unchanged. `verify_pack` ok. `list_packs`, `activate_pack`, MCP `list_packs`, `resource_manifest` all serve the forged labels. |
| H-TOCTOU-CAP | Rewrite capabilities after first verify, before copy | wrap `verify_pack` to edit source on call 1 | **CONFIRMED.** Identity check is `pack_id` + `pack_content_hash` only. Served snapshot carries the new labels. |
| H-TS-FORGE | Forged `created_ts` still listed as latest-usable | set `created_ts=9e18` | **CONFIRMED residual.** Hash unchanged; discovery still returns the pack. |
| H-OWNER-FORGE | Rewrite inventory `owner` / `redistribution` | extra fields not in canonical hash | **CONFIRMED residual.** Verifies. |
| H-SQLITE-URI | Serving open is not `mode=ro&immutable=1` | spy `sqlite3.connect` during `open_store` | **REFUTED.** Serving URI `file://<copy>/pack.sqlite?mode=ro&immutable=1`. Write → `attempt to write a readonly database`. Serving inode ≠ source. |
| H-URI-Q / H-URI-ANCESTOR | `?` in pack path splits the verifier sqlite URI | pack_id / ancestor `evil?mode=rw&…` | **PARTIAL residual.** Untyped `OperationalError` / `DatabaseError`. When the ancestor *is* a sqlite file, `_rederive_counts` opens **that** file (`forged_counts` here). Activate reverify on a `?`-free temp still fail-closes. MCP `safe_pack_component` rejects `?`. Canary bytes unchanged. |
| H-SWITCH | Failed load of a tampered sibling replaces the prior session | load good v2; tamper sibling `schema.json`; `load_pack` | **REFUTED.** `PackIntegrityError` `tampered_artifact:schema.json`; prior `pack_id` / hash / node names unchanged. |
| H-SRC-MUT | Mutate source sqlite + manifest after load | append bytes; inject `attacker` | **REFUTED.** Served node names unchanged; `resource_manifest` has no `attacker`. |
| H-SAMEID-CITE | Keep citation `receipt_id`, change text only | drop append-only trigger; `selected_text+='X'` | **REFUTED as publish.** Seal passes (ID binds `selected_text_hash`, not text). Collect refuses `evidence_hash_mismatch:citation`. Visible packs `[]`. |
| H-SAMEID-CONSISTENT | Keep id, change text **and** hash together | update both columns | **REFUTED.** `stale_receipt:citation` at seal / authorize / build. Visible `[]`. |
| H-SAMEID-REVIEW | Keep review id, change `actor` | drop review trigger | **REFUTED.** `stale_receipt:review_decision`. |
| H-C036-ROOT | C-036 with wrong inventory root authorizes | plant `root="0"*64` + sourced request | **REFUTED.** `c036_stale:c036`. No pack. |
| H-C036-DENY | `decision=deny` authorizes | plant deny row | **REFUTED.** `c036_stale:c036`. |
| H-C036-SCOPE | `scope=reviewed` without `review_publication` sourced still grants `sourced-answer-v2` | plant reviewed C-036 only | **CONFIRMED residual (design).** `publication_scope=reviewed` and `REVIEWED_CAPABILITIES` (both labels). Task 11 wrote this on purpose. |
| H-COPY-NLINK | Serving copy is a hardlink of source | `activate_pack` then `st_nlink` / ino | **REFUTED.** nlink=1; inodes differ. |

Cause of H-CAP-FORGE on committed bytes:

- `pack_v2_manifest._canonical` / `pack_verifier._canonical` hash only `{file_type, mode, path, sha256, size}`.
- `_parse_v2` requires `knowledge-graph-v2`, and `evidence-self-contained-v2` only if some path starts with `evidence/`. Extra capabilities are not rejected and are not re-derived from sqlite/inventory.
- `activate_pack` compares copied vs first `pack_id` and `pack_content_hash`, then `_load_manifest` returns the raw JSON.
- `inspect_verified_manifest` / `list_packs` / `PackSession.resource_manifest` serve that JSON.
- C-036 is **not** copied into the pack (`c036_capability_receipts` is absent from `_V2_ID_TABLES`). After build, the only carrier of `reviewed` / `sourced-answer-v2` is the unsigned capability list.

Canonical miss: `06-pack-contract.md` §7 — “Counts, capabilities, source policy, and schema IDs are re-derived from verified SQLite/inventory before use.” Counts are re-derived. Capabilities are not.

## MEDIUM (blocking)

### M1 — Published unreviewed pack can be relabeled `reviewed` + `sourced-answer-v2` without C-036

Operator path: ordinary ready unreviewed v2 pack (no C-036 table), then chmod `manifest.json`, append the two labels, chmod `0444`. Same `pack_content_hash`. Same sqlite. Same evidence bytes.

Observed on a real `_build_v2(..., evidence_mode="full")` pack:

```
before   capabilities = [knowledge-graph-v2, evidence-self-contained-v2]
after    capabilities = [knowledge-graph-v2, evidence-self-contained-v2, reviewed, sourced-answer-v2]
hash     unchanged
verify   ok, integrity_level=evidence-self-contained-v2
list     forged labels
activate forged labels
MCP list / resource_manifest forged labels
```

The same unsigned field is the verify→copy TOCTOU: edit capabilities after the first `verify_pack` and `activate_pack` hands the new labels to the session because the identity pin does not cover them.

This is not a remote unauth path. It is exactly the threat the inventory verifier exists for (local rewrite of a `0444` published pack). Forged **counts** are refused. Forged **C-036 labels** are not. Build-time `C036_REQUIRED` does not survive first publication.

Do not “fix” this by hashing the whole manifest (self-reference) or by trusting the first capability string. Either (a) put the capability tuple into the canonical hash input **and** refuse any label that is not re-derived, or (b) copy a C-036 / `review_publication` seal into `pack.sqlite` and re-derive `reviewed` / `sourced-answer-v2` from that seal at `verify_pack` / `activate_pack` before any reader sees the manifest list. Unreviewed packs must not be able to grow those two strings.

## LOW residuals (non-blocking)

### L1 — `created_ts` / inventory `owner` / `redistribution` are not hash-bound

Same root as M1. Forged `created_ts` still lists. `get_staleness` ranks by `created_ts` among **verified** manifests, so a lying timestamp can become “latest” without failing verify. Contract §4.3 allows timestamps outside the payload root; C-045 is about unverified latest. Owner/redistribution are described in §7 inventory rows but omitted from `_canonical`.

### L2 — `scope=reviewed` and `scope=sourced` share one capability set

`authorize_publication` grants `sourced-answer-v2` for any valid C-036, including reviewed-only with no `review_publication` sourced row. Matches Task 11’s written contract (`REVIEWED_CAPABILITIES` after any valid C-036). Wording inflation vs a split reviewed-graph / sourced-answer gate, not a C-036 bypass.

### L3 — Verifier sqlite URI is unescaped `file:{path}?mode=ro`

`_rederive_counts` interpolates the path. A pack whose **absolute** path contains `?` & `&` can make SQLite open an ancestor file instead of `pack.sqlite` (measured: existing ancestor sqlite → `forged_counts` against the **wrong** DB). Missing ancestor did not create a file. Activate’s second verify is on a PID temp without `?` and fail-closes if real counts disagree. MCP pack ids cannot contain `?`. Hostile unzip-and-verify paths are the residual; the error is untyped (`DatabaseError` / `OperationalError`), not `PackVerifyRefused`.

### L4 — Citation receipt id binds `selected_text_hash`, not `selected_text`

Inconsistent text/hash is refused at collect (`evidence_hash_mismatch`). Consistent dual update is `stale_receipt` because the hash is in the id. Body digest still includes the raw text, so a live C-036 root would also move. No publish under the old id.

### L5 — First verify opens source sqlite `mode=ro` without `immutable=1`

Correct for a verifier that must see current bytes. Only the process-owned serving copy uses `immutable=1`.

## Controls that hold on committed bytes

- **Path traversal:** `_relpath` rejects `/`, `\`, `:`, empty, `.`, `..`. `safe_pack_component` rejects anything outside `[A-Za-z0-9._-]` on MCP/build pack ids.
- **Symlink / hardlink / writable / inode:** root, manifest, file, and directory symlinks refused; `st_nlink != 1` refused; v2 `0644` payload and manifest refused; `working=` inode set refuses original inodes. `shutil.copyfile` + reverify with `working=source` keeps the serving copy off the source inodes.
- **Self-reference / missing / extra / nested:** `manifest.json` cannot be claimed; every regular file except the manifest is inventoried; extras and holes fail closed.
- **Hash canonicalization of payload files:** `pack_content_hash` is SHA-256 over `json.dumps(sorted-by-path entries, sort_keys=True, separators=(",", ":"))`. Forged `pack_content_hash` / `sqlite_hash` / file bytes refuse. Builder and verifier share the same five-field canonical form.
- **SQLite serving:** `VerifiedPackSnapshot.open_store` → `KGStore.open(..., read_only=True, immutable=True)` → `file://<copy>?mode=ro&immutable=1` (captured). UPDATE refused. Append to the serving file does not change in-connection rows. Source mutation after load does not change served rows or the snapshot manifest.
- **Failed switch:** `load_pack` activates the new snapshot before closing the old one; activate/open/count failures leave the prior session byte-identical.
- **Same-ID receipt tamper at publish:** consistent citation/review body edits are `stale_receipt` before any visible pack or staging. C-036 wrong root / deny / missing (when sourced is requested) refuse `c036_stale` / `c036_required`.
- **Build-time C-036 bind:** generation, fingerprint, inventory root, `decision=authorize`, scope ∈ {reviewed, sourced}. Production never creates the table; absence is unreviewed, not ready-with-labels.

## Focused suite (this review)

```
.venv/bin/python -m pytest \
  tests/test_pack_v2_verifier.py tests/test_verified_pack_reader.py \
  tests/test_mcp_pack_integrity.py tests/test_pack_readiness_refusal.py \
  tests/test_pack_v2_publication_surface.py tests/test_packdiff.py \
  --override-ini='addopts=' -q --tb=line
```

`93 passed, 1 warning in 14.47s` EXIT 0. Warning is third-party Starlette/FastAPI `httpx` deprecation. Those tests never plant a post-publish capability rewrite, so they stay green while M1 holds.

## What was not re-run

- Full `.venv/bin/python -m pytest`.
- Bound-socket uvicorn / real stdio MCP (PackSession is the same load/list/resource path).
- Multi-process writers against one packs dir.

## Confidence

`0.93`

Not 0.95: HTTP/MCP was in-process `PackSession`, not a bound stdio server; URI-injection residual was fail-closed on this host (no created ancestor file, no WAL sidecar); H-C036-SCOPE is documented Task 11 behavior rather than a new bypass.

## Blockers

`verify_pack` / `activate_pack` / discovery must not report `reviewed` or `sourced-answer-v2` unless those labels are re-derived from pack-resident sealed evidence or bound into `pack_content_hash` so a JSON-only edit dies as `forged_hash` / typed capability refusal. Until that is closed, Step 8 is **NEEDS-FIX** for C-036 capability wording.

## Protected-boundary cleanup

- No read/write of `~/Library/Application Support/ontologylab/` contents. Directory mtime still `2026-07-31 17:49:12`.
- No external network.
- Port 8799 / PID 55560 **read-only** before and after: same DEVICE `0x1ff51c806b197195`, still `127.0.0.1:8799`, same argv.
- No 9C identifier opened or queried.
- Disposable probe roots removed (`/private/tmp/ontologylab-wave21-task12-sec` and probe scripts). No leftover listeners from this review. Pre-existing empty `/var/folders/.../ontologylab-pack-*` dirs are ~7.4 days old and were not touched.
- No product/test/plan/canonical edits. No commit/push.
- This file is the only durable write.
- Entry SHA-256 table MATCH exit SHA-256 table.

## Stop

Strict verdict: **NEEDS-FIX**. Maximum severity: **MEDIUM**.
