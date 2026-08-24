"""One-snapshot evidence-self-contained pack v2 closure contracts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from ontologylab.authority_repo import attach_identifier, create_work
from ontologylab.citation import CitationBinding, put_citation_receipts
from ontologylab.citation_ids import citation_receipt_id, fact_revision_id
from ontologylab.extraction_receipt_types import (
    ExtractionChunkReceipt,
    ExtractionRunReceipt,
)
from ontologylab.extraction_state import (
    ChunkSpan,
    ExtractionRunBinding,
    put_extraction_receipts,
)
from ontologylab.file_lifecycle import content_hash_for, finalize_representation
from ontologylab.ingestion_service import IngestItem, RepresentationInput, ingest_item
from ontologylab.kgstore import KGStore
from ontologylab.models import SourceSpan
from ontologylab.migration import (
    MIGRATION_PHASES,
    begin_phase,
    complete_phase,
    compute_source_fingerprint,
)
from ontologylab.pack_readiness import PackReadinessCode, PackReadinessRefused
from ontologylab.pack_v2_closure import (
    CLOSURE_MEMBERS,
    PackV2ClosureCode,
    PackV2ClosureRefused,
    resolve_v2_closure,
)
from ontologylab.packbuilder import (
    build_pack,
    list_packs,
    rewrite_existing_pack,
)
from ontologylab.selection import put_selection_receipt
from ontologylab.selection_types import PolicyVersion, SelectionReceipt
from ontologylab.work_redirects import record_redirect
from tests.factories import make_entity, make_relation

_TEXT: Final = "The PaymentGateway uses the DatabaseService."
_GATEWAY: Final = (4, 18)
_SERVICE: Final = (28, 44)
_DOI: Final = "10.1000/pack.v2.closure"
_GENERATION: Final = 1
_CAPABILITIES: Final = (
    "knowledge-graph-v2",
    "evidence-self-contained-v2",
)


@dataclass(frozen=True, slots=True)
class _V2Fixture:
    store: KGStore
    kg: Path
    root: Path
    work_id: str
    alias_work_id: str
    representation_id: str
    identifier_id: str
    observation_id: str
    citation_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    run_receipt_id: str
    chunk_receipt_id: str
    policy_receipt_id: str
    redirect_id: str
    decision_id: str
    generation: int
    content_hash: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            hasher.update(path.relative_to(root).as_posix().encode())
            hasher.update(b"\0")
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _visible_pack_names(packs: Path) -> list[str]:
    if not packs.is_dir():
        return []
    return sorted(
        path.name
        for path in packs.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def _staging_residue(root: Path) -> list[str]:
    return sorted(path.name for path in root.glob(".*-staging-*"))


def _cite(
    store: KGStore,
    representation_id: str,
    run: ExtractionRunReceipt,
    chunk: ExtractionChunkReceipt,
    selection: SelectionReceipt,
    *,
    fact_kind: str,
    fact_id: str,
    start: int,
    end: int,
) -> str:
    selected = _TEXT[start:end]
    stored = put_citation_receipts(
        store.conn,
        (
            CitationBinding(
                representation_id=representation_id,
                representation_content_hash=run.document_content_hash,
                run_receipt_id=run.receipt_id,
                chunk_receipt_id=chunk.receipt_id,
                chunk_start_offset=chunk.start_offset,
                chunk_end_offset=chunk.end_offset,
                coordinate_profile=chunk.coordinate_profile,
                chunk_text_hash=chunk.chunk_text_hash,
                chunk_plan_receipt_id=chunk.plan_receipt_id,
                selection_receipt_id=selection.receipt_id,
                policy_identity=selection.policy_hash,
                fact_kind=fact_kind,
                fact_id=fact_id,
                proposal_id=fact_id,
                fact_revision=fact_revision_id(fact_kind, fact_id),
                start_offset=start,
                end_offset=end,
                selected_text=selected,
                selected_text_hash=content_hash_for(selected.encode("utf-8")),
            ),
        ),
    )[0]
    return stored.receipt_id


def _complete_streams(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT DISTINCT source_doc_id, "
        "(SELECT content_hash FROM documents WHERE id = source_doc_id), "
        "schema_version_id, extractor_engine, "
        "COALESCE(extractor_model, ''), COALESCE(prompt_version, ''), "
        "COALESCE(decode_params, 'null') "
        "FROM nodes WHERE status = 'verified'"
    ).fetchall()
    for index, row in enumerate(rows):
        run_id = f"stream-run-{index}"
        conn.execute(
            "INSERT INTO extraction_runs ("
            "id, document_id, document_content_hash, schema_version_id, "
            "extractor_engine, extractor_model, prompt_version, decode_params, "
            "chunk_plan_hash, status, created_ts, updated_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'plan', 'complete', 1, 1)",
            (run_id, *row),
        )
        conn.execute(
            "INSERT INTO extraction_chunks ("
            "run_id, chunk_index, char_offset, content_hash, status) "
            "VALUES (?, 0, 0, ?, 'succeeded')",
            (run_id, row[1]),
        )


def _plant_v2(tmp_path: Path, *, complete_stream: bool = True) -> _V2Fixture:
    kg = tmp_path / "kg.sqlite"
    store = KGStore.open(kg)
    body = _TEXT.encode("utf-8")
    digest = content_hash_for(body)
    receipt = ingest_item(
        store.conn,
        IngestItem(
            idempotency_key="pack-v2-closure",
            scheme="doi",
            normalized_value=_DOI,
            source="pmc",
            evidence_grade="A",
            representation=RepresentationInput(
                source_kind="paper_api",
                source_uri="https://example.invalid/pmc/pack-v2",
                title="pack-v2",
                content_hash=digest,
                raw_text=body,
            ),
            stage="unknown",
            content_kind="fulltext",
        ),
    )
    assert receipt.work_id is not None
    assert receipt.representation_id is not None
    assert receipt.identifier_id is not None
    assert receipt.observation_id is not None
    store.conn.commit()
    finalize_representation(store.conn, tmp_path, receipt.representation_id)
    store.conn.commit()
    selection = put_selection_receipt(
        store.conn, receipt.work_id, PolicyVersion.V1,
    )
    runs = put_extraction_receipts(
        store.conn,
        ExtractionRunBinding(
            representation_id=receipt.representation_id,
            policy_identity=selection.policy_hash,
            config_identity="config-pack-v2",
            schema_version_id=1,
            extractor_engine="mock",
            extractor_model="",
            prompt_version="extract-v1",
            decode_params_json="{}",
        ),
        (
            ChunkSpan(
                index=0,
                start_offset=0,
                end_offset=len(_TEXT),
                text=_TEXT,
                text_hash=digest,
                coordinate_profile="document-utf8-v1",
            ),
        ),
    )
    gateway = make_entity(
        "PaymentGateway",
        source_span=SourceSpan(start=_GATEWAY[0], end=_GATEWAY[1]),
    )
    service = make_entity(
        "DatabaseService",
        source_span=SourceSpan(start=_SERVICE[0], end=_SERVICE[1]),
    )
    relation = make_relation(
        gateway,
        service,
        source_span=SourceSpan(start=_GATEWAY[0], end=_SERVICE[1]),
    )
    stats = store.insert_proposed(
        [gateway, service],
        [relation],
        source_doc_id=receipt.representation_id,
        extractor_engine="mock",
        commit=False,
    )
    gateway_id = stats["id_map"][gateway.id]
    service_id = stats["id_map"][service.id]
    edge_id = str(
        store.conn.execute(
            "SELECT id FROM edges WHERE src_node_id = ? AND dst_node_id = ?",
            (gateway_id, service_id),
        ).fetchone()["id"]
    )
    citation_ids = (
        _cite(
            store, receipt.representation_id, runs.run, runs.chunks[0],
            selection, fact_kind="node", fact_id=gateway_id,
            start=_GATEWAY[0], end=_GATEWAY[1],
        ),
        _cite(
            store, receipt.representation_id, runs.run, runs.chunks[0],
            selection, fact_kind="node", fact_id=service_id,
            start=_SERVICE[0], end=_SERVICE[1],
        ),
        _cite(
            store, receipt.representation_id, runs.run, runs.chunks[0],
            selection, fact_kind="edge", fact_id=edge_id,
            start=_GATEWAY[0], end=_SERVICE[1],
        ),
    )
    store.conn.execute(
        "INSERT INTO identifier_decisions "
        "(id, identifier_id, action, actor, reason, created_ts) "
        "VALUES ('idd-pack-v2', ?, 'attach', 'tester', 'seed', 1.0)",
        (receipt.identifier_id,),
    )
    alias_work_id = create_work(store.conn, "work-pack-v2-alias")
    redirect = record_redirect(
        store.conn,
        source_work_id=alias_work_id,
        target_work_id=receipt.work_id,
        action="merge",
        actor="tester",
        reason="alias",
        decided_ts=1.0,
    )
    fingerprint = compute_source_fingerprint(store.conn)
    for phase in MIGRATION_PHASES:
        begin_phase(
            store.conn,
            phase=phase,
            generation=_GENERATION,
            source_fingerprint=fingerprint,
        )
        complete_phase(
            store.conn,
            phase=phase,
            generation=_GENERATION,
            source_fingerprint=fingerprint,
        )
    store.conn.commit()
    approved = store.approve(
        edge_id, cascade=True, by="tester", note="grounded",
    )
    review_ids = tuple(approved["decision_receipt_ids"])
    if complete_stream:
        _complete_streams(store.conn)
    store.conn.commit()
    return _V2Fixture(
        store=store,
        kg=kg,
        root=tmp_path,
        work_id=receipt.work_id,
        alias_work_id=alias_work_id,
        representation_id=receipt.representation_id,
        identifier_id=receipt.identifier_id,
        observation_id=receipt.observation_id,
        citation_ids=citation_ids,
        review_ids=review_ids,
        run_receipt_id=runs.run.receipt_id,
        chunk_receipt_id=runs.chunks[0].receipt_id,
        policy_receipt_id=selection.receipt_id,
        redirect_id=redirect.decision_id,
        decision_id="idd-pack-v2",
        generation=_GENERATION,
        content_hash=digest,
    )


def _delete_source(fixture: _V2Fixture) -> None:
    fixture.store.close()
    fixture.kg.unlink()
    documents = fixture.root / "documents"
    if documents.exists():
        for child in documents.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted(documents.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        documents.rmdir()


def _build_v2(fixture: _V2Fixture, packs: Path, *, evidence_mode: str):
    return build_pack(
        fixture.kg,
        packs,
        name=f"v2-{evidence_mode}",
        evidence_mode=evidence_mode,
    )


def _assert_closure_members(pack_dir: Path, fixture: _V2Fixture) -> None:
    resolved = resolve_v2_closure(pack_dir)
    assert resolved.pack_schema_version == 2
    assert resolved.generation == fixture.generation
    assert set(resolved.members) == set(CLOSURE_MEMBERS)
    for member in CLOSURE_MEMBERS:
        assert resolved.members[member]
    assert fixture.work_id in resolved.members["work"]
    assert fixture.alias_work_id in resolved.members["work"]
    assert fixture.identifier_id in resolved.members["identifier"]
    assert fixture.redirect_id in resolved.members["redirect"]
    assert fixture.decision_id in resolved.members["decision"]
    assert fixture.observation_id in resolved.members["observation"]
    assert fixture.representation_id in resolved.members["representation"]
    assert fixture.run_receipt_id in resolved.members["run"]
    assert fixture.chunk_receipt_id in resolved.members["chunk"]
    assert fixture.policy_receipt_id in resolved.members["policy"]
    assert set(fixture.citation_ids) <= set(resolved.members["citation"])
    assert set(fixture.review_ids) <= set(resolved.members["review_decision"])


def test_v1_build_omits_v2_schema_version_when_evidence_mode_absent(
    tmp_path: Path,
) -> None:
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    document, _created = store.insert_document(
        source_kind="upload",
        source_uri="file:///v1.txt",
        title="v1",
        raw_text="RateLimiter uses TokenBucket",
        content_hash="v1-pack-hash",
    )
    store.insert_proposed(
        [make_entity("RateLimiter")],
        [],
        source_doc_id=document.id,
        extractor_engine="mock",
    )
    node_id = store.conn.execute("SELECT id FROM nodes").fetchone()["id"]
    store.approve(node_id)
    store.close()
    manifest = build_pack(
        kg,
        packs,
        name="legacy",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="v1-compat",
    )
    payload = json.loads(
        (packs / manifest.pack_id / "manifest.json").read_text(encoding="utf-8")
    )
    assert payload.get("pack_schema_version") != 2
    assert "evidence-self-contained-v2" not in (payload.get("capabilities") or [])


def test_full_pack_resolves_every_closure_member_from_pack_bytes(
    tmp_path: Path,
) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    try:
        manifest = _build_v2(fixture, packs, evidence_mode="full")
        pack_dir = packs / manifest.pack_id
        payload = json.loads(
            (pack_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert payload["pack_schema_version"] == 2
        assert payload["evidence_mode"] == "full"
        assert payload["generation"] == _GENERATION
        assert payload["capabilities"] == list(_CAPABILITIES)
        assert payload["selection_policy_version"] == "preferred-representation-v1"
        assert payload["source_material_policy"]["full_count"] == 1
        assert payload["source_material_policy"]["excerpt_count"] == 0
        for key in (
            "works",
            "representations",
            "identifiers",
            "citations",
            "extraction_runs",
            "extraction_chunks",
            "nodes",
            "edges",
        ):
            assert payload["counts"][key] >= 1
        assert payload["counts"]["observations"] >= 1
        assert payload["counts"]["review_decisions"] >= 1
        assert payload["counts"]["nodes_verified"] >= 1
        assert payload["counts"]["edges_verified"] >= 1
        assert payload["integrity_model"] == "sha256-receipt-not-signature"
        assert payload["sqlite_hash"].startswith("sha256:")
        assert payload["pack_content_hash"].startswith("sha256:")
        inventory_paths = [item["path"] for item in payload["artifact_inventory"]]
        assert "manifest.json" not in inventory_paths
        assert inventory_paths == sorted(inventory_paths)
        assert set(payload["closure"]) == set(CLOSURE_MEMBERS)
        _delete_source(fixture)
        _assert_closure_members(pack_dir, fixture)
        full = (
            pack_dir / "evidence" / fixture.representation_id / "full.txt"
        )
        assert full.read_bytes() == _TEXT.encode("utf-8")
        assert resolve_v2_closure(pack_dir).evidence_mode == "full"
    finally:
        if fixture.kg.exists():
            fixture.store.close()


def test_excerpt_pack_resolves_every_closure_member_from_pack_bytes(
    tmp_path: Path,
) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    try:
        manifest = _build_v2(fixture, packs, evidence_mode="excerpt")
        pack_dir = packs / manifest.pack_id
        payload = json.loads(
            (pack_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert payload["pack_schema_version"] == 2
        assert payload["evidence_mode"] == "excerpt"
        assert payload["source_material_policy"]["full_count"] == 0
        assert payload["source_material_policy"]["excerpt_count"] >= 1
        assert not (
            pack_dir / "evidence" / fixture.representation_id / "full.txt"
        ).exists()
        _delete_source(fixture)
        _assert_closure_members(pack_dir, fixture)
        resolved = resolve_v2_closure(pack_dir)
        assert resolved.evidence_mode == "excerpt"
        for citation_id in fixture.citation_ids:
            window = pack_dir / "evidence" / citation_id / "window.txt"
            assert window.is_file()
            assert window.read_bytes()
    finally:
        if fixture.kg.exists():
            fixture.store.close()


def test_sourced_none_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    try:
        with pytest.raises(PackV2ClosureRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="none")
        assert raised.value.code is PackV2ClosureCode.SOURCED_NONE
        assert _visible_pack_names(packs) == []
        assert _staging_residue(tmp_path) == []
    finally:
        fixture.store.close()


def test_dangling_member_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    try:
        fixture.store.conn.execute("PRAGMA foreign_keys=OFF")
        fixture.store.conn.execute(
            "UPDATE documents SET work_id = 'ghost-work' WHERE id = ?",
            (fixture.representation_id,),
        )
        fixture.store.conn.execute("PRAGMA foreign_keys=ON")
        fixture.store.conn.commit()
        with pytest.raises(PackV2ClosureRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackV2ClosureCode.DANGLING_MEMBER
        assert raised.value.member == "work"
        assert _visible_pack_names(packs) == []
        assert _staging_residue(tmp_path) == []
    finally:
        fixture.store.close()


def test_cross_generation_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    try:
        row = fixture.store.conn.execute(
            "SELECT event_id, payload_json FROM provenance_outbox LIMIT 1"
        ).fetchone()
        payload = json.loads(row["payload_json"])
        payload["generation"] = _GENERATION + 1
        fixture.store.conn.execute(
            "INSERT INTO provenance_outbox "
            "(event_id, step, payload_json, created_ts) "
            "VALUES ('evt-cross-gen', ?, ?, 2.0)",
            ("observation.recorded", json.dumps(payload)),
        )
        fixture.store.conn.commit()
        with pytest.raises(PackV2ClosureRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackV2ClosureCode.CROSS_GENERATION
        assert _visible_pack_names(packs) == []
        assert _staging_residue(tmp_path) == []
    finally:
        fixture.store.close()


def test_missing_receipt_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    try:
        fixture.store.conn.execute(
            "DROP TRIGGER IF EXISTS trg_preferred_selection_receipts_no_delete"
        )
        fixture.store.conn.execute("DELETE FROM preferred_selection_receipts")
        fixture.store.conn.commit()
        with pytest.raises(PackReadinessRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackReadinessCode.MISSING_RECEIPT
        assert raised.value.member == "policy"
        assert _visible_pack_names(packs) == []
        assert _staging_residue(tmp_path) == []
    finally:
        fixture.store.close()


def test_incomplete_stream_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path, complete_stream=False)
    packs = tmp_path / "packs"
    try:
        with pytest.raises(PackV2ClosureRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackV2ClosureCode.INCOMPLETE_STREAM
        assert _visible_pack_names(packs) == []
        assert _staging_residue(tmp_path) == []
    finally:
        fixture.store.close()


def test_v1_rewrite_refused_and_preserves_bytes(tmp_path: Path) -> None:
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    document, _created = store.insert_document(
        source_kind="upload",
        source_uri="file:///v1-rewrite.txt",
        title="v1",
        raw_text="RateLimiter uses TokenBucket",
        content_hash="v1-rewrite-hash",
    )
    store.insert_proposed(
        [make_entity("RateLimiter")],
        [],
        source_doc_id=document.id,
        extractor_engine="mock",
    )
    node_id = store.conn.execute("SELECT id FROM nodes").fetchone()["id"]
    store.approve(node_id)
    store.close()
    manifest = build_pack(
        kg,
        packs,
        name="legacy-rewrite",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="v1-rewrite",
    )
    pack_dir = packs / manifest.pack_id
    before = _tree_digest(pack_dir)
    manifest_hash = _sha256(pack_dir / "manifest.json")
    with pytest.raises(PackV2ClosureRefused) as raised:
        rewrite_existing_pack(packs, manifest.pack_id)
    assert raised.value.code is PackV2ClosureCode.V1_REWRITE
    assert _tree_digest(pack_dir) == before
    assert _sha256(pack_dir / "manifest.json") == manifest_hash
    payload = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    assert payload.get("pack_schema_version") != 2


def _drop_citation_update_guard(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TRIGGER IF EXISTS trg_citation_receipts_no_update")


def test_full_evidence_hash_mismatch_refused_before_visible_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    original = __import__(
        "ontologylab.pack_v2_closure", fromlist=["write_v2_evidence"]
    ).write_v2_evidence

    def _tamper_then_write(pack_dir: Path, closure, source_root: Path) -> None:
        raw = source_root / "documents" / fixture.representation_id / "raw.txt"
        raw.write_bytes(raw.read_bytes() + b"\nTAMPER-AFTER-COLLECT")
        original(pack_dir, closure, source_root)

    monkeypatch.setattr(
        "ontologylab.pack_v2_closure.write_v2_evidence", _tamper_then_write,
    )
    try:
        with pytest.raises(PackV2ClosureRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackV2ClosureCode.EVIDENCE_HASH_MISMATCH
        assert raised.value.member == "source"
        assert _visible_pack_names(packs) == []
        assert _staging_residue(tmp_path) == []
    finally:
        fixture.store.close()


def test_unrelated_and_ineligible_rows_are_absent_from_pack(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    extra_work = create_work(fixture.store.conn, "work-unrelated-probe")
    attached = attach_identifier(
        fixture.store.conn,
        work_id=extra_work,
        scheme="doi",
        normalized_value="10.1000/unrelated.probe",
        idempotency_key="unrelated-probe",
        source="web",
        evidence_grade="D",
    )
    ghost = make_entity("UnrelatedGhost")
    stats = fixture.store.insert_proposed(
        [ghost], [], source_doc_id=fixture.representation_id,
        extractor_engine="mock", commit=False,
    )
    proposed_id = stats["id_map"][ghost.id]
    _drop_citation_update_guard(fixture.store.conn)
    source = fixture.store.conn.execute(
        "SELECT * FROM citation_receipts WHERE receipt_id = ?",
        (fixture.citation_ids[0],),
    ).fetchone()
    probe_id = citation_receipt_id(
        CitationBinding(
            representation_id=str(source["representation_id"]),
            representation_content_hash=str(source["representation_content_hash"]),
            run_receipt_id=str(source["run_receipt_id"]),
            chunk_receipt_id=str(source["chunk_receipt_id"]),
            chunk_start_offset=int(source["chunk_start_offset"]),
            chunk_end_offset=int(source["chunk_end_offset"]),
            coordinate_profile=str(source["coordinate_profile"]),
            chunk_text_hash=str(source["chunk_text_hash"]),
            chunk_plan_receipt_id=str(source["chunk_plan_receipt_id"]),
            selection_receipt_id=source["selection_receipt_id"],
            policy_identity=source["policy_identity"],
            fact_kind=str(source["fact_kind"]),
            fact_id=proposed_id,
            proposal_id=str(source["proposal_id"]),
            fact_revision=str(source["fact_revision"]),
            start_offset=int(source["start_offset"]),
            end_offset=int(source["end_offset"]),
            selected_text=str(source["selected_text"]),
            selected_text_hash=str(source["selected_text_hash"]),
        )
    )
    fixture.store.conn.execute(
        "INSERT INTO citation_receipts ("
        "receipt_id, representation_id, representation_content_hash, "
        "run_receipt_id, chunk_receipt_id, chunk_start_offset, chunk_end_offset, "
        "coordinate_profile, chunk_text_hash, chunk_plan_receipt_id, "
        "selection_receipt_id, policy_identity, fact_kind, fact_id, proposal_id, "
        "fact_revision, start_offset, end_offset, selected_text, "
        "selected_text_hash, created_ts) "
        "SELECT ?, representation_id, "
        "representation_content_hash, run_receipt_id, chunk_receipt_id, "
        "chunk_start_offset, chunk_end_offset, coordinate_profile, "
        "chunk_text_hash, chunk_plan_receipt_id, selection_receipt_id, "
        "policy_identity, fact_kind, ?, proposal_id, fact_revision, "
        "start_offset, end_offset, selected_text, selected_text_hash, created_ts "
        "FROM citation_receipts WHERE receipt_id = ?",
        (probe_id, proposed_id, fixture.citation_ids[0]),
    )
    fixture.store.conn.execute(
        "INSERT INTO grounded_review_decisions ("
        "receipt_id, fact_kind, fact_id, proposal_id, fact_revision, action, "
        "actor, reason, decided_ts, as_of_ts, citation_set_digest, "
        "citation_receipt_ids_json, representation_id, selection_receipt_id, "
        "policy_identity, run_receipt_id, predecessor_receipt_id, "
        "pack_ineligible, waived_fact_ids_json, waived_citation_ids_json, "
        "scoped_defects_json) "
        "SELECT 'review-ineligible-probe', fact_kind, fact_id, proposal_id, "
        "fact_revision, action, actor, reason, decided_ts, as_of_ts, "
        "citation_set_digest, citation_receipt_ids_json, representation_id, "
        "selection_receipt_id, policy_identity, run_receipt_id, "
        "predecessor_receipt_id, 1, waived_fact_ids_json, "
        "waived_citation_ids_json, scoped_defects_json "
        "FROM grounded_review_decisions WHERE receipt_id = ?",
        (fixture.review_ids[0],),
    )
    fixture.store.conn.commit()
    try:
        manifest = _build_v2(fixture, packs, evidence_mode="full")
        pack = packs / manifest.pack_id / "pack.sqlite"
        payload = json.loads(
            (packs / manifest.pack_id / "manifest.json").read_text(encoding="utf-8")
        )
        conn = sqlite3.connect(f"file:{pack}?mode=ro", uri=True)
        try:
            works = {row[0] for row in conn.execute("SELECT id FROM works")}
            cites = {
                row[0] for row in conn.execute("SELECT receipt_id FROM citation_receipts")
            }
            reviews = {
                row[0]
                for row in conn.execute("SELECT receipt_id FROM grounded_review_decisions")
            }
            idents = {row[0] for row in conn.execute("SELECT id FROM work_identifiers")}
            observations = {
                row[0] for row in conn.execute("SELECT id FROM document_observations")
            }
        finally:
            conn.close()
        assert extra_work not in works
        assert extra_work not in payload["closure"]["work"]
        assert attached.identifier_id not in idents
        assert attached.identifier_id not in payload["closure"]["identifier"]
        assert attached.observation_id not in observations
        assert attached.observation_id not in payload["closure"]["observation"]
        assert probe_id not in cites
        assert probe_id not in payload["closure"]["citation"]
        assert "review-ineligible-probe" not in reviews
        assert "review-ineligible-probe" not in payload["closure"]["review_decision"]
        assert proposed_id not in {
            row[0]
            for row in sqlite3.connect(f"file:{pack}?mode=ro", uri=True).execute(
                "SELECT id FROM nodes"
            )
        }
    finally:
        fixture.store.close()


def test_empty_optional_redirect_and_decision_publish(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.conn.execute(
        "DROP TRIGGER IF EXISTS trg_work_redirect_decisions_no_delete"
    )
    fixture.store.conn.execute(
        "DROP TRIGGER IF EXISTS trg_identifier_decisions_no_delete"
    )
    fixture.store.conn.execute("DELETE FROM work_redirect_decisions")
    fixture.store.conn.execute("DELETE FROM identifier_decisions")
    fixture.store.conn.commit()
    try:
        manifest = _build_v2(fixture, packs, evidence_mode="full")
        payload = json.loads(
            (packs / manifest.pack_id / "manifest.json").read_text(encoding="utf-8")
        )
        assert payload["closure"]["redirect"] == []
        assert payload["closure"]["decision"] == []
        assert payload["closure"]["work"]
        assert payload["closure"]["citation"]
        resolved = resolve_v2_closure(packs / manifest.pack_id)
        assert resolved.members["redirect"] == ()
        assert resolved.members["decision"] == ()
        assert resolved.members["work"]
    finally:
        if fixture.kg.exists():
            fixture.store.close()


def test_missing_generation_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.conn.execute("DELETE FROM v2_migration_ledger")
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackReadinessCode.INCOMPLETE_LEDGER
        assert raised.value.member == "ledger"
        assert _visible_pack_names(packs) == []
        assert _staging_residue(tmp_path) == []
    finally:
        fixture.store.close()


def test_distinct_ledger_generations_refused_before_visible_staging(
    tmp_path: Path,
) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.conn.execute(
        "INSERT INTO v2_migration_ledger "
        "(phase, cursor, generation, source_fingerprint, created_ts) "
        "VALUES ('expand', NULL, ?, ?, 2.0)",
        (_GENERATION + 1, compute_source_fingerprint(fixture.store.conn)),
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackReadinessCode.AMBIGUOUS_LEDGER
        assert _visible_pack_names(packs) == []
    finally:
        fixture.store.close()


def test_tampered_selected_text_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    _drop_citation_update_guard(fixture.store.conn)
    fixture.store.conn.execute(
        "UPDATE citation_receipts SET selected_text = selected_text || 'X' "
        "WHERE receipt_id = ?",
        (fixture.citation_ids[0],),
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackV2ClosureRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackV2ClosureCode.EVIDENCE_HASH_MISMATCH
        assert raised.value.member == "citation"
        assert _visible_pack_names(packs) == []
    finally:
        fixture.store.close()


def test_tampered_selected_text_hash_refused_before_visible_staging(
    tmp_path: Path,
) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    _drop_citation_update_guard(fixture.store.conn)
    fixture.store.conn.execute(
        "UPDATE citation_receipts SET selected_text_hash = 'sha256:deadbeef' "
        "WHERE receipt_id = ?",
        (fixture.citation_ids[0],),
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackReadinessCode.STALE_RECEIPT
        assert raised.value.member == "citation"
        assert _visible_pack_names(packs) == []
    finally:
        fixture.store.close()


def test_missing_policy_link_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    _drop_citation_update_guard(fixture.store.conn)
    fixture.store.conn.execute(
        "UPDATE citation_receipts SET selection_receipt_id = 'missing-sel', "
        "policy_identity = 'missing-pol' WHERE receipt_id = ?",
        (fixture.citation_ids[0],),
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackReadinessCode.STALE_RECEIPT
        assert raised.value.member == "citation"
        assert _visible_pack_names(packs) == []
    finally:
        fixture.store.close()


def test_cross_bound_run_chunk_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    second = put_extraction_receipts(
        fixture.store.conn,
        ExtractionRunBinding(
            representation_id=fixture.representation_id,
            policy_identity="other-policy",
            config_identity="config-cross-bind",
            schema_version_id=1,
            extractor_engine="mock",
            extractor_model="",
            prompt_version="extract-v1",
            decode_params_json="{}",
        ),
        (
            ChunkSpan(
                index=0,
                start_offset=0,
                end_offset=len(_TEXT),
                text=_TEXT,
                text_hash=fixture.content_hash,
                coordinate_profile="document-utf8-v1",
            ),
        ),
    )
    _drop_citation_update_guard(fixture.store.conn)
    fixture.store.conn.execute(
        "UPDATE citation_receipts SET run_receipt_id = ? WHERE receipt_id = ?",
        (second.run.receipt_id, fixture.citation_ids[0]),
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackReadinessCode.STALE_RECEIPT
        assert raised.value.member == "citation"
        assert _visible_pack_names(packs) == []
    finally:
        fixture.store.close()


def test_source_file_hash_drift_refused_before_visible_staging(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    raw = tmp_path / "documents" / fixture.representation_id / "raw.txt"
    raw.write_bytes(raw.read_bytes() + b"FILE-HASH-DRIFT")
    try:
        with pytest.raises(PackV2ClosureRefused) as raised:
            _build_v2(fixture, packs, evidence_mode="full")
        assert raised.value.code is PackV2ClosureCode.EVIDENCE_HASH_MISMATCH
        assert raised.value.member == "source"
        assert _visible_pack_names(packs) == []
    finally:
        fixture.store.close()
