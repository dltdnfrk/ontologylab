# Task 12 R1–R6 repair independent manual QA

Date: 2026-08-24
Worker: omo senpi-task `st_01a031ec`
Mode: independent hands-on QA of the **uncommitted** Task 12 R1–R6
repair on HEAD `081d8554f814645517a29a0cef1c0e32af3d84df`. Real
`python -m ontologylab.pack_readiness`, standalone
`python -m ontologylab.pack_verifier`, `PackSession.document_raw_text`
(process-owned snapshot; not a 16th MCP tool), and real stdio
`python -m ontologylab.mcp_server`. Bounded event-driven subprocess
I/O (write, then `select` + one-line read or process-exit wait). No
sleeps, polling, or retry-to-pass.

Product/test/plan/authority **read-only**. Original
`task-12-review-manual-qa.md` preserved (same inode/mtime/sha256).
No stage, commit, or push. No external network. No live Application
Support open. Port 8799 / PID 55560 observe-only. No full suite.

## Verdict

`PASS`

The uncommitted R1–R6 repair reproduced the previously uncovered
paths on one disposable ready reviewed/sourced v2 pack
(`rev-sourced-20260824-133631`) plus sibling excerpt / unreviewed /
tamper fixtures:

- MCP `entity_lookup` / `semantic_search` / `graph_query` /
  `traverse_relations` / `get_entity` returned exact Work /
  Representation / Citation receipt ids, hashes, offsets, and policy
- `document_raw_text` FULL returned the exact 44 source bytes from a
  process-owned snapshot path `evidence/<rep>/full.txt`; excerpt is
  typed `excerpt_only`
- Manifest counts match packed `document_observations` /
  `grounded_review_decisions` / verified node+edge tables;
  exclusions all ≥ 1; `get_staleness.pack_verified_count == 3`
- Closure/build CLI `--evidence-mode none` exits 2 with JSON, no
  traceback, no pack/staging
- Post-publish capability forgery is `invalid_manifest:capabilities`
  for verifier, `list_packs`, `activate_pack`, and MCP `load_pack`
- Valid reviewed/sourced session survives forged and tampered
  replacement

Disposable roots and the QA MCP child are gone. PID 55560 device
`0x1ff51c806b197195` is unchanged.

## Authority actually read (not summaries)

- `task-12-review-repair-executor.md` (R1–R6 DoneClaim)
- `task-12-review-code.md` MAJOR findings that named these paths
- `task-12-review-manual-qa.md` (preserved; not re-run)
- Uncommitted product: `pack_v2_derive.py`, `mcp_server.py`,
  `pack_readiness.py`, `pack_verifier.py`, `pack_v2_manifest.py`,
  `pack_v2_closure.py` (read-only)
- `tests/test_pack_v2_review_repair.py` (read-only contract names)

This run did **not** re-execute pytest. It exercised user surfaces
against the working-tree repair bytes.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match before and after |
| Subject | `test(pack): include evidence mode in signature contract` | match |
| Repair present | uncommitted R1–R6 | `git diff --stat` dirty on 8 tracked + 2 untracked repair files |
| Index | empty | `git diff --cached --quiet` exit 0 |
| Original QA file | unchanged | ino `277395770` mtime_ns `1787544428723817094` size `17337` sha256 `8dc3b41338bdb391e94fc311781d8e8a1f306b10085bb80d02e67e21852212a4` |
| Product writes by this QA | none | only this new evidence file |
| Interpreter | `.venv/bin/python` | used |
| MCP | real stdio | pid 97718 |
| HTTP / 8799 | observe-only | not bound, not retargeted |

Working-tree repair blobs observed at QA start (read-only):

```text
pack_v2_derive.py    53ff5ac530e2e62a5cf069c4a54eca0332a427a3e2c6f245119c5cd5debe0a55
mcp_server.py        137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89
pack_readiness.py    550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21
pack_verifier.py     e9ad5467f6a5cba3d658a21613819fef22b6a1f79d56180f36ceb4395f81cc53
```

Passing root (now deleted):
`/var/folders/l_/vy0kynvx0k1dl0p56z0c3xtc0000gn/T/ontologylab-wave21-task12-repair-mqa.jice0kmb`

