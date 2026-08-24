"""Wave 2.1 Step 9A Task 15: forward rollback and additive recovery."""
# noqa: SIZE_OK — one F8/F10 integration matrix over disposable copies

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from ontologylab.authority_repo import create_work
from ontologylab.cutover_rollback import (
    CompatibilityMode,
    ForwardRollbackChecks,
    MutationKind,
    RestoreChecks,
    RollbackCode,
    RollbackRefused,
    apply_irreversible_mutation,
    authorize_backup_restore,
    authorize_old_writer_reopen,
    compatibility_mode,
    enter_forward_rollback,
    file_inventory_hash,
    install_rollback_contract,
    read_rollback_receipts,
    read_rollback_state,
    record_fact_retraction,
    record_recovery_pack,
    record_redirect_compensation,
)
from ontologylab.kgstore import KGStore
from ontologylab.migration import (
    compute_source_fingerprint,
    read_ledger,
)
from ontologylab.pack_verifier import verify_pack
from ontologylab.packbuilder import build_pack
from ontologylab.work_redirects import canonical_work
from tests.test_pack_v2_closure import _build_v2, _plant_v2
from tests.wave21.harness import Failpoint, FailpointArmed


def _files(tmp_path: Path) -> Path:
    root = tmp_path / "files"
    root.mkdir(parents=True)
    (root / "source.txt").write_text("immutable-source", encoding="utf-8")
    return root


def _checks(root: Path) -> RestoreChecks:
    return RestoreChecks(
        writes_refused=True,
        writers_drained=True,
        exclusive_lock=True,
        zero_drift=True,
        fresh_inventory_hash=file_inventory_hash(root),
    )


def _forward_checks() -> ForwardRollbackChecks:
    return ForwardRollbackChecks(writers_drained=True, exclusive_lock=True)


def _create(conn: sqlite3.Connection, work_id: str) -> None:
    create_work(conn, work_id)


