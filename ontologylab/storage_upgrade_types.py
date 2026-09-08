"""Typed state machine contracts for staged desktop storage upgrades."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

JOURNAL_SCHEMA: Final = "ontologylab.storage-upgrade.v1"


@unique
class QuiescenceKind(StrEnum):
    NO_EXISTING_BACKEND = "no_existing_backend"
    STOPPED_BACKEND = "stopped_backend"


@unique
class UpgradePhase(StrEnum):
    PREPARED = "prepared"
    BACKED_UP = "backed-up"
    MIGRATED = "migrated"
    VALIDATED = "validated"
    ACTIVATING = "activating"
    ACTIVATED = "activated"
    COMPLETE = "complete"


@unique
class UpgradeFailpoint(StrEnum):
    BEFORE_BACKUP = "before-backup"
    DURING_BACKUP = "during-backup"
    STAGED_MIGRATION = "staged-migration"
    VALIDATION = "validation"
    PRE_ACTIVATION = "pre-activation"
    SWAP_KG = "swap-kg"
    SWAP_CHAT = "swap-chat"
    SWAP_SETTINGS = "swap-settings"
    SWAP_PROVIDERS = "swap-providers"
    SWAP_SOURCES = "swap-sources"
    POST_ACTIVATION = "post-activation"


class UpgradeJournal(BaseModel):
    """Owner-only, machine-consumed durable upgrade state."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    schema_name: str
    upgrade_id: str
    phase: UpgradePhase
    swapped: tuple[str, ...] = ()
    source_version: int
    source_digest: str = ""
    source_counts: tuple[tuple[str, int], ...] = ()
    source_registry_hashes: tuple[tuple[str, str], ...] = ()
    raw_hashes: tuple[tuple[str, str], ...] = ()
    pack_hashes: tuple[tuple[str, str], ...] = ()
    backup_digest: str = ""
    backup_counts: tuple[tuple[str, int], ...] = ()
    backup_raw_hashes: tuple[tuple[str, str], ...] = ()
    backup_registry_hashes: tuple[tuple[str, str], ...] = ()
    backup_pack_hashes: tuple[tuple[str, str], ...] = ()
    stage_digest: str = ""
    stage_hashes: tuple[tuple[str, str], ...] = ()
    quiescence_receipt_hash: str
    quiescence_proof_kind: QuiescenceKind
    quiescence_inspected_paths: tuple[str, ...]
    quiescence_inspected_at_ns: int
    quiescence_initial_holder_pids: tuple[int, ...]
    quiescence_final_holder_pids: tuple[int, ...]
    quiescence_verified_backend_pid: int | None
    quiescence_verified_backend_version: str | None
    quiescence_verified_bundle_identifier: str | None
    quiescence_verified_executable_path: str | None
    quiescence_verified_start_marker: str | None
    quiescence_verified_uid: int | None
    quiescence_signals: tuple[str, ...]
    quiescence_exit_observed: bool


@dataclass(frozen=True, slots=True)
class VerifiedBackendIdentity:
    pid: int
    version: str
    bundle_identifier: str
    executable_path: str
    start_seconds: int
    start_microseconds: int
    uid: int


@dataclass(frozen=True, slots=True)
class QuiescenceProof:
    """Typed holder-discovery evidence bound to the live supervisor parent."""

    receipt_path: Path
    supervisor_pid: int
    nonce: str
    proof_kind: QuiescenceKind
    inspected_paths: tuple[Path, ...]
    inspected_at_ns: int
    initial_holder_pids: tuple[int, ...]
    final_holder_pids: tuple[int, ...]
    verified_owner: VerifiedBackendIdentity | None
    signals: tuple[str, ...]
    exit_observed: bool


@dataclass(frozen=True, slots=True)
class UpgradeRequest:
    application_support_dir: Path
    data_dir: Path
    packs_dir: Path
    backups_dir: Path
    quiescence: QuiescenceProof


@dataclass(frozen=True, slots=True)
class UpgradeResult:
    upgrade_id: str
    backup_dir: Path | None
    source_digest: str
    backup_digest: str
    activated_digest: str
    source_counts: tuple[tuple[str, int], ...]
    backup_counts: tuple[tuple[str, int], ...]
    activated_counts: tuple[tuple[str, int], ...]
    activated: bool


class UpgradeRefused(Exception):
    """Typed upgrade refusal supporting runtime traceback assignment."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason

    def __str__(self) -> str:
        return f"storage upgrade refused: {self.reason}"


class UpgradeJournalRefused(Exception):
    """Typed journal refusal supporting runtime traceback assignment."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason

    def __str__(self) -> str:
        return f"storage upgrade journal refused: {self.reason}"


class UpgradeInterrupted(Exception):
    """Exact injected interruption used by deterministic recovery tests."""

    def __init__(self, failpoint: UpgradeFailpoint) -> None:
        super().__init__()
        self.failpoint = failpoint

    def __str__(self) -> str:
        return f"storage upgrade interrupted: {self.failpoint.value}"
