# Task 12 Round 6 final uncommitted bytes — independent manual QA

Date: 2026-08-24
Worker: omo senpi-task `st_01a03289`
Mode: independent hands-on QA of the **uncommitted** Task 12 Round 6
v1-disguise gate on HEAD `081d8554f814645517a29a0cef1c0e32af3d84df`.
Real `python -m ontologylab.pack_readiness`, standalone
`python -m ontologylab.pack_verifier`, `list_packs` / `activate_pack`,
in-process `PackSession.load_pack`, and real stdio
`python -m ontologylab.mcp_server`. Bounded event-driven subprocess
I/O (write, then `select` + one-line read or process-exit wait). No
sleeps, polling, or retry-to-pass.

Product/test/plan/authority **read-only**. Prior QA receipts
preserved. No stage, commit, or push. No network. No Application
Support open (directory `lstat` only). Port 8799 / PID 55560
observe-only. No pytest / full suite.

## Verdict

`PASS`

Honest reviewed+sourced v2 `honest-20260824-155616` published via the
readiness CLI, verified, listed, activated, and served over stdio MCP.
Honest builder v1 `legacy-r6-20260824-155618` (`knowledge-graph-v1`
only) plus historical no-capability and methodology-v1 siblings all
verified as `legacy-graph-only` and stayed listable. Exact four-field
reviewed-v2 disguises — explicit `pack_schema_version=1`, omitted
schema, omitted schema + dropped C-036, raw
`knowledge-graph-v2` / `evidence-self-contained-v2` / `reviewed` /
`sourced-answer-v2`, legacy `content_hash` of unchanged `pack.sqlite`
— were refused as typed `invalid_manifest:capabilities` on verifier
CLI (JSON, exit 2, empty stderr, no traceback), `list_packs`,
`activate_pack`, in-process `load_pack`, and stdio MCP `load_pack`
before any session switch. Caps-stripped v1-shaped rewrite that kept
`closure` refused on `closure`. Unknown `admin-override` on a real
builder v1 refused on `capabilities`. Closure-strip and
citation / fingerprint-witness siblings also refused typed. After
every failed load the honest session still returned
`6b6aafae…` / `honest-20260824-155616`.

Entry product SHA-256 == exit product SHA-256. Disposable root
`ontologylab-t12r6-mqa.1cgegnyi` and MCP pid 74369 leftovers are
gone. PID 55560 device `0x1ff51c806b197195` unchanged.

## Authority actually read (not summaries)

- `task-12-review-repair-6-executor.md` (R6 design: `_parse_v1` is the
  v1 trust boundary)
- Uncommitted product read-only: `pack_verifier.py` (`_V1_CAPABILITIES`,
  `_V2_ONLY_FIELDS`, `_parse_v1` / `_parse_v1_capabilities` /
  `_refuse_v2_only_fields`), `pack_readiness.py` CLI, `mcp_server.py`
  `load_pack`
- Prior receipts (not rewritten):
  `task-12-review-manual-qa.md`,
  `task-12-review-repair-manual-qa.md`,
  `task-12-review-repair-2-manual-qa.md`,
  `task-12-review-repair-3-manual-qa.md`,
  `task-12-review-repair-4-manual-qa.md`,
  `task-12-review-repair-4-security-bypass-qa.md`,
  `task-12-review-final-manual-qa.md`

This run did **not** execute pytest.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match before and after |
| Product/test writes by this QA | none | entry hashes == exit hashes |
| Index | empty | cached exit 0 |
| Prior QA receipts | unchanged | ino/mtime/size/sha256 match preflight |
| Interpreter | `.venv/bin/python` | used |
| MCP | real stdio | pid 74369, rc=0, leftovers=[] |
| HTTP / 8799 | observe-only | device `0x1ff51c806b197195` |

Entry = exit product hashes:

```text
ontologylab/mcp_server.py                 137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89
ontologylab/pack_readiness.py             550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21
ontologylab/pack_receipt_seal.py          aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c
ontologylab/pack_v2_closure.py            9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968
ontologylab/pack_v2_manifest.py           64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f
ontologylab/pack_verifier.py              2b64a110fa3789de3a53245e950f73cb8dccc9bdb78025394fbe3316b55130ed
ontologylab/pack_v2_derive.py             7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577
ontologylab/pack_source_fingerprint.py    a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7
ontologylab/pack_v2_validate.py           ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6
tests/test_pack_v2_review_repair.py       622c7602c2f961c4dca98711d409c87123c257227d0610046e6e11a2ba417b76
tests/test_pack_v2_closure.py             96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff
tests/test_pack_v2_verifier.py            78ae23f199897c87841a9dc908bcd168dbfc93162ee4beaa1735a045b80c8ce5
tests/test_packdiff.py                    296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6
```

