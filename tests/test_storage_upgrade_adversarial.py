from __future__ import annotations

import errno
import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest

from ontologylab.storage_compatibility import preflight_storage
from ontologylab.storage_types import CompatibilityState
from ontologylab.storage_upgrade import (
    UpgradeJournalRefused,
    UpgradeRefused,
    UpgradeRequest,
    rollback_pre_activation,
    run_staged_upgrade,
)
from ontologylab.storage_upgrade_journal import upgrade_lock
from tests.storage_upgrade_support import (
    make_older_fixture,
    quiescence_proof,
    tree_hashes,
)


def _request(root: Path, *, quiesced: bool = True) -> UpgradeRequest:
    return UpgradeRequest(
        application_support_dir=root,
        data_dir=root / "data",
        packs_dir=root / "packs",
        backups_dir=root / "backups",
        quiescence=quiescence_proof(root, valid=quiesced),
    )


def test_pre_activation_rollback_is_exact_and_owner_only(tmp_path: Path) -> None:
    fixture = make_older_fixture(tmp_path / "rollback")
    before = tree_hashes(fixture.data_dir)

    def stop_before_activation(point) -> None:
        if point.value == "pre-activation":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_staged_upgrade(_request(fixture.root), failpoint=stop_before_activation)
    rollback_pre_activation(_request(fixture.root))

    assert tree_hashes(fixture.data_dir) == before
    assert not (fixture.root / ".upgrade-staging").exists()
    assert not (fixture.root / "upgrade-journal.json").exists()


def test_post_activation_restore_is_refused_and_recovery_is_forward(
    tmp_path: Path,
) -> None:
    fixture = make_older_fixture(tmp_path / "forward")

    def stop_after_activation(point) -> None:
        if point.value == "post-activation":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_staged_upgrade(_request(fixture.root), failpoint=stop_after_activation)
    with pytest.raises(UpgradeRefused) as raised:
        rollback_pre_activation(_request(fixture.root))
    assert raised.value.reason == "activation-started-forward-recovery-required"


def test_post_activation_new_write_is_preserved_by_forward_recovery(
    tmp_path: Path,
) -> None:
    fixture = make_older_fixture(tmp_path / "post-activation-write")

    def stop(point) -> None:
        if point.value == "post-activation":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_staged_upgrade(_request(fixture.root), failpoint=stop)
    with sqlite3.connect(fixture.database) as connection:
        connection.execute("CREATE TABLE post_activation_write (value TEXT)")
        connection.execute("INSERT INTO post_activation_write VALUES ('forward')")

    result = run_staged_upgrade(_request(fixture.root))

    assert result.activated is True
    with sqlite3.connect(fixture.database) as connection:
        assert connection.execute(
            "SELECT value FROM post_activation_write"
        ).fetchone() == ("forward",)
    with pytest.raises(UpgradeRefused) as raised:
        rollback_pre_activation(_request(fixture.root))
    assert raised.value.reason == "activation-started-forward-recovery-required"


def test_malformed_journal_and_unowned_staging_refuse_without_cleanup(
    tmp_path: Path,
) -> None:
    fixture = make_older_fixture(tmp_path / "malformed")
    staging = fixture.root / ".upgrade-staging"
    staging.mkdir()
    sentinel = staging / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(UpgradeJournalRefused):
        run_staged_upgrade(_request(fixture.root))
    assert sentinel.read_text() == "keep"

    (fixture.root / "upgrade-journal.json").write_text(json.dumps({"phase": "forged"}))
    os.chmod(fixture.root / "upgrade-journal.json", 0o600)
    with pytest.raises(UpgradeJournalRefused):
        run_staged_upgrade(_request(fixture.root))


