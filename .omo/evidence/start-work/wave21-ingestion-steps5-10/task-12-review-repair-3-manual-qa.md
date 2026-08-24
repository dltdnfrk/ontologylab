# Task 12 combined-witness (round 3) independent manual QA

Date: 2026-08-24
Worker: omo senpi-task `st_01a031ec`
Mode: independent hands-on QA of the **uncommitted** combined witness
repair on HEAD `081d8554f814645517a29a0cef1c0e32af3d84df`. Real
`python -m ontologylab.pack_readiness`, standalone
`python -m ontologylab.pack_verifier`, `list_packs` / `activate_pack`,
`PackSession.document_raw_text`, and real stdio
`python -m ontologylab.mcp_server`. Bounded event-driven subprocess
I/O (write, then `select` + one-line read or process-exit wait). No
sleeps, polling, or retry-to-pass.

Product/test/plan/authority **read-only**. Prior QA receipts
preserved. No stage, commit, or push. No network. No Application
Support open. Port 8799 / PID 55560 observe-only. No pytest / full
suite.

## Verdict

`PASS`

One authorized live snapshot held **both** an extra valid unshipped
run and an unpublished document. CLI publish stayed reviewed+sourced.
Packed sqlite, evidence tree, and MCP query omitted both extras.
`receipt-inventory.json` and `source-fingerprint.json` were inventoried
mode `0444` and were the only place those extras appeared. Tamper and
delete of **each** witness separately refused verifier / list /
activate / MCP. After fingerprint tamper on the loaded pack, the prior
stdio session still served `323cdb07…`. R1–R6 key surfaces
reconfirmed once.

Entry product SHA-256 == exit product SHA-256. Disposable roots and
MCP pid 71899 are gone. PID 55560 device `0x1ff51c806b197195`
unchanged.

## Authority actually read (not summaries)

- `task-12-review-repair-3-executor.md`
- `task-12-review-repair-2-code.md` MAJOR 1 (fingerprint witness)
- Prior receipts (not rewritten):
  `task-12-review-manual-qa.md`,
  `task-12-review-repair-manual-qa.md`,
  `task-12-review-repair-2-manual-qa.md`
- Uncommitted product read-only: `pack_source_fingerprint.py`,
  `pack_v2_derive.py`, `pack_v2_closure.py`

This run did **not** execute pytest.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match before and after |
| Product/test writes by this QA | none | entry hashes == exit hashes |
| Index | empty | cached exit 0 |
| Prior manual / R1 / R2 QA | unchanged | ino/mtime/size/sha256 match preflight |
| Interpreter | `.venv/bin/python` | used |
| MCP | real stdio | pid 71899 |
| HTTP / 8799 | observe-only | device `0x1ff51c806b197195` |

Entry = exit product hashes:

```text
ontologylab/mcp_server.py                 137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89
ontologylab/pack_readiness.py             550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21
ontologylab/pack_receipt_seal.py          aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c
ontologylab/pack_v2_closure.py            9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968
ontologylab/pack_v2_manifest.py           64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f
ontologylab/pack_verifier.py              9fa11d41aeda3677725fa222697e98c710e1e0c474d720913eefd3d353bb1273
ontologylab/pack_v2_derive.py             7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577
ontologylab/pack_source_fingerprint.py    a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7
tests/test_pack_v2_review_repair.py       d2088b1e863a29b69866a645754561874fe136ad0c09eebdc32e71c3a486914c
tests/test_pack_v2_closure.py             96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff
tests/test_pack_v2_verifier.py            5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b
tests/test_packdiff.py                    296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6
```

Prior QA preserved:

```text
task-12-review-manual-qa.md
  ino=277395770 sha256=8dc3b41338bdb391e94fc311781d8e8a1f306b10085bb80d02e67e21852212a4
task-12-review-repair-manual-qa.md
  ino=277742305 sha256=29ed0e0c4c2dcf82c08456522dd01d1cb76954121ca3b22b15b75e2821ff552c
task-12-review-repair-2-manual-qa.md
  ino=277985088 sha256=b385d6ed7366d0a8f9a376ee16ed663b6db2170e41a99f725fba36139a7da3c3
```

