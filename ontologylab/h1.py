"""Public H1 historical receipt migration API.

Transaction ownership: ``prepare_h1_copy`` is filesystem-only.
``run_h1_migration`` uses SAVEPOINTs and never COMMIT/ROLLBACK.
``run_h1_operator`` owns BEGIN/COMMIT on the destination copy.
"""

from __future__ import annotations

from pathlib import Path

from ontologylab.h1_migrate import (
    build_receipt as build_receipt,
    h1_inventory as h1_inventory,
    run_h1_migration as run_h1_migration,
)
from ontologylab.h1_types import (
    H1Failpoint,
    H1Interruption,
    H1Receipt,
    H1RefusalCode,
    H1SourceRefused,
    refuse_source,
)
from ontologylab.migration_backfill import prepare_backup_copy


_SQLITE_MAGIC = b"SQLite format 3\x00"


def prepare_h1_copy(source_path: str | Path, dest_dir: str | Path) -> Path:
    """SQLite backup-API snapshot plus documents/ sidecar copy."""
    source = Path(source_path)
    target = Path(dest_dir)
    _refuse_overlap(source, target)
    return prepare_backup_copy(source, target)


def run_h1_operator(
    source_path: str | Path,
    dest_dir: str | Path,
    *,
    failpoint: H1Failpoint | None = None,
) -> H1Receipt:
    """Validate source, copy once, migrate destination, commit."""
    source = Path(source_path)
    target = Path(dest_dir)
    _require_sqlite_source(source)
    _refuse_overlap(source, target)
    dest = _existing_or_copy(source, target)
    return _migrate_destination(dest, failpoint)


def _require_sqlite_source(source: Path) -> None:
    if not source.is_file():
        refuse_source(
            H1RefusalCode.MISSING_SOURCE,
            f"snapshot source missing: {source}",
        )
    try:
        header = source.read_bytes()[:16]
    except OSError as exc:
        raise H1SourceRefused(
            H1RefusalCode.UNREADABLE_SOURCE,
            f"unreadable source: {source}",
        ) from exc
    if header != _SQLITE_MAGIC:
        refuse_source(
            H1RefusalCode.NOT_SQLITE,
            f"source is not a sqlite database: {source}",
        )


def _refuse_overlap(source: Path, dest: Path) -> None:
    src = source.resolve()
    src_root = src.parent
    dest_resolved = dest.resolve()
    dest_db = dest_resolved / src.name
    if dest_resolved == src or dest_resolved == src_root or dest_db == src:
        refuse_source(
            H1RefusalCode.SOURCE_OVERLAP,
            f"destination overlaps source: {dest}",
        )
    try:
        dest_resolved.relative_to(src_root)
    except ValueError:
        pass
    else:
        refuse_source(
            H1RefusalCode.SOURCE_OVERLAP,
            f"destination is inside the source tree: {dest}",
        )
    if dest_db.exists() and dest_db.samefile(src):
        refuse_source(
            H1RefusalCode.SOURCE_OVERLAP,
            f"destination store is the source file: {dest_db}",
        )


def _existing_or_copy(source: Path, target: Path) -> Path:
    existing = target / source.name
    if existing.is_file():
        return existing
    target.mkdir(parents=True, exist_ok=True)
    return prepare_h1_copy(source, target)


def _migrate_destination(
    dest: Path, failpoint: H1Failpoint | None,
) -> H1Receipt:
    from ontologylab.kgstore import KGStore

    store = KGStore.open(dest)
    try:
        if not store.conn.in_transaction:
            store.conn.execute("BEGIN IMMEDIATE")
        try:
            receipt = run_h1_migration(store.conn, failpoint=failpoint)
        except H1Interruption:
            store.conn.commit()
            raise
        except Exception:
            if store.conn.in_transaction:
                store.conn.rollback()
            raise
        store.conn.commit()
        return receipt
    finally:
        store.close()