Verifier inode `274739540` still matches the R6 freeze. Validate /
closure / reader bytes were not touched by this QA.

Prior QA preserved:

```text
task-12-review-manual-qa.md                 sha256=8dc3b413…  ino=277395770
task-12-review-repair-manual-qa.md          sha256=29ed0e0c…  ino=277742305
task-12-review-repair-2-manual-qa.md        sha256=b385d6ed…  ino=277985088
task-12-review-repair-3-manual-qa.md        sha256=43048482…  ino=278245825
task-12-review-repair-4-manual-qa.md        sha256=cf055d27…  ino=278522456
task-12-review-repair-4-security-bypass-qa.md sha256=6914408d… ino=278540065
task-12-review-final-manual-qa.md           sha256=38a8bda2…  ino=278793223
task-12-review-repair-6-executor.md         sha256=6209b4ae…  ino=278990742
```

Passing root (deleted):
`/var/folders/l_/vy0kynvx0k1dl0p56z0c3xtc0000gn/T/ontologylab-t12r6-mqa.1cgegnyi`

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | readiness + verifier `--help` | exit 0 | both EXIT 0 | PASS |
| S2 | CLI publish honest reviewed v2 | reviewed+sourced | `honest-20260824-155616` | PASS |
| S3 | honest builder v1 | verify / list / activate | schema=1 `legacy-graph-only`; caps=`knowledge-graph-v1` | PASS |
| S4 | historical no-cap v1 | verify | EXIT 0; listed; caps absent | PASS |
| S5 | methodology-v1 | verify | EXIT 0; listed; caps=`knowledge-graph-v1`,`methodology-v1` | PASS |
| S6 | disguise schema=1 + raw v2/reviewed/sourced + legacy `content_hash` | typed refuse, no traceback, no list/activate/switch | `invalid_manifest:capabilities` | PASS |
| S7 | disguise omitted schema (same caps + hash) | same refuse | `invalid_manifest:capabilities` | PASS |
| S8 | disguise omitted schema + C-036 drop | same refuse | `invalid_manifest:capabilities` | PASS |
| S9 | v2-only `closure` kept, caps stripped, schema=1 | typed refuse | `invalid_manifest:closure` | PASS |
| S10 | unknown cap on real builder v1 | typed refuse | `invalid_manifest:capabilities` | PASS |
| S11 | spot-check citation delete + rehash | typed refuse | `invalid_manifest:citation` | PASS |
| S12 | spot-check closure-strip + C-036 drop + keep evidence cap | typed refuse | `invalid_manifest:closure` | PASS |
| S13 | spot-check fingerprint witness tamper + rehash | typed refuse | `invalid_manifest:capabilities` | PASS |
| S14 | missing pack path | exit 2 JSON | `invalid_manifest`; stderr empty | PASS |
| S15 | `--evidence-mode none` | exit 2 JSON | `sourced_none`; visible=[] | PASS |
| S16 | stdio MCP load disguises | isError; honest session holds | eight failed loads; id still `6b6aafae…` | PASS |
| S17 | cleanup / hashes / boundary | entry=exit; prior QA + 8799 unchanged | proven below | PASS |

## Commands and outputs

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Env: no `DATA_DIR`; no `PYTEST_*`; no `ONTOLOGYLAB_OFFLINE`;
`PYTHONDONTWRITEBYTECODE=1`.

Plant: authorized combined extra-run + unpublished-doc kg (read-only
use of existing plant helpers; publish/verify/list/activate/MCP were
the real surfaces). Extra run
`sha256:7276ac6035e46858…` and extra doc `b87d13e6772d4525…` /
`unpublished-doc-hash-v1`. Published honest + seven siblings from that
kg via readiness CLI, then mutated six of the siblings (three
four-field disguises, one caps-stripped v2-field rewrite, citation
gap, closure-strip, fingerprint tamper). Separate incomplete kg built
honest builder v1; three clones rewrote capabilities only.

### S1 / S14 — help + bad input

