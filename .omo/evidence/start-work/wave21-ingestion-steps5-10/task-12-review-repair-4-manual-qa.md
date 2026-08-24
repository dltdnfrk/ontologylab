# Task 12 packed-closure validator (round 4) independent manual QA

Date: 2026-08-24
Worker: omo senpi-task `st_01a031ec`
Mode: independent hands-on QA of the **uncommitted** packed-closure
validator on HEAD `081d8554f814645517a29a0cef1c0e32af3d84df`. Real
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
`honest-20260824-150202` published reviewed+sourced, verified, listed,
activated, and served over stdio MCP. Two hash-refreshed siblings
(delete one citation; delete packed document + evidence with FK off
and rewritten closure/counts) plus a deleted-review sibling all
refused as typed `invalid_manifest` on verifier CLI / list / activate
/ MCP `load_pack`, with empty stderr (no traceback) and no serve.
After those failed loads the prior honest session still returned
`27f12624…`. R1–R6 and both witnesses reconfirmed.

Entry product SHA-256 == exit product SHA-256. Disposable roots and
MCP pid 88665 are gone. PID 55560 device `0x1ff51c806b197195`
unchanged.

## Authority actually read (not summaries)

- `task-12-review-repair-4-executor.md`
- `ontologylab/pack_v2_validate.py` (read-only)
- Prior receipts (not rewritten):
  `task-12-review-manual-qa.md`,
  `task-12-review-repair-manual-qa.md`,
  `task-12-review-repair-2-manual-qa.md`,
  `task-12-review-repair-3-manual-qa.md`

This run did **not** execute pytest.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match before and after |
| Product/test writes by this QA | none | entry hashes == exit hashes |
| Index | empty | cached exit 0 |
| Prior QA receipts | unchanged | ino/mtime/size/sha256 match preflight |
| Interpreter | `.venv/bin/python` | used |
| MCP | real stdio | pid 88665 |
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
ontologylab/pack_v2_validate.py           d6e83fdda3eff5b58e433a6d6d0c840e80ac5efe1f6ca22aec344ac8ca587dcd
tests/test_pack_v2_review_repair.py       0b6371c91c5a35679d58439762ee174cddb06441ec6a32e206c1fc43fd871df4
tests/test_pack_v2_closure.py             96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff
tests/test_pack_v2_verifier.py            5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b
tests/test_packdiff.py                    296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6
```

Prior QA preserved:

```text
task-12-review-manual-qa.md            sha256=8dc3b413…  ino=277395770
task-12-review-repair-manual-qa.md     sha256=29ed0e0c…  ino=277742305
task-12-review-repair-2-manual-qa.md   sha256=b385d6ed…  ino=277985088
task-12-review-repair-3-manual-qa.md   sha256=43048482…  ino=278245825
```

Passing root (deleted):
`/var/folders/l_/vy0kynvx0k1dl0p56z0c3xtc0000gn/T/ontologylab-wave21-task12-repair4-mqa.3niqvl8u`

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | readiness + verifier `--help` | exit 0 | both EXIT 0 | PASS |
| S2 | CLI publish honest combined | reviewed+sourced | `honest-20260824-150202` | PASS |
| S3 | extras unshipped; both witnesses 0444 | extras only in witnesses | run/doc absent from sqlite; INV+FP inventoried | PASS |
| S4 | verifier happy + missing path | 0 / 2 `invalid_manifest` | observed | PASS |
| S5 | FULL raw text + extra doc (R3) | claimed bytes; extra unavailable | extra `unknown_representation` | PASS |
| S6 | excerpt limitation (R4) | `excerpt_only` | `available=false` | PASS |
| S7 | `--evidence-mode none` (R5) | exit 2 JSON | `sourced_none`; stderr empty | PASS |
| S8 | forged caps (R6) | refuse | `invalid_manifest:capabilities` | PASS |
| S9 | delete citation + rehash | typed refuse, no traceback | `invalid_manifest:citation` | PASS |
| S10 | delete document+evidence + rehash | typed refuse, not hash mismatch | `invalid_manifest:capabilities` | PASS |
| S11 | delete review + rehash | typed refuse | `invalid_manifest:review_decision` | PASS |
| S12 | stdio query (R1/R2) | exact receipts; no unpublished leak | all four tools match; stale=3 | PASS |
| S13 | MCP load siblings | isError; prior session holds | all three refuse; id still `27f12624…` | PASS |
| S14 | MCP EOF | exit 0; snapshots gone | pid 88665 rc=0 | PASS |
| S15 | cleanup / hashes / boundary | entry=exit; prior QA + 8799 unchanged | proven below | PASS |

## Commands and outputs

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Env: no `DATA_DIR`; no `PYTEST_*`; no `ONTOLOGYLAB_OFFLINE`.

Plant: ready reviewed/sourced fixture, extra unshipped run
`sha256:5c6858e6…`, unpublished document `743e1bf5…` /
`unpublished-doc-hash-v1`, reseal ledger, bind C-036. Published four
sibling packs from that kg, then mutated three of them with
`PRAGMA foreign_keys=OFF`, rewritten `closure`/`counts` from remaining
SQL/evidence, and rematerialized inventory hashes so the refuse is
not `tampered_artifact`.

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
 "pack_id":"honest-20260824-150202",
 "publication_scope":"sourced"}

siblings: sib-cite-20260824-150202
          sib-doc-20260824-150202
          sib-review-20260824-150203
```

