"""Wave 2.1 Step 9A: disposable cutover rehearsal state machine."""
# noqa: SIZE_OK — single SUT rehearsal matrix; Step 9A owns only this file

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from ontologylab.authority_repo import create_work
from ontologylab.cutover_readers import (
    GenerationBinding,
    ReaderObservation,
    ReaderSurfaces,
    record_all_reader_observation,
)
from ontologylab.cutover_rehearsal import (
    CutoverBind,
    CutoverChecks,
    CutoverCode,
    CutoverPhase,
    CutoverRefused,
    DriftObservation,
    advance_cutover,
    canonical_data_hash,
    install_cutover,
    read_cutover_receipts,
    read_cutover_state,
    record_drift_observation,
)
from ontologylab.kgstore import KGStore
from ontologylab.mcp_server import PackSession
from ontologylab.migration import (
    WritesFenced,
    apply_v2_authority_mutation,
    compute_source_fingerprint,
    read_ledger,
    snapshot_db,
)
from ontologylab.packbuilder import build_pack
from tests.factories import make_entity
from tests.wave21.harness import Failpoint, FailpointArmed


def _insert_doc(conn: sqlite3.Connection, doc_id: str) -> None:
    conn.execute(
        "INSERT INTO documents "
        "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
        "raw_text_path) "
        "VALUES (?, 'upload', ?, ?, 0, ?, ?)",
        (
            doc_id,
            f"file:///{doc_id}.txt",
            doc_id,
            f"sha256:{doc_id}",
            f"documents/{doc_id}/raw.txt",
        ),
    )


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_pair(tmp_path: Path) -> tuple[Path, Path, str]:
    source = tmp_path / "src" / "kg.sqlite"
    source.parent.mkdir()
    store = KGStore.open(source)
    _insert_doc(store.conn, "doc-a")
    store.conn.commit()
    store.close()
    target = tmp_path / "copy"
    target.mkdir()
    copied = snapshot_db(source, target)
    return source, copied, _file_hash(source)


def _bind(conn: sqlite3.Connection, *, high_water: int = 7) -> CutoverBind:
    return CutoverBind(
        generation=1,
        high_water=high_water,
        source_fingerprint=compute_source_fingerprint(conn),
        backup_receipt="sha256:" + "ab" * 32,
    )


def _plant_verified(copied: Path) -> None:
    store = KGStore.open(copied)
    try:
        doc_id = str(store.conn.execute("SELECT id FROM documents").fetchone()[0])
        store.insert_proposed(
            [make_entity("RateLimiter")], [], source_doc_id=doc_id, extractor_engine="mock",
        )
        node_id = str(store.conn.execute("SELECT id FROM nodes").fetchone()[0])
        store.approve(node_id)
        store.conn.commit()
    finally:
        store.close()


@dataclass(frozen=True, slots=True)
class _Kit:
    source: Path
    copied: Path
    source_hash: str
    store: KGStore
    session: PackSession
    surfaces: ReaderSurfaces

    def close(self) -> None:
        self.session.close()
        self.store.close()


def _kit(tmp_path: Path) -> _Kit:
    source, copied, source_hash = _snapshot_pair(tmp_path)
    _plant_verified(copied)
    store = KGStore.open(copied)
    packs = tmp_path / "packs"
    manifest = build_pack(
        copied, packs, name="t13-kit",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="t13-kit",
    )
    session = PackSession(str(packs))
    surfaces = ReaderSurfaces(
        conn=store.conn, sqlite_path=copied, data_dir=copied.parent,
        pack_dir=packs / manifest.pack_id, session=session,
    )
    return _Kit(source, copied, source_hash, store, session, surfaces)


def _zero(kit: _Kit, binding: GenerationBinding | None = None) -> None:
    record_all_reader_observation(
        kit.store.conn, binding or GenerationBinding(1, 7), kit.surfaces,
    )


def _walk(kit: _Kit, target: CutoverPhase, checks: CutoverChecks | None = None) -> None:
    gates = checks or CutoverChecks(pack_verified=True)
    current = read_cutover_state(kit.store.conn).phase
    for phase in CutoverPhase:
        if list(CutoverPhase).index(phase) <= list(CutoverPhase).index(current):
            continue
        if phase is CutoverPhase.DRAINED:
            _zero(kit)
            _zero(kit)
        advance_cutover(kit.store.conn, phase, gates)
        if phase is target:
            return