```text
ARGV: python -m ontologylab.pack_readiness --help     EXIT 0
usage: python -m ontologylab.pack_readiness [-h]
                                            [--check-generation CHECK_GENERATION]
                                            [--publish PUBLISH] [--name NAME]
                                            [--evidence-mode EVIDENCE_MODE]
                                            kg

ARGV: python -m ontologylab.pack_verifier --help      EXIT 0
usage: python -m ontologylab.pack_verifier [-h] [--working WORKING] pack_dir

ARGV: python -m ontologylab.pack_verifier .../no-such-pack
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":".../no-such-pack"}
stderr empty; Traceback absent
```

### S2 — honest reviewed v2

```text
ARGV: python -m ontologylab.pack_readiness \
      .../kg.sqlite --publish .../packs \
      --name honest --evidence-mode full
EXIT: 0
{"c036_receipt_id":"c036-valid",
 "capabilities":["knowledge-graph-v2","evidence-self-contained-v2",
                 "reviewed","sourced-answer-v2"],
 "generation":1,"ok":true,
 "pack_id":"honest-20260824-155616",
 "publication_scope":"sourced",
 "receipt_inventory_root":"f0c07a2289757a610807bc9a5594b6ce25b7819246eae5b222e5e00a05f76bcb",
 "source_fingerprint":"11cc979c2ddb8eef95aacdd0c62819951b7d5b72d407f8cc4c19f722295eca08"}

ARGV: python -m ontologylab.pack_verifier .../honest-20260824-155616
EXIT: 0
{"ok":true,"pack_id":"honest-20260824-155616",
 "pack_schema_version":2,
 "integrity_level":"evidence-self-contained-v2",
 "pack_content_hash":"sha256:63b7b6fa4621a8ac32d89ea1daaa42073284fb4e332fc016d0ee942a5e5eb2d6",
 "counts":{"citations":3,"nodes_verified":2,"edges_verified":1,
           "extraction_runs":1,"representations":1,"review_decisions":3}}
stderr empty

packed sqlite runs: only sha256:55657846…   extra 7276ac60… ABSENT
packed sqlite docs: only rep-369d1883680d   extra b87d13e6… ABSENT
receipt-inventory.json     mode=0444  includes extra run
source-fingerprint.json    mode=0444  includes extra doc
```

### S3 / S4 / S5 — honest and legitimate v1

```text
builder: legacy-r6-20260824-155618
  manifest capabilities=["knowledge-graph-v1"]
  pack_schema_version omitted on disk
  verifier EXIT 0  pack_schema_version=1  integrity_level=legacy-graph-only
  content_hash=sha256:e1cc1e3ef0802b7454414262abbc02932dcbb2662717d2d5deece9cb15bf2245
  listed; activate ok; caps ⊆ {knowledge-graph-v1, methodology-v1}

legacy-nocap  (capabilities key deleted)
  verifier EXIT 0  schema=1  legacy-graph-only  listed  activate caps=None

legacy-method (capabilities=["knowledge-graph-v1","methodology-v1"])
  verifier EXIT 0  schema=1  legacy-graph-only  listed  activate those two caps
```

### S6 / S7 / S8 — exact four-field reviewed-v2 disguises

Each sibling started as a published reviewed+sourced v2, then the
manifest was replaced with only `pack_id`, raw v2/reviewed/sourced
caps, and `content_hash` of the unchanged `pack.sqlite`.

```text
d1-schema1-20260824-155616
  keys={pack_id, capabilities, content_hash, pack_schema_version=1}
  content_hash=sha256:91467dbc…

d2-omit-20260824-155616
  keys={pack_id, capabilities, content_hash}
  pack_schema_version ABSENT

d3-c036-20260824-155617
  keys={pack_id, capabilities, content_hash}
  pack_schema_version ABSENT; c036_capability_receipts DROPPED
```

All three:

```text
ARGV: python -m ontologylab.pack_verifier <disguise>
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":"capabilities"}
stderr empty; Traceback absent
list_packs omits the id
activate: PackIntegrityError
  pack '<id>' is unverifiable: invalid_manifest:capabilities; rebuild ...
```

### S9 / S10 — caps-stripped v2 field; unknown cap

```text
d4-field-20260824-155617
  keys={pack_id, pack_schema_version=1, content_hash, closure}
  capabilities ABSENT
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":"closure"}
stderr empty; not listed; activate PackIntegrityError invalid_manifest:closure

legacy-unknown
  capabilities=["knowledge-graph-v1","admin-override"]
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":"capabilities"}
stderr empty; not listed; activate PackIntegrityError invalid_manifest:capabilities
```

### S11 / S12 / S13 — spot-check defects