@pytest.mark.parametrize(
    ("field", "code"),
    (
        ("writes_refused", RollbackCode.WRITES_LIVE),
        ("writers_drained", RollbackCode.WRITERS_LIVE),
        ("exclusive_lock", RollbackCode.LOCK_REQUIRED),
        ("zero_drift", RollbackCode.DRIFT_NONZERO),
    ),
)
def test_pre_marker_restore_requires_every_quiescence_gate(
    tmp_path: Path,
    field: str,
    code: RollbackCode,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    files = _files(tmp_path)
    try:
        install_rollback_contract(store.conn, generation=1, inventory_root=files)
        checks = replace(_checks(files), **{field: False})
        with pytest.raises(RollbackRefused) as raised:
            authorize_backup_restore(store.conn, checks, inventory_root=files)
        assert raised.value.code is code
        assert not [
            row for row in read_rollback_receipts(store.conn)
            if row.action == "restore_authorized"
        ]
    finally:
        store.close()


def test_pre_marker_restore_binds_fresh_file_inventory(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    files = _files(tmp_path)
    try:
        install_rollback_contract(store.conn, generation=1, inventory_root=files)
        permit = authorize_backup_restore(
            store.conn, _checks(files), inventory_root=files,
        )
        assert permit.inventory_hash == file_inventory_hash(files)
        (files / "source.txt").write_text("changed", encoding="utf-8")
        with pytest.raises(RollbackRefused) as raised:
            authorize_backup_restore(
                store.conn,
                replace(
                    _checks(files),
                    fresh_inventory_hash=permit.inventory_hash,
                ),
                inventory_root=files,
            )
        assert raised.value.code is RollbackCode.INVENTORY_CHANGED
    finally:
        store.close()


@pytest.mark.parametrize("kind", tuple(MutationKind))
def test_each_irreversible_mutation_kind_sets_marker_in_same_transaction(
    tmp_path: Path,
    kind: MutationKind,
) -> None:
    store = KGStore.open(tmp_path / f"{kind.value}.sqlite")
    files = _files(tmp_path / kind.value)
    try:
        install_rollback_contract(store.conn, generation=1, inventory_root=files)
        fingerprint = compute_source_fingerprint(store.conn)
        apply_irreversible_mutation(
            store.conn,
            kind=kind,
            mutate=lambda conn: _create(conn, f"work-{kind.value}"),
            generation=1,
            source_fingerprint=fingerprint,
            actor="operator",
            reason=f"exercise {kind.value}",
        )
        assert store.conn.execute(
            "SELECT COUNT(*) FROM works WHERE id = ?",
            (f"work-{kind.value}",),
        ).fetchone()[0] == 1
        assert len([
            row for row in read_ledger(store.conn)
            if row.phase == "post_cutover_write"
        ]) == 1
        receipt = read_rollback_receipts(store.conn)[-1]
        assert receipt.action == "irreversible_mutation"
        assert receipt.mutation_kind is kind
    finally:
        store.close()


def test_irreversible_mutation_and_marker_rollback_together(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    files = _files(tmp_path)
    failpoint = Failpoint()
    failpoint.arm("after_v2_mutation")
    try:
        install_rollback_contract(store.conn, generation=1, inventory_root=files)
        fingerprint = compute_source_fingerprint(store.conn)
        with pytest.raises(FailpointArmed):
            apply_irreversible_mutation(
                store.conn,
                kind=MutationKind.IDENTITY,
                mutate=lambda conn: _create(conn, "work-torn"),
                generation=1,
                source_fingerprint=fingerprint,
                actor="operator",
                reason="torn write",
                failpoint=failpoint.hit,
            )
        assert store.conn.execute(
            "SELECT COUNT(*) FROM works WHERE id='work-torn'"
        ).fetchone()[0] == 0
        assert not [
            row for row in read_ledger(store.conn)
            if row.phase == "post_cutover_write"
        ]
        assert not [
            row for row in read_rollback_receipts(store.conn)
            if row.action == "irreversible_mutation"
        ]
    finally:
        store.close()


def test_generation_mismatch_cannot_write_marker(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    files = _files(tmp_path)
    try:
        install_rollback_contract(store.conn, generation=2, inventory_root=files)
        fingerprint = compute_source_fingerprint(store.conn)
        with pytest.raises(RollbackRefused) as raised:
            apply_irreversible_mutation(
                store.conn,
                kind=MutationKind.IDENTITY,
                mutate=lambda conn: _create(conn, "work-wrong-generation"),
                generation=1,
                source_fingerprint=fingerprint,
                actor="operator",
                reason="must refuse stale writer",
            )
        assert raised.value.code is RollbackCode.INVALID_INPUT
        assert store.conn.execute(
            "SELECT COUNT(*) FROM works WHERE id='work-wrong-generation'"
        ).fetchone()[0] == 0
    finally:
        store.close()


@pytest.mark.parametrize("field", ("writers_drained", "exclusive_lock"))
def test_forward_rollback_requires_quiescence(
    tmp_path: Path,
    field: str,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    files = _files(tmp_path)
    try:
        install_rollback_contract(store.conn, generation=1, inventory_root=files)
        fingerprint = compute_source_fingerprint(store.conn)
        apply_irreversible_mutation(
            store.conn,
            kind=MutationKind.IDENTITY,
            mutate=lambda conn: _create(conn, "work-marker"),
            generation=1,
            source_fingerprint=fingerprint,
            actor="operator",
            reason="marker",
        )
        with pytest.raises(RollbackRefused):
            enter_forward_rollback(
                store.conn,
                checks=replace(_forward_checks(), **{field: False}),
                actor="operator",
                reason="not quiescent",
            )
        assert read_rollback_state(store.conn).v2_writes_enabled
    finally:
        store.close()


def test_marker_forbids_restore_and_forward_rollback_disables_writes(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    files = _files(tmp_path)
    try:
        install_rollback_contract(store.conn, generation=1, inventory_root=files)
        fingerprint = compute_source_fingerprint(store.conn)
        apply_irreversible_mutation(
            store.conn,
            kind=MutationKind.INGESTION,
            mutate=lambda conn: _create(conn, "work-held"),
            generation=1,
            source_fingerprint=fingerprint,
            actor="operator",
            reason="first post-cutover write",
        )
        with pytest.raises(RollbackRefused) as restore:
            authorize_backup_restore(store.conn, _checks(files), inventory_root=files)
        assert restore.value.code is RollbackCode.POST_CUTOVER_RESTORE

        enter_forward_rollback(
            store.conn,
            checks=_forward_checks(),
            actor="operator",
            reason="disable v2 authority writes",
        )
        state = read_rollback_state(store.conn)
        assert not state.v2_writes_enabled
        assert not state.preferred_selection_enabled
        assert not state.publication_enabled
        assert compatibility_mode(store.conn, representable=True) is CompatibilityMode.READ_ONLY
        assert compatibility_mode(store.conn, representable=False) is CompatibilityMode.UNAVAILABLE
        with pytest.raises(RollbackRefused) as write:
            apply_irreversible_mutation(
                store.conn,
                kind=MutationKind.IDENTITY,
                mutate=lambda conn: _create(conn, "work-lost"),
                generation=1,
                source_fingerprint=fingerprint,
                actor="operator",
                reason="must refuse",
            )
        assert write.value.code is RollbackCode.V2_WRITES_DISABLED
        with pytest.raises(RollbackRefused) as reopen:
            authorize_old_writer_reopen(store.conn)
        assert reopen.value.code is RollbackCode.OLD_WRITER_FORBIDDEN
        with pytest.raises(RollbackRefused):
            enter_forward_rollback(
                store.conn,
                checks=_forward_checks(),
                actor="operator",
                reason="duplicate",
            )
        assert store.conn.execute(
            "SELECT COUNT(*) FROM works WHERE id='work-held'"
        ).fetchone()[0] == 1
    finally:
        store.close()


def _tree_hash(root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        hasher.update(path.relative_to(root).as_posix().encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def test_compensation_requires_marker_and_forward_mode(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path / "fixture")
    files = fixture.root / "documents"
    try:
        install_rollback_contract(
            fixture.store.conn,
            generation=fixture.generation,
            inventory_root=files,
        )
        with pytest.raises(RollbackRefused) as no_marker:
            record_redirect_compensation(
                fixture.store.conn,
                merge_decision_id=fixture.redirect_id,
                actor="curator",
                reason="too early",
            )
        assert no_marker.value.code is RollbackCode.MARKER_REQUIRED
        fingerprint = compute_source_fingerprint(fixture.store.conn)
        apply_irreversible_mutation(
            fixture.store.conn,
            kind=MutationKind.IDENTITY,
            mutate=lambda conn: _create(conn, "work-marker-only"),
            generation=fixture.generation,
            source_fingerprint=fingerprint,
            actor="operator",
            reason="marker only",
        )
        with pytest.raises(RollbackRefused) as no_forward:
            record_redirect_compensation(
                fixture.store.conn,
                merge_decision_id=fixture.redirect_id,
                actor="curator",
                reason="still too early",
            )
        assert no_forward.value.code is RollbackCode.MARKER_REQUIRED
    finally:
        fixture.store.close()


def test_forward_recovery_is_additive_and_builds_new_immutable_v2_pack(
    tmp_path: Path,
) -> None:
    fixture = _plant_v2(tmp_path / "fixture")
    packs = tmp_path / "packs"
    old = _build_v2(fixture, packs, evidence_mode="full")
    old_dir = packs / old.pack_id
    old_tree = _tree_hash(old_dir)
    files_hash = file_inventory_hash(fixture.root / "documents")
    edge_id = str(fixture.store.conn.execute(
        "SELECT id FROM edges ORDER BY id LIMIT 1"
    ).fetchone()[0])
    citations_before = tuple(fixture.store.conn.execute(
        "SELECT receipt_id, fact_id, representation_id, start_offset, end_offset "
        "FROM citation_receipts ORDER BY receipt_id"
    ))
    fk_before = tuple(fixture.store.conn.execute(
        "SELECT id, work_id FROM documents ORDER BY id"
    ))

    try:
        install_rollback_contract(
            fixture.store.conn,
            generation=fixture.generation,
            inventory_root=fixture.root / "documents",
        )
        fingerprint = compute_source_fingerprint(fixture.store.conn)
        apply_irreversible_mutation(
            fixture.store.conn,
            kind=MutationKind.PUBLICATION,
            mutate=lambda conn: _create(conn, "work-post-cutover"),
            generation=fixture.generation,
            source_fingerprint=fingerprint,
            actor="operator",
            reason="first published v2 authority mutation",
        )
        enter_forward_rollback(
            fixture.store.conn,
            checks=_forward_checks(),
            actor="operator",
            reason="recover forward without restore",
        )

        merge = record_redirect_compensation(
            fixture.store.conn,
            merge_decision_id=fixture.redirect_id,
            actor="curator",
            reason="false merge",
        )
        with pytest.raises(RollbackRefused) as duplicate:
            record_redirect_compensation(
                fixture.store.conn,
                merge_decision_id=fixture.redirect_id,
                actor="curator",
                reason="duplicate false merge compensation",
            )
        assert duplicate.value.code is RollbackCode.INVALID_INPUT
        retraction = record_fact_retraction(
            fixture.store.conn,
            item_id=edge_id,
            actor="curator",
            reason="source retracted relation",
        )
        assert merge.supersedes_id == fixture.redirect_id
        assert canonical_work(
            fixture.store.conn, fixture.alias_work_id,
        ) == fixture.alias_work_id
        assert tuple(fixture.store.conn.execute(
            "SELECT id, work_id FROM documents ORDER BY id"
        )) == fk_before
        assert tuple(fixture.store.conn.execute(
            "SELECT receipt_id, fact_id, representation_id, start_offset, end_offset "
            "FROM citation_receipts ORDER BY receipt_id"
        )) == citations_before
        assert retraction.citation_receipt_ids
        assert fixture.store.conn.execute(
            "SELECT status FROM edges WHERE id = ?", (edge_id,),
        ).fetchone()[0] == "rejected"
        assert file_inventory_hash(fixture.root / "documents") == files_hash

        new = build_pack(
            fixture.kg,
            packs,
            name="v2-recovery",
            evidence_mode="full",
        )
        new_dir = packs / new.pack_id
        assert verify_pack(old_dir).pack_content_hash != verify_pack(new_dir).pack_content_hash
        assert _tree_hash(old_dir) == old_tree
        with sqlite3.connect(
            f"file:{new_dir / 'pack.sqlite'}?mode=ro", uri=True,
        ) as packed:
            assert packed.execute(
                "SELECT COUNT(*) FROM edges WHERE id = ?", (edge_id,),
            ).fetchone()[0] == 0
        record_recovery_pack(
            fixture.store.conn,
            old_pack_path=old_dir,
            new_pack_path=new_dir,
            actor="operator",
            reason="publish additive compensation",
        )
        recovery = read_rollback_receipts(fixture.store.conn)[-1]
        assert recovery.action == "recovery_pack"
        recovery_detail = json.loads(recovery.detail)
        assert recovery_detail == {
            "new_pack_hash": verify_pack(new_dir).pack_content_hash,
            "old_pack_hash": verify_pack(old_dir).pack_content_hash,
        }
        with pytest.raises(RollbackRefused) as same_pack:
            record_recovery_pack(
                fixture.store.conn,
                old_pack_path=old_dir,
                new_pack_path=old_dir,
                actor="operator",
                reason="same pack must refuse",
            )
        assert same_pack.value.code is RollbackCode.PACK_UNCHANGED
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            fixture.store.conn.execute(
                "UPDATE cutover_rollback_receipts SET reason='rewrite'"
            )
    finally:
        fixture.store.close()