Passing root (deleted):
`/var/folders/l_/vy0kynvx0k1dl0p56z0c3xtc0000gn/T/ontologylab-wave21-task12-repair3-mqa.8c3lggaz`

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | readiness + verifier `--help` | exit 0 | both EXIT 0 | PASS |
| S2 | CLI publish reviewed+sourced + both extras | exit 0; sourced caps | `both-main-20260824-142738` | PASS |
| S3 | Packed omit extras; both witnesses 0444 inventoried | extra run/doc unshipped | sqlite 1 run / 1 doc; extras only in witnesses | PASS |
| S4 | verifier happy + missing path | 0 / 2 `invalid_manifest` | observed | PASS |
| S5 | `document_raw_text` FULL + extra doc (R3) | claimed bytes; extra unavailable | extra `unknown_representation` | PASS |
| S6 | excerpt limitation (R4) | `excerpt_only` | `available=false` | PASS |
| S7 | `--evidence-mode none` (R5 + bad input) | exit 2 JSON | `sourced_none`; stderr empty | PASS |
| S8 | forged caps (R6) | refuse | `invalid_manifest:capabilities` | PASS |
| S9 | stdio query + receipts + omit unpublished (R1/R2) | exact Work/Rep/Cite; no leak; count ≥ 3 | all four tools match; leak=false; stale=3 | PASS |
| S10 | tamper `source-fingerprint.json` after load | refuse; session holds | `invalid_manifest:capabilities`; id still `323cdb07…` | PASS |
| S11 | delete fingerprint sibling | `missing_artifact` | path `source-fingerprint.json` | PASS |
| S12 | tamper `receipt-inventory.json` sibling | refuse | `invalid_manifest:capabilities` | PASS |
| S13 | delete inventory sibling | `missing_artifact` | path `receipt-inventory.json` | PASS |
| S14 | MCP EOF | exit 0; snapshots gone | pid 71899 rc=0 | PASS |
| S15 | cleanup / hashes / boundary | entry=exit; prior QA + 8799 unchanged | proven below | PASS |

## Commands and outputs

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Env: no `DATA_DIR`; no `PYTEST_*`; no `ONTOLOGYLAB_OFFLINE`.

Plant: ready reviewed/sourced fixture, extra unshipped
`put_extraction_receipts` run, unpublished
`insert_document(title=unpublished, hash=unpublished-doc-hash-v1)`,
then reseal ledger and bind C-036 to the **live** fingerprint +
inventory root. Published four sibling packs from that kg.

### S1 / S2 — help + publish

```text
ARGV: python -m ontologylab.pack_readiness --help     EXIT 0
ARGV: python -m ontologylab.pack_verifier --help      EXIT 0

ARGV: python -m ontologylab.pack_readiness \
      .../live/kg.sqlite --publish .../packs \
      --name both-main --evidence-mode full
EXIT: 0
{"c036_receipt_id":"c036-valid",
 "capabilities":["knowledge-graph-v2","evidence-self-contained-v2",
                 "reviewed","sourced-answer-v2"],
 "generation":1,"ok":true,
 "pack_id":"both-main-20260824-142738",
 "publication_scope":"sourced",
 "receipt_inventory_root":"e505b63d6c7e38b60a494c307d56675d196758aba6ba8e22ab23a9e841c5ea49",
 "source_fingerprint":"40450b0086a44fb7aa84f66404a5a6791c8bd7701f33ec96a6dae68b3b6f0d74"}

siblings: both-fp-del-20260824-142738
          both-inv-tamper-20260824-142738
          both-inv-del-20260824-142738
extra_run    = sha256:dadba173d2599d1b07931c2b557ed46ae4e2a6ca679684a12970bee41ec2b80f
extra_doc_id = 5c1e8f64d9c54be3988d2289aab92f24
extra_doc_hash = unpublished-doc-hash-v1
```

### S3 — packed omit vs witness metadata

```text
manifest.capabilities = knowledge-graph-v2, evidence-self-contained-v2,
                        reviewed, sourced-answer-v2
counts.extraction_runs=1 representations=1 nodes_verified=2 edges_verified=1

pack.sqlite documents: only rep-4645a9047ecd
pack.sqlite runs:      only sha256:287a4bc7…   (claimed)
extra run dadba173… ABSENT
extra doc 5c1e8f64… ABSENT
evidence/5c1e8f64…  ABSENT

receipt-inventory.json     mode=0444  inventoried
  run ids: claimed 287a4bc7… AND extra dadba173…
source-fingerprint.json    mode=0444  inventoried
  doc ids: rep-4645a9047ecd AND 5c1e8f64d9c54be3988d2289aab92f24
artifact_inventory paths include both witness files
```

### S4 — verifier happy / bad

