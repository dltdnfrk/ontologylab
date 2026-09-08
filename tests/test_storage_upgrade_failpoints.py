from __future__ import annotations

from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.packbuilder import build_pack
from ontologylab.storage_compatibility import preflight_storage
from ontologylab.storage_types import CompatibilityState
from ontologylab.storage_upgrade import (
    UpgradeFailpoint,
    UpgradeInterrupted,
    UpgradeRequest,
    recover_staged_upgrade,
    run_staged_upgrade,
)
from tests.storage_upgrade_support import (
    make_older_fixture,
    quiescence_proof,
    tree_hashes,
)


def _request(root: Path) -> UpgradeRequest:
    return UpgradeRequest(
        application_support_dir=root,
        data_dir=root / "data",
        packs_dir=root / "packs",
        backups_dir=root / "backups",
        quiescence=quiescence_proof(root),
    )


@pytest.mark.parametrize("failpoint", tuple(UpgradeFailpoint))
def test_upgrade_recovers_deterministically_from_every_exact_failpoint(
    tmp_path: Path,
    failpoint: UpgradeFailpoint,
) -> None:
    # Given an N-1 canonical store and one exact interruption boundary.
    fixture = make_older_fixture(tmp_path / failpoint.value)
    hits: list[UpgradeFailpoint] = []

    def interrupt(point: UpgradeFailpoint) -> None:
        hits.append(point)
        if point is failpoint:
            raise UpgradeInterrupted(point)

    # When the upgrade is interrupted and then resumed twice.
    with pytest.raises(UpgradeInterrupted):
        run_staged_upgrade(_request(fixture.root), failpoint=interrupt)
    first = recover_staged_upgrade(_request(fixture.root))
    second = recover_staged_upgrade(_request(fixture.root))

    # Then recovery converges, preserves source data, and never re-migrates live.
    assert failpoint in hits
    assert first.activated is True
    assert second == first
    assert preflight_storage(fixture.data_dir, fixture.packs_dir).state is CompatibilityState.CURRENT
    assert (fixture.data_dir / "documents/doc-1/raw.txt").read_bytes() == b"raw body"
    assert (fixture.data_dir / "session.token").read_text() != fixture.token
    assert tuple(fixture.backups_dir.glob("*/data/kg.sqlite"))
    with KGStore.open(fixture.database, read_only=True) as reader:
        assert reader.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert reader.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_upgrade_backup_preserves_preupgrade_logical_state(tmp_path: Path) -> None:
    # Given a populated N-1 store.
    fixture = make_older_fixture(tmp_path / "backup")

    # When staged upgrade completes.
    result = run_staged_upgrade(_request(fixture.root))

    # Then retained backup and activated store carry the pinned logical digest/counts.
    assert result.source_digest == result.backup_digest == result.activated_digest
    assert result.source_counts == result.backup_counts == result.activated_counts
    assert result.backup_dir is not None
    backup = result.backup_dir / "data"
    assert (backup / "documents/doc-1/raw.txt").read_bytes() == b"raw body"
    assert dict(tree_hashes(fixture.data_dir))["documents/doc-1/raw.txt"] == dict(
        fixture.source_hashes
    )["documents/doc-1/raw.txt"]


def test_upgrade_revalidates_and_preserves_real_pack_bytes(tmp_path: Path) -> None:
    fixture = make_older_fixture(tmp_path / "pack")
    manifest = build_pack(
        fixture.database,
        fixture.packs_dir,
        "upgrade-pinned",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="upgrade fixture",
    )
    pack_dir = fixture.packs_dir / manifest.pack_id
    before = tree_hashes(pack_dir)

    run_staged_upgrade(_request(fixture.root))

    assert tree_hashes(pack_dir) == before
