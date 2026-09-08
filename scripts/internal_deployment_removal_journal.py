"""Hash-chained durable state for retained-removal recovery."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Annotated, Final, Literal, assert_never

from pydantic import Field, TypeAdapter, ValidationError

from scripts.internal_deployment_types import (
    CompletedRemovalJournal,
    DeploymentRefused,
    PreparedRemovalJournal,
    RemovalJournalProgress,
    RemovalJournalRecord,
)

ProgressEvent = Literal[
    "app_retained", "forward_recovery_required", "runtime_retained"
]
_RECORD_ADAPTER = TypeAdapter(
    Annotated[RemovalJournalRecord, Field(discriminator="event")]
)
_PREPARED_ANCHOR_DOMAIN: Final = b"ontologylab.retained-uninstall.prepared.v1\0"


@unique
class JournalPhase(StrEnum):
    PREPARED = "prepared"
    APP_RETAINED = "app_retained"
    APP_RETAIN_FAILED = "app_retain_failed"
    RUNTIME_RETAINED = "runtime_retained"
    RUNTIME_RETAINED_AFTER_FAILURE = "runtime_retained_after_failure"


_PHASES: Final = {
    (): JournalPhase.PREPARED,
    ("app_retained",): JournalPhase.APP_RETAINED,
    (
        "app_retained",
        "forward_recovery_required",
    ): JournalPhase.APP_RETAIN_FAILED,
    ("app_retained", "runtime_retained"): JournalPhase.RUNTIME_RETAINED,
    (
        "app_retained",
        "forward_recovery_required",
        "runtime_retained",
    ): JournalPhase.RUNTIME_RETAINED_AFTER_FAILURE,
}


@dataclass(frozen=True, slots=True)
class RemovalJournalState:
    prepared: PreparedRemovalJournal
    events: tuple[ProgressEvent, ...]
    phase: JournalPhase
    state_sha256: str
    completed: CompletedRemovalJournal | None


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_record_bytes(record: RemovalJournalRecord) -> bytes:
    """Return the exact canonical bytes committed by journal hashes."""
    return record.model_dump_json(by_alias=True).encode()


def prepared_anchor(prepared_bytes: bytes) -> str:
    """Commit controller state to exact pre-rename prepared bytes."""
    return _digest(_PREPARED_ANCHOR_DOMAIN + prepared_bytes)


def _serialized(record: RemovalJournalRecord) -> bytes:
    return canonical_record_bytes(record) + b"\n"


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise DeploymentRefused("retained_removal_durability") from exc


def create_journal(path: Path, prepared: PreparedRemovalJournal) -> None:
    """Create and durably persist the authoritative initial transaction state."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_serialized(prepared))
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(path.parent)
    except OSError as exc:
        raise DeploymentRefused("retained_removal_journal") from exc


def _append(path: Path, record: RemovalJournalRecord) -> None:
    try:
        with path.open("ab") as stream:
            stream.write(_serialized(record))
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(path.parent)
    except OSError as exc:
        raise DeploymentRefused("retained_removal_journal") from exc


def append_progress(path: Path, event: ProgressEvent, event_id: str) -> None:
    """Append one transition bound to the complete preceding journal bytes."""
    try:
        previous = _digest(path.read_bytes())
    except OSError as exc:
        raise DeploymentRefused("retained_removal_journal") from exc
    _append(
        path,
        RemovalJournalProgress(
            schema="ontologylab.retained-removal-journal.v3",
            event=event,
            event_id=event_id,
            previous_sha256=previous,
        ),
    )


def append_completed(
    path: Path, state: RemovalJournalState, receipt_sha256: str
) -> None:
    """Append the terminal transition binding receipt and external authorities."""
    try:
        previous = _digest(path.read_bytes())
    except OSError as exc:
        raise DeploymentRefused("retained_removal_journal") from exc
    _append(
        path,
        CompletedRemovalJournal(
            schema="ontologylab.retained-removal-journal.v3",
            event="completed",
            event_id=state.prepared.event_id,
            previous_sha256=previous,
            receipt_sha256=receipt_sha256,
            prepared_anchor=prepared_anchor(canonical_record_bytes(state.prepared)),
            release_authority_sha256=(
                state.prepared.release_authority_sha256
            ),
        ),
    )


def verify_prepared_anchor(path: Path, expected: str | None) -> None:
    """Authenticate exact first-record bytes before parsing local state."""
    if expected is None:
        raise DeploymentRefused("prepared_anchor_required")
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise DeploymentRefused("prepared_anchor_malformed")
    try:
        first = path.read_bytes().splitlines(keepends=True)[0]
    except (OSError, IndexError) as exc:
        raise DeploymentRefused("prepared_anchor_mismatch") from exc
    if not first.endswith(b"\n"):
        raise DeploymentRefused("prepared_anchor_mismatch")
    actual = prepared_anchor(first[:-1])
    if not hmac.compare_digest(actual, expected):
        raise DeploymentRefused("prepared_anchor_mismatch")


def load_journal(path: Path) -> RemovalJournalState:
    """Parse and verify schema, event order, identity, and the complete hash chain."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DeploymentRefused("retained_removal_journal_malformed") from exc
    lines = payload.splitlines(keepends=True)
    if not lines or any(not line.endswith(b"\n") for line in lines):
        raise DeploymentRefused("retained_removal_journal_malformed")
    try:
        records = tuple(
            _RECORD_ADAPTER.validate_json(line, strict=True) for line in lines
        )
    except ValidationError as exc:
        raise DeploymentRefused("retained_removal_journal_malformed") from exc
    match records[0]:
        case PreparedRemovalJournal() as prepared:
            pass
        case RemovalJournalProgress() | CompletedRemovalJournal():
            raise DeploymentRefused("retained_removal_journal_malformed")
        case unreachable:
            assert_never(unreachable)
    prefix = lines[0]
    events: list[ProgressEvent] = []
    completed: CompletedRemovalJournal | None = None
    for record, line in zip(records[1:], lines[1:], strict=True):
        match record:
            case RemovalJournalProgress(event=event, event_id=event_id):
                if event_id != prepared.event_id or record.previous_sha256 != _digest(
                    prefix
                ):
                    raise DeploymentRefused("retained_removal_journal_tampered")
                events.append(event)
            case CompletedRemovalJournal(event_id=event_id):
                if (
                    event_id != prepared.event_id
                    or record.previous_sha256 != _digest(prefix)
                    or completed is not None
                ):
                    raise DeploymentRefused("retained_removal_journal_tampered")
                completed = record
            case PreparedRemovalJournal():
                raise DeploymentRefused("retained_removal_journal_malformed")
            case unreachable:
                assert_never(unreachable)
        prefix += line
    try:
        phase = _PHASES[tuple(events)]
    except KeyError as exc:
        raise DeploymentRefused("retained_removal_journal_state") from exc
    if completed is not None and not events[-1:] == ["runtime_retained"]:
        raise DeploymentRefused("retained_removal_journal_state")
    if completed is not None and records[-1] is not completed:
        raise DeploymentRefused("retained_removal_journal_state")
    state_sha256 = (
        completed.previous_sha256 if completed is not None else _digest(payload)
    )
    return RemovalJournalState(
        prepared, tuple(events), phase, state_sha256, completed
    )
