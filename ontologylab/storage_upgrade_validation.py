"""Retained-backup and live-source invariants checked before every swap."""

from __future__ import annotations

from ontologylab.storage_compatibility import (
    CURRENT_STORAGE_VERSION,
    preflight_database,
)
from ontologylab.storage_upgrade_io import (
    checkpoint_database,
    logical_snapshot,
    pack_hashes,
    registry_hashes,
    tree_hashes,
    validate_database,
)
from ontologylab.storage_upgrade_types import (
    UpgradeJournal,
    UpgradeRefused,
    UpgradeRequest,
)


def validate_retained_backup(
    request: UpgradeRequest,
    journal: UpgradeJournal,
) -> None:
    """Refuse any retained-backup or bound-pack drift as one typed outcome."""
    backup_data = request.backups_dir / journal.upgrade_id / "data"
    try:
        for name in ("kg.sqlite", "chat.sqlite"):
            path = backup_data / name
            if path.is_file():
                validate_database(path)
        digest, counts = logical_snapshot(backup_data)
        if (
            digest != journal.backup_digest
            or counts != journal.backup_counts
            or tree_hashes(backup_data / "documents")
            != journal.backup_raw_hashes
            or registry_hashes(backup_data)
            != journal.backup_registry_hashes
            or pack_hashes(request.packs_dir) != journal.backup_pack_hashes
        ):
            raise UpgradeRefused("backup-integrity")
    except UpgradeRefused as exc:
        if exc.reason == "backup-integrity":
            raise
        raise UpgradeRefused("backup-integrity") from exc


def validate_live_before_swap(
    request: UpgradeRequest,
    journal: UpgradeJournal,
    *,
    swapped: tuple[str, ...],
) -> None:
    """Prove the live source still equals the snapshot or already-swapped stage."""
    for name in ("kg.sqlite", "chat.sqlite"):
        path = request.data_dir / name
        if path.is_file():
            checkpoint_database(path)
    digest, counts = logical_snapshot(request.data_dir)
    report = preflight_database(request.data_dir / "kg.sqlite", request.packs_dir)
    expected_version = (
        int(CURRENT_STORAGE_VERSION)
        if "kg.sqlite" in swapped
        else journal.source_version
    )
    stage = dict(journal.stage_hashes)
    expected_registries = tuple(
        (name, stage[name] if name in swapped else source_hash)
        for name, source_hash in journal.source_registry_hashes
    )
    if (
        digest != journal.source_digest
        or counts != journal.source_counts
        or report.storage_version != expected_version
        or registry_hashes(request.data_dir) != expected_registries
    ):
        raise UpgradeRefused("live-diverged-forward-recovery-required")
