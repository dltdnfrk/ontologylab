"""Pack builds are gated on durable extraction completion for shipped facts."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ontologylab import packbuilder
from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity
from ontologylab.packbuilder import (
    IncompleteExtractionError,
    PackBuildError,
    build_pack,
)


def _verified_fact(
    store: KGStore,
    *,
    suffix: str = "fact",
    engine: str = "mock",
    model: str | None = None,
    prompt: str = "extract-v1",
    decode_params: dict | None = None,
) -> str:
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri=f"file:///{suffix}.txt",
        title=suffix,
        raw_text="RateLimiter",
        content_hash=f"sha256:{suffix}",
    )
    entity = ProposedEntity(
        id=f"node-{suffix}", entity_type="Component", name=f"RateLimiter{suffix}"
    )
    store.insert_proposed(
        [entity], [], source_doc_id=doc.id, extractor_engine=engine,
        extractor_model=model, prompt_version=prompt, decode_params=decode_params,
    )
    store.approve(entity.id)
    return doc.id


def _run(
    store: KGStore,
    doc_id: str,
    run_status: str,
    chunk_status: str,
    *,
    run_id: str | None = None,
    engine: str = "mock",
    model: str | None = None,
    prompt: str = "extract-v1",
    decode_params: str = "null",
) -> None:
    now = time.time()
    run_id = run_id or f"run-{doc_id}"
    store.conn.execute(
        "INSERT INTO extraction_runs (id, document_id, document_content_hash, "
        "schema_version_id, extractor_engine, extractor_model, prompt_version, "
        "decode_params, chunk_plan_hash, status, created_ts, updated_ts, finished_ts) "
        "SELECT ?, id, content_hash, 1, ?, ?, ?, ?, ?, ?, ?, ?, ? "
        "FROM documents WHERE id = ?",
        (
            run_id, engine, model or "", prompt, decode_params,
            f"sha256:plan-{run_id}", run_status, now, now,
            now if run_status == "complete" else None, doc_id,
        ),
    )
    store.conn.execute(
        "INSERT INTO extraction_chunks (run_id, chunk_index, char_offset, "
        "content_hash, status) VALUES (?, 0, 0, 'sha256:chunk', ?)",
        (run_id, chunk_status),
    )
    store.conn.commit()


@pytest.mark.parametrize(
    ("run_status", "chunk_status"),
    [
        ("pending", "pending"),
        ("running", "running"),
        ("failed", "failed"),
        ("interrupted", "interrupted"),
        ("cancelled", "cancelled"),
        ("complete", "failed"),
    ],
)
def test_pack_refuses_each_incomplete_durable_state(
    tmp_path: Path, run_status: str, chunk_status: str
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(store)
    _run(store, doc_id, run_status, chunk_status)
    store.close()

    with pytest.raises(IncompleteExtractionError) as exc_info:
        build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "blocked")

    summary = exc_info.value.summary
    assert summary["status"] == "incomplete"
    assert summary["run_status_counts"] == {run_status: 1}
    assert summary["chunk_status_counts"] == {chunk_status: 1}
    assert not (tmp_path / "packs").exists()


def test_pack_refuses_unknown_completeness_for_a_relevant_stream(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(store)
    store.close()

    with pytest.raises(IncompleteExtractionError) as exc_info:
        build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "unknown")

    assert exc_info.value.summary["unknown_streams"][0]["document_id"] == doc_id
    assert "unknown=1" in str(exc_info.value)


def test_complete_unrelated_stream_cannot_launder_shipped_stream(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(store, engine="claude", model="fact-model")
    _run(store, doc_id, "failed", "failed", engine="claude", model="fact-model")
    _run(
        store, doc_id, "complete", "succeeded", run_id="unrelated-complete",
        engine="mock", model="other-model",
    )
    store.close()

    with pytest.raises(IncompleteExtractionError) as exc_info:
        build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "not-laundered")

    assert exc_info.value.summary["run_status_counts"] == {"failed": 1}


def test_incomplete_same_document_producing_stream_blocks_pack(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(
        store,
        suffix="same-document",
        engine="engine-a",
        model="model-a",
        prompt="prompt-a",
    )
    _run(
        store,
        doc_id,
        "complete",
        "succeeded",
        run_id="run-a",
        engine="engine-a",
        model="model-a",
        prompt="prompt-a",
    )
    store.insert_proposed(
        [
            ProposedEntity(
                id="merged-from-b",
                entity_type="Component",
                name="RateLimitersame-document",
                aliases=["RL"],
                properties={"produced_by_failed_stream": "stream-b"},
            )
        ],
        [],
        source_doc_id=doc_id,
        extractor_engine="engine-b",
        extractor_model="model-b",
        prompt_version="prompt-b",
        decode_params={"temperature": 0.7},
    )
    _run(
        store,
        doc_id,
        "failed",
        "failed",
        run_id="run-b",
        engine="engine-b",
        model="model-b",
        prompt="prompt-b",
        decode_params='{"temperature":0.7}',
    )
    store.close()

    with pytest.raises(IncompleteExtractionError) as exc_info:
        build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "same-doc-blocked")

    summary = exc_info.value.summary
    assert summary["status"] == "incomplete"
    assert summary["relevant_stream_count"] == 2
    assert summary["relevant_document_ids"] == [doc_id]
    assert summary["run_status_counts"] == {"complete": 1, "failed": 1}
    assert summary["chunk_status_counts"] == {"failed": 1, "succeeded": 1}
    expected_incomplete_stream = {
        "document_id": doc_id,
        "document_content_hash": "sha256:same-document",
        "schema_version_id": 1,
        "extractor_engine": "engine-b",
        "extractor_model": "model-b",
        "prompt_version": "prompt-b",
        "decode_params": '{"temperature":0.7}',
    }
    assert summary["incomplete_streams"] == [expected_incomplete_stream]
    assert not (tmp_path / "packs").exists()

    manifest = build_pack(
        tmp_path / "kg.sqlite",
        tmp_path / "packs",
        "same-doc-override",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="ship reviewed merged output after stream B failed",
    )
    pack_dir = tmp_path / "packs" / manifest.pack_id
    events = [
        json.loads(line)
        for line in (pack_dir / "provenance.jsonl").read_text().splitlines()
    ]
    override_event = next(
        event
        for event in events
        if event["step"] == "build_pack.extraction_override"
    )
    assert manifest.extraction_completeness["incomplete_streams"] == [
        expected_incomplete_stream
    ]
    assert override_event["payload"]["summary"]["incomplete_streams"] == [
        expected_incomplete_stream
    ]
    assert override_event["payload"]["operator_intent"] == (
        "ship reviewed merged output after stream B failed"
    )


def test_nonproducing_same_document_stream_does_not_block_pack(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(store, suffix="attributed")
    _run(store, doc_id, "complete", "succeeded", run_id="producing-run")
    _run(
        store,
        doc_id,
        "failed",
        "failed",
        run_id="nonproducing-run",
        engine="unused-engine",
        model="unused-model",
        prompt="unused-prompt",
    )
    store.close()

    manifest = build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "attributed")

    summary = manifest.extraction_completeness
    assert summary["status"] == "complete"
    assert summary["relevant_stream_count"] == 1
    assert summary["run_status_counts"] == {"complete": 1}
    assert summary["chunk_status_counts"] == {"succeeded": 1}
    assert summary["incomplete_streams"] == []


def test_legacy_same_document_citations_gate_ambiguous_candidate_streams(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(store, suffix="legacy", engine="engine-a")
    _run(store, doc_id, "complete", "succeeded", run_id="legacy-a", engine="engine-a")
    store.insert_proposed(
        [
            ProposedEntity(
                id="legacy-merged",
                entity_type="Component",
                name="RateLimiterlegacy",
                aliases=["Legacy RL"],
            )
        ],
        [],
        source_doc_id=doc_id,
        extractor_engine="engine-b",
        prompt_version="extract-v1",
    )
    _run(store, doc_id, "failed", "failed", run_id="legacy-b", engine="engine-b")
    store.conn.execute(
        "UPDATE citations SET extractor_engine = NULL, extractor_model = NULL, "
        "prompt_version = NULL, decode_params = NULL"
    )
    store.conn.commit()
    store.close()

    with pytest.raises(IncompleteExtractionError) as exc_info:
        build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "legacy-blocked")

    summary = exc_info.value.summary
    assert summary["relevant_stream_count"] == 2
    assert summary["run_status_counts"] == {"complete": 1, "failed": 1}
    assert summary["incomplete_streams"][0]["extractor_engine"] == "engine-b"


def test_incomplete_later_citation_stream_blocks_complete_owning_stream(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    owning_doc_id = _verified_fact(store, suffix="owning")
    _run(store, owning_doc_id, "complete", "succeeded")

    citation_doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///later-citation.txt",
        title="later citation",
        raw_text="RateLimiterowning",
        content_hash="sha256:later-citation",
    )
    store.insert_proposed(
        [
            ProposedEntity(
                id="merged-mention",
                entity_type="Component",
                name="RateLimiterowning",
            )
        ],
        [],
        source_doc_id=citation_doc.id,
        extractor_engine="later-engine",
        extractor_model="later-model",
        prompt_version="later-prompt",
    )
    _run(
        store,
        citation_doc.id,
        "failed",
        "failed",
        engine="later-engine",
        model="later-model",
        prompt="later-prompt",
    )
    store.close()

    with pytest.raises(IncompleteExtractionError) as exc_info:
        build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "citation-blocked")

    summary = exc_info.value.summary
    assert summary["status"] == "incomplete"
    assert summary["relevant_document_ids"] == sorted(
        [owning_doc_id, citation_doc.id]
    )
    assert summary["run_status_counts"] == {"complete": 1, "failed": 1}


def test_pack_export_uses_the_same_snapshot_as_completeness_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kg_path = tmp_path / "kg.sqlite"
    store = KGStore.open(kg_path)
    owning_doc_id = _verified_fact(store, suffix="snapshot-owner")
    _run(store, owning_doc_id, "complete", "succeeded")
    store.close()

    original_completeness = packbuilder.extraction_completeness

    def mutate_source_after_gate(conn):
        summary = original_completeness(conn)
        mutation_store = KGStore.open(kg_path)
        late_doc_id = _verified_fact(mutation_store, suffix="post-gate")
        _run(mutation_store, late_doc_id, "failed", "failed")
        mutation_store.close()
        return summary

    monkeypatch.setattr(
        packbuilder, "extraction_completeness", mutate_source_after_gate
    )

    manifest = build_pack(kg_path, tmp_path / "packs", "stable-snapshot")
    pack_path = tmp_path / "packs" / manifest.pack_id / "pack.sqlite"
    pack_store = KGStore.open(pack_path, read_only=True)
    try:
        shipped = pack_store.conn.execute(
            "SELECT id FROM nodes WHERE id = 'node-post-gate'"
        ).fetchone()
    finally:
        pack_store.close()

    assert shipped is None
    assert manifest.extraction_completeness["relevant_document_ids"] == [
        owning_doc_id
    ]


def test_complete_run_satisfies_stream_despite_historical_failure(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(store)
    _run(store, doc_id, "failed", "failed", run_id="historical-failure")
    _run(store, doc_id, "complete", "succeeded", run_id="successful-retry")
    store.close()

    manifest = build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "retried")

    summary = manifest.extraction_completeness
    assert summary["status"] == "complete"
    assert summary["run_status_counts"] == {"complete": 1, "failed": 1}
    assert summary["chunk_status_counts"] == {"failed": 1, "succeeded": 1}


def test_complete_relevant_extraction_builds_and_is_recorded(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(store, decode_params={"top_p": 0.9, "temperature": 0.2})
    _run(
        store, doc_id, "complete", "succeeded",
        decode_params='{"temperature":0.2,"top_p":0.9}',
    )
    store.close()

    manifest = build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "complete")

    summary = manifest.extraction_completeness
    assert summary["status"] == "complete"
    assert summary["relevant_stream_count"] == 1
    assert summary["relevant_document_ids"] == [doc_id]
    assert summary["unknown_streams"] == []
    assert summary["run_status_counts"] == {"complete": 1}
    assert summary["chunk_status_counts"] == {"succeeded": 1}
    assert summary["override"] == {"used": False, "operator_intent": None}


def test_unrelated_incomplete_document_does_not_block_pack(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    relevant = _verified_fact(store, suffix="relevant")
    _run(store, relevant, "complete", "succeeded")
    unrelated, _ = store.insert_document(
        source_kind="upload", source_uri="file:///unrelated.txt", title="unrelated",
        raw_text="unfinished", content_hash="sha256:unrelated",
    )
    _run(store, unrelated.id, "failed", "failed")
    store.close()

    manifest = build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "relevant")

    assert manifest.extraction_completeness["relevant_document_ids"] == [relevant]


def test_operator_override_is_auditable_in_manifest_and_provenance(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(store)
    _run(store, doc_id, "failed", "failed")
    store.close()

    manifest = build_pack(
        tmp_path / "kg.sqlite", tmp_path / "packs", "override",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="publish reviewed facts after provider outage",
    )
    pack_dir = tmp_path / "packs" / manifest.pack_id
    disk_manifest = json.loads((pack_dir / "manifest.json").read_text())
    events = [
        json.loads(line)
        for line in (pack_dir / "provenance.jsonl").read_text().splitlines()
    ]

    override = disk_manifest["extraction_completeness"]["override"]
    assert override == {
        "used": True,
        "operator_intent": "publish reviewed facts after provider outage",
    }
    audit = next(
        event for event in events
        if event["step"] == "build_pack.extraction_override"
    )
    assert audit["payload"]["summary"]["run_status_counts"] == {"failed": 1}
    assert audit["payload"]["operator_intent"] == override["operator_intent"]


def test_override_requires_nonempty_operator_intent(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc_id = _verified_fact(store)
    _run(store, doc_id, "failed", "failed")
    store.close()

    with pytest.raises(PackBuildError, match="requires non-empty operator intent"):
        build_pack(
            tmp_path / "kg.sqlite", tmp_path / "packs", "bad-override",
            allow_incomplete_extraction=True,
        )


def test_browser_pack_surface_sends_explicit_override_and_intent() -> None:
    markup = Path("web/index.html").read_text(encoding="utf-8")
    script = Path("web/app.js").read_text(encoding="utf-8")

    assert 'id="pack-allow-incomplete"' in markup
    assert 'id="pack-override-intent"' in markup
    assert "allow_incomplete_extraction: allowIncomplete" in script
    assert "override_intent: allowIncomplete ? overrideIntent : null" in script


def test_empty_pack_remains_buildable_without_an_override(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    store.close()

    manifest = build_pack(tmp_path / "kg.sqlite", tmp_path / "packs", "empty")

    assert manifest.extraction_completeness["status"] == "not_applicable"
