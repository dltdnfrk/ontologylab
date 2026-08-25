"""Per-process session token for the local web API.

The dashboard is a single-user loopback app. A token is minted when the
process starts, written next to the working store, and required on every
``/api/*`` request. Browsers receive it as an HttpOnly cookie on the
loopback document; non-browser callers send ``X-OntologyLab-Session``.
"""

from __future__ import annotations

import hmac
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

TOKEN_BYTES = 32
TOKEN_HEX_LENGTH = TOKEN_BYTES * 2
SESSION_FILENAME = "session.token"
COOKIE_NAME = "ontologylab_session"
HEADER_NAME = "X-OntologyLab-Session"
DATA_DIR_MODE = 0o700
TOKEN_FILE_MODE = 0o600


@dataclass(frozen=True, slots=True)
class SessionSecret:
    token: str
    path: Path


def mint_session_token() -> str:
    """Return a new 256-bit token as lowercase hex."""
    return secrets.token_hex(TOKEN_BYTES)


def ensure_private_data_dir(data_dir: Path) -> None:
    """Create ``data_dir`` if needed and force mode ``0700``."""
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(data_dir, DATA_DIR_MODE)


def persist_session_token(data_dir: Path, token: str) -> Path:
    """Write ``session.token`` as ``0600`` via a same-directory replace."""
    path = Path(data_dir) / SESSION_FILENAME
    tmp_path = path.with_name(f"{SESSION_FILENAME}.tmp")
    tmp_path.write_text(token, encoding="utf-8")
    tmp_path.chmod(TOKEN_FILE_MODE)
    tmp_path.replace(path)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        path.chmod(TOKEN_FILE_MODE)
    return path


def install_session(data_dir: Path) -> SessionSecret:
    """Mint a process token and persist it under ``data_dir``."""
    resolved = Path(data_dir)
    ensure_private_data_dir(resolved)
    token = mint_session_token()
    return SessionSecret(token=token, path=persist_session_token(resolved, token))


def tokens_match(presented: str | None, expected: str) -> bool:
    """Constant-time compare; different lengths are a miss, not an exception."""
    if presented is None or not expected:
        return False
    if len(presented) != len(expected):
        return False
    return hmac.compare_digest(presented, expected)


def presented_session_token(*, cookie: str | None, header: str | None) -> str | None:
    """Prefer the explicit header; fall back to the session cookie."""
    if header:
        return header
    if cookie:
        return cookie
    return None