def _diverge_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def _ghost(path: str, binding: GenerationBinding) -> ReaderObservation:
        from ontologylab.cutover_readers import (
            ReaderKind, ReaderObservation, ReaderStatus, hash_identity, identity_from_payload,
        )
        from ontologylab.kgstore import KGStore as Store

        store = Store.open(path)
        try:
            graph = store.graph_query(include_proposed=False, limit=500)
        finally:
            store.close()
        nodes = list(graph["nodes"]) + [
            {"id": "ghost", "name": "Ghost", "entity_type": "Component", "status": "verified"},
        ]
        digest = hash_identity(identity_from_payload(nodes, graph["edges"]))
        return ReaderObservation(ReaderKind.CLI_GRAPH, binding, ReaderStatus.AVAILABLE, digest, "")

    monkeypatch.setattr("ontologylab.cutover_readers.observe_cli_graph", _ghost)


def test_happy_path_reaches_authority_flipped_on_backup_copy(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        bind = _bind(kit.store.conn)
        installed = install_cutover(kit.store.conn, bind)
        assert installed.phase is CutoverPhase.EXPAND
        _walk(kit, CutoverPhase.FULL_V2)
        before = canonical_data_hash(kit.store.conn)
        advance_cutover(
            kit.store.conn, CutoverPhase.AUTHORITY_FLIPPED, CutoverChecks(pack_verified=True),
        )
        state = read_cutover_state(kit.store.conn)
        assert state.phase is CutoverPhase.AUTHORITY_FLIPPED
        assert state.generation == 1
        assert state.high_water == 7
        assert state.source_fingerprint == bind.source_fingerprint
        kinds = [(row.kind, row.phase) for row in read_cutover_receipts(kit.store.conn)]
        assert kinds == [
            ("transition", "expand"),
            ("transition", "shadow_write"),
            ("transition", "backfill"),
            ("transition", "catch_up"),
            ("reader_bundle", "catch_up"),
            ("observation", "catch_up"),
            ("reader_bundle", "catch_up"),
            ("observation", "catch_up"),
            ("transition", "drained"),
            ("transition", "fenced"),
            ("transition", "constraints_rebuilt"),
            ("transition", "full_v2"),
            ("transition", "authority_flipped"),
        ]
        assert canonical_data_hash(kit.store.conn) == before
        assert _file_hash(kit.source) == kit.source_hash
    finally:
        kit.close()


def test_one_zero_drift_cannot_drain(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        _zero(kit)
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(kit.store.conn, CutoverPhase.DRAINED, CutoverChecks())
        assert raised.value.code is CutoverCode.DRIFT_REQUIRED
        assert read_cutover_state(kit.store.conn).phase is CutoverPhase.CATCH_UP
    finally:
        kit.close()


def test_nonzero_drift_resets_and_cannot_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        _zero(kit)
        _diverge_cli(monkeypatch)
        _zero(kit)
        monkeypatch.undo()
        _zero(kit)
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(kit.store.conn, CutoverPhase.DRAINED, CutoverChecks())
        assert raised.value.code is CutoverCode.DRIFT_REQUIRED
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 1
    finally:
        kit.close()


def test_generation_mismatch_resets_and_cannot_drain(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        _zero(kit)
        _zero(kit, GenerationBinding(2, 7))
        _zero(kit)
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(kit.store.conn, CutoverPhase.DRAINED, CutoverChecks())
        assert raised.value.code is CutoverCode.DRIFT_REQUIRED
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 1
    finally:
        kit.close()


def test_high_water_mismatch_resets_and_cannot_drain(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        _zero(kit)
        _zero(kit, GenerationBinding(1, 8))
        _zero(kit)
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(kit.store.conn, CutoverPhase.DRAINED, CutoverChecks())
        assert raised.value.code is CutoverCode.DRIFT_REQUIRED
    finally:
        kit.close()


def test_live_writers_block_fence(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.DRAINED)
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(
                kit.store.conn, CutoverPhase.FENCED, CutoverChecks(old_writer_count=1),
            )
        assert raised.value.code is CutoverCode.WRITERS_LIVE
        assert read_cutover_state(kit.store.conn).phase is CutoverPhase.DRAINED
    finally:
        kit.close()


def test_fenced_apply_v2_authority_mutation_is_refused(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        bind = _bind(kit.store.conn)
        install_cutover(kit.store.conn, bind)
        _walk(kit, CutoverPhase.FENCED)
        with pytest.raises(WritesFenced) as raised:
            def _create(conn: sqlite3.Connection) -> None:
                create_work(conn, "w-fenced")

            apply_v2_authority_mutation(
                kit.store.conn,
                _create,
                generation=1,
                source_fingerprint=bind.source_fingerprint,
            )
        assert raised.value.generation == 1
        assert kit.store.conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 0
    finally:
        kit.close()


@pytest.mark.parametrize(
    ("field", "code"),
    (
        ("unmigrated_rows", CutoverCode.UNMIGRATED),
        ("blocking_collisions", CutoverCode.COLLISION),
        ("fk_errors", CutoverCode.FK_ERROR),
        ("citation_errors", CutoverCode.CITATION_ERROR),
        ("outbox_gap", CutoverCode.OUTBOX_GAP),
    ),
)
def test_integrity_blocker_refuses_constraints(
    tmp_path: Path, field: str, code: CutoverCode,
) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.FENCED)
        blocked = CutoverChecks(
            unmigrated_rows=1 if field == "unmigrated_rows" else 0,
            blocking_collisions=1 if field == "blocking_collisions" else 0,
            fk_errors=1 if field == "fk_errors" else 0,
            citation_errors=1 if field == "citation_errors" else 0,
            outbox_gap=1 if field == "outbox_gap" else 0,
        )
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(kit.store.conn, CutoverPhase.CONSTRAINTS_REBUILT, blocked)
        assert raised.value.code is code
        assert read_cutover_state(kit.store.conn).phase is CutoverPhase.FENCED
    finally:
        kit.close()


def test_open_outbox_blocks_full_v2(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CONSTRAINTS_REBUILT)
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(
                kit.store.conn,
                CutoverPhase.FULL_V2,
                CutoverChecks(pack_verified=True, open_outbox=1),
            )
        assert raised.value.code is CutoverCode.OUTBOX_OPEN
    finally:
        kit.close()


def test_unverified_pack_blocks_full_v2(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CONSTRAINTS_REBUILT)
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(
                kit.store.conn, CutoverPhase.FULL_V2, CutoverChecks(pack_verified=False),
            )
        assert raised.value.code is CutoverCode.VERIFIER_FAILED
    finally:
        kit.close()


def test_skipped_transition_is_refused(tmp_path: Path) -> None:
    source, copied, _hash = _snapshot_pair(tmp_path)
    store = KGStore.open(copied)
    try:
        install_cutover(store.conn, _bind(store.conn))
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(store.conn, CutoverPhase.BACKFILL, CutoverChecks())
        assert raised.value.code is CutoverCode.INVALID_TRANSITION
        assert read_cutover_state(store.conn).phase is CutoverPhase.EXPAND
    finally:
        store.close()


def test_duplicate_transition_is_refused(tmp_path: Path) -> None:
    source, copied, _hash = _snapshot_pair(tmp_path)
    store = KGStore.open(copied)
    try:
        install_cutover(store.conn, _bind(store.conn))
        advance_cutover(store.conn, CutoverPhase.SHADOW_WRITE, CutoverChecks())
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(store.conn, CutoverPhase.SHADOW_WRITE, CutoverChecks())
        assert raised.value.code is CutoverCode.DUPLICATE_TRANSITION
        assert read_cutover_state(store.conn).phase is CutoverPhase.SHADOW_WRITE
    finally:
        store.close()


def test_failpoint_rolls_back_state_and_receipt(tmp_path: Path) -> None:
    source, copied, _hash = _snapshot_pair(tmp_path)
    store = KGStore.open(copied)
    try:
        install_cutover(store.conn, _bind(store.conn))
        before_state = read_cutover_state(store.conn)
        before_receipts = read_cutover_receipts(store.conn)
        failpoint = Failpoint()
        failpoint.arm("after_state")
        with pytest.raises(FailpointArmed) as raised:
            advance_cutover(
                store.conn,
                CutoverPhase.SHADOW_WRITE,
                CutoverChecks(),
                failpoint=failpoint.hit,
            )
        assert raised.value.name == "after_state"
        assert read_cutover_state(store.conn) == before_state
        assert read_cutover_receipts(store.conn) == before_receipts
    finally:
        store.close()


def test_source_db_bytes_unchanged_after_rehearsal(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.AUTHORITY_FLIPPED)
    finally:
        kit.close()
    assert _file_hash(kit.source) == kit.source_hash
    assert read_ledger(sqlite3.connect(f"file:{kit.source}?mode=ro", uri=True)) == ()


def test_authority_flip_is_data_neutral(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.FULL_V2)
        before = canonical_data_hash(kit.store.conn)
        docs = list(kit.store.conn.execute("SELECT id, content_hash FROM documents"))
        advance_cutover(
            kit.store.conn, CutoverPhase.AUTHORITY_FLIPPED, CutoverChecks(pack_verified=True),
        )
        assert canonical_data_hash(kit.store.conn) == before
        assert list(kit.store.conn.execute("SELECT id, content_hash FROM documents")) == docs
        assert all(row.phase != "post_cutover_write" for row in read_ledger(kit.store.conn))
    finally:
        kit.close()


def test_expand_zero_observations_are_refused(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        with pytest.raises(CutoverRefused) as raised:
            _zero(kit)
        assert raised.value.code is CutoverCode.WRONG_PHASE
        with pytest.raises(CutoverRefused):
            _zero(kit)
        state = read_cutover_state(kit.store.conn)
        assert state.phase is CutoverPhase.EXPAND
        assert state.zero_drift_streak == 0
        assert all(row.kind != "observation" for row in read_cutover_receipts(kit.store.conn))
    finally:
        kit.close()


@pytest.mark.parametrize(
    ("start", "blocked"),
    (
        (CutoverPhase.DRAINED, CutoverPhase.FENCED),
        (CutoverPhase.FENCED, CutoverPhase.CONSTRAINTS_REBUILT),
        (CutoverPhase.CONSTRAINTS_REBUILT, CutoverPhase.FULL_V2),
        (CutoverPhase.FULL_V2, CutoverPhase.AUTHORITY_FLIPPED),
    ),
)
def test_stale_drift_after_drain_blocks_later_phases(
    tmp_path: Path, start: CutoverPhase, blocked: CutoverPhase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, start)
        _diverge_cli(monkeypatch)
        _zero(kit)
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(
                kit.store.conn, blocked, CutoverChecks(pack_verified=True),
            )
        assert raised.value.code is CutoverCode.DRIFT_REQUIRED
        assert read_cutover_state(kit.store.conn).phase is start
    finally:
        kit.close()


def test_install_pending_insert_rolls_back_with_caller_transaction(
    tmp_path: Path,
) -> None:
    _source, copied, _hash = _snapshot_pair(tmp_path)
    store = KGStore.open(copied)
    try:
        _insert_doc(store.conn, "doc-pending")
        assert store.conn.in_transaction
        install_cutover(store.conn, _bind(store.conn))
        assert store.conn.in_transaction
        store.conn.rollback()
        ids = [
            row[0] for row in store.conn.execute("SELECT id FROM documents ORDER BY id")
        ]
        tables = [
            row[0]
            for row in store.conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'cutover_%'"
            )
        ]
        assert "doc-pending" not in ids
        assert tables == []
    finally:
        store.close()


def test_public_record_drift_observation_cannot_advance_streak(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        with pytest.raises(CutoverRefused) as raised:
            record_drift_observation(
                kit.store.conn, DriftObservation(generation=1, high_water=7, drift=0),
            )
        assert raised.value.code is CutoverCode.DRIFT_REQUIRED
        assert raised.value.detail == "reader_proof"
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
    finally:
        kit.close()
