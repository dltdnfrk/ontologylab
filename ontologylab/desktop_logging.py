"""Owner-only rotating and redacting logs for the macOS desktop process."""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from ontologylab.desktop_state import DesktopPaths, DesktopStateRefused

_PRIVATE_FILE_MODE: Final = 0o600
_LOG_FILENAME: Final = "ontologylab.log"


@dataclass(frozen=True, slots=True)
class DesktopLogPolicy:
    sensitive_values: tuple[str, ...] = ()
    max_bytes: int = 1_048_576
    backup_count: int = 3


_DEFAULT_LOG_POLICY: Final = DesktopLogPolicy()


class _RedactingFilter(logging.Filter):
    def __init__(self, values: tuple[str, ...]) -> None:
        super().__init__()
        self._values = tuple(
            sorted((value for value in values if value), key=len, reverse=True)
        )

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        for value in self._values:
            rendered = rendered.replace(value, "<redacted>")
        record.msg = rendered
        record.args = ()
        return True


class _PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):  # type annotation is inherited from logging.
        descriptor = os.open(
            self.baseFilename,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
            _PRIVATE_FILE_MODE,
        )
        os.fchmod(descriptor, _PRIVATE_FILE_MODE)
        return os.fdopen(descriptor, "a", encoding=self.encoding)

    def doRollover(self) -> None:
        super().doRollover()
        for path in Path(self.baseFilename).parent.glob(f"{_LOG_FILENAME}*"):
            path.chmod(_PRIVATE_FILE_MODE)


def configure_desktop_logging(
    paths: DesktopPaths, policy: DesktopLogPolicy = _DEFAULT_LOG_POLICY
) -> logging.Logger:
    """Install one bounded owner-only desktop log with deterministic redaction."""
    paths.prepare()
    log_path = paths.logs_dir / _LOG_FILENAME
    if log_path.is_symlink():
        raise DesktopStateRefused(member="log_symlink")
    if log_path.exists() and stat.S_IMODE(log_path.stat().st_mode) != _PRIVATE_FILE_MODE:
        raise DesktopStateRefused(member="log_permissions")
    handler = _PrivateRotatingFileHandler(
        log_path,
        maxBytes=policy.max_bytes,
        backupCount=policy.backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.addFilter(
        _RedactingFilter((str(paths.home), *policy.sensitive_values))
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root_logger = logging.getLogger()
    for existing in tuple(root_logger.handlers):
        if isinstance(existing, _PrivateRotatingFileHandler):
            root_logger.removeHandler(existing)
            existing.close()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    logger = logging.getLogger("ontologylab.desktop")
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger
