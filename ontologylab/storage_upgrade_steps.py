"""Durable backup, migration, validation, and activation transitions."""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Final

from ontologylab.storage_compatibility import bootstrap_metadata_sql, preflight_database
from ontologylab.storage_quiescence import validate_quiescence
from ontologylab.storage_types import CompatibilityState
from ontologylab.storage_upgrade_io import (
    atomic_copy,
    backup_database,
    copy_documents,
    hash_file,
    logical_snapshot,
    pack_hashes,
    registry_hashes,
    stage_members,
    tree_hashes,
    validate_database,
)
from ontologylab.storage_upgrade_journal import fsync_directory, write_journal
from ontologylab.storage_upgrade_types import (
    UpgradeFailpoint,
    UpgradeJournal,
    UpgradePhase,
    UpgradeRefused,
    UpgradeRequest,
)
from ontologylab.storage_upgrade_validation import (
    validate_live_before_swap,
    validate_retained_backup,
)

STAGING_NAME: Final = ".upgrade-staging"
_SWAP_FAILPOINTS: Final = {
    "kg.sqlite": UpgradeFailpoint.SWAP_KG,
    "chat.sqlite": UpgradeFailpoint.SWAP_CHAT,
    "settings.json": UpgradeFailpoint.SWAP_SETTINGS,
    "providers.json": UpgradeFailpoint.SWAP_PROVIDERS,
    "sources.json": UpgradeFailpoint.SWAP_SOURCES,
}


def upgrade_paths(request: UpgradeRequest, upgrade_id: str) -> tuple[Path, Path]:
    return (
        request.application_support_dir / STAGING_NAME / upgrade_id,
        request.backups_dir / upgrade_id,
    )


def _hit(
    failpoint: Callable[[UpgradeFailpoint], None] | None,
    point: UpgradeFailpoint,
) -> None:
    if failpoint is not None:
        failpoint(point)


def backup_transition(
    request: UpgradeRequest,
    journal: UpgradeJournal,
    failpoint: Callable[[UpgradeFailpoint], None] | None,
) -> UpgradeJournal:
    staging, backup = upgrade_paths(request, journal.upgrade_id)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    stage_data, backup_data = staging / "data", backup / "data"
    stage_data.mkdir(mode=0o700, parents=True)
    backup_data.mkdir(mode=0o700, parents=True)
    backup_database(request.data_dir / "kg.sqlite", stage_data / "kg.sqlite")
    backup_database(request.data_dir / "kg.sqlite", backup_data / "kg.sqlite")
    _hit(failpoint, UpgradeFailpoint.DURING_BACKUP)
    chat = request.data_dir / "chat.sqlite"
    if chat.is_file():
        backup_database(chat, stage_data / "chat.sqlite")
        backup_database(chat, backup_data / "chat.sqlite")
    for name in ("settings.json", "providers.json", "sources.json"):
        source = request.data_dir / name
        if source.exists():
            atomic_copy(source, stage_data / name)
            atomic_copy(source, backup_data / name)
    copy_documents(request.data_dir / "documents", backup_data / "documents")
    backup_digest, backup_counts = logical_snapshot(backup_data)
    if (backup_digest, backup_counts) != (journal.source_digest, journal.source_counts):
        raise UpgradeRefused("backup-logical-mismatch")
    if tree_hashes(backup_data / "documents") != journal.raw_hashes:
        raise UpgradeRefused("backup-raw-mismatch")
    backup_raw_hashes = tree_hashes(backup_data / "documents")
    backup_registry_hashes = registry_hashes(backup_data)
    updated = journal.model_copy(
        update={
            "phase": UpgradePhase.BACKED_UP,
            "backup_digest": backup_digest,
            "backup_counts": backup_counts,
            "backup_raw_hashes": backup_raw_hashes,
            "backup_registry_hashes": backup_registry_hashes,
            "backup_pack_hashes": pack_hashes(request.packs_dir),
        }
    )
    write_journal(request.application_support_dir, updated)
    return updated


def migrate_transition(
    request: UpgradeRequest,
    journal: UpgradeJournal,
) -> UpgradeJournal:
    staging, _backup = upgrade_paths(request, journal.upgrade_id)
    try:
        with sqlite3.connect(staging / "data/kg.sqlite") as connection:
            connection.executescript(bootstrap_metadata_sql())
    except sqlite3.DatabaseError as exc:
        raise UpgradeRefused("staged-migration-failed") from exc
    updated = journal.model_copy(update={"phase": UpgradePhase.MIGRATED})
    write_journal(request.application_support_dir, updated)
    return updated


