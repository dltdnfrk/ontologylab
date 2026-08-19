# W1D-F7 — pack discovery rejects malformed packs

Date: 2026-08-14
Files changed: `ontologylab/packbuilder.py`, `ontologylab/server/routes.py`,
`tests/test_pack_discovery_validation.py` (new).

## The bug

`list_packs()` appended whatever `manifest.json` parsed to, as long as a file
named `pack.sqlite` existed next to it. Consequences measured before the fix:

| fixture | `/api/packs` | `/api/mcp/status` |
|---|---|---|
| `{"counts":{}}` + dummy sqlite | count=1, phantom row | count=0 |
| `[]` (JSON array) | 200, `packs=[[]]` | **HTTP 500** `AttributeError: 'list' object has no attribute 'get'` |
| valid `pack_id`, broken sqlite | count=1 | 200 **with a copyable serve command** for a pack that cannot serve |

## Design choice: mark, don't silently drop

`list_packs()` now returns only validated manifests (its contract for
`mcp_server`, CLI, packdiff, and existing tests is unchanged — every element
is a dict with a safe `pack_id` backed by a readable pack.sqlite).

New `scan_packs(packs_dir) -> (packs, unusable)` additionally returns the
rejects. Both HTTP endpoints use it and expose an `unusable` array.

Reasoning: silent exclusion has a real support cost — an operator who hand-
copied a pack directory would see nothing and have no way to learn why. But a
rejected directory must never be *listable as a pack* (that is exactly the
original bug), so it is not returned in `packs` and gets no `serve_command`.
Reporting it in a separate `unusable` array with a human reason gives the
dashboard something to explain without letting garbage back into the pack
list. Directories with no `manifest.json` at all (e.g. an empty dir) are not
pack attempts and remain silently skipped, as before.

Validation performed per directory, in order:
1. `manifest.json` parses (else `manifest.json unreadable: ...`)
2. parsed value is a JSON object (else `manifest.json must be a JSON object, got list/str/int`)
3. `pack_id` is a non-empty string (else `manifest.json has no usable 'pack_id'`)
4. `pack_id` passes `safe_pack_component` (else `invalid pack id '../escape': ...`)
5. `pack.sqlite` exists (else `pack.sqlite is missing`)
6. `pack.sqlite` opens read-only and `nodes`/`edges`/`documents` are queryable
   (else `pack.sqlite is not a usable pack database: file is not a database`)

## JSON shape the UI now receives

`GET /api/packs`:

```json
{
  "packs": [ { "pack_id": "goodpack-20260815-083158", "counts": {...}, "search_tier": "fts5", "content_hash": "sha256:...", "...": "full manifest, unchanged" } ],
  "count": 1,
  "unusable": [ { "pack_dir": "array-manifest", "reason": "manifest.json must be a JSON object, got list" } ],
  "competency": { "...": "unchanged" }
}
```

`GET /api/mcp/status`:

```json
{
  "packs_dir": "/private/tmp/w1df7/packs",
  "packs": [ { "pack_id": "...", "counts": {...}, "created_ts": 1786750318.776059, "serve_command": "python -m ontologylab.mcp_server --packs-dir ... --pack ...", "stdio_config": { "command": "python", "args": [...] } } ],
  "count": 1,
  "unusable": [ { "pack_dir": "no-pack-id", "reason": "manifest.json has no usable 'pack_id'" } ]
}
```

Contract for the Wave-2 `web/app.js` worker:
- `packs[]` is unchanged in element shape; every element is guaranteed to have a
  string `pack_id`. No more blank rows, no more `—000—.mcpb`.
- `unusable[]` is new, always present (possibly `[]`). Each element has exactly
  two string fields: `pack_dir` (the directory name under the packs dir, NOT a
  pack id) and `reason` (operator-facing English). Never a `serve_command`,
  never `counts`. Render it as an advisory block, not as a pack row.
- `count` counts only usable packs and is identical between the two endpoints.

## STEP 1 — failing-first (before any production edit)

```
$ .venv/bin/python -m pytest tests/test_pack_discovery_validation.py --tb=line
...
E   AttributeError: 'int' object has no attribute 'get'
/Users/hyunjun/Documents/MUNI/ontologylab/ontologylab/server/routes.py:2515: AttributeError: 'int' object has no attribute 'get'
E   KeyError: 'unusable'
E   AssertionError: assert [{'pack_id': 'empty-db'}] == []
=========================== short test summary ============================
FAILED tests/test_pack_discovery_validation.py::test_list_packs_returns_only_valid_manifests
FAILED tests/test_pack_discovery_validation.py::test_packs_and_mcp_status_agree_on_usable_packs
FAILED tests/test_pack_discovery_validation.py::test_no_serve_command_for_unusable_pack
FAILED tests/test_pack_discovery_validation.py::test_unusable_packs_are_reported_with_reasons
FAILED tests/test_pack_discovery_validation.py::test_manifest_scalar_and_traversal_pack_id_rejected
FAILED tests/test_pack_discovery_validation.py::test_removing_malformed_fixture_restores_clean_listing
FAILED tests/test_pack_discovery_validation.py::test_truncated_but_valid_sqlite_without_pack_tables_rejected
7 failed, 1 warning in 2.75s
```

