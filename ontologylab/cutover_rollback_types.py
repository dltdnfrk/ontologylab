"""Typed values for forward-only rollback and additive recovery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import NoReturn


@unique
class MutationKind(StrEnum):
    INGESTION = "ingestion"
    IDENTITY = "identity"
    EXTRACTION_REVIEW = "extraction_review"
    PUBLICATION = "publication"


@unique
class CompatibilityMode(StrEnum):
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"
    UNAVAILABLE = "unavailable"


@unique
class RollbackCode(StrEnum):
    NOT_INSTALLED = "not_installed"
    INVALID_INPUT = "invalid_input"
    WRITES_LIVE = "writes_live"
    WRITERS_LIVE = "writers_live"
    LOCK_REQUIRED = "lock_required"
    DRIFT_NONZERO = "drift_nonzero"
    INVENTORY_CHANGED = "inventory_changed"
    POST_CUTOVER_RESTORE = "post_cutover_restore"
    MARKER_REQUIRED = "marker_required"
    V2_WRITES_DISABLED = "v2_writes_disabled"
    OLD_WRITER_FORBIDDEN = "old_writer_forbidden"
    PACK_UNCHANGED = "pack_unchanged"


@dataclass(slots=True)
class RollbackRefused(Exception):
    code: RollbackCode
    detail: str

    def __str__(self) -> str:
        return f"{self.code.value}:{self.detail}"


@dataclass(frozen=True, slots=True)
class RestoreChecks:
    writes_refused: bool
    writers_drained: bool
    exclusive_lock: bool
    zero_drift: bool
    fresh_inventory_hash: str


@dataclass(frozen=True, slots=True)
class ForwardRollbackChecks:
    writers_drained: bool
    exclusive_lock: bool


@dataclass(frozen=True, slots=True)
class RestorePermit:
    generation: int
    inventory_hash: str


@dataclass(frozen=True, slots=True)
class RollbackState:
    generation: int
    forward_only: bool
    v2_writes_enabled: bool
    preferred_selection_enabled: bool
    publication_enabled: bool
    inventory_hash: str


@dataclass(frozen=True, slots=True)
class RollbackReceipt:
    seq: int
    action: str
    mutation_kind: MutationKind | None
    actor: str
    reason: str
    detail: str


@dataclass(frozen=True, slots=True)
class RedirectCompensation:
    decision_id: str
    supersedes_id: str


@dataclass(frozen=True, slots=True)
class FactRetraction:
    decision_receipt_ids: tuple[str, ...]
    citation_receipt_ids: tuple[str, ...]


def refuse(code: RollbackCode, detail: str) -> NoReturn:
    raise RollbackRefused(code, detail)


def require_text(value: str, field: str) -> str:
    clean = value.strip()
    if not clean:
        refuse(RollbackCode.INVALID_INPUT, field)
    return clean