```text
ARGV: python -m ontologylab.pack_verifier .../both-main-20260824-142738
EXIT: 0
{"ok":true,"pack_id":"both-main-20260824-142738",
 "pack_schema_version":2,"integrity_level":"evidence-self-contained-v2"}

ARGV: python -m ontologylab.pack_verifier .../no-such-pack
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":".../no-such-pack"}
```

### S5 / S6 — R3 / R4 document_raw_text

```text
claimed FULL (snapshot ontologylab-pack-71770-b5hqx4nq/…):
  path=evidence/rep-4645a9047ecd/full.txt
  text=The PaymentGateway uses the DatabaseService.
  available=true

unpublished extra doc 5c1e8f64…:
  available=false limitation=unknown_representation
  path=null text=null

excerpt-20260824-142739:
  available=false limitation=excerpt_only text=null
```

### S7 / S8 — R5 closure + R6 forgery

```text
ARGV: pack_readiness … --evidence-mode none --publish …/packs-none
EXIT: 2
{"code":"sourced_none","member":"source","ok":false}
stderr empty; visible=[]

forged unreviewed-20260824-142739 += reviewed, sourced-answer-v2
verifier EXIT 2  {"code":"invalid_manifest","path":"capabilities"}
list_packs does not include forged id
activate: PackIntegrityError invalid_manifest:capabilities
```

### S9 — stdio MCP (R1/R2) omits extras

```text
SERVE: python -m ontologylab.mcp_server --packs-dir …/packs
       --pack both-main-20260824-142738
MCP_PID=71899
initialize.protocolVersion=2025-06-18
```

Node `323cdb07e97f419da2d55b96720babd5` matched field-for-field on
`entity_lookup`, `semantic_search`, `graph_query`, and
`traverse_relations`:

```text
work_id=work-ca0b0e66d113
representation_id=rep-4645a9047ecd
representation_content_hash=sha256:24c97a0eefe5a9ea67059607c4e3a57779ef0f6b23673cc11f091e2a2a071263
citation_id=sha256:e0f2588f7d7d57ca203e7e1487b5970e2cab778545b62dc59ac8551cf6829467
selected_text_hash=sha256:6af7820e0e2abdd15e0e44fe60ed6f5c3d2f4b19c1c59534e68e5101c7eaa925
start_offset=4 end_offset=18
policy_identity=sha256:9b7403c72d206a7903c57a6575d8ad744829cab7be3cf4acabb60a2239dd62c8
pack_schema_version=2
content_hash=sha256:59d78f0fc7b20d2bb01fa937d87a1b83a6149ef3af850b300205672ca1ad9e35
get_staleness.pack_verified_count=3
unpublished_leaked=false
```

### S10 — tamper fingerprint, prior session holds

After load, extra-doc pair stripped from source
`source-fingerprint.json` and inventory hashes rematerialized:

```text
verifier EXIT 2  {"code":"invalid_manifest","path":"capabilities"}
list_packs: both-fp-del, both-inv-del, both-inv-tamper, excerpt
            (both-main ABSENT)
activate: PackIntegrityError invalid_manifest:capabilities
MCP load_pack both-main: isError=true  invalid_manifest:capabilities
entity_lookup after failed reload:
  id=323cdb07e97f419da2d55b96720babd5
  pack_id=both-main-20260824-142738
```

### S11 / S12 / S13 — delete/tamper each witness separately

```text
DELETE source-fingerprint.json on both-fp-del-20260824-142738
verifier EXIT 2  {"code":"missing_artifact","path":"source-fingerprint.json"}
list/activate refuse

TAMPER receipt-inventory.json (drop extra run, rematerialize)
      on both-inv-tamper-20260824-142738
verifier EXIT 2  {"code":"invalid_manifest","path":"capabilities"}
list/activate refuse

DELETE receipt-inventory.json on both-inv-del-20260824-142738
verifier EXIT 2  {"code":"missing_artifact","path":"receipt-inventory.json"}
list/activate refuse
```

### S14 / S15 — exit, hashes, boundary

```text
MCP pid 71899 exit=0 leftovers=[]
root_gone=true
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

- Extra run also minted an extra chunk; that chunk is likewise
  unshipped and only in the receipt witness. Same unshipped-family
  pattern as round 2.
- `get_staleness.latest_pack_id` was the later excerpt sibling.
  `pack_verified_count` was still nonzero `3`.
- Uncommitted combined-witness repair remains dirty; this QA did not
  commit it.

## Stop

Strict verdict: **PASS**.
