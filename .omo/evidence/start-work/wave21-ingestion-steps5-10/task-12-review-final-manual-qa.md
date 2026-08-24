# Task 12 final uncommitted repair bytes — independent manual QA

Date: 2026-08-24
Worker: omo senpi-task `st_01a03272`
Mode: independent hands-on QA of the **uncommitted** Task 12 final
repair bytes on HEAD `081d8554f814645517a29a0cef1c0e32af3d84df`. Real
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

Honest combined extra-run + unpublished-doc pack
`honest-20260824-152910` published reviewed+sourced, verified, listed,
activated, and served over stdio MCP. Packed sqlite / evidence omitted
both extras; `receipt-inventory.json` and `source-fingerprint.json`
were inventoried mode `0444` and were the only place those extras
appeared. Exact work/representation/citation receipts and FULL raw
text matched the claimed document; unpublished extra returned
`unknown_representation`. Witness tamper, hash-refreshed citation
deletion, hash-refreshed packed-document deletion, and the exact
citation-delete + C-036 drop + `evidence_mode`/`closure` strip while
keeping `evidence-self-contained-v2` all refused as typed
`invalid_manifest` on verifier CLI / list / activate / MCP
`load_pack`, with empty stderr (no traceback) and no serve. After
every failed load the prior honest session still returned
`8c74d275…` / `honest-20260824-152910`. Forged reviewed labels,
`--evidence-mode none`, missing pack path, honest unreviewed v2, and
v1 also behaved as required.

Entry product SHA-256 == exit product SHA-256. Disposable root and
MCP pid 81357 leftovers are gone. PID 55560 device
`0x1ff51c806b197195` unchanged.

## Authority actually read (not summaries)

- `task-12-review-repair-5-executor.md`
- `task-12-review-repair-4-security-bypass-qa.md` (H-SKIP-UNREV-KEEP-EV recipe)
- Uncommitted product read-only: `pack_v2_validate.py`,
  `pack_readiness.py`, `pack_verifier.py`, `mcp_server.py`
- Prior receipts (not rewritten):
  `task-12-review-manual-qa.md`,
  `task-12-review-repair-manual-qa.md`,
  `task-12-review-repair-2-manual-qa.md`,
  `task-12-review-repair-3-manual-qa.md`,
  `task-12-review-repair-4-manual-qa.md`

This run did **not** execute pytest.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match before and after |
| Product/test writes by this QA | none | entry hashes == exit hashes |
| Index | empty | cached exit 0 |
| Prior QA receipts | unchanged | ino/mtime/size/sha256 match preflight |
| Interpreter | `.venv/bin/python` | used |
| MCP | real stdio | pid 81357 |
| HTTP / 8799 | observe-only | device `0x1ff51c806b197195` |

Entry = exit product hashes:

```text
ontologylab/mcp_server.py                 137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89
ontologylab/pack_readiness.py             550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21
ontologylab/pack_receipt_seal.py          aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c
ontologylab/pack_v2_closure.py            9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968
ontologylab/pack_v2_manifest.py           64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f
ontologylab/pack_verifier.py              ac2d55740ea1e7e6df4aaa2155ad8ca331f3b6447d86015a0bddc9e9bbf6907c
ontologylab/pack_v2_derive.py             7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577
ontologylab/pack_source_fingerprint.py    a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7
ontologylab/pack_v2_validate.py           ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6
tests/test_pack_v2_review_repair.py       483ce682f024d7462503c530d45c4bcd536750582a055f9c49952a9c93383015
tests/test_pack_v2_closure.py             96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff
tests/test_pack_v2_verifier.py            5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b
tests/test_packdiff.py                    296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6
```

Prior QA preserved:

```text
task-12-review-manual-qa.md                 sha256=8dc3b413…  ino=277395770
task-12-review-repair-manual-qa.md          sha256=29ed0e0c…  ino=277742305
task-12-review-repair-2-manual-qa.md        sha256=b385d6ed…  ino=277985088
task-12-review-repair-3-manual-qa.md        sha256=43048482…  ino=278245825
task-12-review-repair-4-manual-qa.md        sha256=cf055d27…  ino=278522456
task-12-review-repair-4-security-bypass-qa.md sha256=6914408d… ino=278540065
```

