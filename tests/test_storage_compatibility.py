from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.server.app import create_app
from ontologylab.storage_compatibility import (
    CURRENT_MIGRATION_IDS,
    CURRENT_STORAGE_VERSION,
    load_compatibility_matrix,
    preflight_database,
    preflight_storage,
)
from ontologylab.storage_types import (
    CompatibilityState,
    StorageCompatibilityRefused,
    StorageMatrixRefused,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current(path: Path) -> None:
    KGStore.open(path).close()


def _sidecars(path: Path) -> tuple[str, ...]:
    return tuple(sorted(item.name for item in path.parent.glob(f"{path.name}-*")))


def _persist_mutation(path: Path, sql: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute(sql)


def test_current_kgstore_open_reopens_without_changing_supported_behavior(
    tmp_path: Path,
) -> None:
    # Given a store bootstrapped by the current writer.
    path = tmp_path / "kg.sqlite"
    _current(path)
    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]

    # When the current writer reopens it.
    _current(path)

    # Then the established deterministic schema seed remains unchanged.
    with sqlite3.connect(path) as connection:
        after = connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert (before, after) == (1, 1)


def test_bootstrap_records_current_version_and_immutable_migration_ids(
    tmp_path: Path,
) -> None:
    # Given a fresh disposable path, when the writer bootstraps it.
    path = tmp_path / "kg.sqlite"
    _current(path)

    # Then deterministic component records match the shipped matrix exactly.
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT component, storage_version, migration_ids_json "
            "FROM ontologylab_storage_metadata ORDER BY component"
        ).fetchall()
    assert tuple(row[0] for row in rows) == tuple(
        migration_id.split("-", 1)[0] for migration_id in CURRENT_MIGRATION_IDS
    )
    assert {row[1] for row in rows} == {CURRENT_STORAGE_VERSION}
    assert tuple(json.loads(row[2])[0] for row in rows) == CURRENT_MIGRATION_IDS
    with KGStore.open(path, read_only=True) as reader:
        assert reader.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert reader.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_preflight_classifies_current_without_calling_kgstore_or_mutating_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a current store and a trap on the migrating API.
    path = tmp_path / "data" / "kg.sqlite"
    path.parent.mkdir()
    _current(path)
    before = (_sha256(path), path.stat().st_mtime_ns, _sidecars(path))
    monkeypatch.setattr(KGStore, "open", lambda *args, **kwargs: pytest.fail("KGStore.open called"))

    # When raw immutable preflight runs.
    report = preflight_database(path, tmp_path / "packs")

    # Then it identifies current state without changing source bytes or sidecars.
    assert report.state is CompatibilityState.CURRENT
    assert report.storage_version == CURRENT_STORAGE_VERSION
    assert report.starts_without_migration is True
    assert (_sha256(path), path.stat().st_mtime_ns, _sidecars(path)) == before


def test_preflight_refuses_active_wal_without_checkpointing_or_mutating_it(
    tmp_path: Path,
) -> None:
    # Given a current store with an uncheckpointed writer transaction.
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "kg.sqlite"
    _current(path)
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE active_writer_probe (value TEXT)")
        writer.commit()
        wal = path.with_name(path.name + "-wal")
        before = (_sha256(path), _sha256(wal), wal.stat().st_size)

        # When startup preflight runs, then active WAL is typed without a checkpoint.
        report = preflight_storage(data_dir, tmp_path / "packs")
        assert (report.state, report.reason) == (
            CompatibilityState.UNKNOWN,
            "active-wal",
        )
        assert report.inventory.wal_present is True
        assert (_sha256(path), _sha256(wal), wal.stat().st_size) == before


def test_preflight_classifies_recognized_unversioned_layout_as_supported_older(
    tmp_path: Path,
) -> None:
    # Given the exact prior canonical layout with no explicit version journal.
    path = tmp_path / "kg.sqlite"
    _current(path)
    _persist_mutation(path, "DROP TABLE ontologylab_storage_metadata")
    before = _sha256(path)

    # When preflight inspects it, then it emits the staged-migration seam only.
    report = preflight_database(path, tmp_path / "packs")
    assert report.state is CompatibilityState.SUPPORTED_OLDER
    assert report.storage_version == 0
    assert report.starts_without_migration is False
    assert _sha256(path) == before


