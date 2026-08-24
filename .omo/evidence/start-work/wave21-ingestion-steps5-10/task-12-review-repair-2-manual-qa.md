# Task 12 witness-repair (round 2) independent manual QA

Date: 2026-08-24
Worker: omo senpi-task `st_01a031ec`
Mode: independent hands-on QA of the **uncommitted** witness repair
on HEAD `081d8554f814645517a29a0cef1c0e32af3d84df`. Real
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

Authorized reviewed+sourced publish of a live snapshot that also
held one extra valid run (and its chunk) outside claimed closure:

- Pack `rev-extra-20260824-135746` kept `reviewed` + `sourced-answer-v2`
- Extra run `sha256:692af2bb…` is **absent** from pack sqlite
  (`extraction_runs=1`, only claimed run `sha256:48eb9d81…`)
- `receipt-inventory.json` is inventoried, mode `0444`, and is the
  only place the extra run appears (`[run, id, body_digest]`)
- Verify / load / query succeeded
- Tampered witness (extra run stripped, hashes rematerialized):
  verifier/list/activate/MCP all `invalid_manifest:capabilities`;
  prior MCP session still served `f4229a93…`
- Deleted witness on the sibling pack: `missing_artifact:receipt-inventory.json`
- R1–R6 critical paths reconfirmed once on the same roots

Entry product SHA-256 == exit product SHA-256. Disposable roots and
MCP pid 70004 are gone. PID 55560 device `0x1ff51c806b197195`
unchanged.

## Authority actually read (not summaries)

- `task-12-review-repair-2-executor.md`
- `task-12-review-repair-code.md` MAJOR 1 (witness / extra live receipt)
- Prior receipts (not rewritten):
  `task-12-review-manual-qa.md`,
  `task-12-review-repair-manual-qa.md`
- Uncommitted product read-only: `pack_v2_derive.py`,
  `pack_v2_closure.py`, `pack_verifier.py`, `pack_receipt_seal.py`

This run did **not** execute pytest.

## Bound identity

| Fact | Required | Observed |
|---|---|---|
| HEAD | `081d8554f814645517a29a0cef1c0e32af3d84df` | match before and after |
| Product/test writes by this QA | none | entry hashes == exit hashes |
| Index | empty | cached exit 0 |
| Prior manual QA | unchanged | ino/mtime/size/sha256 match preflight |
| Prior repair QA | unchanged | ino `277742305` sha256 `29ed0e0c…` |
| Interpreter | `.venv/bin/python` | used |
| MCP | real stdio | pid 70004 |
| HTTP / 8799 | observe-only | device `0x1ff51c806b197195` |

Entry = exit product hashes:

```text
ontologylab/mcp_server.py            137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89
ontologylab/pack_readiness.py        550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21
ontologylab/pack_receipt_seal.py     aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c
ontologylab/pack_v2_closure.py       24d2e2f31671d988b8a28aec409b360df057d0e12ca57d2820d46c4b6503cba2
ontologylab/pack_v2_manifest.py      64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f
ontologylab/pack_verifier.py         9fa11d41aeda3677725fa222697e98c710e1e0c474d720913eefd3d353bb1273
ontologylab/pack_v2_derive.py        e5ee3cc0b4be2c987d368d72bb9d6d0ee998d1b2156163c357ad83577e3c5946
tests/test_pack_v2_review_repair.py  97cdaaa515ac295de105cdbfc3686feec048b2b69236e10b4969fba039bf1cad
tests/test_pack_v2_closure.py        96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff
tests/test_pack_v2_verifier.py       5be208ea052e9d7f30e3834298da7dc055127817fc37ef038985a219703a302b
tests/test_packdiff.py               296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6
```

Passing root (deleted):
`/var/folders/l_/vy0kynvx0k1dl0p56z0c3xtc0000gn/T/ontologylab-wave21-task12-repair2-mqa.zf1l7crl`

## Scenario matrix

