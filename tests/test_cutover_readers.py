"""Wave 2.1 Step 9A Task 14: all-reader generation-bound zero drift."""
# noqa: SIZE_OK — single SUT reader-proof matrix; Task 14 owns only this file

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ontologylab.cutover_readers import (
    GenerationBinding,
    ReaderKind,
    ReaderObservation,
    ReaderStatus,
    hash_identity,
    identity_from_payload,
    observe_cli_graph,
    observe_http_query,
    observe_mcp_session,
    observe_method_graph,
    reader_probes,
    record_all_reader_observation,
)
from ontologylab.cutover_rehearsal import (
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
from ontologylab.packbuilder import build_pack
from tests.test_cutover_rehearsal import _bind, _kit, _walk, _zero
from tests.test_method_pack import seed_method_pack_database


def _binding() -> GenerationBinding:
    return GenerationBinding(1, 7)


def test_two_real_reader_passes_drain_and_flip(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.AUTHORITY_FLIPPED)
        assert read_cutover_state(kit.store.conn).phase is CutoverPhase.AUTHORITY_FLIPPED
        kinds = [row.kind for row in read_cutover_receipts(kit.store.conn)]
        assert kinds.count("reader_bundle") == 2
        assert hashlib.sha256(kit.source.read_bytes()).hexdigest() == kit.source_hash
    finally:
        kit.close()


def test_omit_duplicate_reader_refuses(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        probes = reader_probes(kit.surfaces, _binding())
        with pytest.raises(CutoverRefused) as omitted:
            record_all_reader_observation(
                kit.store.conn, _binding(), probes=probes[:-1],
            )
        assert omitted.value.code is CutoverCode.READER_SET
        with pytest.raises(CutoverRefused) as duplicated:
            record_all_reader_observation(
                kit.store.conn, _binding(), probes=(*probes, probes[0]),
            )
        assert duplicated.value.code is CutoverCode.READER_SET
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
    finally:
        kit.close()


def test_cli_payload_corrupt_resets_streak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        _zero(kit)
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 1
        real = observe_cli_graph

        def _corrupt(path: str, binding: GenerationBinding) -> ReaderObservation:
            store = KGStore.open(path)
            try:
                graph = store.graph_query(include_proposed=False, limit=500)
            finally:
                store.close()
            nodes = list(graph["nodes"]) + [
                {"id": "cli-ghost", "name": "G", "entity_type": "Component", "status": "verified"},
            ]
            digest = hash_identity(identity_from_payload(nodes, graph["edges"]))
            return ReaderObservation(
                ReaderKind.CLI_GRAPH, binding, ReaderStatus.AVAILABLE, digest, "",
            )

        monkeypatch.setattr("ontologylab.cutover_readers.observe_cli_graph", _corrupt)
        _zero(kit)
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
        with pytest.raises(CutoverRefused):
            advance_cutover(kit.store.conn, CutoverPhase.DRAINED, CutoverChecks())
        monkeypatch.setattr("ontologylab.cutover_readers.observe_cli_graph", real)
    finally:
        kit.close()


def test_http_payload_corrupt_resets_streak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        _zero(kit)
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 1

        def _corrupt(data_dir: Path, binding: GenerationBinding) -> ReaderObservation:
            honest = observe_http_query(data_dir, binding)
            digest = "sha256:" + ("aa" * 32)
            return ReaderObservation(
                honest.kind, honest.binding, honest.status, digest, honest.detail,
            )

        monkeypatch.setattr("ontologylab.cutover_readers.observe_http_query", _corrupt)
        _zero(kit)
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
    finally:
        kit.close()


def test_mcp_payload_corrupt_resets_streak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        _zero(kit)
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 1

        def _corrupt(session: PackSession, pack_id: str, binding: GenerationBinding) -> ReaderObservation:
            honest = observe_mcp_session(session, pack_id, binding)
            return ReaderObservation(
                honest.kind, honest.binding, honest.status, "sha256:" + ("bb" * 32), "",
            )

        monkeypatch.setattr("ontologylab.cutover_readers.observe_mcp_session", _corrupt)
        _zero(kit)
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
    finally:
        kit.close()


def test_stale_binding_resets_and_cannot_drain(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        _zero(kit)
        _zero(kit, GenerationBinding(9, 7))
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
        with pytest.raises(CutoverRefused):
            advance_cutover(kit.store.conn, CutoverPhase.DRAINED, CutoverChecks())
    finally:
        kit.close()


def test_arbitrary_unavailable_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)

        def _bad(session: PackSession, pack_id: str, binding: GenerationBinding) -> ReaderObservation:
            return ReaderObservation(
                ReaderKind.METHOD_GRAPH, binding, ReaderStatus.UNAVAILABLE, "", "admin-override",
            )

        monkeypatch.setattr("ontologylab.cutover_readers.observe_method_graph", _bad)
        with pytest.raises(CutoverRefused) as raised:
            _zero(kit)
        assert raised.value.code is CutoverCode.READER_UNAVAILABLE
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
    finally:
        kit.close()


def test_reader_exception_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)

        def _boom(path: str, binding: GenerationBinding) -> ReaderObservation:
            raise OSError("adapter-down")

        monkeypatch.setattr("ontologylab.cutover_readers.observe_cli_graph", _boom)
        with pytest.raises(CutoverRefused) as raised:
            _zero(kit)
        assert raised.value.code is CutoverCode.READER_FAILED
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
    finally:
        kit.close()


def test_apply_reader_drift_symbol_is_absent() -> None:
    import ontologylab.cutover_rehearsal as rehearsal
    import ontologylab.cutover_readers as readers

    with pytest.raises(AttributeError):
        getattr(rehearsal, "_apply_reader_drift")
    assert "_apply_reader_drift" not in Path(readers.__file__).read_text(encoding="utf-8")
    assert "_apply_reader_drift" not in Path(rehearsal.__file__).read_text(encoding="utf-8")


def test_zero_reader_bundles_cannot_drain_or_hold_positive_streak(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.CATCH_UP)
        assert read_cutover_state(kit.store.conn).zero_drift_streak == 0
        assert all(
            row.kind != "reader_bundle" for row in read_cutover_receipts(kit.store.conn)
        )
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(kit.store.conn, CutoverPhase.DRAINED, CutoverChecks())
        assert raised.value.code is CutoverCode.DRIFT_REQUIRED
        _zero(kit)
        _zero(kit)
        state = read_cutover_state(kit.store.conn)
        bundles = [
            row for row in read_cutover_receipts(kit.store.conn) if row.kind == "reader_bundle"
        ]
        assert state.zero_drift_streak == 2
        assert len(bundles) == 2
    finally:
        kit.close()


def test_low_level_drift_observation_cannot_bypass_reader_proof(tmp_path: Path) -> None:
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
        assert not hasattr(
            __import__("ontologylab.cutover_readers", fromlist=["ReaderBundleProof"]),
            "ReaderBundleProof",
        )
    finally:
        kit.close()


def test_rewritten_bundle_row_cannot_flip(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        _walk(kit, CutoverPhase.FULL_V2)
        before = canonical_data_hash(kit.store.conn)
        kit.store.conn.execute(
            "UPDATE cutover_receipts SET detail = ? WHERE kind = 'reader_bundle'",
            (json.dumps({"hash": "sha256:" + ("cd" * 32), "readers": []}),),
        )
        with pytest.raises(CutoverRefused) as raised:
            advance_cutover(
                kit.store.conn,
                CutoverPhase.AUTHORITY_FLIPPED,
                CutoverChecks(pack_verified=True, reader_bundle_hash="sha256:" + ("cd" * 32)),
            )
        assert raised.value.code is CutoverCode.HASH_CHANGED
        assert read_cutover_state(kit.store.conn).phase is CutoverPhase.FULL_V2
        assert canonical_data_hash(kit.store.conn) == before
    finally:
        kit.close()


def test_method_capable_fixture_is_available(tmp_path: Path) -> None:
    source_path = tmp_path / "source.sqlite"
    source = seed_method_pack_database(source_path)
    source.close()
    packs = tmp_path / "packs"
    manifest = build_pack(
        source_path, packs, name="method-cap",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="t14-method",
        method_release_ids=("release-1",),
    )
    session = PackSession(str(packs))
    try:
        session.load_pack(manifest.pack_id)
        listed = session.list_methods()
        methods = listed["methods"] if isinstance(listed, dict) else listed.methods
        assert methods
        obs = observe_method_graph(session, manifest.pack_id, _binding())
        assert obs.status is ReaderStatus.AVAILABLE
        assert obs.canonical_hash.startswith("sha256:")
    finally:
        session.close()


def test_graph_only_method_is_unrepresentable(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    try:
        install_cutover(kit.store.conn, _bind(kit.store.conn))
        obs = observe_method_graph(kit.session, kit.surfaces.pack_dir.name, _binding())
        assert obs.status is ReaderStatus.UNAVAILABLE
        assert obs.detail == "unrepresentable_v2_state"
    finally:
        kit.close()


def test_synthetic_helper_not_exported() -> None:
    import ontologylab.cutover_readers as readers

    assert not hasattr(readers, "synthetic_reader_probes")
    assert not hasattr(readers, "ReaderBundleProof")
