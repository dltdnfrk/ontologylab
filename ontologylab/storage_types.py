"""Typed storage-version contracts shared by preflight and writer boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import NewType

from pydantic import BaseModel, ConfigDict, Field

StorageVersion = NewType("StorageVersion", int)
MigrationId = NewType("MigrationId", str)


@unique
class CompatibilityState(StrEnum):
    BOOTSTRAP_REQUIRED = "bootstrap-required"
    CURRENT = "current"
    SUPPORTED_OLDER = "supported-older"
    NEWER = "newer"
    UNKNOWN = "unknown"
    CORRUPT = "corrupt"


class MatrixVersion(BaseModel):
    """One immutable storage layout accepted by a release."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    storage_version: int
    state: str
    migration_ids: tuple[str, ...]


class CompatibilityMatrix(BaseModel):
    """Release-bound monotonic storage support policy."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    contract_schema: str = Field(alias="schema")
    release_version: str
    current_storage_version: int
    versions: tuple[MatrixVersion, ...]


@dataclass(frozen=True, slots=True)
class StorageInventory:
    database_bytes: int
    wal_present: bool
    wal_bytes: int
    permissions: int | None
    free_bytes: int
    pack_count: int
    logical_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    """Raw inspection outcome; constructing it never opens a writer."""

    path: Path
    state: CompatibilityState
    storage_version: StorageVersion | None
    migration_ids: tuple[MigrationId, ...]
    reason: str
    inventory: StorageInventory

    @property
    def starts_without_migration(self) -> bool:
        return self.state in {
            CompatibilityState.BOOTSTRAP_REQUIRED,
            CompatibilityState.CURRENT,
        }


class StorageMatrixRefused(Exception):
    """Typed malformed/stale compatibility-matrix refusal."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason

    def __str__(self) -> str:
        return f"storage compatibility matrix refused: {self.reason}"


class StorageCompatibilityRefused(Exception):
    """Typed refusal kept mutable because Python assigns exception tracebacks."""

    def __init__(self, report: CompatibilityReport) -> None:
        super().__init__()
        self.report = report

    def __str__(self) -> str:
        return (
            "storage compatibility refused: "
            f"state={self.report.state.value} reason={self.report.reason}"
        )


class StorageHandshakeRefused(Exception):
    """Typed handshake refusal supporting runtime traceback assignment."""

    def __init__(self, expected: StorageVersion, received: str) -> None:
        super().__init__()
        self.expected = expected
        self.received = received

    def __str__(self) -> str:
        return (
            "storage handshake refused: "
            f"expected={self.expected} received={self.received}"
        )
