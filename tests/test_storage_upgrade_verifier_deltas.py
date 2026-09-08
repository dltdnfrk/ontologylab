from __future__ import annotations

import sqlite3
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest

from ontologylab.packbuilder import build_pack
from ontologylab.storage_upgrade import (
    QuiescenceProof,
    UpgradeRefused,
    UpgradeRequest,
    run_staged_upgrade,
)
from tests.storage_upgrade_support import (
    make_older_fixture,
    quiescence_proof,
    tree_hashes,
)


@unique
class BackupMember(StrEnum):
    DATABASE = "database"
    RAW = "raw"
    REGISTRY = "registry"


def _request(root: Path) -> UpgradeRequest:
    return UpgradeRequest(
        application_support_dir=root,
        data_dir=root / "data",
        packs_dir=root / "packs",
        backups_dir=root / "backups",
        quiescence=quiescence_proof(root),
    )


def _interrupt_before_migration(point) -> None:
    if point.value == "staged-migration":
        raise KeyboardInterrupt


def test_recovery_refuses_when_live_sqlite_diverged_before_activation(
    tmp_path: Path,
) -> None:
    fixture = make_older_fixture(tmp_path / "live-diverged")

    def stop(point) -> None:
        if point.value == "pre-activation":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_staged_upgrade(_request(fixture.root), failpoint=stop)
    with sqlite3.connect(fixture.database) as connection:
        connection.execute("CREATE TABLE legitimate_new_write (value TEXT)")
        connection.execute("INSERT INTO legitimate_new_write VALUES ('preserve-me')")

    for _attempt in range(2):
        with pytest.raises(UpgradeRefused) as raised:
            run_staged_upgrade(_request(fixture.root))
        assert raised.value.reason == "live-diverged-forward-recovery-required"
    with sqlite3.connect(fixture.database) as connection:
        assert connection.execute(
            "SELECT value FROM legitimate_new_write"
        ).fetchone() == ("preserve-me",)


@pytest.mark.parametrize("member", tuple(BackupMember))
def test_recovery_refuses_tampered_retained_backup_without_live_mutation(
    tmp_path: Path,
    member: BackupMember,
) -> None:
    fixture = make_older_fixture(tmp_path / f"backup-{member.value}")
    with pytest.raises(KeyboardInterrupt):
        run_staged_upgrade(
            _request(fixture.root),
            failpoint=_interrupt_before_migration,
        )
    before = tree_hashes(fixture.data_dir)
    backup = next(fixture.backups_dir.glob("*/data"))
    match member:
        case BackupMember.DATABASE:
            with sqlite3.connect(backup / "kg.sqlite") as connection:
                connection.execute("CREATE TABLE tampered_backup (value TEXT)")
        case BackupMember.RAW:
            (backup / "documents/doc-1/raw.txt").write_text(
                "tampered", encoding="utf-8"
            )
        case BackupMember.REGISTRY:
            (backup / "settings.json").write_text("{}", encoding="utf-8")
        case unreachable:
            assert_never(unreachable)

    for _attempt in range(2):
        with pytest.raises(UpgradeRefused) as raised:
            run_staged_upgrade(_request(fixture.root))
        assert raised.value.reason == "backup-integrity"
    assert tree_hashes(fixture.data_dir) == before


def test_recovery_refuses_pack_inventory_drift_after_backup(tmp_path: Path) -> None:
    fixture = make_older_fixture(tmp_path / "backup-pack")
    manifest = build_pack(
        fixture.database,
        fixture.packs_dir,
        "backup-pack",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="backup integrity fixture",
    )
    with sqlite3.connect(fixture.database) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("DROP TABLE ontologylab_storage_metadata")
    with pytest.raises(KeyboardInterrupt):
        run_staged_upgrade(
            _request(fixture.root),
            failpoint=_interrupt_before_migration,
        )
    before = tree_hashes(fixture.data_dir)
    (fixture.packs_dir / manifest.pack_id / "unexpected").write_bytes(b"tamper")

    with pytest.raises(UpgradeRefused) as raised:
        run_staged_upgrade(_request(fixture.root))
    assert raised.value.reason == "backup-integrity"
    assert tree_hashes(fixture.data_dir) == before


def test_quiescence_contract_has_no_unbound_boolean_or_optional_pid() -> None:
    fields = tuple(QuiescenceProof.__dataclass_fields__)
    assert fields == (
        "receipt_path",
        "supervisor_pid",
        "nonce",
        "proof_kind",
        "inspected_paths",
        "inspected_at_ns",
        "initial_holder_pids",
        "final_holder_pids",
        "verified_owner",
        "signals",
        "exit_observed",
    )