### S3 — honest witnesses

```text
capabilities include reviewed + sourced-answer-v2
counts.extraction_runs=1 representations=1 citations=3 review_decisions=3
pack.sqlite runs: only sha256:79b72d48…   extra 5c6858e6… ABSENT
pack.sqlite docs: only rep-c7ca09c3e6d8   extra 743e1bf5… ABSENT
evidence/743e1bf5… ABSENT
receipt-inventory.json     mode=0444  includes extra run
source-fingerprint.json    mode=0444  includes extra doc
artifact_inventory lists both witness files
```

### S4 / S5 / S6 / S7 / S8 — happy, bad, R3–R6

```text
verifier honest EXIT 0  pack_schema_version=2
verifier no-such-pack EXIT 2  {"code":"invalid_manifest"}

document_raw_text claimed:
  available=true path=evidence/rep-c7ca09c3e6d8/full.txt
  text=The PaymentGateway uses the DatabaseService.
document_raw_text extra 743e1bf5…:
  available=false limitation=unknown_representation
excerpt: available=false limitation=excerpt_only

--evidence-mode none EXIT 2
{"code":"sourced_none","member":"source","ok":false}  stderr empty

forged unreviewed += reviewed, sourced-answer-v2
EXIT 2 {"code":"invalid_manifest","path":"capabilities"}  no Traceback
```

### S9 / S10 / S11 — hash-refreshed incomplete siblings

Citation sibling (one `citation_receipts` row deleted, FK off,
closure/counts rewritten, inventory rematerialized):

```text
ARGV: python -m ontologylab.pack_verifier .../sib-cite-20260824-150202
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
ARGV: python -m ontologylab.pack_verifier .../sib-doc-20260824-150202
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":"capabilities"}
stderr empty
list/activate refuse
```

The capability path fires because packed document membership no
longer matches the inventoried `source-fingerprint.json` / C-036
fingerprint. That is still a typed pre-serve refuse, not a shallow
hash mismatch.

Review sibling (one `grounded_review_decisions` row deleted, rehash):

```text
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":"review_decision"}
stderr empty
list/activate refuse
```

### S12 / S13 — stdio MCP + prior session

```text
SERVE: python -m ontologylab.mcp_server --packs-dir …/packs
       --pack honest-20260824-150202
MCP_PID=88665
initialize.protocolVersion=2025-06-18
```

Node `27f12624bc02438c9777e40b24654c0f` matched field-for-field on
`entity_lookup`, `semantic_search`, `graph_query`, and
`traverse_relations`:

```text
work_id=work-0e56175c2e23
representation_id=rep-c7ca09c3e6d8
representation_content_hash=sha256:24c97a0eefe5a9ea67059607c4e3a57779ef0f6b23673cc11f091e2a2a071263
citation_id=sha256:379a3dacbc4038211c4e91cf3ca5c90a1acee6e221dd0100e8e1f327f8869790
selected_text_hash=sha256:6af7820e0e2abdd15e0e44fe60ed6f5c3d2f4b19c1c59534e68e5101c7eaa925
start_offset=4 end_offset=18
policy_identity=sha256:9b7403c72d206a7903c57a6575d8ad744829cab7be3cf4acabb60a2239dd62c8
pack_schema_version=2
content_hash=sha256:78c4de166480971414370a4beecea9371c6943ef7b7cfd6d746caa4b4e48b3b8
get_staleness.pack_verified_count=3
unpublished_leaked=false
```

Failed sibling loads, then lookup still honest:

```text
load_pack sib-cite    isError  invalid_manifest:citation
load_pack sib-doc     isError  invalid_manifest:capabilities
load_pack sib-review  isError  invalid_manifest:review_decision
entity_lookup after all three:
  id=27f12624bc02438c9777e40b24654c0f
  pack_id=honest-20260824-150202
```

### S14 / S15 — exit, hashes, boundary

```text
MCP pid 88665 exit=0 leftovers=[]
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
  `invalid_manifest:capabilities` (fingerprint/C-036 membership) before
  the new closure validator names `foreign_keys` / `representation`.
  Citation and review deletions reach the validator members
  `citation` and `review_decision`. All three are typed pre-serve
  refuses with no traceback.
- `get_staleness.latest_pack_id` was the later excerpt sibling.
  `pack_verified_count` was still nonzero `3`.
- Uncommitted validator repair remains dirty; this QA did not commit
  it.

## Stop

Strict verdict: **PASS**.
