"""macOS Keychain access for publisher API keys (stdlib only, secret-safe).

Why the Keychain and not a file: `data/` was found to be syncing to iCloud
(the working tree and `~/Library/Mobile Documents/...` share an inode), so a
key written next to `kg.sqlite` would be uploaded and kept in Time Machine.
Why not an environment variable, which was the interim answer: adding a key
would mean editing a plist and `launchctl bootout`/`bootstrap`-ing the
service. The Keychain keeps "no secret on disk in the clear" and drops that
friction.

**Verified on this machine before any of this was written** (the plan made
these a precondition, not a hope):

* a real one-shot LaunchAgent submitted into `gui/$UID` — the same domain the
  server runs in — read an item back successfully;
* no GUI authorization prompt appeared, because the item's ACL trusts
  `/usr/bin/security`, which is the binary both the server and the CLI shell
  out to;
* a missing item returns a non-zero exit rather than blocking.

**Transport.** The key is passed to `security` in argv. The alternative,
`-w` with the value on stdin, was measured at eight lengths from 32 to 1024
bytes and stored an *empty* password every time — silently. A key that
round-trips to nothing is worse than one that round-trips visibly.

argv is world-readable via `ps` for the duration of the call, and that is
worth stating plainly rather than hiding: on a single-user Mac it changes
little, because any process running as this user can already read the item by
exec'ing `security` itself. What the Keychain actually buys is encryption at
rest and a secret that no longer rides the iCloud sync.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional

# All ontologylab items live under one service name; the account distinguishes
# them. Grouping by role rather than by publisher is deliberate — the user
# connects "journal access" once, not Elsevier and Springer and CORE
# separately.
KEYCHAIN_SERVICE = "ontologylab"

# Keychain account: a short slug, because it is passed to `security` in argv
# and lands in `sources.json`. Deliberately narrower than it needs to be.
ACCOUNT_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

# `security` is not fast, but it is not slow either; a call that has not
# returned by now is most likely a GUI prompt waiting for a click nobody will
# give it. Not always, though — see `write_key`.
_TIMEOUT_S = 15.0


class KeychainError(Exception):
    """Raised when the Keychain cannot be written.

    Reads never raise — a missing key is a normal state (`key_present:
    false`), not a failure. Writes do, because a write that silently did
    nothing would leave the user believing a key was stored.
    """


def keychain_available() -> bool:
    """Whether this machine has the `security` binary at all.

    Everything here degrades to the environment-variable path on a non-macOS
    host, so this is a capability question, not an error condition.
    """
    return shutil.which("security") is not None


def _validate_account(account: str) -> str:
    if not ACCOUNT_RE.fullmatch(account):
        raise KeychainError(
            f"invalid keychain account {account!r}: must match "
            r"^[a-z0-9][a-z0-9._-]{0,63}$"
        )
    return account


def read_key(account: str) -> Optional[str]:
    """Return the stored key for ``account``, or None.

    None covers every way this can not-work: no `security` binary, no such
    item, a locked keychain, a malformed account name. The caller's job is to
    report `key_present: false` and carry on — a research run without a
    publisher key still collects open metadata from five sources.

    The subprocess output is never logged. `security` writes the key to
    stdout, so anything that echoed the result of this call would defeat it.
    """
    if not keychain_available():
        return None
    try:
        _validate_account(account)
    except KeychainError:
        return None
    try:
        completed = subprocess.run(
            ["security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        # Includes TimeoutExpired: a prompt is waiting, and blocking the
        # request thread on it would hang the dashboard.
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def write_key(account: str, key: str) -> None:
    """Store ``key`` under ``account``, replacing any existing item.

    Raises KeychainError rather than returning a flag: the caller is a route
    answering "did you save my key", and the honest answers are yes and an
    explanation. Neither the key nor any part of it appears in the messages
    raised here.

    **The write is always verified by reading it back**, because a zero exit
    status was measured not to mean "stored". The rejected stdin transport
    exited 0 and stored an empty password at every length tried; there is no
    reason to assume argv can never do something similar on some future
    macOS. Confirming costs one more `security` call on a path the user
    takes once.

    A timeout is likewise not taken as failure. Once during development
    `securityd` exceeded the timeout on a write that had in fact landed —
    reporting that as an error would send the user to re-enter a key already
    in the Keychain, and (worse) make them believe journal access was
    unconfigured when it was working. So a timeout falls through to the same
    read-back, and only a value that does not match is an error.
    """
    _validate_account(account)
    if not key or not key.strip():
        raise KeychainError("refusing to store an empty key")
    if not keychain_available():
        raise KeychainError(
            "the macOS `security` command is unavailable; set the key as an "
            "environment variable and reference it with api_key_env instead"
        )
    expected = key.strip()
    timed_out = False
    # Delete first, then create — never `-U` onto an existing item.
    #
    # `add-generic-password -U -T ...` against an item that already exists is
    # an ACL *modification*, and macOS demands the login password for that in
    # a SecurityAgent dialog: "security wants to change the access
    # permissions of the item". Creating a fresh item with the same `-T` is
    # not a modification and raises nothing. Rotating a key is the single
    # most common reason to come back here, so the update path is the one
    # that must not prompt.
    #
    # This was found the hard way: a run of the test suite put that dialog on
    # the user's screen repeatedly. An earlier 15s timeout on a write had
    # already been the same dialog, and calling it a transient was wrong.
    # Deleting first means a failed create leaves the user with no key at
    # all — and rotation is exactly when that would happen. Keep the old
    # value so the failure path can put it back.
    previous = read_key(account)
    delete_key(account)
    try:
        completed = subprocess.run(
            ["security", "add-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", account,
             "-w", expected,
             # Pre-authorize the binary that will read it back, so neither
             # the server nor the CLI ever raises a prompt. Both shell out to
             # this same binary, which is why one entry covers both.
             "-T", "/usr/bin/security"],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        completed = None
        timed_out = True
    except (OSError, subprocess.SubprocessError) as exc:
        # `from None`: the underlying error can quote the command line, and
        # the command line contains the key.
        raise KeychainError(
            f"could not write to the Keychain ({type(exc).__name__})"
        ) from None

    if read_key(account) == expected:
        return  # stored, whatever the exit status or the clock said

    # The write did not land. Put back whatever was there, so a failed
    # rotation costs the user nothing rather than their working key.
    if previous:
        _restore(account, previous)
    if timed_out:
        raise KeychainError(
            f"the Keychain did not answer within {_TIMEOUT_S:.0f}s and the "
            "key was not stored (an authorization prompt may be open)"
        )
    if completed is not None and completed.returncode != 0:
        # `security`'s stderr does not echo the value, but it is not worth
        # trusting that with a key on the line.
        raise KeychainError(
            f"the Keychain refused the write (exit {completed.returncode})"
        )
    raise KeychainError(
        "the Keychain accepted the write but did not store the value"
    )


def _restore(account: str, value: str) -> None:
    """Best-effort put-back after a failed replacement. Never raises."""
    try:
        subprocess.run(
            ["security", "add-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", account, "-w", value,
             "-T", "/usr/bin/security"],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        pass  # the caller is already raising; this was the salvage attempt


def delete_key(account: str) -> bool:
    """Remove the item; return whether one was there to remove."""
    if not keychain_available():
        return False
    try:
        _validate_account(account)
    except KeychainError:
        return False
    try:
        completed = subprocess.run(
            ["security", "delete-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", account],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def resolve_key(account: str = "", env_name: str = "") -> Optional[str]:
    """Resolve a key from the Keychain, falling back to the environment.

    The fallback is not decoration. The plan made Keychain viability a
    precondition with a stated retreat: if a machine cannot use it, the
    system goes back to storing only the *name* of an environment variable —
    the same posture `providers.py` has always had. Keeping both paths live
    means a non-macOS host, or a locked keychain, degrades instead of
    breaking.

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
    "KEYCHAIN_SERVICE",
    "KeychainError",
    "delete_key",
    "keychain_available",
    "read_key",
    "resolve_key",
    "write_key",
]
