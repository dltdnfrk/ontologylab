"""Durable copy, digest, checkpoint, and validation primitives for upgrades."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import stat
from pathlib import Path
from typing import Final
from urllib.parse import quote

from ontologylab.method_store import prepare_method_connection
from ontologylab.pack_verifier import PackVerifyRefused, verify_pack
from ontologylab.storage_upgrade_journal import fsync_directory
from ontologylab.storage_upgrade_types import UpgradeRefused

_SQLITE_FILES: Final = ("kg.sqlite", "chat.sqlite")
_REGISTRY_FILES: Final = (
    "settings.json",
    "providers.json",
    "sources.json",
)
_METADATA_TABLE: Final = "ontologylab_storage_metadata"


def available_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(root: Path) -> tuple[tuple[str, str], ...]:
    if not root.is_dir():
        return ()
    return tuple(
        (path.relative_to(root).as_posix(), hash_file(path))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def required_space(data_dir: Path) -> int:
    total = sum(path.stat().st_size for path in data_dir.rglob("*") if path.is_file())
    return max(total * 3, 4096)


def checkpoint_database(path: Path) -> None:
    """Prove writer quiescence, then truncate all committed WAL frames."""
    try:
        with sqlite3.connect(path, timeout=0) as connection:
            connection.execute("BEGIN EXCLUSIVE")
            connection.rollback()
            result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result is not None and int(result[0]) != 0:
                raise UpgradeRefused("wal-checkpoint-busy")
    except sqlite3.OperationalError as exc:
        raise UpgradeRefused("wal-checkpoint-busy") from exc
    except sqlite3.DatabaseError as exc:
        raise UpgradeRefused("source-corrupt") from exc


def backup_database(source: Path, destination: Path) -> None:
    """Create a mode-0600 consistent SQLite backup-API copy."""
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    encoded = quote(str(source.resolve()), safe="/")
    try:
        with (
            sqlite3.connect(
                f"file:{encoded}?mode=ro", uri=True, timeout=0
            ) as source_db,
            sqlite3.connect(destination) as target_db,
        ):
            source_db.backup(target_db)
    except sqlite3.DatabaseError as exc:
        destination.unlink(missing_ok=True)
        raise UpgradeRefused("backup-failed") from exc
    destination.chmod(0o600)
    _fsync_file(destination)
    fsync_directory(destination.parent)


def atomic_copy(source: Path, destination: Path) -> None:
    """Copy one small registry through a same-directory fsynced replace."""
    if source.is_symlink() or not source.is_file():
        raise UpgradeRefused("registry-path")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(source.read_bytes())
    temporary.chmod(0o600)
    _fsync_file(temporary)
    os.replace(temporary, destination)
    fsync_directory(destination.parent)


def copy_documents(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if source.is_symlink() or not source.is_dir():
        raise UpgradeRefused("documents-path")
    temporary = destination.with_name(destination.name + ".tmp")
    shutil.rmtree(temporary, ignore_errors=True)
    shutil.copytree(source, temporary, symlinks=False)
    _fsync_tree(temporary)
    os.replace(temporary, destination)
    fsync_directory(destination.parent)


def logical_snapshot(data_dir: Path) -> tuple[str, tuple[tuple[str, int], ...]]:
    """Digest logical SQLite rows while excluding version metadata itself."""
    digest = hashlib.sha256()
    counts: list[tuple[str, int]] = []
    for filename in _SQLITE_FILES:
        path = data_dir / filename
        if not path.is_file():
            continue
        try:
            with sqlite3.connect(f"file:{quote(str(path.resolve()), safe='/')}?mode=ro", uri=True) as connection:
                tables = tuple(
                    str(row[0]) for row in connection.execute(
                        "SELECT name FROM sqlite_schema WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%' AND name != ? ORDER BY name",
                        (_METADATA_TABLE,),
                    )
                )
                for table in tables:
                    columns = tuple(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")'))
                    order = ",".join(f'"{column}"' for column in columns)
                    rows = connection.execute(f'SELECT * FROM "{table}" ORDER BY {order}').fetchall()
                    counts.append((f"{filename}:{table}", len(rows)))
                    digest.update(filename.encode())
                    digest.update(table.encode())
                    for row in rows:
                        digest.update(repr(tuple(row)).encode())
        except sqlite3.DatabaseError as exc:
            raise UpgradeRefused("source-corrupt") from exc
    return digest.hexdigest(), tuple(counts)


def validate_database(path: Path) -> None:
    try:
        with sqlite3.connect(path) as connection:
            prepare_method_connection(connection)
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise UpgradeRefused("integrity-check")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise UpgradeRefused("foreign-key-check")
    except sqlite3.DatabaseError as exc:
        raise UpgradeRefused("integrity-check") from exc


def pack_hashes(packs_dir: Path) -> tuple[tuple[str, str], ...]:
    receipts: list[tuple[str, str]] = []
    if not packs_dir.is_dir():
        return ()
    for pack_dir in sorted(path for path in packs_dir.iterdir() if path.is_dir()):
        try:
            receipt = verify_pack(pack_dir)
        except PackVerifyRefused as exc:
            raise UpgradeRefused("pack-invalid") from exc
        inventory = hashlib.sha256()
        for relative, file_hash in tree_hashes(pack_dir):
            inventory.update(relative.encode())
            inventory.update(file_hash.encode())
        inventory.update(receipt.pack_content_hash.encode())
        receipts.append((pack_dir.name, inventory.hexdigest()))
    return tuple(receipts)


def registry_hashes(data_dir: Path) -> tuple[tuple[str, str], ...]:
    """Return the exact inventory and hashes of mutable small registries."""
    return tuple(
        (name, hash_file(data_dir / name))
        for name in _REGISTRY_FILES
        if (data_dir / name).is_file()
    )


def stage_members(data_dir: Path) -> tuple[str, ...]:
    return tuple(
        name
        for name in (*_SQLITE_FILES, *_REGISTRY_FILES)
        if (data_dir / name).is_file()
    )


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            _fsync_file(path)
        elif stat.S_ISDIR(path.stat().st_mode):
            fsync_directory(path)
    fsync_directory(root)
