"""macOS Keychain access for publisher API keys (stdlib only, secret-safe).

Why the Keychain and not a file: `data/` was found to be syncing to iCloud
(the working tree and `~/Library/Mobile Documents/...` share an inode), so a
key written next to `kg.sqlite` would be uploaded and kept in Time Machine.
Why not an environment variable, which was the interim answer: adding a key
would mean editing a plist and `launchctl bootout`/`bootstrap`-ing the
service. The Keychain keeps "no secret on disk in the clear" and drops that
friction.

**Transport.** Writes, reads, and deletes go through a signed Swift helper
(`launcher/keychain-helper.swift`) that calls Security.framework
(`SecItemAdd`, `SecItemCopyMatching`, `SecItemUpdate`, `SecItemDelete`).
The helper takes one JSON object on stdin — operation, service, account,
and the secret when writing — and prints one JSON object on stdout. The
secret is never placed on argv, in the environment, or in helper error
text. `ps` therefore cannot see it.

The helper path is `ONTOLOGYLAB_KEYCHAIN_HELPER` or a stable Application
Support default. Only an absolute executable is accepted. JSON parse
failures, a nonzero helper status, a timeout, or a missing helper become
typed `KeychainError` values whose messages do not quote the secret.

New items use service `ontologylab.v2`. A missing v2 item may still be
read from the legacy `ontologylab` service via `security
find-generic-password` (read-only). Migration writes and verifies the
native item first, then deletes the legacy copy. This module never calls
`security add-generic-password` and never passes `-T /usr/bin/security`.

Code signing is what the Keychain uses to decide who may read an item.
This transport does not claim stronger same-user isolation than that.

The environment-variable fallback in `resolve_key` stays: a host without
the helper, or a locked keychain, degrades instead of breaking.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Optional

# New items live here. The account still distinguishes roles.
KEYCHAIN_SERVICE = "ontologylab.v2"
# Pre-helper items. Read-only fallback; deleted only after a verified v2 write.
KEYCHAIN_SERVICE_LEGACY = "ontologylab"

HELPER_ENV = "ONTOLOGYLAB_KEYCHAIN_HELPER"
_DEFAULT_HELPER_NAME = "keychain-helper"

# Keychain account: a short slug, because it is passed to the helper and
# lands in `sources.json`. Deliberately narrower than it needs to be.
ACCOUNT_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

# A call that has not returned by now is most likely a GUI prompt waiting
# for a click nobody will give it.
_TIMEOUT_S = 15.0

_TYPED_KINDS = frozenset({"malformed", "unauthorized", "not_found", "refused"})


class KeychainError(Exception):
    """Raised when the Keychain cannot be written.

    Reads never raise — a missing key is a normal state (`key_present:
    false`), not a failure. Writes do, because a write that silently did
    nothing would leave the user believing a key was stored.

    ``kind`` is a closed set of redacted codes: malformed, unauthorized,
    missing_helper, timeout, refused. Messages never include the secret.
    """

    def __init__(self, message: str, kind: str = "error") -> None:
        super().__init__(message)
        self.kind = kind


def default_helper_path() -> str:
    """Stable Application Support location for the signed helper binary."""
    return str(
        Path.home()
        / "Library"
        / "Application Support"
        / "OntologyLab"
        / _DEFAULT_HELPER_NAME
    )


def _resolved_helper_path() -> Optional[str]:
    raw = os.environ.get(HELPER_ENV, "").strip() or default_helper_path()
    if not os.path.isabs(raw):
        return None
    try:
        path = os.path.realpath(raw)
    except OSError:
        return None
    if not os.path.isfile(path):
        return None
    mode = os.stat(path).st_mode
    if not stat.S_ISREG(mode):
        return None
    if not os.access(path, os.X_OK):
        return None
    return path


def keychain_available() -> bool:
    """Whether this machine can talk to a Keychain at all.

    The native helper is required to write. A leftover `security` binary
    is enough to *read* a legacy item. Everything here degrades to the
    environment-variable path when neither is present.
    """
    return _resolved_helper_path() is not None or shutil.which("security") is not None


def _validate_account(account: str) -> str:
    if not ACCOUNT_RE.fullmatch(account):
        raise KeychainError(
            f"invalid keychain account {account!r}: must match "
            r"^[a-z0-9][a-z0-9._-]{0,63}$",
            kind="malformed",
        )
    return account


def _kind_from_helper(completed: subprocess.CompletedProcess, body: Optional[dict]) -> str:
    if body and body.get("error") in _TYPED_KINDS:
        return str(body["error"])
    if completed.returncode == 2:
        return "malformed"
    if completed.returncode == 3:
        return "unauthorized"
    return "refused"


def _invoke_helper(
    operation: str,
    account: str,
    secret: Optional[str] = None,
    service: Optional[str] = None,
) -> dict:
    path = _resolved_helper_path()
    if path is None:
        raise KeychainError(
            "the Keychain helper is unavailable; set the key as an "
            "environment variable and reference it with api_key_env instead",
            kind="missing_helper",
        )
    payload: dict = {
        "operation": operation,
        "service": service or KEYCHAIN_SERVICE,
        "account": account,
    }
    if secret is not None:
        payload["secret"] = secret
    try:
        completed = subprocess.run(
            [path],
            input=json.dumps(payload, separators=(",", ":")),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise KeychainError(
            f"the Keychain helper did not answer within {_TIMEOUT_S:.0f}s",
            kind="timeout",
        ) from None
    except OSError:
        raise KeychainError(
            "the Keychain helper could not be started",
            kind="missing_helper",
        ) from None

    body: Optional[dict] = None
    raw = completed.stdout or ""
    if raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise KeychainError(
                "the Keychain helper returned a malformed response",
                kind="malformed",
            ) from None
        if not isinstance(parsed, dict):
            raise KeychainError(
                "the Keychain helper returned a malformed response",
                kind="malformed",
            )
        body = parsed

    if completed.returncode != 0:
        raise KeychainError(
            f"the Keychain helper refused the request "
            f"(exit {completed.returncode})",
            kind=_kind_from_helper(completed, body),
        ) from None

    if body is None:
        raise KeychainError(
            "the Keychain helper returned a malformed response",
            kind="malformed",
        )
    return body


def _read_native(account: str) -> Optional[str]:
    if _resolved_helper_path() is None:
        return None
    try:
        body = _invoke_helper("read", account)
    except KeychainError:
        return None
    if not body.get("ok"):
        return None
    value = str(body.get("secret") or "").strip()
    return value or None


def _read_legacy(account: str) -> Optional[str]:
    if shutil.which("security") is None:
        return None
    try:
        completed = subprocess.run(
            ["security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE_LEGACY, "-a", account, "-w"],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _delete_legacy(account: str) -> bool:
    if shutil.which("security") is None:
        return False
    try:
        completed = subprocess.run(
            ["security", "delete-generic-password",
             "-s", KEYCHAIN_SERVICE_LEGACY, "-a", account],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _try_migrate(account: str, value: str) -> bool:
    if _resolved_helper_path() is None:
        return False
    try:
        _invoke_helper("write", account, secret=value)
    except KeychainError:
        return False
    if _read_native(account) != value:
        return False
    _delete_legacy(account)
    return True


def read_key(account: str) -> Optional[str]:
    """Return the stored key for ``account``, or None.

    None covers every way this can not-work: no helper, no such item, a
    locked keychain, a malformed account name. The caller's job is to
    report `key_present: false` and carry on.

    Native v2 is tried first. A hit on the legacy service is returned even
    if migration fails; the legacy item is deleted only after a native
    write+read that matches.
    """
    try:
        _validate_account(account)
    except KeychainError:
        return None
    native = _read_native(account)
    if native:
        return native
    legacy = _read_legacy(account)
    if not legacy:
        return None
    _try_migrate(account, legacy)
    return legacy


def write_key(account: str, key: str) -> None:
    """Store ``key`` under ``account``, replacing any existing v2 item.

    Raises KeychainError rather than returning a flag. Neither the key nor
    any part of it appears in the messages raised here.

    The write is always verified by a native read, because a zero exit
    status was measured not to mean "stored" on the old transport. A
    timeout falls through to the same read-back. Legacy items are deleted
    only after that verification succeeds.
    """
    _validate_account(account)
    if not key or not key.strip():
        raise KeychainError("refusing to store an empty key", kind="malformed")
    if _resolved_helper_path() is None:
        raise KeychainError(
            "the Keychain helper is unavailable; set the key as an "
            "environment variable and reference it with api_key_env instead",
            kind="missing_helper",
        )
    expected = key.strip()
    previous = read_key(account)
    timed_out = False
    write_error: Optional[KeychainError] = None
    try:
        _invoke_helper("write", account, secret=expected)
    except KeychainError as exc:
        if exc.kind == "timeout":
            timed_out = True
        else:
            write_error = exc

    if _read_native(account) == expected:
        _delete_legacy(account)
        return

    if previous:
        _restore(account, previous)
    if write_error is not None:
        raise write_error
    if timed_out:
        raise KeychainError(
            f"the Keychain helper did not answer within {_TIMEOUT_S:.0f}s "
            "and the key was not stored (an authorization prompt may be open)",
            kind="timeout",
        )
    raise KeychainError(
        "the Keychain accepted the write but did not store the value",
        kind="refused",
    )


def _restore(account: str, value: str) -> None:
    """Best-effort put-back after a failed replacement. Never raises."""
    try:
        _invoke_helper("write", account, secret=value)
    except KeychainError:
        pass


def delete_key(account: str) -> bool:
    """Remove the v2 item and any leftover legacy item."""
    try:
        _validate_account(account)
    except KeychainError:
        return False
    removed = False
    if _resolved_helper_path() is not None:
        try:
            body = _invoke_helper("delete", account)
        except KeychainError:
            body = None
        if body is not None and body.get("ok"):
            removed = True
    if _delete_legacy(account):
        removed = True
    return removed


def resolve_key(account: str = "", env_name: str = "") -> Optional[str]:
    """Resolve a key from the Keychain, falling back to the environment.

    The fallback is not decoration. If a machine cannot use the helper,
    the system goes back to storing only the *name* of an environment
    variable. Keeping both paths live means a non-macOS host, or a locked
    keychain, degrades instead of breaking.

    Keychain first: a machine that has both configured has deliberately
    stored one, and an environment variable is the more likely leftover.
    """
    if account:
        value = read_key(account)
        if value:
            return value
    if env_name:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return None


__all__ = [
    "ACCOUNT_RE",
    "HELPER_ENV",
    "KEYCHAIN_SERVICE",
    "KEYCHAIN_SERVICE_LEGACY",
    "KeychainError",
    "default_helper_path",
    "delete_key",
    "keychain_available",
    "read_key",
    "resolve_key",
    "write_key",
]
