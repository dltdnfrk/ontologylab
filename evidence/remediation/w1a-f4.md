# W1A-F4: MCP named-pack schema integrity remediation

## Finding and fix

`PackSession.get_schema(pack_id=...)` opened a non-active pack through
`pack_sqlite_path()` and `KGStore.open()` without recomputing the current
`pack.sqlite` SHA-256. It now obtains the path through `_verified_pack()`, the
same current-byte verification used by `load_pack()`, before making the
read-only ephemeral open. The active session is not switched.

The regression contract explicitly lists the named-pack tool read entry points
(`load_pack`, `get_schema`) and compares that list to public non-resource
`PackSession` methods accepting `pack_id`, so a future named-pack tool requires
an integrity assertion.

## Failing-first proof (production code still vulnerable)

Command:

```text
.venv/bin/python -m pytest tests/test_mcp_pack_integrity.py::test_named_pack_read_surface_rejects_current_tampered_bytes -v
```

Output:

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/hyunjun/Documents/MUNI/ontologylab
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 1 item

tests/test_mcp_pack_integrity.py F                                       [100%]

=================================== FAILURES ===================================
_________ test_named_pack_read_surface_rejects_current_tampered_bytes __________

tmp_path = PosixPath('/private/var/folders/l_/vy0kynvx0k1dl0p56z0c3xtc0000gn/T/pytest-of-hyunjun/pytest-12930/test_named_pack_read_surface_r0')

    def test_named_pack_read_surface_rejects_current_tampered_bytes(
        tmp_path: Path,
    ) -> None:
        public_named_pack_tools = {
            name
            for name, method in inspect.getmembers(PackSession, inspect.isfunction)
            if not name.startswith("_")
            and not name.startswith("resource_")
            and "pack_id" in inspect.signature(method).parameters
        }
        assert set(_NAMED_PACK_READ_ENTRY_POINTS) == public_named_pack_tools
    
        packs, good_id = _build_fixture_pack(tmp_path, name="mcp-surface-good")
        _, tampered_id = _build_fixture_pack(tmp_path, name="mcp-surface-tampered")
        session = PackSession(packs)
        session.load_pack(good_id)
        before_id = session.pack_id
        before_hash = session.pack_hash
    
        sqlite_path = pack_sqlite_path(packs, tampered_id)
        original = sqlite_path.read_bytes()
        schema_label = b"Component"
        tampered_label = b"Tampered!"
        assert len(schema_label) == len(tampered_label)
        assert schema_label in original
        sqlite_path.write_bytes(original.replace(schema_label, tampered_label, 1))
    
        try:
            for entry_point in _NAMED_PACK_READ_ENTRY_POINTS:
>               with pytest.raises(
                    mcp_server.PackIntegrityError,
                    match="(?i)(integrity|mismatch)",
                ):
E               Failed: DID NOT RAISE PackIntegrityError

tests/test_mcp_pack_integrity.py:123: Failed
=========================== short test summary info ============================
FAILED tests/test_mcp_pack_integrity.py::test_named_pack_read_surface_rejects_current_tampered_bytes
============================== 1 failed in 0.45s ===============================
```

The loop first observed `load_pack` reject the modified bytes; the failure is
at the next listed reader, `get_schema`, which returned instead of raising.

## Mutation check (test retained, production fix temporarily reverted)

Command (bounded by a Python `subprocess.run(..., timeout=300)` wrapper because
macOS on this workstation has no `timeout`/`gtimeout` executable):

```text
.venv/bin/python -m pytest tests/test_mcp_pack_integrity.py -v
```

Output:

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/hyunjun/Documents/MUNI/ontologylab
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 12 items

tests/test_mcp_pack_integrity.py F...........                            [100%]

=================================== FAILURES ===================================
_________ test_named_pack_read_surface_rejects_current_tampered_bytes __________

tmp_path = PosixPath('/private/var/folders/l_/vy0kynvx0k1dl0p56z0c3xtc0000gn/T/pytest-of-hyunjun/pytest-12947/test_named_pack_read_surface_r0')

    def test_named_pack_read_surface_rejects_current_tampered_bytes(
        tmp_path: Path,
    ) -> None:
        public_named_pack_tools = {
            name
            for name, method in inspect.getmembers(PackSession, inspect.isfunction)
            if not name.startswith("_")
            and not name.startswith("resource_")
            and "pack_id" in inspect.signature(method).parameters
        }
        assert set(_NAMED_PACK_READ_ENTRY_POINTS) == public_named_pack_tools
    
        packs, good_id = _build_fixture_pack(tmp_path, name="mcp-surface-good")
        _, tampered_id = _build_fixture_pack(tmp_path, name="mcp-surface-tampered")
        session = PackSession(packs)
        session.load_pack(good_id)
        before_id = session.pack_id
        before_hash = session.pack_hash
    
        sqlite_path = pack_sqlite_path(packs, tampered_id)
        original = sqlite_path.read_bytes()
        schema_label = b"Component"
        tampered_label = b"Tampered!"
        assert len(schema_label) == len(tampered_label)
        assert schema_label in original
        sqlite_path.write_bytes(original.replace(schema_label, tampered_label, 1))
    
        try:
            for entry_point in _NAMED_PACK_READ_ENTRY_POINTS:
>               with pytest.raises(
                    mcp_server.PackIntegrityError,
                    match="(?i)(integrity|mismatch)",
                ):
E               Failed: DID NOT RAISE PackIntegrityError

tests/test_mcp_pack_integrity.py:123: Failed
=========================== short test summary info ============================
FAILED tests/test_mcp_pack_integrity.py::test_named_pack_read_surface_rejects_current_tampered_bytes
========================= 1 failed, 11 passed in 0.89s =========================
```

The production fix was restored immediately after this expected failure.

## Automated verification with fix restored

The requested literal `timeout 300 ...` command was attempted first and the
Darwin shell returned `/bin/bash: timeout: command not found` (exit 127).
Equivalent bounded Python subprocess wrappers ran the exact pytest arguments:

- `.venv/bin/python -m pytest tests/test_mcp_pack_integrity.py -v`
  - `12 passed in 1.15s`
- `.venv/bin/python -m pytest tests/test_mcp_session.py tests/test_mcp_two_tier.py -v`
  - `15 passed in 1.33s`

Diagnostics:

- `tests/test_mcp_pack_integrity.py`: no diagnostics.
- `ontologylab/mcp_server.py`: the language server reports existing TypedDict
  return-type findings in the MCP registration section; no finding is on or
  caused by the changed `get_schema` branch.

## Manual MCP stdio QA

A real `python -m ontologylab.mcp_server` process was started with two packs
under `/private/tmp/ontologylab-st_01a00285-qa`. JSON-RPC lines were written to
its stdin and response lines read from stdout with a bounded event wait.

Binary observations:

- Equal-length in-place schema-byte tamper: refused (`isError:true`, hash
  mismatch, no `structuredContent`).
- Untampered named-pack read: succeeded (`isError:false`).
- Active pack: remained `stdio-good-20260815-080948` before and after every
  rejected non-active read.
- Stale state: the non-active pack succeeded before tampering (request 2) and
  was refused after later tampering (request 3), ruling out cached verdicts.
- Truncated manifest: refused as unverifiable (request 6).
- Zero-byte SQLite: refused as hash mismatch (request 7).
- `../` traversal ID: refused as invalid with no path separators (request 8).
- Misleading success: ruled out because all refusals carry `isError:true` and
  the tamper response has no `structuredContent`.
- Port 8799: not touched; QA used stdio only and bound no network port.

Raw request/response capture and receipts:

```text
REQUEST {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}
RESPONSE {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":false},"resources":{"subscribe":false,"listChanged":false}},"serverInfo":{"name":"ontologylab","version":"1"}}}
REQUEST {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_schema","arguments":{"pack_id":"stdio-tampered-20260815-080948"}}}
RESPONSE {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"{\"entity_types\":[{\"attributes\":{\"language\":{\"required\":false,\"type\":\"string\"},\"version\":{\"required\":false,\"type\":\"string\"}},\"description\":\"A concrete software artifact: module, service, library, tool, API.\",\"name\":\"Component\"},{\"attributes\":{},\"description\":\"An abstract idea, algorithm, pattern, or principle.\",\"name\":\"Concept\"},{\"attributes\":{},\"description\":\"A method, procedure, or practice applied to build or operate systems.\",\"name\":\"Technique\"}],\"relation_types\":[{\"description\":\"Source is a constituent of target.\",\"directed\":true,\"domain_type\":\"*\",\"name\":\"part_of\",\"qualifiers\":{},\"range_type\":\"*\"},{\"description\":\"Source and target are associated.\",\"directed\":false,\"domain_type\":\"*\",\"name\":\"related_to\",\"qualifiers\":{},\"range_type\":\"*\"},{\"description\":\"Source makes use of target.\",\"directed\":true,\"domain_type\":\"*\",\"name\":\"uses\",\"qualifiers\":{},\"range_type\":\"*\"}],\"schema_label\":\"software-docs-v1\",\"schema_version_id\":1}"}],"isError":false,"structuredContent":{"schema_version_id":1,"schema_label":"software-docs-v1","entity_types":[{"name":"Component","description":"A concrete software artifact: module, service, library, tool, API.","attributes":{"language":{"type":"string","required":false},"version":{"type":"string","required":false}}},{"name":"Concept","description":"An abstract idea, algorithm, pattern, or principle.","attributes":{}},{"name":"Technique","description":"A method, procedure, or practice applied to build or operate systems.","attributes":{}}],"relation_types":[{"name":"part_of","description":"Source is a constituent of target.","domain_type":"*","range_type":"*","directed":true,"qualifiers":{}},{"name":"related_to","description":"Source and target are associated.","domain_type":"*","range_type":"*","directed":false,"qualifiers":{}},{"name":"uses","description":"Source makes use of target.","domain_type":"*","range_type":"*","directed":true,"qualifiers":{}}]}}}
REQUEST {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_schema","arguments":{"pack_id":"stdio-tampered-20260815-080948"}}}
RESPONSE {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"pack 'stdio-tampered-20260815-080948' failed integrity verification: pack.sqlite hash mismatch (manifest sha256:e44669e0a62a218a504bc7217a5cc690236d79f03b9886dd8a5551690677909b, actual sha256:fa2c385c368656899dfb7998ed16b3806dcc0c6a6fb6feb14666f5a270b18ea4); the pack was tampered with or corrupted — rebuild it from the working store"}],"isError":true}}
REQUEST {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_schema","arguments":{"pack_id":"stdio-good-20260815-080948"}}}
RESPONSE {"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"{\"entity_types\":[{\"attributes\":{\"language\":{\"required\":false,\"type\":\"string\"},\"version\":{\"required\":false,\"type\":\"string\"}},\"description\":\"A concrete software artifact: module, service, library, tool, API.\",\"name\":\"Component\"},{\"attributes\":{},\"description\":\"An abstract idea, algorithm, pattern, or principle.\",\"name\":\"Concept\"},{\"attributes\":{},\"description\":\"A method, procedure, or practice applied to build or operate systems.\",\"name\":\"Technique\"}],\"relation_types\":[{\"description\":\"Source is a constituent of target.\",\"directed\":true,\"domain_type\":\"*\",\"name\":\"part_of\",\"qualifiers\":{},\"range_type\":\"*\"},{\"description\":\"Source and target are associated.\",\"directed\":false,\"domain_type\":\"*\",\"name\":\"related_to\",\"qualifiers\":{},\"range_type\":\"*\"},{\"description\":\"Source makes use of target.\",\"directed\":true,\"domain_type\":\"*\",\"name\":\"uses\",\"qualifiers\":{},\"range_type\":\"*\"}],\"schema_label\":\"software-docs-v1\",\"schema_version_id\":1}"}],"isError":false,"structuredContent":{"schema_version_id":1,"schema_label":"software-docs-v1","entity_types":[{"name":"Component","description":"A concrete software artifact: module, service, library, tool, API.","attributes":{"language":{"type":"string","required":false},"version":{"type":"string","required":false}}},{"name":"Concept","description":"An abstract idea, algorithm, pattern, or principle.","attributes":{}},{"name":"Technique","description":"A method, procedure, or practice applied to build or operate systems.","attributes":{}}],"relation_types":[{"name":"part_of","description":"Source is a constituent of target.","domain_type":"*","range_type":"*","directed":true,"qualifiers":{}},{"name":"related_to","description":"Source and target are associated.","domain_type":"*","range_type":"*","directed":false,"qualifiers":{}},{"name":"uses","description":"Source makes use of target.","domain_type":"*","range_type":"*","directed":true,"qualifiers":{}}]}}}
REQUEST {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"list_packs","arguments":{}}}
RESPONSE {"jsonrpc":"2.0","id":5,"result":{"content":[{"type":"text","text":"{\"active_pack_id\":\"stdio-good-20260815-080948\",\"count\":2,\"packs\":[{\"basis_commit\":\"0108c370908ac1463e08c4063ec54e3dac37e2b3\",\"capabilities\":[\"knowledge-graph-v1\"],\"content_hash\":\"sha256:cd54391c8ae7af4d4492c2def421ee0f8c66660eb8b03ecc21d15963b2b1032d\",\"counts\":{\"communities\":1,\"documents\":1,\"edges_verified\":1,\"entity_types\":3,\"nodes_verified\":2,\"ontology_terms_reviewed\":6,\"relation_types\":3,\"term_aliases_reviewed\":0,\"term_xrefs_reviewed\":0},\"created_ts\":1786748988.7126908,\"embedding_model\":null,\"extraction_completeness\":{\"chunk_status_counts\":{},\"incomplete_streams\":[],\"override\":{\"operator_intent\":\"synthetic MCP pack integrity fixture\",\"used\":true},\"relevant_document_ids\":[\"af27b81c994e417aad2c152a34d1d3c1\"],\"relevant_stream_count\":1,\"run_status_counts\":{},\"status\":\"incomplete\",\"unknown_streams\":[{\"decode_params\":\"null\",\"document_content_hash\":\"stdio-good-h1\",\"document_id\":\"af27b81c994e417aad2c152a34d1d3c1\",\"extractor_engine\":\"mock\",\"extractor_model\":\"\",\"prompt_version\":\"\",\"schema_version_id\":1}]},\"included_schema_version_ids\":[1],\"ontology_publication\":{\"external_descriptive_text\":\"not-in-term-xref-schema\",\"license_modes\":[\"allow\",\"identifier-only\",\"deny-text\"],\"review_boundary\":\"explicit-current-review-fields-v1\",\"version\":1,\"xref_verification\":\"complete-source-license-contract-v1\"},\"ontologylab_version\":\"0.1.0\",\"pack_id\":\"stdio-good-20260815-080948\",\"schema_label\":\"software-docs-v1\",\"schema_version_id\":1,\"search_tier\":\"fts5\",\"semantic_fact_baseline\":{\"fingerprint_algorithm\":\"sha256-canonical-json-v1\",\"source\":\"pack.sqlite\",\"version\":1},\"source_job_id\":null,\"staleness_policy\":{\"description\":\"pending_verified_count is a backward-compatible count-difference advisory, not semantic truth. Semantic additions, invalidations, and replacements are authoritative; any nonzero delta recommends rebuilding.\",\"pending_verified_count_threshold\":0}},{\"basis_commit\":\"0108c370908ac1463e08c4063ec54e3dac37e2b3\",\"capabilities\":[\"knowledge-graph-v1\"],\"content_hash\":\"sha256:e44669e0a62a218a504bc7217a5cc690236d79f03b9886dd8a5551690677909b\",\"counts\":{\"communities\":1,\"documents\":1,\"edges_verified\":1,\"entity_types\":3,\"nodes_verified\":2,\"ontology_terms_reviewed\":6,\"relation_types\":3,\"term_aliases_reviewed\":0,\"term_xrefs_reviewed\":0},\"created_ts\":1786748988.776852,\"embedding_model\":null,\"extraction_completeness\":{\"chunk_status_counts\":{},\"incomplete_streams\":[],\"override\":{\"operator_intent\":\"synthetic MCP pack integrity fixture\",\"used\":true},\"relevant_document_ids\":[\"2beef0dd559144559ee49e033b21fa0a\"],\"relevant_stream_count\":1,\"run_status_counts\":{},\"status\":\"incomplete\",\"unknown_streams\":[{\"decode_params\":\"null\",\"document_content_hash\":\"stdio-tampered-h1\",\"document_id\":\"2beef0dd559144559ee49e033b21fa0a\",\"extractor_engine\":\"mock\",\"extractor_model\":\"\",\"prompt_version\":\"\",\"schema_version_id\":1}]},\"included_schema_version_ids\":[1],\"ontology_publication\":{\"external_descriptive_text\":\"not-in-term-xref-schema\",\"license_modes\":[\"allow\",\"identifier-only\",\"deny-text\"],\"review_boundary\":\"explicit-current-review-fields-v1\",\"version\":1,\"xref_verification\":\"complete-source-license-contract-v1\"},\"ontologylab_version\":\"0.1.0\",\"pack_id\":\"stdio-tampered-20260815-080948\",\"schema_label\":\"software-docs-v1\",\"schema_version_id\":1,\"search_tier\":\"fts5\",\"semantic_fact_baseline\":{\"fingerprint_algorithm\":\"sha256-canonical-json-v1\",\"source\":\"pack.sqlite\",\"version\":1},\"source_job_id\":null,\"staleness_policy\":{\"description\":\"pending_verified_count is a backward-compatible count-difference advisory, not semantic truth. Semantic additions, invalidations, and replacements are authoritative; any nonzero delta recommends rebuilding.\",\"pending_verified_count_threshold\":0}}],\"packs_dir\":\"/private/tmp/ontologylab-st_01a00285-qa/packs\"}"}],"isError":false,"structuredContent":{"packs_dir":"/private/tmp/ontologylab-st_01a00285-qa/packs","active_pack_id":"stdio-good-20260815-080948","packs":[{"pack_id":"stdio-good-20260815-080948","created_ts":1786748988.7126908,"schema_version_id":1,"schema_label":"software-docs-v1","source_job_id":null,"counts":{"documents":1,"nodes_verified":2,"edges_verified":1,"entity_types":3,"relation_types":3,"communities":1,"ontology_terms_reviewed":6,"term_aliases_reviewed":0,"term_xrefs_reviewed":0},"search_tier":"fts5","embedding_model":null,"ontologylab_version":"0.1.0","content_hash":"sha256:cd54391c8ae7af4d4492c2def421ee0f8c66660eb8b03ecc21d15963b2b1032d","basis_commit":"0108c370908ac1463e08c4063ec54e3dac37e2b3","staleness_policy":{"pending_verified_count_threshold":0,"description":"pending_verified_count is a backward-compatible count-difference advisory, not semantic truth. Semantic additions, invalidations, and replacements are authoritative; any nonzero delta recommends rebuilding."},"extraction_completeness":{"status":"incomplete","relevant_stream_count":1,"relevant_document_ids":["af27b81c994e417aad2c152a34d1d3c1"],"unknown_streams":[{"document_id":"af27b81c994e417aad2c152a34d1d3c1","document_content_hash":"stdio-good-h1","schema_version_id":1,"extractor_engine":"mock","extractor_model":"","prompt_version":"","decode_params":"null"}],"incomplete_streams":[],"run_status_counts":{},"chunk_status_counts":{},"override":{"used":true,"operator_intent":"synthetic MCP pack integrity fixture"}},"semantic_fact_baseline":{"version":1,"fingerprint_algorithm":"sha256-canonical-json-v1","source":"pack.sqlite"},"included_schema_version_ids":[1],"ontology_publication":{"version":1,"review_boundary":"explicit-current-review-fields-v1","xref_verification":"complete-source-license-contract-v1","license_modes":["allow","identifier-only","deny-text"],"external_descriptive_text":"not-in-term-xref-schema"},"capabilities":["knowledge-graph-v1"]},{"pack_id":"stdio-tampered-20260815-080948","created_ts":1786748988.776852,"schema_version_id":1,"schema_label":"software-docs-v1","source_job_id":null,"counts":{"documents":1,"nodes_verified":2,"edges_verified":1,"entity_types":3,"relation_types":3,"communities":1,"ontology_terms_reviewed":6,"term_aliases_reviewed":0,"term_xrefs_reviewed":0},"search_tier":"fts5","embedding_model":null,"ontologylab_version":"0.1.0","content_hash":"sha256:e44669e0a62a218a504bc7217a5cc690236d79f03b9886dd8a5551690677909b","basis_commit":"0108c370908ac1463e08c4063ec54e3dac37e2b3","staleness_policy":{"pending_verified_count_threshold":0,"description":"pending_verified_count is a backward-compatible count-difference advisory, not semantic truth. Semantic additions, invalidations, and replacements are authoritative; any nonzero delta recommends rebuilding."},"extraction_completeness":{"status":"incomplete","relevant_stream_count":1,"relevant_document_ids":["2beef0dd559144559ee49e033b21fa0a"],"unknown_streams":[{"document_id":"2beef0dd559144559ee49e033b21fa0a","document_content_hash":"stdio-tampered-h1","schema_version_id":1,"extractor_engine":"mock","extractor_model":"","prompt_version":"","decode_params":"null"}],"incomplete_streams":[],"run_status_counts":{},"chunk_status_counts":{},"override":{"used":true,"operator_intent":"synthetic MCP pack integrity fixture"}},"semantic_fact_baseline":{"version":1,"fingerprint_algorithm":"sha256-canonical-json-v1","source":"pack.sqlite"},"included_schema_version_ids":[1],"ontology_publication":{"version":1,"review_boundary":"explicit-current-review-fields-v1","xref_verification":"complete-source-license-contract-v1","license_modes":["allow","identifier-only","deny-text"],"external_descriptive_text":"not-in-term-xref-schema"},"capabilities":["knowledge-graph-v1"]}],"count":2}}}
REQUEST {"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"get_schema","arguments":{"pack_id":"stdio-tampered-20260815-080948"}}}
RESPONSE {"jsonrpc":"2.0","id":6,"result":{"content":[{"type":"text","text":"pack 'stdio-tampered-20260815-080948' is unverifiable: no readable manifest.json (Unterminated string starting at: line 31 column 7 (char 1096)); rebuild the pack to generate an integrity receipt"}],"isError":true}}
REQUEST {"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"get_schema","arguments":{"pack_id":"stdio-tampered-20260815-080948"}}}
RESPONSE {"jsonrpc":"2.0","id":7,"result":{"content":[{"type":"text","text":"pack 'stdio-tampered-20260815-080948' failed integrity verification: pack.sqlite hash mismatch (manifest sha256:e44669e0a62a218a504bc7217a5cc690236d79f03b9886dd8a5551690677909b, actual sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855); the pack was tampered with or corrupted — rebuild it from the working store"}],"isError":true}}
REQUEST {"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"get_schema","arguments":{"pack_id":"../escape"}}}
RESPONSE {"jsonrpc":"2.0","id":8,"result":{"content":[{"type":"text","text":"invalid pack id '../escape': use only letters, digits, '.', '_', '-' (no path separators)"}],"isError":true}}
REQUEST {"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"list_packs","arguments":{}}}
RESPONSE {"jsonrpc":"2.0","id":9,"result":{"content":[{"type":"text","text":"{\"active_pack_id\":\"stdio-good-20260815-080948\",\"count\":1,\"packs\":[{\"basis_commit\":\"0108c370908ac1463e08c4063ec54e3dac37e2b3\",\"capabilities\":[\"knowledge-graph-v1\"],\"content_hash\":\"sha256:cd54391c8ae7af4d4492c2def421ee0f8c66660eb8b03ecc21d15963b2b1032d\",\"counts\":{\"communities\":1,\"documents\":1,\"edges_verified\":1,\"entity_types\":3,\"nodes_verified\":2,\"ontology_terms_reviewed\":6,\"relation_types\":3,\"term_aliases_reviewed\":0,\"term_xrefs_reviewed\":0},\"created_ts\":1786748988.7126908,\"embedding_model\":null,\"extraction_completeness\":{\"chunk_status_counts\":{},\"incomplete_streams\":[],\"override\":{\"operator_intent\":\"synthetic MCP pack integrity fixture\",\"used\":true},\"relevant_document_ids\":[\"af27b81c994e417aad2c152a34d1d3c1\"],\"relevant_stream_count\":1,\"run_status_counts\":{},\"status\":\"incomplete\",\"unknown_streams\":[{\"decode_params\":\"null\",\"document_content_hash\":\"stdio-good-h1\",\"document_id\":\"af27b81c994e417aad2c152a34d1d3c1\",\"extractor_engine\":\"mock\",\"extractor_model\":\"\",\"prompt_version\":\"\",\"schema_version_id\":1}]},\"included_schema_version_ids\":[1],\"ontology_publication\":{\"external_descriptive_text\":\"not-in-term-xref-schema\",\"license_modes\":[\"allow\",\"identifier-only\",\"deny-text\"],\"review_boundary\":\"explicit-current-review-fields-v1\",\"version\":1,\"xref_verification\":\"complete-source-license-contract-v1\"},\"ontologylab_version\":\"0.1.0\",\"pack_id\":\"stdio-good-20260815-080948\",\"schema_label\":\"software-docs-v1\",\"schema_version_id\":1,\"search_tier\":\"fts5\",\"semantic_fact_baseline\":{\"fingerprint_algorithm\":\"sha256-canonical-json-v1\",\"source\":\"pack.sqlite\",\"version\":1},\"source_job_id\":null,\"staleness_policy\":{\"description\":\"pending_verified_count is a backward-compatible count-difference advisory, not semantic truth. Semantic additions, invalidations, and replacements are authoritative; any nonzero delta recommends rebuilding.\",\"pending_verified_count_threshold\":0}}],\"packs_dir\":\"/private/tmp/ontologylab-st_01a00285-qa/packs\"}"}],"isError":false,"structuredContent":{"packs_dir":"/private/tmp/ontologylab-st_01a00285-qa/packs","active_pack_id":"stdio-good-20260815-080948","packs":[{"pack_id":"stdio-good-20260815-080948","created_ts":1786748988.7126908,"schema_version_id":1,"schema_label":"software-docs-v1","source_job_id":null,"counts":{"documents":1,"nodes_verified":2,"edges_verified":1,"entity_types":3,"relation_types":3,"communities":1,"ontology_terms_reviewed":6,"term_aliases_reviewed":0,"term_xrefs_reviewed":0},"search_tier":"fts5","embedding_model":null,"ontologylab_version":"0.1.0","content_hash":"sha256:cd54391c8ae7af4d4492c2def421ee0f8c66660eb8b03ecc21d15963b2b1032d","basis_commit":"0108c370908ac1463e08c4063ec54e3dac37e2b3","staleness_policy":{"pending_verified_count_threshold":0,"description":"pending_verified_count is a backward-compatible count-difference advisory, not semantic truth. Semantic additions, invalidations, and replacements are authoritative; any nonzero delta recommends rebuilding."},"extraction_completeness":{"status":"incomplete","relevant_stream_count":1,"relevant_document_ids":["af27b81c994e417aad2c152a34d1d3c1"],"unknown_streams":[{"document_id":"af27b81c994e417aad2c152a34d1d3c1","document_content_hash":"stdio-good-h1","schema_version_id":1,"extractor_engine":"mock","extractor_model":"","prompt_version":"","decode_params":"null"}],"incomplete_streams":[],"run_status_counts":{},"chunk_status_counts":{},"override":{"used":true,"operator_intent":"synthetic MCP pack integrity fixture"}},"semantic_fact_baseline":{"version":1,"fingerprint_algorithm":"sha256-canonical-json-v1","source":"pack.sqlite"},"included_schema_version_ids":[1],"ontology_publication":{"version":1,"review_boundary":"explicit-current-review-fields-v1","xref_verification":"complete-source-license-contract-v1","license_modes":["allow","identifier-only","deny-text"],"external_descriptive_text":"not-in-term-xref-schema"},"capabilities":["knowledge-graph-v1"]}],"count":1}}}
ASSERTIONS stale_verdict_refused=true untampered_succeeded=true active_unchanged=stdio-good-20260815-080948 misleading_success=false
PROCESS_RECEIPT pid=82393 returncode=0 alive=False
CLEANUP_RECEIPT path=/private/tmp/ontologylab-st_01a00285-qa exists=False
```

## Cleanup receipts

- MCP PID `82393`: exited normally with return code 0; `alive=False`.
- `/private/tmp/ontologylab-st_01a00285-qa`: removed; `exists=False`.
- Temporary proof logs were removed after this artifact was written.
- No port was opened and no commit was created.