```text
sib-cite-20260824-155617
  one citation_receipts row deleted (FK off), closure/counts rewritten,
  inventory rematerialized
EXIT: 2  {"code":"invalid_manifest","path":"citation"}
stderr empty; not listed; activate refuse

sib-strip-20260824-155617
  citation deleted + C-036 table dropped; evidence_mode+closure popped;
  capabilities kept as knowledge-graph-v2 + evidence-self-contained-v2;
  hashes rematerialized
EXIT: 2  {"code":"invalid_manifest","path":"closure"}
stderr empty; not listed; activate refuse

sib-fp-20260824-155618
  source-fingerprint.json extra-doc pair stripped; inventory rematerialized
EXIT: 2  {"code":"invalid_manifest","path":"capabilities"}
stderr empty; not listed; activate refuse
```

After all mutants, `list_packs` ids were exactly:

```text
honest-20260824-155616
legacy-method
legacy-nocap
legacy-r6-20260824-155618
```

No disguise, unknown-cap, citation, strip, or fingerprint sibling
appeared.

### S15 — `--evidence-mode none`

Separate authorized kg (root `ontologylab-t12r6-none.*`, removed):

```text
ARGV: python -m ontologylab.pack_readiness \
      .../kg.sqlite --publish .../packs \
      --name none --evidence-mode none
EXIT: 2
{"code":"sourced_none","member":"source","ok":false}
stderr empty; Traceback absent
visible=[]
```

### S16 — stdio MCP + prior session

```text
SERVE: python -m ontologylab.mcp_server --packs-dir …/packs
       --pack honest-20260824-155616
MCP_PID=74369
initialize.protocolVersion=2025-06-18
tools_count=15
  list_packs, get_staleness, load_pack, get_schema, entity_lookup,
  get_communities, get_entity, semantic_search, graph_query,
  traverse_relations, find_path, list_methods, get_method,
  trace_method, list_method_gaps

entity_lookup PaymentGateway:
  id=6b6aafae3a3e4f7bbc0ac98c86b0a178
  pack_id=honest-20260824-155616
```

Failed loads, then lookup still honest (same id + pack after each):

```text
load_pack d1-schema1-20260824-155616  isError  invalid_manifest:capabilities
load_pack d2-omit-20260824-155616     isError  invalid_manifest:capabilities
load_pack d3-c036-20260824-155617     isError  invalid_manifest:capabilities
load_pack d4-field-20260824-155617    isError  invalid_manifest:closure
load_pack sib-cite-20260824-155617    isError  invalid_manifest:citation
load_pack sib-strip-20260824-155617   isError  invalid_manifest:closure
load_pack sib-fp-20260824-155618      isError  invalid_manifest:capabilities
load_pack legacy-unknown              isError  invalid_manifest:capabilities
```

In-process `PackSession` on the same packs dir reproduced the same
typed refuses and held `honest-20260824-155616` / `6b6aafae…`.

### S17 — exit, hashes, boundary

```text
MCP pid 74369 exit=0 leftovers_after=[]
root_gone=true
none-mode root gone
entry_hashes == exit_hashes
prior QA files byte-identical to preflight
HEAD=081d8554f814645517a29a0cef1c0e32af3d84df
PID 55560 DEVICE 0x1ff51c806b197195 TCP 127.0.0.1:8799 (LISTEN)
AS ino=102434596 mtime_ns=1785487752937707432 size=192
plan.md ino=276402724 size=45752
blueprint.md ino=251846738 size=40995
analysis.md ino=251846735 size=43015
```

Did not:

- edit prior QA receipts
- edit product, tests, plans, or authority docs
- read or write Application Support data
- bind/kill/retarget 8799 or PID 55560
- use network, commit, push, pytest, or full suite
- execute Step 9+

## Residuals (not blockers)

- `get_staleness.latest_pack_id` was the later legitimate v1 sibling
  `legacy-method`. `pack_verified_count` was `1` (that v1's verified
  node), not the honest v2 count. The active MCP session still served
  honest `6b6aafae…`. Same latest-sibling advisory shape as prior
  rounds; not a disguise listing or session switch.
- Hash-refreshed fingerprint tamper is still named
  `invalid_manifest:capabilities` (C-036 / fingerprint membership)
  rather than a witness-specific member. Still a typed pre-serve
  refuse with no traceback.
- Uncommitted R6 verifier repair remains dirty; this QA did not
  commit it.

## Stop

Strict verdict: **PASS**.