def validate_transition(
    request: UpgradeRequest,
    journal: UpgradeJournal,
) -> UpgradeJournal:
    validate_retained_backup(request, journal)
    staging, backup = upgrade_paths(request, journal.upgrade_id)
    stage_data, backup_data = staging / "data", backup / "data"
    for name in ("kg.sqlite", "chat.sqlite"):
        if (stage_data / name).is_file():
            validate_database(stage_data / name)
        if (backup_data / name).is_file():
            validate_database(backup_data / name)
    report = preflight_database(stage_data / "kg.sqlite", request.packs_dir)
    if report.state is not CompatibilityState.CURRENT:
        raise UpgradeRefused("staged-migration-ids")
    stage_digest, stage_counts = logical_snapshot(stage_data)
    backup_digest, backup_counts = logical_snapshot(backup_data)
    if stage_digest != journal.source_digest or stage_counts != journal.source_counts:
        raise UpgradeRefused("staged-logical-mismatch")
    if backup_digest != journal.backup_digest or backup_counts != journal.source_counts:
        raise UpgradeRefused("backup-validation-mismatch")
    if tree_hashes(request.data_dir / "documents") != journal.raw_hashes:
        raise UpgradeRefused("source-raw-drift")
    if pack_hashes(request.packs_dir) != journal.pack_hashes:
        raise UpgradeRefused("pack-drift")
    hashes = tuple(
        (name, hash_file(stage_data / name)) for name in stage_members(stage_data)
    )
    updated = journal.model_copy(
        update={
            "phase": UpgradePhase.VALIDATED,
            "stage_digest": stage_digest,
            "stage_hashes": hashes,
        }
    )
    write_journal(request.application_support_dir, updated)
    return updated


def activate_transition(
    request: UpgradeRequest,
    journal: UpgradeJournal,
    failpoint: Callable[[UpgradeFailpoint], None] | None,
) -> UpgradeJournal:
    staging, _backup = upgrade_paths(request, journal.upgrade_id)
    stage_data = staging / "data"
    expected = dict(journal.stage_hashes)
    effective_swapped = list(journal.swapped)
    for name, expected_hash in expected.items():
        if (
            name not in effective_swapped
            and not (stage_data / name).exists()
            and (request.data_dir / name).is_file()
            and hash_file(request.data_dir / name) == expected_hash
        ):
            effective_swapped.append(name)
    validate_quiescence(request.quiescence, data_dir=request.data_dir)
    validate_retained_backup(request, journal)
    validate_live_before_swap(
        request,
        journal,
        swapped=tuple(effective_swapped),
    )
    if journal.phase is UpgradePhase.VALIDATED:
        journal = journal.model_copy(update={"phase": UpgradePhase.ACTIVATING})
        write_journal(request.application_support_dir, journal)
    swapped = list(journal.swapped)
    for name, expected_hash in expected.items():
        if name in swapped:
            continue
        source, destination = stage_data / name, request.data_dir / name
        validate_quiescence(request.quiescence, data_dir=request.data_dir)
        validate_retained_backup(request, journal)
        validate_live_before_swap(
            request,
            journal,
            swapped=tuple(effective_swapped),
        )
        if not source.exists():
            if destination.is_file() and hash_file(destination) == expected_hash:
                swapped.append(name)
                if name not in effective_swapped:
                    effective_swapped.append(name)
                journal = journal.model_copy(update={"swapped": tuple(swapped)})
                write_journal(request.application_support_dir, journal)
                continue
            raise UpgradeRefused("activation-state-mismatch")
        os.replace(source, destination)
        destination.chmod(0o600)
        descriptor = os.open(destination, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_directory(request.data_dir)
        swapped.append(name)
        effective_swapped.append(name)
        journal = journal.model_copy(update={"swapped": tuple(swapped)})
        write_journal(request.application_support_dir, journal)
        _hit(failpoint, _SWAP_FAILPOINTS[name])
    updated = journal.model_copy(update={"phase": UpgradePhase.ACTIVATED})
    write_journal(request.application_support_dir, updated)
    return updated
