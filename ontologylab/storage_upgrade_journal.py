"""Owner-only atomic journal and singleton lock for storage upgrades."""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from ontologylab.storage_upgrade_types import (
    JOURNAL_SCHEMA,
    UpgradeJournal,
    UpgradeJournalRefused,
)

JOURNAL_NAME: Final = "upgrade-journal.json"
LOCK_NAME: Final = ".upgrade.lock"
_OWNER_FILE_MODE: Final = 0o600


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_journal(root: Path, journal: UpgradeJournal) -> None:
    """Atomically persist one durable journal generation as mode 0600."""
    path = root / JOURNAL_NAME
    temporary = root / f"{JOURNAL_NAME}.tmp"
    payload = journal.model_dump_json().encode()
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        _OWNER_FILE_MODE,
    )
    try:
        os.fchmod(descriptor, _OWNER_FILE_MODE)
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    fsync_directory(root)


def read_journal(root: Path) -> UpgradeJournal | None:
    """Parse the journal boundary without trusting paths or partial JSON."""
    path = root / JOURNAL_NAME
    if not path.exists():
        return None
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or stat.S_IMODE(info.st_mode) != _OWNER_FILE_MODE:
            raise UpgradeJournalRefused("permissions")
        journal = UpgradeJournal.model_validate_json(path.read_bytes(), strict=True)
    except (OSError, ValidationError) as exc:
        raise UpgradeJournalRefused("malformed") from exc
    if journal.schema_name != JOURNAL_SCHEMA:
        raise UpgradeJournalRefused("schema")
    return journal


@contextmanager
def upgrade_lock(root: Path) -> Iterator[None]:
    """Hold the canonical nonblocking process lock for one engine transition."""
    path = root / LOCK_NAME
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, _OWNER_FILE_MODE)
    os.fchmod(descriptor, _OWNER_FILE_MODE)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpgradeJournalRefused("concurrent-upgrade") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
