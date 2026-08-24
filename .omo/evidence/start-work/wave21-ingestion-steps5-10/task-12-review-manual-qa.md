# Task 12 independent manual QA (Wave 2.1 Step 8)

Date: 2026-08-24
Worker: omo senpi-task `st_01a031ec`
Mode: independent hands-on QA on committed HEAD. Installed
`.venv/bin/ontologylab pack-diff`, standalone
`python -m ontologylab.pack_verifier`, v2 publication CLI
`python -m ontologylab.pack_readiness --publish --evidence-mode full`,
and real stdio `python -m ontologylab.mcp_server`. Bounded
event-driven subprocess I/O (write, then `select` + one-line read or
process-exit wait). No sleeps, polling, or retry-to-pass.

No product/test/plan/authority edits. No stage, commit, or push. No
external network. No live Application Support open. Port 8799 / PID
55560 observe-only.

## Verdict

`PASS`

Committed Step 8 on `081d8554f814645517a29a0cef1c0e32af3d84df`
(`test(pack): include evidence mode in signature contract`) reproduced
the required real surfaces on one disposable ready reviewed/sourced
SQLite snapshot plus sibling refusal fixtures:

- `evidence_mode=full` v2 publish with C-036 `sourced` capabilities
- Manifest/files: schema 2, 0444 payload, closure, `full.txt` bytes
- Standalone verifier `--help`, happy, missing path, tampered sqlite
- Real stdio MCP initialize, 15 tools, 7 `pack://` templates,
  `list_packs`, `load_pack`, `resources/read`, `entity_lookup`
- Installed `pack-diff` on two valid v2 packs
- Tampered replacement keeps the prior session
- Source inode/DB/manifest mutation after activation cannot change the
  served response
- Ready-unreviewed publishes; migrating / missing-receipt / no-C036
  refuse with typed codes and no visible pack or staging

Disposable roots and the QA MCP child are gone. PID 55560 inode/device
`0x1ff51c806b197195` is unchanged.

## Authority actually read (not summaries)

- Canonical Step 8 kickoff:
  `.omo/ulw-loop/wave21-step7-representation-grounding-20260824/step8-kickoff.md`
- Plan Task 12 close / QA scenarios:
  `.omo/plans/wave21-ingestion-steps5-10.md` (Tasks 8-12; not edited)
- Task 8-11 executor receipts and Task 10/11 repair notes
- Product-commit verifier: `task-12-product-commit-verifier.md`
  **CONFIRMED** `d740a646574b843e3bb8958823c20fa0e883499f`
- Signature-repair verifier: `task-12-signature-repair-commit-verifier.md`
  **CONFIRMED** `081d8554f814645517a29a0cef1c0e32af3d84df`
- Final committed-state suite receipt: `task-12-final-full-suite.md`
  `2740 passed, 1 skipped, 2 xfailed`, exit 0, perimeter
  `5bfc7bbd2dcd61ceddc43c31ba5afc2c8590fa36007d6af6748fa8b15f8850e6`

This run did **not** re-execute the full suite. It exercised user
surfaces against the committed bytes.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match before and after |
| Subject | `test(pack): include evidence mode in signature contract` | match |
| Parent | `d740a646574b843e3bb8958823c20fa0e883499f` | match |
| Tree | `8677230e75080e5fae606b8dfac568619bfd569c` | match |
| Product/test vs HEAD | clean | `git diff --stat -- ontologylab tests scripts pyproject.toml` empty |
| Index | empty | `git diff --cached --quiet` exit 0 |
| Interpreter | `.venv/bin/python` | used |
| CLI | `.venv/bin/ontologylab` | used for `pack-diff` |
| MCP | real `python -m ontologylab.mcp_server` stdio | pid 88910 |
| HTTP / 8799 | observe-only | not bound, not retargeted |
| Denylist / AS contents | unread | directory metadata only |
| Product/test dirty | none | empty after QA |

