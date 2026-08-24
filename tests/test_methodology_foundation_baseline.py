"""Freeze current KG-only pack, MCP, hash/span, and transaction behavior.

This module characterizes behavior that exists today, before any Method IR
work. It asserts observable contracts (signatures, table inventories, tool and
resource sets, exact bytes, transaction visibility), never the absence of
future source files.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

from ontologylab.extraction_state import ExtractionState
from ontologylab.extractor import Chunk
from ontologylab.kgstore import KGStore
from ontologylab.mcp_server import PackSession, build_mcp_app
from ontologylab.models import ProposedEntity, SourceSpan
from ontologylab.packbuilder import build_pack

CURRENT_BUILD_PACK_SIGNATURE = (
    "(kg_db_path: 'str | Path', packs_dir: 'str | Path', name: 'str', *, "
    "source_job_id: 'str | None' = None, "
    "provenance_jsonl: 'str | Path | None' = None, summarizer=None, "
    "summary_method: 'str' = 'extractive', "
    "allow_incomplete_extraction: 'bool' = False, "
    "incomplete_extraction_intent: 'str | None' = None, "
    "method_release_ids: 'Sequence[str]' = (), "
    "evidence_mode: 'str | None' = None) -> 'PackManifest'"
)

CURRENT_GRAPH_ONLY_PACK_TABLES = set("""annotations artifacts citations
communities community_members critic_reviews documents edges
entity_enrichments entity_type merge_candidates node_aliases nodes nodes_fts
nodes_fts_config nodes_fts_data nodes_fts_docsize nodes_fts_idx ontology_term
relation_type runs schema_version sqlite_sequence sqlite_stat1 term_alias
term_xref""".split())

# Every Method/compiled-method table name any later phase may introduce.
BLOCKED_METHOD_TABLE_NAMES = set("""bridge_evidence bridge_proposal
compiled_method compiled_method_source compiled_methods
document_policy_snapshot method_compilation_attempt
method_counter_evidence_search method_extraction_chunks
method_extraction_runs method_fragment method_fragment_evidence method_gap
method_link method_release method_releases method_review_event
method_workspace methodology_publication_receipt source_policy
statement_occurrence""".split())

CURRENT_MCP_TOOLS = set("""entity_lookup find_path get_communities get_entity
get_schema get_staleness graph_query list_packs load_pack semantic_search
traverse_relations list_methods get_method trace_method
list_method_gaps""".split())

CURRENT_MCP_RESOURCE_TEMPLATES = {
    "pack://{pack_id}/" + suffix
    for suffix in (
        "entity/{entity_id}", "manifest", "schema", "term/{term_id}",
        "xref/{xref_id}",
        "method/{method_id}",
        "method/{method_id}/trace/{field_path}",
    )
}

# U+00E9 and U+2192 are multi-byte in UTF-8: character offsets must not be
# reused as byte offsets anywhere in this module.
UNICODE_TEXT = "Le débit → RateLimiter protège l'API."
UNICODE_TERM = "RateLimiter"


def _insert_document(store: KGStore, text: str, name: str):
    content_hash = "sha256:" + hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()
    document, created = store.insert_document(
        source_kind="upload",
        source_uri=f"file:///{name}.txt",
        title=name,
        raw_text=text,
        content_hash=content_hash,
    )
    assert created
    return document


def _propose(store: KGStore, document, node_id: str, span: SourceSpan, **kw):
    return store.insert_proposed(
        [
            ProposedEntity(
                id=node_id,
                entity_type="Component",
                name=UNICODE_TERM,
                source_span=span,
            )
        ],
        [],
        source_doc_id=document.id,
        extractor_engine="baseline",
        **kw,
    )


def _seed_graph_store(database: Path, text: str, name: str) -> None:
    store = KGStore.open(database)
    try:
        document = _insert_document(store, text, name)
        _propose(
            store, document, "baseline-node",
            SourceSpan(0, len(UNICODE_TERM)),
        )
        store.approve("baseline-node")
    finally:
        store.close()


def _plan_one_chunk(state: ExtractionState, store: KGStore, document, text):
    chunk = Chunk(index=0, char_offset=0, text=text)
    plan = state.plan(
        document.id, [chunk],
        schema_version_id=store.active_schema_version()["id"],
        engine="baseline", model=None, prompt_version="baseline-v1",
        decode_params=None,
    )
    assert state.claim(plan.run_id, chunk.index)
    return plan, chunk


def test_build_pack_signature_has_explicit_method_selection() -> None:
    signature = inspect.signature(build_pack)
    assert str(signature) == CURRENT_BUILD_PACK_SIGNATURE
    # summary_method is pre-existing and unrelated to release selection.
    assert signature.parameters["method_release_ids"].default == ()


def test_graph_only_pack_has_exact_table_inventory_and_no_manifest_section(
    tmp_path: Path,
) -> None:
    database = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    _seed_graph_store(database, "RateLimiter protects the API.", "graph-only")

    manifest = build_pack(
        database, packs, name="graph-only-baseline",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="Task 1 graph-only baseline fixture",
    )
    pack_dir = packs / manifest.pack_id
    uri = f"file:{pack_dir / 'pack.sqlite'}?mode=ro"

    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()

    assert sorted(tables) == sorted(CURRENT_GRAPH_ONLY_PACK_TABLES)
    assert tables & BLOCKED_METHOD_TABLE_NAMES == set()
    assert not [t for t in tables if t.startswith(("method", "compiled_"))]

    manifest_json = json.loads(
        (pack_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert not [k for k in manifest_json if "method" in k.lower()]
    assert manifest_json["capabilities"] == ["knowledge-graph-v1"]


def test_mcp_surface_pins_fifteen_tools_and_seven_resource_templates(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp")
    import asyncio

    session = PackSession(tmp_path / "packs")
    try:
        app = build_mcp_app(session)
        tools = {tool.name for tool in asyncio.run(app.list_tools())}
        templates = {
            str(template.uriTemplate)
            for template in asyncio.run(app.list_resource_templates())
        }
    finally:
        session.close()

    assert tools == CURRENT_MCP_TOOLS
    assert len(tools) == 15
    assert templates == CURRENT_MCP_RESOURCE_TEMPLATES
    assert len(templates) == 7


def test_document_hash_is_raw_bytes_and_span_is_character_offsets(
    tmp_path: Path,
) -> None:
    database = tmp_path / "kg.sqlite"
    store = KGStore.open(database)
    try:
        document = _insert_document(store, UNICODE_TEXT, "unicode-span")
        raw_path = store.db_path.parent / document.raw_text_path
        raw_bytes = raw_path.read_bytes()

        digest = hashlib.sha256(raw_bytes).hexdigest()
        assert document.content_hash == "sha256:" + digest
        decoded = raw_bytes.decode("utf-8")
        assert decoded == UNICODE_TEXT
        char_start = decoded.index(UNICODE_TERM)
        char_end = char_start + len(UNICODE_TERM)
        span = SourceSpan(char_start, char_end)

        # Character offsets address decoded text, never raw bytes here.
        assert decoded[span.start:span.end] == UNICODE_TERM
        assert len(raw_bytes) != len(decoded)
        assert raw_bytes[span.start:span.end] != UNICODE_TERM.encode("utf-8")

        byte_start = len(decoded[:char_start].encode("utf-8"))
        byte_end = byte_start + len(UNICODE_TERM.encode("utf-8"))
        assert raw_bytes[byte_start:byte_end] == UNICODE_TERM.encode("utf-8")
        assert byte_start != char_start

        _propose(store, document, "unicode-node", span)
        row = store.conn.execute(
            "SELECT source_span FROM nodes WHERE id = 'unicode-node'"
        ).fetchone()
        stored = json.loads(row[0])
        assert (stored["start"], stored["end"]) == (char_start, char_end)
        assert decoded[stored["start"]:stored["end"]] == UNICODE_TERM
    finally:
        store.close()


def test_chunk_success_commits_proposals_and_marker_atomically(
    tmp_path: Path,
) -> None:
    database = tmp_path / "kg.sqlite"
    store = KGStore.open(database)
    text = "RateLimiter protects the API."
    document = _insert_document(store, text, "atomic-success")

    with ExtractionState(store.conn) as state:
        plan, chunk = _plan_one_chunk(state, store, document, text)
        stats = _propose(
            store, document, "atomic-success-node",
            SourceSpan(0, len(UNICODE_TERM)), commit=False,
        )

        observer = sqlite3.connect(database)
        try:
            assert observer.execute(
                "SELECT 1 FROM nodes WHERE id = 'atomic-success-node'"
            ).fetchone() is None

            state.succeeded(plan.run_id, chunk.index, stats)

            node = observer.execute(
                "SELECT source_doc_id FROM nodes "
                "WHERE id = 'atomic-success-node'"
            ).fetchone()
            status = observer.execute(
                "SELECT status FROM extraction_chunks "
                "WHERE run_id = ? AND chunk_index = ?",
                (plan.run_id, chunk.index),
            ).fetchone()[0]
        finally:
            observer.close()

    assert node is not None and node[0] == document.id
    assert status == "succeeded"
    store.close()


def test_chunk_failure_rolls_back_proposals_before_failure_marker(
    tmp_path: Path,
) -> None:
    database = tmp_path / "kg.sqlite"
    store = KGStore.open(database)
    text = "RateLimiter protects the API."
    document = _insert_document(store, text, "atomic-failure")

    with ExtractionState(store.conn) as state:
        plan, chunk = _plan_one_chunk(state, store, document, text)
        _propose(
            store, document, "rolled-back-node",
            SourceSpan(0, len(UNICODE_TERM)), commit=False,
        )
        state.failed(plan.run_id, chunk.index, "baseline_failure")

        observer = sqlite3.connect(database)
        try:
            assert observer.execute(
                "SELECT 1 FROM nodes WHERE id = 'rolled-back-node'"
            ).fetchone() is None
            chunk_row = observer.execute(
                "SELECT status, error_kind FROM extraction_chunks "
                "WHERE run_id = ? AND chunk_index = ?",
                (plan.run_id, chunk.index),
            ).fetchone()
            run_status = observer.execute(
                "SELECT status FROM extraction_runs WHERE id = ?",
                (plan.run_id,),
            ).fetchone()[0]
        finally:
            observer.close()

    # Exact failure identity, not merely "some failure".
    assert tuple(chunk_row) == ("failed", "baseline_failure")
    assert run_status == "failed"
    store.close()