def test_quiescence_and_active_writer_are_hard_gates(tmp_path: Path) -> None:
    fixture = make_older_fixture(tmp_path / "writer")
    with pytest.raises(UpgradeRefused) as unowned:
        run_staged_upgrade(_request(fixture.root, quiesced=False))
    assert unowned.value.reason == "quiescence-receipt-mismatch"

    writer = sqlite3.connect(fixture.database, timeout=0)
    try:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(UpgradeRefused) as busy:
            run_staged_upgrade(_request(fixture.root))
        assert busy.value.reason == "wal-checkpoint-busy"
    finally:
        writer.rollback()
        writer.close()


def test_corrupt_low_space_read_only_and_concurrent_upgrade_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corrupt = make_older_fixture(tmp_path / "corrupt")
    corrupt.database.write_bytes(b"not sqlite")
    with pytest.raises(UpgradeRefused) as damaged:
        run_staged_upgrade(_request(corrupt.root))
    assert damaged.value.reason == "source-corrupt"

    low = make_older_fixture(tmp_path / "low")
    usage = os.statvfs(low.root)
    monkeypatch.setattr("ontologylab.storage_upgrade.available_bytes", lambda _path: 0)
    with pytest.raises(UpgradeRefused) as space:
        run_staged_upgrade(_request(low.root))
    assert space.value.reason == "insufficient-space"
    assert usage.f_bsize > 0


def test_current_noop_does_not_create_backup_or_journal(tmp_path: Path) -> None:
    fixture = make_older_fixture(tmp_path / "current")
    run_staged_upgrade(_request(fixture.root))
    before = tree_hashes(fixture.data_dir)

    result = run_staged_upgrade(_request(fixture.root))

    assert result.activated is True
    assert tree_hashes(fixture.data_dir) == before
    assert len(tuple(fixture.backups_dir.iterdir())) == 1


def test_owner_only_journal_and_concurrent_launch_refusal(tmp_path: Path) -> None:
    fixture = make_older_fixture(tmp_path / "concurrent")

    def stop(point) -> None:
        if point.value == "before-backup":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_staged_upgrade(_request(fixture.root), failpoint=stop)
    journal = fixture.root / "upgrade-journal.json"
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    with (
        upgrade_lock(fixture.root),
        pytest.raises(UpgradeJournalRefused) as raised,
    ):
        run_staged_upgrade(_request(fixture.root))
    assert raised.value.reason == "concurrent-upgrade"


def test_repeated_interrupts_remain_resumable(tmp_path: Path) -> None:
    fixture = make_older_fixture(tmp_path / "repeated")

    def stop(point) -> None:
        if point.value == "pre-activation":
            raise KeyboardInterrupt

    for _attempt in range(2):
        with pytest.raises(KeyboardInterrupt):
            run_staged_upgrade(_request(fixture.root), failpoint=stop)

    result = run_staged_upgrade(_request(fixture.root))
    assert result.activated is True


def test_corrupt_staged_copy_refuses_without_touching_source(tmp_path: Path) -> None:
    fixture = make_older_fixture(tmp_path / "staged-corrupt")
    before = tree_hashes(fixture.data_dir)

    def corrupt_before_validation(point) -> None:
        if point.value == "validation":
            staged = next((fixture.root / ".upgrade-staging").glob("*/data/kg.sqlite"))
            staged.write_bytes(b"corrupt staged copy")

    with pytest.raises(UpgradeRefused):
        run_staged_upgrade(_request(fixture.root), failpoint=corrupt_before_validation)
    assert tree_hashes(fixture.data_dir) == before


def test_read_only_activation_refuses_without_source_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = make_older_fixture(tmp_path / "readonly")
    before = tree_hashes(fixture.data_dir)

    def refuse_write(_root, _journal) -> None:
        raise PermissionError(errno.EROFS, "read-only fixture")

    monkeypatch.setattr("ontologylab.storage_upgrade.write_journal", refuse_write)
    with pytest.raises(UpgradeRefused) as raised:
        run_staged_upgrade(_request(fixture.root))
    assert raised.value.reason == "filesystem-read-only"
    assert tree_hashes(fixture.data_dir) == before
    assert preflight_storage(fixture.data_dir, fixture.packs_dir).state is CompatibilityState.SUPPORTED_OLDER