Passing root (now deleted):
`/var/folders/l_/vy0kynvx0k1dl0p56z0c3xtc0000gn/T/ontologylab-wave21-task12-mqa.ex3xj38_`

Driver (disposable, `/tmp`, not a repo write):
`/tmp/ontologylab-wave21-task12-mqa-driver.py`

A first driver pass failed only `S6` because the tampered copy directory
was named `verifier-tampered` and the verifier correctly refused
`path_mismatch` before hash checks. The copy was renamed to the claimed
`pack_id` and the whole matrix was re-run on a fresh snapshot. This
report is that second observed run.

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | pack_readiness `--publish --evidence-mode full` on ready reviewed/sourced | exit 0; scope `sourced`; reviewed + sourced-answer-v2 | pack `rev-sourced-20260824-130445`; caps include both | PASS |
| S2 | Inspect manifest/files | v2, hashes, closure, 0444, `full.txt`, no staging | all five files 0444; `full.txt` 44 bytes match; staging `[]` | PASS |
| S3 | verifier `--help` | exit 0; lists `pack_dir` | EXIT 0 | PASS |
| S4 | verifier happy | exit 0; `ok=true`; schema 2 | hash `sha256:3616b993…`; integrity `evidence-self-contained-v2` | PASS |
| S5 | verifier missing path | exit 2; `invalid_manifest` | EXIT 2 | PASS |
| S6 | verifier tampered sqlite | exit 2; `tampered_artifact` | `{"code":"tampered_artifact","path":"pack.sqlite"}` | PASS |
| S7 | ready-unreviewed publish | exit 0; no reviewed/sourced labels | `ready-unreviewed-20260824-130445`; `c036_receipt_id=null` | PASS |
| S8 | installed `pack-diff` two valid v2 packs | exit 0 | EXIT 0; nodes +2 -2 / edges +1 -1 (distinct fixture ids) | PASS |
| S9 | migrating ledger publish | exit 2; `migrating`; no pack/staging | `member=expand`; visible `[]` | PASS |
| S10 | missing policy receipts | exit 2; `missing_receipt` | `member=policy`; visible `[]` | PASS |
| S11 | sourced request, no C-036 | exit 2; `c036_required` | `member=c036`; visible `[]` | PASS |
| S12 | stdio initialize / tools / templates | protocol `2025-06-18`; 15 tools; 7 `pack://` | observed exactly | PASS |
| S13 | list_packs / load_pack / resources/read / entity_lookup | tampered hidden; detached ro snapshot; lookup hits | serving ino `277356956` ≠ source `277356527`; entity `bdf25b9d…` | PASS |
| S14 | tampered replacement | `isError`; prior session unchanged | `tampered_artifact:pack.sqlite hash mismatch`; same entity + pack | PASS |
| S15 | source sqlite + manifest mutation after activation | served bytes/hash unchanged; no `attacker` | hash still `sha256:3616b993…`; attacker absent | PASS |
| S16 | MCP EOF | exit 0; owned snapshots gone | pid 88910 rc=0; leftovers `[]` | PASS |
| S17 | cleanup + PID 55560 | QA gone; 8799/AS/plan/HEAD unchanged | proven below | PASS |

## Commands and outputs

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Interpreter: `.venv/bin/python`
CLI: `.venv/bin/ontologylab`
Env: no `DATA_DIR`; no `PYTEST_*`; no `ONTOLOGYLAB_OFFLINE`. All stores
under the disposable root above. MCP I/O was one JSON-RPC line written,
then `select` on stdout with a 20s bound, then a single `readline`.

### Preflight

```text
HEAD=081d8554f814645517a29a0cef1c0e32af3d84df
subject=test(pack): include evidence mode in signature contract
tree=8677230e75080e5fae606b8dfac568619bfd569c
parent=d740a646574b843e3bb8958823c20fa0e883499f
product_test_diff=
cached_exit=0
PID 55560 ALIVE  TCP 127.0.0.1:8799 (LISTEN)  DEVICE 0x1ff51c806b197195
AS ino=102434596 mtime_ns=1785487752937707432 size=192
analysis.md ino=251846735 mtime_ns=1787198701168262937 size=43015
blueprint.md ino=251846738 mtime_ns=1787198279698273142 size=40995
plan.md ino=276402724 mtime_ns=1787540737262102344 size=45752
```