def test_writer_refuses_newer_storage_before_schema_mutation(tmp_path: Path) -> None:
    # Given a structurally current store claiming a future storage version.
    path = tmp_path / "future.sqlite"
    _current(path)
    _persist_mutation(
        path,
        "UPDATE ontologylab_storage_metadata SET storage_version = 999",
    )
    before = _sha256(path)

    # When the current writer is asked to open it, then refusal precedes DDL.
    with pytest.raises(StorageCompatibilityRefused) as raised:
        KGStore.open(path)
    assert raised.value.report.state is CompatibilityState.NEWER
    assert _sha256(path) == before


def test_writer_refuses_unknown_layout_before_schema_mutation(tmp_path: Path) -> None:
    # Given valid SQLite with an unrelated, unversioned layout.
    path = tmp_path / "unknown.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    before = _sha256(path)

    # When a writer opens it, then typed refusal leaves bytes unchanged.
    with pytest.raises(StorageCompatibilityRefused) as raised:
        KGStore.open(path)
    assert raised.value.report.state is CompatibilityState.UNKNOWN
    assert _sha256(path) == before


def test_preflight_distinguishes_missing_version_record_and_corrupt_file(
    tmp_path: Path,
) -> None:
    # Given one partial journal and one malformed database.
    missing = tmp_path / "missing.sqlite"
    _current(missing)
    _persist_mutation(
        missing,
        "DELETE FROM ontologylab_storage_metadata WHERE component = 'chat'",
    )
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"not a sqlite database")

    # When both are inspected, then each has a typed adversarial classification.
    missing_report = preflight_database(missing, tmp_path / "packs")
    corrupt_report = preflight_database(corrupt, tmp_path / "packs")
    assert (missing_report.state, missing_report.reason) == (
        CompatibilityState.UNKNOWN,
        "missing-version-record",
    )
    assert corrupt_report.state is CompatibilityState.CORRUPT


def test_writer_refuses_malformed_migration_metadata_without_mutation(
    tmp_path: Path,
) -> None:
    # Given a current schema with malformed machine-consumed migration JSON.
    path = tmp_path / "malformed.sqlite"
    _current(path)
    _persist_mutation(
        path,
        "UPDATE ontologylab_storage_metadata SET migration_ids_json = '{' "
        "WHERE component = 'kg'",
    )
    before = _sha256(path)

    # When writer classification parses metadata, then it refuses typed and unchanged.
    with pytest.raises(StorageCompatibilityRefused) as raised:
        KGStore.open(path)
    assert (raised.value.report.state, raised.value.report.reason) == (
        CompatibilityState.UNKNOWN,
        "malformed-migration-ids",
    )
    assert _sha256(path) == before


def test_server_stages_supported_older_before_session_or_database_write(
    tmp_path: Path,
) -> None:
    # Given a recognized N-1 store at the server's canonical data path.
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "kg.sqlite"
    _current(path)
    _persist_mutation(path, "DROP TABLE ontologylab_storage_metadata")
    before = (_sha256(path), path.stat().st_mtime_ns, _sidecars(path))

    # When server startup reaches compatibility, then it exposes Task 8's seam.
    with pytest.raises(StorageCompatibilityRefused) as raised:
        create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    assert raised.value.report.state is CompatibilityState.SUPPORTED_OLDER
    assert not (data_dir / "session.token").exists()
    assert (_sha256(path), path.stat().st_mtime_ns, _sidecars(path)) == before


def test_compatibility_matrix_is_monotonic_release_bound_and_complete() -> None:
    # Given the shipped matrix, when it is parsed at the package boundary.
    matrix = load_compatibility_matrix()

    # Then versions are monotonic N-1/current and every component has one ID.
    assert tuple(item.storage_version for item in matrix.versions) == (0, 1)
    assert matrix.current_storage_version == CURRENT_STORAGE_VERSION
    assert matrix.release_version == "0.1.0"
    assert tuple(matrix.versions[-1].migration_ids) == CURRENT_MIGRATION_IDS


def test_compatibility_matrix_refuses_release_version_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given installed package identity drifting from the shipped matrix.
    monkeypatch.setattr("importlib.metadata.version", lambda _name: "9.9.9")

    # When the boundary reloads policy, then stale release binding is typed.
    with pytest.raises(StorageMatrixRefused) as raised:
        load_compatibility_matrix()
    assert raised.value.reason == "release-version"