Driver (disposable `/tmp`, not a repo write):
`/tmp/ontologylab-wave21-task12-repair-mqa-driver.py`

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | pack_readiness `--publish --evidence-mode full` reviewed/sourced | exit 0; `sourced`; reviewed + sourced-answer-v2 | `rev-sourced-20260824-133631` | PASS |
| S2 | Manifest counts + exclusions | counts = packed tables; all exclusion keys ≥ 1 | observations 1, reviews 3, nodes_v 2, edges_v 1; exclusions 1/1/1/1 | PASS |
| S3 | pack_readiness `--help` | exit 0; lists `--evidence-mode` | EXIT 0 | PASS |
| S4 | `--evidence-mode none` | exit 2 JSON; no traceback; no residue | `sourced_none:source`; stderr empty; visible `[]` | PASS |
| S5 | verifier `--help` + happy | exit 0 both | schema 2; hash `sha256:ab4b695b…` | PASS |
| S6 | Post-publish capability forgery | verifier/list/activate refuse | `invalid_manifest` path `capabilities`; forged id absent from list; activate PackIntegrityError | PASS |
| S7 | `document_raw_text` FULL | exact bytes from process-owned snapshot | 44-byte text; path `evidence/rep-16a19b74f720/full.txt`; serving ≠ published | PASS |
| S8 | `document_raw_text` excerpt | typed limitation; no full text | `available=false` `limitation=excerpt_only` `text=null` | PASS |
| S9 | stdio entity/search/graph/traverse | exact Work/Rep/Citation receipts + pack schema 2 | all four match packed `citation_receipts`/`documents`; 15 tools | PASS |
| S10 | `get_staleness` | nonzero `pack_verified_count` | `3` == 2+1 verified | PASS |
| S11 | forged + tampered replacement | `isError`; prior session holds | both refuse; lookup still `f5862793…` on reviewed pack | PASS |
| S12 | MCP EOF | exit 0; snapshots gone | pid 97718 rc=0; leftovers `[]` | PASS |
| S13 | cleanup + boundary | original QA + 8799/AS/plan/HEAD unchanged | proven below | PASS |

## Commands and outputs

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Env: no `DATA_DIR`; no `PYTEST_*`; no `ONTOLOGYLAB_OFFLINE`.

Plant: ready reviewed/sourced snapshot with C-036 plus the four
exclusion rows (proposed ungrounded node, pack-ineligible waiver,
`resolve_collision`, quarantined H1 citation). Published via CLI.

### S1 / S2 — publish + inspect

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_readiness",
       ".../reviewed/kg.sqlite", "--publish", ".../packs",
       "--name", "rev-sourced", "--evidence-mode", "full"]
EXIT: 0
{"c036_receipt_id":"c036-valid",
 "capabilities":["knowledge-graph-v2","evidence-self-contained-v2",
                 "reviewed","sourced-answer-v2"],
 "generation":1,"ok":true,
 "pack_id":"rev-sourced-20260824-133631",
 "publication_scope":"sourced"}

manifest.counts:
  observations=1 review_decisions=3 citations=3
  nodes_verified=2 edges_verified=1 works=2 nodes=2 edges=1
packed sqlite COUNTs: identical
manifest.exclusions:
  ungrounded=1 waived=1 invalid_legacy_evidence=1 identity_conflicts=1
```

### S3 / S4 — --help and closure refusal

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_readiness", "--help"]
EXIT: 0
usage: python -m ontologylab.pack_readiness [-h]
                                            [--check-generation CHECK_GENERATION]
                                            [--publish PUBLISH] [--name NAME]
                                            [--evidence-mode EVIDENCE_MODE]
                                            kg
```

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_readiness",
       ".../reviewed/kg.sqlite", "--publish", ".../packs-none",
       "--name", "none-mode", "--evidence-mode", "none"]
EXIT: 2
stdout: {"code":"sourced_none","member":"source","ok":false}
stderr: (empty — no Traceback)
visible=[] staging=[]
```

### S5 — standalone verifier

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_verifier", "--help"]
EXIT: 0

ARGV: [".venv/bin/python", "-m", "ontologylab.pack_verifier",
       ".../packs/rev-sourced-20260824-133631"]
EXIT: 0
{"ok":true,"pack_id":"rev-sourced-20260824-133631",
 "pack_schema_version":2,
 "pack_content_hash":"sha256:ab4b695b1d58d44c66c95b2988619ec38aac720657f594d2edadd7c994b453be",
 "integrity_level":"evidence-self-contained-v2"}
```

### S6 — post-publish capability forgery

Unreviewed pack `unreviewed-20260824-133632` had `reviewed` and
`sourced-answer-v2` appended to `manifest.json` after publish (mode
restored to 0444).

```text
ARGV: [".venv/bin/python", "-m", "ontologylab.pack_verifier",
       ".../packs/unreviewed-20260824-133632"]
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":"capabilities"}

list_packs usable ids:
  excerpt-20260824-133631          (no reviewed/sourced)
  rev-sourced-20260824-133631      (reviewed + sourced-answer-v2)
  to-tamper-20260824-133632        (no reviewed/sourced)
  unreviewed-20260824-133632       ABSENT

activate_pack(.../unreviewed-20260824-133632):
  PackIntegrityError: pack 'unreviewed-20260824-133632' is unverifiable:
  invalid_manifest:capabilities; rebuild the pack so its integrity can
  be verified at load time
```

### S7 / S8 — document_raw_text

`document_raw_text` is a `PackSession` method (same logic MCP would
use). It is **not** a 16th FastMCP tool (`tools/list` stayed 15).

FULL, after `load_pack` onto a process-owned snapshot:

```text
representation_id=rep-16a19b74f720
evidence_mode=full available=true limitation=null
path=evidence/rep-16a19b74f720/full.txt
text=The PaymentGateway uses the DatabaseService.
pack_schema_version=2 evidence_mode=full
content_hash=sha256:ab4b695b1d58d44c66c95b2988619ec38aac720657f594d2edadd7c994b453be
serving  = .../T/ontologylab-pack-97624-yjuhk7rv/rev-sourced-20260824-133631
published= .../task12-repair-mqa.jice0kmb/packs/rev-sourced-20260824-133631
snapshot file bytes == text  (true)
"documents/" not in path
```

Excerpt pack `excerpt-20260824-133631`:

```text
representation_id=rep-1db0e23ce2af
evidence_mode=excerpt available=false
limitation=excerpt_only text=null path=null
```

### S9 — real stdio MCP provenance

```text
SERVE_ARGV: [".venv/bin/python", "-m", "ontologylab.mcp_server",
             "--packs-dir", ".../packs",
             "--pack", "rev-sourced-20260824-133631"]
MCP_PID=97718
initialize.protocolVersion=2025-06-18
tools/list count=15  (document_raw_text absent)
```

Packed sqlite receipts for node `f586279349434e96b07681098b9d404d`
(compared field-for-field to every tool row):

```text
work_id=work-489adfc91750
representation_id=rep-16a19b74f720
representation_content_hash=sha256:24c97a0eefe5a9ea67059607c4e3a57779ef0f6b23673cc11f091e2a2a071263
citation_id=sha256:2ce8d7392025ec64b524cbae37cd422b69d6e96d4cf72120e70664326cf6d63e
selected_text_hash=sha256:6af7820e0e2abdd15e0e44fe60ed6f5c3d2f4b19c1c59534e68e5101c7eaa925
start_offset=4 end_offset=18
policy_identity=sha256:9b7403c72d206a7903c57a6575d8ad744829cab7be3cf4acabb60a2239dd62c8
```

`entity_lookup`, `semantic_search`, `graph_query` node, and
`traverse_relations` node all returned those exact eight fields.
`get_entity.citation_id` was the same citation. Graph edge carried
its own citation `sha256:7ae31a1a0d0811bc7f707f3d0128af7f33b83c35cc6140caeef7820a213951a1`
plus work/representation/policy/offsets. Every tool `pack` object
was schema 2 / `evidence_mode=full` /
`sha256:ab4b695b1d58d44c66c95b2988619ec38aac720657f594d2edadd7c994b453be`.

### S10 — nonzero get_staleness

```text
tools/call get_staleness
pack_verified_count=3
# 2 verified nodes + 1 verified edge from v2 counts
# (latest listed pack by created_ts was excerpt; same 2+1)
store_verified_count=null   # no --live-store; typed unavailable, not zero
```

### S11 — forged / tampered replacement, prior session holds

MCP `list_packs` after forgery + sqlite XOR: usable
`excerpt-20260824-133631`, `rev-sourced-20260824-133631` only.

```text
load_pack unreviewed-20260824-133632
isError=true
text=pack 'unreviewed-20260824-133632' is unverifiable: invalid_manifest:capabilities; ...

load_pack to-tamper-20260824-133632
isError=true
text=pack 'to-tamper-20260824-133632' failed integrity verification: tampered_artifact:pack.sqlite hash mismatch

entity_lookup PaymentGateway after both failures:
id=f586279349434e96b07681098b9d404d
pack_id=rev-sourced-20260824-133631
```

### S12 / S13 — exit and protected boundary

```text
MCP pid 97718 exit=0 leftovers=[]
root_gone=true
orig QA sha256=8dc3b41338bdb391e94fc311781d8e8a1f306b10085bb80d02e67e21852212a4
HEAD=081d8554f814645517a29a0cef1c0e32af3d84df
PID 55560 DEVICE 0x1ff51c806b197195 TCP 127.0.0.1:8799 (LISTEN)
AS ino=102434596 mtime_ns=1785487752937707432 size=192
analysis.md ino=251846735 mtime_ns=1787198701168262937 size=43015
blueprint.md ino=251846738 mtime_ns=1787198279698273142 size=40995
plan.md ino=276402724 mtime_ns=1787540737262102344 size=45752
index empty; this QA wrote no product/test bytes
```

Did not:

- edit `task-12-review-manual-qa.md`
- edit product, tests, plans, or authority docs
- read or write `~/Library/Application Support/ontologylab/` data
- bind, kill, or retarget port 8799 or PID 55560
- use external network
- stage, commit, or push
- run the full suite
- execute Step 9+ or claim production readiness

## Residuals (not blockers)

- `get_staleness.latest_pack_id` was the later excerpt sibling
  (`max(created_ts)`), not the reviewed pack. `pack_verified_count`
  was still the required nonzero `3`. Semantic deltas stayed typed
  unavailable without `--live-store`.
- `document_raw_text` is intentionally not a FastMCP tool (15-tool
  pin). FULL/excerpt were driven through `PackSession` after
  `load_pack`, which is the same snapshot boundary MCP uses.
- Uncommitted repair remains dirty in the worktree; this QA did not
  commit it.

## Stop

Strict verdict: **PASS**.