Plant: ready reviewed/sourced snapshot via the committed test fixture
helpers (`_reviewed_authorized`): complete generation-1 ledger, sourced
`review_publication`, and a C-036 row bound to live fingerprint
`dc7c6bcf301845acdf47be23b35cac5a7ce5fa4fdb3616f6f5d6b12567d1a973` and
receipt-inventory root
`b9c73775e6fde626f4ccb534f07ac0c6dc2c124f3ee735fbfca96d80635c7715`.

### S1 — build evidence_mode=full v2

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_readiness",
       ".../reviewed/kg.sqlite",
       "--publish", ".../packs", "--name", "rev-sourced",
       "--evidence-mode", "full"]
EXIT: 0
{"c036_receipt_id":"c036-valid",
 "capabilities":["knowledge-graph-v2","evidence-self-contained-v2",
                 "reviewed","sourced-answer-v2"],
 "generation":1,"ok":true,
 "pack_id":"rev-sourced-20260824-130445",
 "publication_scope":"sourced",
 "receipt_inventory_root":"b9c73775e6fde626f4ccb534f07ac0c6dc2c124f3ee735fbfca96d80635c7715",
 "source_fingerprint":"dc7c6bcf301845acdf47be23b35cac5a7ce5fa4fdb3616f6f5d6b12567d1a973"}
```

### S2 — inspect manifest / files

```text
pack_schema_version=2
evidence_mode=full
generation=1
integrity_model=sha256-receipt-not-signature
sqlite_hash=sha256:e2462735a6172f103369c2d40597b5315fb83cec443c94b9add1e35a9fa0e09c
pack_content_hash=sha256:3616b99326c0403c42669b416a3fc84e7e4a60f43b9c65a1ba6bd5a04c5e502d
source_material_policy={full_count:1, excerpt_count:0, unavailable_excluded_count:0}
artifact_inventory_len=4  (manifest.json not self-listed)
writable_payload=[]
staging=[]
closure families = work,identifier,redirect,decision,observation,
                   representation,source,run,chunk,citation,
                   review_decision,policy,provenance

rel                              mode   size
evidence/rep-1fec1fa0fe7b/full.txt 0444  44
manifest.json                    0444  5099
pack.sqlite                      0444  491520
provenance.jsonl                 0444  316
schema.json                      0444  2900

full.txt bytes == b"The PaymentGateway uses the DatabaseService."
```

### S3 / S4 / S5 / S6 — standalone verifier CLI

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_verifier", "--help"]
EXIT: 0
usage: python -m ontologylab.pack_verifier [-h] [--working WORKING] pack_dir
```

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_verifier",
       ".../packs/rev-sourced-20260824-130445"]
EXIT: 0
{"ok":true,
 "pack_id":"rev-sourced-20260824-130445",
 "pack_schema_version":2,
 "pack_content_hash":"sha256:3616b99326c0403c42669b416a3fc84e7e4a60f43b9c65a1ba6bd5a04c5e502d",
 "integrity_level":"evidence-self-contained-v2",
 "sqlite_hash":"sha256:e2462735a6172f103369c2d40597b5315fb83cec443c94b9add1e35a9fa0e09c",
 "inventory":4}
```

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_verifier",
       ".../no-such-pack"]
EXIT: 2
{"code":"invalid_manifest","ok":false,
 "path":".../ontologylab-wave21-task12-mqa.ex3xj38_/no-such-pack"}
```

Tampered copy kept the claimed directory name
`to-tamper-20260824-130446`, then one sqlite byte was flipped and mode
restored to 0444:

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_verifier",
       ".../verifier-tampered/to-tamper-20260824-130446"]