| ID | Surface | Expected | Actual | Verdict |
|---|---|---|---|---|
| S1 | readiness + verifier `--help` | exit 0 | both EXIT 0 | PASS |
| S2 | CLI publish reviewed+sourced + extra live run | exit 0; sourced caps | `rev-extra-20260824-135746` | PASS |
| S3 | Witness vs packed sqlite | extra run unshipped; witness 0444 + inventoried | extra only in `receipt-inventory.json` 3-tuples | PASS |
| S4 | verifier happy + missing path | 0 / 2 `invalid_manifest` | observed | PASS |
| S5 | `document_raw_text` FULL (R3) | exact bytes from snapshot | 44 bytes; serving ≠ published | PASS |
| S6 | excerpt limitation (R4) | `excerpt_only` | `available=false` | PASS |
| S7 | `--evidence-mode none` (R5 + bad input) | exit 2 JSON, no traceback | `sourced_none`; stderr empty | PASS |
| S8 | forged caps (R6) | verifier/list refuse | `invalid_manifest:capabilities`; id absent | PASS |
| S9 | stdio query + receipts + staleness (R1/R2) | exact Work/Rep/Cite; count ≥ 3 | all four tools match; `pack_verified_count=3` | PASS |
| S10 | tamper witness after load | refuse all openers; session holds | `invalid_manifest:capabilities`; lookup still `f4229a93…` | PASS |
| S11 | delete witness sibling | `missing_artifact` | path `receipt-inventory.json` | PASS |
| S12 | MCP EOF | exit 0; snapshots gone | pid 70004 rc=0 | PASS |
| S13 | cleanup / hashes / boundary | entry=exit; prior QA + 8799 unchanged | proven below | PASS |

## Commands and outputs

CWD: `/Users/hyunjun/Documents/MUNI/ontologylab`
Env: no `DATA_DIR`; no `PYTEST_*`; no `ONTOLOGYLAB_OFFLINE`.

Plant: ready reviewed/sourced fixture, then one extra
`put_extraction_receipts` run (`config-unshipped-extra`) that is
valid but not in claimed closure. C-036 bound to the **live**
inventory root (includes the extra run). Published twice via CLI
(`rev-extra`, `rev-extra-del`).

### S1 / S2 — help + publish

```text
ARGV: python -m ontologylab.pack_readiness --help     EXIT 0
ARGV: python -m ontologylab.pack_verifier --help      EXIT 0

ARGV: python -m ontologylab.pack_readiness \
      .../reviewed/kg.sqlite --publish .../packs \
      --name rev-extra --evidence-mode full
EXIT: 0
{"c036_receipt_id":"c036-valid",
 "capabilities":["knowledge-graph-v2","evidence-self-contained-v2",
                 "reviewed","sourced-answer-v2"],
 "generation":1,"ok":true,
 "pack_id":"rev-extra-20260824-135746",
 "publication_scope":"sourced",
 "receipt_inventory_root":"42d8c196bbe3c2346e7b54fbd00f186aa0c68936c6eb12e9dd577ad0046ef868"}
```

Extra live receipts:

```text
extra_run   = sha256:692af2bbf23d91b93751b1111e5ffb3dd80c7190bdc56d202c9dcf32744c5893
extra_chunk = sha256:a65971f674ed953642199347ae259925c900090ea290f74f25a35a4d529a3a20
claimed_run = sha256:48eb9d81617c06e3c6ef9c8081e249cc88b20de28e771d9412db925642864b0f
```

### S3 — packed sqlite vs witness

```text
manifest.capabilities = knowledge-graph-v2, evidence-self-contained-v2,
                        reviewed, sourced-answer-v2
counts.extraction_runs=1 extraction_chunks=1
counts.observations=1 review_decisions=3 nodes_verified=2 edges_verified=1
exclusions keys present (all 0 on this snapshot)

pack.sqlite extraction_run_receipts:
  sha256:48eb9d81…          # claimed only
  extra 692af2bb… ABSENT
pack.sqlite extraction_chunk_receipts:
  sha256:d644243b…          # claimed only
  extra a65971f6… ABSENT

receipt-inventory.json mode=0444 (292)
artifact_inventory includes receipt-inventory.json
witness run ids: claimed 48eb9d81… AND extra 692af2bb…
extra entries (metadata only):
  ["run","sha256:692af2bb…","sha256:149045b9…"]
  ["chunk","sha256:a65971f6…","sha256:b193bb5e…"]
```

The extra receipts exist only as inventoried `[family, id, digest]`
rows. They are not packed table rows.

### S4 — verifier happy / bad

