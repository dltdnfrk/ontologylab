"""Immutable, raw SQLite compatibility inspection for canonical desktop state."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.resources
import json
import shutil
import sqlite3
import stat
import sys
from dataclasses import replace
from pathlib import Path
from typing import Final
from urllib.parse import quote

from pydantic import ValidationError

from ontologylab.storage_types import (
    CompatibilityMatrix,
    CompatibilityReport,
    CompatibilityState,
    MigrationId,
    StorageCompatibilityRefused,
    StorageInventory,
    StorageMatrixRefused,
    StorageVersion,
)

_MATRIX_RESOURCE: Final = "storage-compatibility.json"
_METADATA_TABLE: Final = "ontologylab_storage_metadata"
_LEGACY_TABLES: Final = frozenset({"schema_version", "documents", "nodes", "edges"})
_COUNT_TABLES: Final = ("documents", "nodes", "edges", "runs", "artifacts")


def load_compatibility_matrix() -> CompatibilityMatrix:
    """Load and validate the shipped release/storage compatibility contract."""
    raw = importlib.resources.files("ontologylab").joinpath(_MATRIX_RESOURCE).read_text()
    matrix = CompatibilityMatrix.model_validate_json(raw, strict=True)
    versions = tuple(item.storage_version for item in matrix.versions)
    if versions != tuple(sorted(set(versions))) or versions[-1] != matrix.current_storage_version:
        raise StorageMatrixRefused("versions")
    states = tuple(item.state for item in matrix.versions)
    if states[-1] != CompatibilityState.CURRENT.value:
        raise StorageMatrixRefused("current-state")
    package_version = importlib.metadata.version("ontologylab")
    if matrix.release_version != package_version:
        raise StorageMatrixRefused("release-version")
    return matrix


MATRIX: Final = load_compatibility_matrix()
CURRENT_STORAGE_VERSION: Final = StorageVersion(MATRIX.current_storage_version)
CURRENT_MIGRATION_IDS: Final = tuple(
    MigrationId(item)
    for item in MATRIX.versions[-1].migration_ids
)


def bootstrap_metadata_sql() -> str:
    """Return deterministic DDL/DML for the current immutable migration journal."""
    values = ",\n".join(
        "(" + ", ".join(
            (
                repr(migration_id.split("-", 1)[0]),
                str(CURRENT_STORAGE_VERSION),
                repr(json.dumps([migration_id], separators=(",", ":"))),
                repr(MATRIX.release_version),
            )
        ) + ")"
        for migration_id in CURRENT_MIGRATION_IDS
    )
    return f"""