EXIT: 2
{"code":"tampered_artifact","ok":false,"path":"pack.sqlite"}
```

### S7 / S8 — ready-unreviewed + pack-diff

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_readiness",
       ".../unreviewed/kg.sqlite",
       "--publish", ".../packs", "--name", "ready-unreviewed",
       "--evidence-mode", "full"]
EXIT: 0
{"c036_receipt_id":null,
 "capabilities":["knowledge-graph-v2","evidence-self-contained-v2"],
 "generation":1,"ok":true,
 "pack_id":"ready-unreviewed-20260824-130445",
 "publication_scope":"unreviewed"}
```

```text
ARGV: [".venv/bin/ontologylab", "pack-diff",
       "--a", "rev-sourced-20260824-130445",
       "--b", "ready-unreviewed-20260824-130445",
       "--packs-dir", ".../packs"]
EXIT: 0
[ontologylab] rev-sourced-20260824-130445 -> ready-unreviewed-20260824-130445
  added node: PaymentGateway
  added node: DatabaseService
  removed node: DatabaseService
  removed node: PaymentGateway
  added edge: PaymentGateway -[uses]-> DatabaseService
  removed edge: PaymentGateway -[uses]-> DatabaseService
[ontologylab] nodes +2 -2 ~0 | edges +1 -1 ~0
```

Two independently planted snapshots; labels match, ids do not. Both
sides were verifier-valid v2 packs.

### S9 / S10 / S11 — refusal outcomes

```text
ARGV: pack_readiness .../migrating/kg.sqlite --publish .../packs-migrating
EXIT: 2
{"code":"migrating","member":"expand","ok":false}
visible=[] staging=[]

ARGV: pack_readiness .../missing-receipt/kg.sqlite --publish .../packs-missing
EXIT: 2
{"code":"missing_receipt","member":"policy","ok":false}
visible=[] staging=[]

ARGV: pack_readiness .../no-c036/kg.sqlite --publish .../packs-noc036
EXIT: 2
{"code":"c036_required","member":"c036","ok":false}
visible=[] staging=[]
```

### S12 / S13 — real stdio MCP

```text
SERVE_ARGV: [".venv/bin/python", "-m", "ontologylab.mcp_server",
             "--packs-dir", ".../packs",
             "--pack", "rev-sourced-20260824-130445"]
MCP_PID=88910
```

`initialize` result:

```text
{"protocolVersion":"2025-06-18",
 "capabilities":{"tools":{"listChanged":false},
                 "resources":{"subscribe":false,"listChanged":false}},
 "serverInfo":{"name":"ontologylab","version":"1"}}
```

`tools/list` (15): `list_packs`, `get_staleness`, `load_pack`,
`get_schema`, `entity_lookup`, `get_communities`, `get_entity`,
`semantic_search`, `graph_query`, `traverse_relations`, `find_path`,
`list_methods`, `get_method`, `trace_method`, `list_method_gaps`.

`resources/templates/list` (7):

```text
pack://{pack_id}/manifest
pack://{pack_id}/schema
pack://{pack_id}/entity/{entity_id}
pack://{pack_id}/term/{term_id}
pack://{pack_id}/xref/{xref_id}
pack://{pack_id}/method/{method_id}
pack://{pack_id}/method/{method_id}/trace/{field_path}
```

`list_packs`: usable ids
`ready-unreviewed-20260824-130445`,
`rev-sourced-20260824-130445`. Active
`rev-sourced-20260824-130445`. In-place tampered sibling
`to-tamper-20260824-130446` absent.

`load_pack` of the reviewed pack:

```text
pack_id=rev-sourced-20260824-130445
content_hash=sha256:3616b99326c0403c42669b416a3fc84e7e4a60f43b9c65a1ba6bd5a04c5e502d
sqlite_path=.../T/ontologylab-pack-88910-_xc8n50r/rev-sourced-20260824-130445/pack.sqlite
serving ino=277356956 mode=0444 writable=false
source  ino=277356527
nodes_verified=2 edges_verified=1
```

`entity_lookup name=PaymentGateway`:

```text
id=bdf25b9d1f4e4a3d9c27de3776a42faf
entity_type=Component status=verified match_score=1.0
source_document_ids=["rep-1fec1fa0fe7b"]
pack.pack_id=rev-sourced-20260824-130445
```

`resources/read pack://rev-sourced-20260824-130445/manifest` returned
the frozen snapshot JSON (`pack_schema_version` 2, same hashes).
`resources/read pack://.../entity/bdf25b9d…` returned the verified
Component with `source_span {start:4,end:18}`.

### S14 — tampered replacement preserves prior session

In-place XOR of `to-tamper-20260824-130446/pack.sqlite`, mode restored:

```text
tools/call load_pack {pack_id: to-tamper-20260824-130446}
isError=true
text=pack 'to-tamper-20260824-130446' failed integrity verification: tampered_artifact:pack.sqlite hash mismatch
```

Follow-up `entity_lookup PaymentGateway` still
`id=bdf25b9d1f4e4a3d9c27de3776a42faf` on
`rev-sourced-20260824-130445` /
`sha256:3616b99326c0403c42669b416a3fc84e7e4a60f43b9c65a1ba6bd5a04c5e502d`.

### S15 — source mutation after activation

Appended `0x00` to the published `pack.sqlite` (same inode `277356527`)
and rewrote published `manifest.json` with `"attacker":"attacker-stdio"`.

Served lookup still `bdf25b9d…`. Served content hash unchanged.
Served manifest resource did not contain `attacker-stdio`.

### S16 — MCP exit

stdin closed; process 88910 exited 0; no
`ontologylab-pack-88910-*` leftovers; MCP stderr empty.

## Cleanup and protected boundary

After QA, the disposable root and MCP child were removed:

```text
root_gone=true
ls: .../ontologylab-wave21-task12-mqa.ex3xj38_: No such file or directory
ls: /tmp/ontologylab-wave21-task12-mqa.*: No such file or directory
owned snapshots for pid 88910: []
pgrep task12-mqa|mcp_server|pack_verifier|pack_readiness: none

# PID 55560 / 8799 unchanged
python3.1 55560  10u  IPv4 0x1ff51c806b197195  TCP 127.0.0.1:8799 (LISTEN)

# Application Support directory metadata unchanged (contents not read)
ino=102434596 mtime_ns=1785487752937707432 size=192

# planning / authority docs unchanged
analysis.md   ino=251846735 mtime_ns=1787198701168262937 size=43015
blueprint.md  ino=251846738 mtime_ns=1787198279698273142 size=40995
plan.md       ino=276402724 mtime_ns=1787540737262102344 size=45752

# product/test worktree
git diff --stat -- ontologylab tests scripts pyproject.toml  → empty
git diff --cached --stat                                     → empty
HEAD                                                         → 081d8554f814645517a29a0cef1c0e32af3d84df
```

Did not:

- read or write `~/Library/Application Support/ontologylab/` data
- bind, kill, or retarget port 8799 or PID 55560
- use external network
- edit planning/authority documents
- edit product or tests
- stage, commit, or push
- run the full suite
- execute Step 9A/9B/9C or claim production readiness
- enable `FULL_V2_AUTHORITY`

## Residuals (not blockers)

- Installed `ontologylab build-pack` still does not take
  `evidence_mode`. The shipped v2 publication CLI observed here is
  `python -m ontologylab.pack_readiness --publish`.
- `pack-diff` of two independently planted fixtures reports add+remove
  of the same labels because node ids differ. Both packs verified.
- Manifest `counts.review_decisions` is `0` while `closure.review_decision`
  lists three grounded receipt ids. The standalone verifier re-derived
  the same `0`, so the count contract is internally consistent; the
  closure family is a separate packed table. Not a surface refusal.
- Six empty pre-existing `ontologylab-pack-*` directories under
  `$TMPDIR`, aged ~7.4 days and not prefixed with this MCP pid, were
  observed and left untouched.

## Stop

Strict verdict: **PASS**.