```text
ARGV: python -m ontologylab.pack_verifier .../rev-extra-20260824-135746
EXIT: 0
{"ok":true,"pack_id":"rev-extra-20260824-135746",
 "pack_schema_version":2,
 "integrity_level":"evidence-self-contained-v2"}

ARGV: python -m ontologylab.pack_verifier .../no-such-pack
EXIT: 2
{"code":"invalid_manifest","ok":false,"path":".../no-such-pack"}
```

### S5 / S6 — R3 / R4 document_raw_text

```text
FULL pack (process-owned snapshot ontologylab-pack-69904-ye58jf0x/…):
  path=evidence/rep-79e8438d5c03/full.txt
  text=The PaymentGateway uses the DatabaseService.
  available=true  serving ≠ published

excerpt-20260824-135746:
  available=false limitation=excerpt_only text=null
```

### S7 / S8 — R5 closure refusal + R6 forgery

```text
ARGV: pack_readiness … --evidence-mode none --publish …/packs-none
EXIT: 2
{"code":"sourced_none","member":"source","ok":false}
stderr empty; visible=[]; staging=[]

forged unreviewed-20260824-135746 capabilities += reviewed, sourced-answer-v2
verifier EXIT 2  {"code":"invalid_manifest","path":"capabilities"}
list_packs ids: excerpt, rev-extra, rev-extra-del   (forged id absent)
```

### S9 — stdio MCP query (R1/R2)

```text
SERVE: python -m ontologylab.mcp_server --packs-dir …/packs
       --pack rev-extra-20260824-135746
MCP_PID=70004
initialize.protocolVersion=2025-06-18
```

Packed citation for node `f4229a9350c64b0582f6dd3be5899887` matched
field-for-field on `entity_lookup`, `semantic_search`, `graph_query`,
and `traverse_relations`:

```text
work_id=work-0c2114d6fde2
representation_id=rep-79e8438d5c03
representation_content_hash=sha256:24c97a0eefe5a9ea67059607c4e3a57779ef0f6b23673cc11f091e2a2a071263
citation_id=sha256:a0f284f0d6b370fdb4c57fad6fbd84addc12163c8e092d9bda82100e4018cacd
selected_text_hash=sha256:6af7820e0e2abdd15e0e44fe60ed6f5c3d2f4b19c1c59534e68e5101c7eaa925
start_offset=4 end_offset=18
policy_identity=sha256:9b7403c72d206a7903c57a6575d8ad744829cab7be3cf4acabb60a2239dd62c8
pack_schema_version=2 evidence_mode=full
content_hash=sha256:80461769506c7d4ef956969952f7514d5a21a89cdc3c4b6f456ce990c3c1bb89
get_staleness.pack_verified_count=3
```

### S10 — tamper witness, prior session holds

After load, extra run entry stripped from source
`receipt-inventory.json` and inventory hashes rematerialized:

```text
verifier EXIT 2  {"code":"invalid_manifest","ok":false,"path":"capabilities"}
list_packs: excerpt-20260824-135746, rev-extra-del-20260824-135746
            (rev-extra-20260824-135746 ABSENT)
activate: PackIntegrityError invalid_manifest:capabilities
MCP load_pack same id: isError=true  invalid_manifest:capabilities
entity_lookup after failed reload:
  id=f4229a9350c64b0582f6dd3be5899887
  pack_id=rev-extra-20260824-135746
```

### S11 — delete witness

Sibling `rev-extra-del-20260824-135746` had
`receipt-inventory.json` unlinked:

```text
verifier EXIT 2
{"code":"missing_artifact","ok":false,"path":"receipt-inventory.json"}
list_packs: excerpt-20260824-135746 only
activate: PackIntegrityError missing_artifact:receipt-inventory.json
```

### S12 / S13 — exit, hashes, boundary

```text
MCP pid 70004 exit=0 leftovers=[]
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

- Planting the extra run also minted an extra chunk receipt. That
  chunk is likewise unshipped and appears only as a witness 3-tuple.
  The extra **run** is the named contract; the extra chunk is the
  same unshipped-family pattern.
- `get_staleness.latest_pack_id` was the later excerpt sibling
  (`max(created_ts)`). `pack_verified_count` was still nonzero `3`.
- Uncommitted witness repair remains dirty; this QA did not commit it.

## Stop

Strict verdict: **PASS**.