CREATE TABLE IF NOT EXISTS {_METADATA_TABLE} (
    component TEXT PRIMARY KEY,
    storage_version INTEGER NOT NULL CHECK (storage_version >= 0),
    migration_ids_json TEXT NOT NULL,
    release_version TEXT NOT NULL
);
INSERT OR IGNORE INTO {_METADATA_TABLE}
(component, storage_version, migration_ids_json, release_version) VALUES
{values};
"""


def _inventory(path: Path, packs_dir: Path, counts: tuple[tuple[str, int], ...] = ()) -> StorageInventory:
    wal = path.with_name(path.name + "-wal")
    try:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
        database_bytes = path.stat().st_size if path.exists() else 0
        wal_bytes = wal.stat().st_size if wal.is_file() else 0
        free_bytes = shutil.disk_usage(path.parent if path.parent.exists() else packs_dir.parent).free
    except OSError:
        mode, database_bytes, wal_bytes, free_bytes = None, 0, 0, 0
    pack_count = sum(1 for item in packs_dir.glob("*/pack.sqlite") if item.is_file()) if packs_dir.is_dir() else 0
    return StorageInventory(database_bytes, wal_bytes > 0, wal_bytes, mode, free_bytes, pack_count, counts)


def _report(
    path: Path,
    packs_dir: Path,
    state: CompatibilityState,
    *,
    version: int | None = None,
    migrations: tuple[str, ...] = (),
    reason: str,
    counts: tuple[tuple[str, int], ...] = (),
) -> CompatibilityReport:
    return CompatibilityReport(
        path=path,
        state=state,
        storage_version=StorageVersion(version) if version is not None else None,
        migration_ids=tuple(MigrationId(item) for item in migrations),
        reason=reason,
        inventory=_inventory(path, packs_dir, counts),
    )


def _readonly_connection(path: Path, *, immutable: bool) -> sqlite3.Connection:
    encoded = quote(str(path.resolve()), safe="/")
    immutable_query = "&immutable=1" if immutable else ""
    connection = sqlite3.connect(
        f"file:{encoded}?mode=ro{immutable_query}", uri=True, timeout=1.0
    )
    connection.execute("PRAGMA query_only=ON")
    return connection


def _classify_metadata(rows: list[tuple[str, int, str, str]], path: Path, packs_dir: Path, counts: tuple[tuple[str, int], ...]) -> CompatibilityReport:
    expected_components = tuple(item.split("-", 1)[0] for item in CURRENT_MIGRATION_IDS)
    if tuple(row[0] for row in rows) != expected_components:
        return _report(path, packs_dir, CompatibilityState.UNKNOWN, reason="missing-version-record", counts=counts)
    versions = {row[1] for row in rows}
    if len(versions) != 1:
        return _report(path, packs_dir, CompatibilityState.UNKNOWN, reason="mixed-storage-versions", counts=counts)
    if {row[3] for row in rows} != {MATRIX.release_version}:
        return _report(path, packs_dir, CompatibilityState.UNKNOWN, reason="release-version-drift", counts=counts)
    version = versions.pop()
    try:
        migrations = tuple(json.loads(row[2])[0] for row in rows)
    except (json.JSONDecodeError, IndexError, TypeError):
        return _report(path, packs_dir, CompatibilityState.UNKNOWN, version=version, reason="malformed-migration-ids", counts=counts)
    known = {item.storage_version: item for item in MATRIX.versions}
    if version > CURRENT_STORAGE_VERSION:
        return _report(path, packs_dir, CompatibilityState.NEWER, version=version, migrations=migrations, reason="newer-storage-version", counts=counts)
    entry = known.get(version)
    if entry is None or migrations != entry.migration_ids:
        return _report(path, packs_dir, CompatibilityState.UNKNOWN, version=version, migrations=migrations, reason="unknown-version-or-migration-ids", counts=counts)
    state = CompatibilityState(entry.state)
    return _report(path, packs_dir, state, version=version, migrations=migrations, reason="recognized-version", counts=counts)


def _preflight_database(
    path: Path,
    packs_dir: Path,
    *,
    immutable: bool,
) -> CompatibilityReport:
    if path.is_symlink():
        return _report(path, packs_dir, CompatibilityState.UNKNOWN, reason="symlink")
    if not path.exists() or path.stat().st_size == 0:
        return _report(path, packs_dir, CompatibilityState.BOOTSTRAP_REQUIRED, reason="database-absent")
    try:
        with _readonly_connection(path, immutable=immutable) as connection:
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                return _report(path, packs_dir, CompatibilityState.CORRUPT, reason="quick-check-failed")
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            counts = tuple((name, connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in _COUNT_TABLES if name in tables)
            if _METADATA_TABLE not in tables:
                state = CompatibilityState.SUPPORTED_OLDER if _LEGACY_TABLES <= tables else CompatibilityState.UNKNOWN
                reason = "recognized-legacy-layout" if state is CompatibilityState.SUPPORTED_OLDER else "unversioned-unknown-layout"
                return _report(path, packs_dir, state, version=0 if state is CompatibilityState.SUPPORTED_OLDER else None, reason=reason, counts=counts)
            rows = connection.execute(f"SELECT component, storage_version, migration_ids_json, release_version FROM {_METADATA_TABLE} ORDER BY component").fetchall()
            return _classify_metadata(rows, path, packs_dir, counts)
    except (OSError, sqlite3.DatabaseError):
        return _report(path, packs_dir, CompatibilityState.CORRUPT, reason="sqlite-unreadable")


def preflight_database(path: Path, packs_dir: Path) -> CompatibilityReport:
    """Classify one KG database through immutable read-only SQLite."""
    return _preflight_database(path, packs_dir, immutable=True)


def preflight_storage(data_dir: Path, packs_dir: Path) -> CompatibilityReport:
    """Classify canonical startup state, including an active-WAL refusal seam."""
    report = preflight_database(data_dir / "kg.sqlite", packs_dir)
    if report.inventory.wal_present:
        return replace(
            report,
            state=CompatibilityState.UNKNOWN,
            reason="active-wal",
        )
    return report


def require_writer_compatible(
    path: Path, *, packs_dir: Path | None = None,
) -> CompatibilityReport:
    """Refuse newer/unknown/corrupt stores before opening a writer."""
    if packs_dir is None:
        packs_dir = path.parent.parent / "packs"
    immutable_report = preflight_database(path, packs_dir)
    report = (
        _preflight_database(path, packs_dir, immutable=False)
        if immutable_report.inventory.wal_present
        else immutable_report
    )
    if report.state in {CompatibilityState.NEWER, CompatibilityState.UNKNOWN, CompatibilityState.CORRUPT}:
        raise StorageCompatibilityRefused(report)
    return report


def _payload(report: CompatibilityReport) -> dict[str, str | int | bool | list[list[str | int]] | None]:
    return {
        "schema": "ontologylab.storage-preflight.v1",
        "state": report.state.value,
        "storage_version": report.storage_version,
        "reason": report.reason,
        "starts_without_migration": report.starts_without_migration,
        "database_bytes": report.inventory.database_bytes,
        "wal_present": report.inventory.wal_present,
        "wal_bytes": report.inventory.wal_bytes,
        "free_bytes": report.inventory.free_bytes,
        "pack_count": report.inventory.pack_count,
        "logical_counts": [[name, count] for name, count in report.inventory.logical_counts],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontologylab.storage_compatibility")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--packs-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    report = preflight_storage(args.data_dir, args.packs_dir)
    print(json.dumps(_payload(report), sort_keys=True))
    return 0 if report.state in {CompatibilityState.BOOTSTRAP_REQUIRED, CompatibilityState.CURRENT, CompatibilityState.SUPPORTED_OLDER} else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValidationError, StorageMatrixRefused) as exc:
        print(f"storage compatibility matrix refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
