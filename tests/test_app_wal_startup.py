"""Writable app startup sees committed WAL without changing desktop preflight."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from ontologylab.server.app import create_app
from ontologylab.storage_compatibility import preflight_database, preflight_storage
from ontologylab.storage_types import CompatibilityState, StorageCompatibilityRefused
from tests.test_storage_compatibility import _current, _sha256


@pytest.fixture
def wal_store(tmp_path: Path) -> Iterator[tuple[Path, sqlite3.Connection]]:
    path = tmp_path / "data" / "kg.sqlite"
    path.parent.mkdir()
    _current(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_autocheckpoint=0")
        yield path, connection
    finally:
        connection.close()


def _image(path: Path) -> tuple[str, str, int, int]:
    wal = path.with_name(path.name + "-wal")
    return (
        _sha256(path), _sha256(wal),
        path.stat().st_mtime_ns, wal.stat().st_mtime_ns,
    )


def test_current_wal_startup_preserves_logical_state_and_explicit_pack_inventory(
    wal_store: tuple[Path, sqlite3.Connection], tmp_path: Path,
) -> None:
    path, writer = wal_store
    packs = tmp_path / "operator-selected" / "packs"
    for root, count in ((tmp_path / "packs", 1), (packs, 2)):
        for index in range(count):
            member = root / str(index) / "pack.sqlite"
            member.parent.mkdir(parents=True)
            member.touch()  # Inventory entries only, not claimed verified packs.
    # Complete the existing G002 auxiliary-schema bootstrap before measuring reopen.
    create_app(data_dir=path.parent, packs_dir=packs)
    writer.execute("CREATE TABLE active_writer_probe (value TEXT)")
    writer.execute("INSERT INTO active_writer_probe VALUES ('committed only in WAL')")
    writer.commit()
    before = tuple(writer.iterdump())
    before_preflight = _image(path)

    desktop = preflight_storage(path.parent, packs)
    assert (desktop.state, desktop.reason) == (CompatibilityState.UNKNOWN, "active-wal")
    assert _image(path) == before_preflight

    app = create_app(data_dir=path.parent, packs_dir=packs)

    report = app.state.storage_preflight
    assert report.state is CompatibilityState.CURRENT
    assert report.inventory.wal_present is True
    assert report.inventory.pack_count == 2
    assert app.state.packs_dir == packs
    assert tuple(writer.iterdump()) == before
    assert writer.in_transaction is False
    desktop_after = preflight_storage(path.parent, packs)
    assert (desktop_after.state, desktop_after.reason) == (
        CompatibilityState.UNKNOWN, "active-wal",
    )


@pytest.mark.parametrize(
    ("mutation", "state", "reason"),
    [
        (
            "UPDATE ontologylab_storage_metadata SET storage_version = 999",
            CompatibilityState.NEWER, "newer-storage-version",
        ),
        (
            "DELETE FROM ontologylab_storage_metadata WHERE component = 'chat'",
            CompatibilityState.UNKNOWN, "missing-version-record",
        ),
        (
            "UPDATE ontologylab_storage_metadata SET migration_ids_json = '{' "
            "WHERE component = 'kg'",
            CompatibilityState.UNKNOWN, "malformed-migration-ids",
        ),
        (
            "DROP TABLE ontologylab_storage_metadata",
            CompatibilityState.SUPPORTED_OLDER, "recognized-legacy-layout",
        ),
    ],
    ids=["newer", "missing-component", "malformed-metadata", "migration-required"],
)
def test_app_refuses_metadata_visible_only_in_wal_before_startup_writes(
    wal_store: tuple[Path, sqlite3.Connection], tmp_path: Path,
    mutation: str, state: CompatibilityState, reason: str,
) -> None:
    path, writer = wal_store
    packs = tmp_path / "selected-packs"
    main_before = _sha256(path)
    writer.execute(mutation)
    writer.commit()
    assert _sha256(path) == main_before
    # A stale immutable read would misclassify every case as current.
    assert preflight_database(path, packs).state is CompatibilityState.CURRENT
    before = _image(path)
    logical_before = tuple(writer.iterdump())

    with pytest.raises(StorageCompatibilityRefused) as raised:
        create_app(data_dir=path.parent, packs_dir=packs)

    assert (raised.value.report.state, raised.value.report.reason) == (state, reason)
    assert raised.value.report.inventory.wal_present is True
    assert not (path.parent / "session.token").exists()
    assert _image(path) == before
    assert tuple(writer.iterdump()) == logical_before
    assert writer.in_transaction is False