Passing root (deleted):
`/var/folders/l_/vy0kynvx0k1dl0p56z0c3xtc0000gn/T/ontologylab-t12-final-mqa.4m7cpwr0`

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | readiness + verifier `--help` | exit 0 | both EXIT 0 | PASS |
| S2 | CLI publish honest combined | reviewed+sourced | `honest-20260824-152910` | PASS |
| S3 | extras unshipped; both witnesses 0444 | extras only in witnesses | run/doc absent from sqlite; INV+FP inventoried | PASS |
| S4 | verifier happy + missing path | 0 / 2 `invalid_manifest` | observed | PASS |
| S5 | FULL raw text + extra doc | claimed bytes; extra unavailable | extra `unknown_representation` | PASS |
| S6 | excerpt limitation | `excerpt_only` | `available=false` | PASS |
| S7 | `--evidence-mode none` | exit 2 JSON | `sourced_none`; stderr empty | PASS |
| S8 | forged caps | refuse | `invalid_manifest:capabilities` | PASS |
| S9 | delete citation + rehash | typed refuse, no traceback | `invalid_manifest:citation` | PASS |
| S10 | delete document+evidence + rehash | typed refuse, not hash mismatch | `invalid_manifest:capabilities` | PASS |
| S11 | tamper FP + inventory witnesses | typed refuse | both `invalid_manifest:capabilities` | PASS |
| S12 | closure-strip + C-036 drop + keep evidence cap | typed refuse, no serve | `invalid_manifest:closure` | PASS |
| S13 | stdio query + receipts + omit unpublished | exact receipts; no leak | all four tools match; stale=3 | PASS |
| S14 | MCP load siblings | isError; prior session holds | five mutants refuse; id still `8c74d275…` | PASS |
| S15 | v1 / unreviewed | both verify | unreviewed EXIT 0; v1 schema=1 | PASS |
| S16 | cleanup / hashes / boundary | entry=exit; prior QA + 8799 unchanged | proven below | PASS |

## Commands and outputs

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Env: no `DATA_DIR`; no `PYTEST_*`; no `ONTOLOGYLAB_OFFLINE`;
`PYTHONDONTWRITEBYTECODE=1`.

Plant: ready reviewed/sourced fixture, extra unshipped run, unpublished
document `ec3e98cfeb6e40f4a894c4f149cdca3f` /
`unpublished-doc-hash-v1`, reseal ledger, bind C-036. Published seven
sibling packs from that kg via readiness CLI, then mutated five of
them (witness tamper; citation delete; packed document+evidence
delete; exact H-SKIP-UNREV-KEEP-EV strip) with
`PRAGMA foreign_keys=OFF` and rematerialized inventory hashes so the
refuse is not `tampered_artifact`. Separate sealed kg published
unreviewed + forged. v1 built with `allow_incomplete_extraction`.

### S1 / S2 — help + honest publish

```text
ARGV: python -m ontologylab.pack_readiness --help     EXIT 0
ARGV: python -m ontologylab.pack_verifier --help      EXIT 0

ARGV: python -m ontologylab.pack_readiness \
      .../live/kg.sqlite --publish .../packs \
      --name honest --evidence-mode full
EXIT: 0
{"c036_receipt_id":"c036-valid",
 "capabilities":["knowledge-graph-v2","evidence-self-contained-v2",
                 "reviewed","sourced-answer-v2"],
 "generation":1,"ok":true,
 "pack_id":"honest-20260824-152910",
 "publication_scope":"sourced",
 "receipt_inventory_root":"f0297299671e93cd34d41d70f0d57add29fbdfe09321140f16684c5b7083be8e",
 "source_fingerprint":"0cbc26ed840d02dfc87387d6aafedb7f0295cbf2933eb090a4e0f9c013a654dd"}

siblings: sib-cite-20260824-152910
          sib-doc-20260824-152911
          sib-fp-20260824-152911
          sib-inv-20260824-152911
          sib-bypass-20260824-152911
          excerpt-20260824-152911
```

### S3 — honest witnesses

```text
capabilities include reviewed + sourced-answer-v2
counts.extraction_runs=1 representations=1 citations=3
      review_decisions=3 nodes_verified=2 edges_verified=1
pack.sqlite runs: only sha256:2893081a…   extra run ABSENT
pack.sqlite docs: only rep-336d33151b31   extra ec3e98cf… ABSENT
evidence/ec3e98cf… ABSENT
receipt-inventory.json     mode=0444  includes extra run
source-fingerprint.json    mode=0444  includes extra doc
artifact_inventory lists both witness files (mode 292 == 0444)
```

### S4 / S5 / S6 / S7 — happy, bad, raw text, none-mode

```text
verifier honest EXIT 0  pack_schema_version=2
  integrity_level=evidence-self-contained-v2
  pack_content_hash=sha256:6689b6caabe03b44850b940f5725ab47bd25df360777cb31c62995d57c2297ce
verifier no-such-pack EXIT 2  {"code":"invalid_manifest"}  stderr empty

document_raw_text claimed:
  available=true path=evidence/rep-336d33151b31/full.txt
  text=The PaymentGateway uses the DatabaseService.
document_raw_text extra ec3e98cf…:
  available=false limitation=unknown_representation
excerpt-20260824-152911:
  available=false limitation=excerpt_only text=null

--evidence-mode none EXIT 2
{"code":"sourced_none","member":"source","ok":false}  stderr empty
visible=[]
```

### S8 / S15 — forged labels, unreviewed, v1