(Earlier in the same run, before assertions were reached, `/api/mcp/status`
raised the unhandled `AttributeError` that FastAPI turns into the reported
HTTP 500 `text/plain Internal Server Error`.)

## STEP 3 — mutation check

Production change reverted (`git stash push ontologylab/packbuilder.py
ontologylab/server/routes.py`), tests kept:

```
FAILED tests/test_pack_discovery_validation.py::test_list_packs_returns_only_valid_manifests
FAILED tests/test_pack_discovery_validation.py::test_packs_and_mcp_status_agree_on_usable_packs
FAILED tests/test_pack_discovery_validation.py::test_no_serve_command_for_unusable_pack
FAILED tests/test_pack_discovery_validation.py::test_unusable_packs_are_reported_with_reasons
FAILED tests/test_pack_discovery_validation.py::test_manifest_scalar_and_traversal_pack_id_rejected
FAILED tests/test_pack_discovery_validation.py::test_removing_malformed_fixture_restores_clean_listing
FAILED tests/test_pack_discovery_validation.py::test_truncated_but_valid_sqlite_without_pack_tables_rejected
7 failed, 1 warning in 0.88s
```

Restored (`git stash pop`), byte-identical to the fixed files (`diff -q` on
pre-revert copies → `RESTORED_OK`), and green:

```
$ .venv/bin/python -m pytest tests/test_packbuilder.py tests/test_cli_pack.py tests/test_mcp_session.py tests/test_pack_discovery_validation.py -v
tests/test_packbuilder.py ..                                             [ 14%]
tests/test_cli_pack.py ..                                                [ 28%]
tests/test_mcp_session.py ...                                            [ 50%]
tests/test_pack_discovery_validation.py .......                          [100%]
14 passed, 1 warning in 1.48s
```

Regression sweep over every other `list_packs` consumer:

```
$ .venv/bin/python -m pytest tests/test_server_m8.py tests/test_pipeline_e2e.py \
    tests/test_method_pack_atomicity.py tests/test_ontology_pack_publication.py \
    tests/test_app_isolation.py tests/test_competency_release_gate.py \
    tests/test_security_hardening.py
52 passed, 1 warning in 3.76s
```

## MANUAL QA — real server, ephemeral port, disposable dirs

Server: `python -m ontologylab.serve --port 56687 --data-dir /private/tmp/w1df7/data
--packs-dir /private/tmp/w1df7/packs`, PID 68120. Port 8799 untouched; the real
data dir under `~/Library/Application Support` untouched.

Packs dir contained one real pack plus the three malformed fixtures.

### `curl -i http://127.0.0.1:56687/api/packs`

```
HTTP/1.1 200 OK
date: Fri, 14 Aug 2026 23:32:16 GMT
server: uvicorn
content-length: 2873
content-type: application/json

{"packs":[{"pack_id":"goodpack-20260815-083158","created_ts":1786750318.776059,"schema_version_id":1,"schema_label":"software-docs-v1","source_job_id":null,"counts":{"documents":1,"nodes_verified":2,"edges_verified":1,"entity_types":3,"relation_types":3,"communities":1,"ontology_terms_reviewed":6,"term_aliases_reviewed":0,"term_xrefs_reviewed":0},"search_tier":"fts5","embedding_model":null,"ontologylab_version":"0.1.0","content_hash":"sha256:a96585c829240e1a20308b6694973778568470d03ace4616bb2abd84f2e85191","basis_commit":"0108c370908ac1463e08c4063ec54e3dac37e2b3","staleness_policy":{"pending_verified_count_threshold":0,"description":"pending_verified_count is a backward-compatible count-difference advisory, not semantic truth. Semantic additions, invalidations, and replacements are authoritative; any nonzero delta recommends rebuilding."},"extraction_completeness":{"status":"incomplete","relevant_stream_count":1,"relevant_document_ids":["23ff52253b8d4ee3a78a1afe05982b13"],"unknown_streams":[{"document_id":"23ff52253b8d4ee3a78a1afe05982b13","document_content_hash":"qa-hash-1","schema_version_id":1,"extractor_engine":"mock","extractor_model":"","prompt_version":"","decode_params":"null"}],"incomplete_streams":[],"run_status_counts":{},"chunk_status_counts":{},"override":{"used":true,"operator_intent":"manual qa fixture"}},"semantic_fact_baseline":{"version":1,"fingerprint_algorithm":"sha256-canonical-json-v1","source":"pack.sqlite"},"included_schema_version_ids":[1],"ontology_publication":{"version":1,"review_boundary":"explicit-current-review-fields-v1","xref_verification":"complete-source-license-contract-v1","license_modes":["allow","identifier-only","deny-text"],"external_descriptive_text":"not-in-term-xref-schema"},"capabilities":["knowledge-graph-v1"]}],"count":1,"unusable":[{"pack_dir":"array-manifest","reason":"manifest.json must be a JSON object, got list"},{"pack_dir":"broken-sqlite","reason":"pack.sqlite is not a usable pack database: file is not a database"},{"pack_dir":"no-pack-id","reason":"manifest.json has no usable 'pack_id'"}],"competency":{"questions":[{"question_id":"Q1","question":"Can every verified fact be traced to its exact source document, extraction stream, and approval record?","passed":true,"expected_count":5,"actual_count":5,"missing":[],"spurious":[],"detail":{}},{"question_id":"Q2","question":"Does the extractor produce the exact expected entities and relations from a known document?","passed":true,"expected_count":11,"actual_count":11,"missing":[],"spurious":[],"detail":{"parser_f1":1.0}},{"question_id":"Q3","question":"Does a built pack return exact answers to user queries?","passed":true,"expected_count":5,"actual_count":5,"missing":[],"spurious":[],"detail":{"pack_id":"cq-release-pack-20260815-083217"}}],"all_passed":true,"passed_count":3,"total_count":3,"evaluated_at":1786750337.636629}}
```