```text
unreviewed-20260824-152912
  publication_scope=unreviewed  c036_receipt_id=null
  verifier EXIT 0  pack_schema_version=2

forged-20260824-152912 += reviewed, sourced-answer-v2
EXIT 2 {"code":"invalid_manifest","path":"capabilities"}  no Traceback
list_packs omits forged
activate: PackIntegrityError invalid_manifest:capabilities

legacy-final-20260824-152912
EXIT 0 pack_schema_version=1 integrity_level=legacy-graph-only
```

### S9 / S10 / S11 / S12 — hash-refreshed mutants

Citation sibling (one `citation_receipts` row deleted, FK off,
closure/counts rewritten, inventory rematerialized):

```text
ARGV: python -m ontologylab.pack_verifier .../sib-cite-20260824-152910
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":"citation"}
stderr empty
list_packs omits sib-cite
activate: PackIntegrityError invalid_manifest:citation
```

Document+evidence sibling (packed `documents` row + `evidence/<rep>/`
removed, FK off, closure/counts rewritten from remaining SQL, hashes
refreshed — **not** `tampered_artifact`):

```text
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":"capabilities"}
stderr empty
list/activate refuse
```

The capability path fires because packed document membership no
longer matches the inventoried `source-fingerprint.json` / C-036
fingerprint. Still a typed pre-serve refuse.

Fingerprint witness sibling (extra-doc pair stripped, hashes
refreshed) and receipt-inventory sibling (extra run stripped, hashes
refreshed):

```text
both EXIT 2 {"code":"invalid_manifest","path":"capabilities"}
stderr empty; list/activate refuse
```

Bypass sibling — exact frozen recipe: delete one citation, drop
C-036, pop `evidence_mode`+`closure`, keep
`knowledge-graph-v2`+`evidence-self-contained-v2`, rewrite
`counts.citations=2`, rematerialize hashes:

```text
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":"closure"}
stderr empty
list_packs ids after mutants: excerpt-20260824-152911, honest-20260824-152910
activate: PackIntegrityError invalid_manifest:closure
```

Honest activate after mutants still
`integrity_level=evidence-self-contained-v2`
`content_hash=sha256:6689b6ca…`.

### S13 / S14 — stdio MCP + prior session

```text
SERVE: python -m ontologylab.mcp_server --packs-dir …/packs
       --pack honest-20260824-152910
MCP_PID=81357
initialize.protocolVersion=2025-06-18
tools_count=15
  list_packs, get_staleness, load_pack, get_schema, entity_lookup,
  get_communities, get_entity, semantic_search, graph_query,
  traverse_relations, find_path, list_methods, get_method,
  trace_method, list_method_gaps
```

Node `8c74d2752d1e4ac196c35162bce145f4` matched field-for-field on
`entity_lookup`, `semantic_search`, `graph_query`, and
`traverse_relations`:

```text
work_id=work-dbde01a6ee1d
representation_id=rep-336d33151b31
representation_content_hash=sha256:24c97a0eefe5a9ea67059607c4e3a57779ef0f6b23673cc11f091e2a2a071263
citation_id=sha256:d5f2d58189ca921cb3e367b646203e68b3adb6d26efcbe1dba8b9fea8b550911
selected_text_hash=sha256:6af7820e0e2abdd15e0e44fe60ed6f5c3d2f4b19c1c59534e68e5101c7eaa925
start_offset=4 end_offset=18
policy_identity=sha256:9b7403c72d206a7903c57a6575d8ad744829cab7be3cf4acabb60a2239dd62c8
pack_schema_version=2
content_hash=sha256:6689b6caabe03b44850b940f5725ab47bd25df360777cb31c62995d57c2297ce
get_staleness.pack_verified_count=3
unpublished_leaked=false
```

Failed sibling loads, then lookup still honest:

```text
load_pack sib-cite    isError  invalid_manifest:citation
load_pack sib-doc     isError  invalid_manifest:capabilities
load_pack sib-fp      isError  invalid_manifest:capabilities
load_pack sib-inv     isError  invalid_manifest:capabilities
load_pack sib-bypass  isError  invalid_manifest:closure
entity_lookup after each:
  id=8c74d2752d1e4ac196c35162bce145f4
  pack_id=honest-20260824-152910
```

### S16 — exit, hashes, boundary

```text
MCP pid 81357 exit=0 leftovers_after=[]
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

- Hash-refreshed **document** deletion is refused as
  `invalid_manifest:capabilities` (fingerprint/C-036 membership)
  before the closure validator names `representation`. Citation
  deletion reaches `citation`. The H-SKIP-UNREV-KEEP-EV strip now
  reaches `closure`. All are typed pre-serve refuses with no
  traceback.
- `get_staleness.latest_pack_id` was the later excerpt sibling.
  `pack_verified_count` was still nonzero `3`.
- MCP `load_pack forged-20260824-152912` returned
  `pack directory not found` because that pack lived in a separate
  unreviewed packs dir, not the MCP `--packs-dir`. Forged-label
  refuse itself was observed on verifier / list / activate as
  `invalid_manifest:capabilities`. Session still held honest.
- Uncommitted validator repair remains dirty; this QA did not commit
  it.

## Stop

Strict verdict: **PASS**.