### `curl -i http://127.0.0.1:56687/api/mcp/status`

```
HTTP/1.1 200 OK
date: Fri, 14 Aug 2026 23:32:22 GMT
server: uvicorn
content-length: 876
content-type: application/json

{"packs_dir":"/private/tmp/w1df7/packs","packs":[{"pack_id":"goodpack-20260815-083158","counts":{"documents":1,"nodes_verified":2,"edges_verified":1,"entity_types":3,"relation_types":3,"communities":1,"ontology_terms_reviewed":6,"term_aliases_reviewed":0,"term_xrefs_reviewed":0},"created_ts":1786750318.776059,"serve_command":"python -m ontologylab.mcp_server --packs-dir /private/tmp/w1df7/packs --pack goodpack-20260815-083158","stdio_config":{"command":"python","args":["-m","ontologylab.mcp_server","--packs-dir","/private/tmp/w1df7/packs","--pack","goodpack-20260815-083158"]}}],"count":1,"unusable":[{"pack_dir":"array-manifest","reason":"manifest.json must be a JSON object, got list"},{"pack_dir":"broken-sqlite","reason":"pack.sqlite is not a usable pack database: file is not a database"},{"pack_dir":"no-pack-id","reason":"manifest.json has no usable 'pack_id'"}]}
```

Binary observable: both 2xx, both `count: 1`, both name the same single
`goodpack-20260815-083158`, and the three malformed directories appear only
under `unusable`.

## Adversarial probes (live server)

- **malformed input** — added `string-manifest` (`"just a string"`),
  `number-manifest` (`7`), `traversal` (`{"pack_id": "../escape"}`), and an
  empty dir. `/api/mcp/status` stayed `count: 1` and reported:
  `manifest.json must be a JSON object, got str`,
  `invalid pack id '../escape': use only letters, digits, '.', '_', '-' (no path separators)`.
  The empty dir is correctly absent from both lists (no manifest = no pack
  attempt). Covered by `test_manifest_scalar_and_traversal_pack_id_rejected`.
- **stale state** — deleting all malformed fixtures from the running server's
  packs dir returned `unusable: []` and `count: 1` on both endpoints with no
  restart (same PID 68120): discovery is a live filesystem scan, no cache
  added. Covered by `test_removing_malformed_fixture_restores_clean_listing`.
- **misleading success output** — `grep -o -- '--pack [^"]*'` on the status
  body with five malformed fixtures present emits exactly one line,
  `--pack goodpack-20260815-083158`. Covered by
  `test_no_serve_command_for_unusable_pack`.
- concurrency — ruled out: discovery is read-only and pack builds already
  publish atomically via rename into the packs dir, so a scan sees a directory
  either complete or absent; no new window opened.
- auth/permissions — ruled out: the server is loopback-only, single-user, no
  auth surface touched.
- resource exhaustion — ruled out: the sqlite probe opens read-only, runs three
  COUNT(*) statements, and closes in a `finally`; no handle is retained.
- persistence/migration — ruled out: no schema or on-disk format changed; only
  read-side filtering.
- i18n/encoding — ruled out: manifest reading still uses explicit `utf-8` and
  the added strings are the same ASCII diagnostics style as the rest of the file.

## Cleanup

- Server PID 68120 terminated (`kill 68120`, confirmed gone).
- `/private/tmp/w1df7` (data dir, packs dir, fixtures, captures) removed.
- `/private/tmp/w1df7_*.txt`, `/private/tmp/w1df7_*.bak` removed.
- No git commit. No unrelated dirty file modified.
