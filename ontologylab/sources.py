"""Publisher-source registry (stdlib only, secret-safe).

A *source* is a publisher API the user has connected so full text can be
reached beyond the five keyless metadata endpoints. Structurally this is
`providers.py` again — frozen dataclass, validation, atomic write, soft-fail
load, upsert by id — because that module's secret posture is the one worth
copying, not re-deriving.

**There is no field on `Source` that can hold a key.** That is the whole
design. `keychain_account` names a Keychain item and `api_key_env` names an
environment variable; `resolve_source_key` turns either into a value at call
time, and nothing writes that value anywhere. A registry that *could* store a
key would eventually store one — `data/` syncs to iCloud, and this file sits
in it.

Roles rather than publishers: a user connects "journal access" once, and one
Keychain item covers Elsevier, Springer and CORE together. Borrowed from
Claude Science, which solves the same problem with the same shape (see
`docs/claude-science-analysis.md`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ontologylab.keychain import ACCOUNT_RE, resolve_key
from ontologylab.paths import sources_path

# Source id: a short slug, mirroring PROVIDER_ID_RE.
SOURCE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
# Env var name (POSIX-ish) — the registry stores this, never the value.
_ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]*")

# Roles a source can fill. One entry per *capability*, not per vendor, so the
# UI can say "journal access: connected" instead of listing three publishers.
SOURCE_ROLES = ("literature",)


class SourceError(Exception):
    """Raised when a source definition is invalid or cannot be registered."""


@dataclass(frozen=True)
class Source:
    """One connected publisher API.

    Neither field is a secret. ``keychain_account`` is the account name of a
    Keychain item under the ``ontologylab`` service; ``api_key_env`` is the
    NAME of an environment variable, kept as the documented fallback for
    hosts where the Keychain is unavailable. Resolve with
    :func:`resolve_source_key` at call time.
    """

    id: str
    role: str
    keychain_account: str = ""
    api_key_env: str = ""
    label: str = ""

    def to_dict(self) -> dict:
        """Serializable view. There is no key field, so none can leak."""
        return {
            "id": self.id,
            "role": self.role,
            "keychain_account": self.keychain_account,
            "api_key_env": self.api_key_env,
            "label": self.label,
        }


def _source_from_dict(raw: dict) -> Source:
    return Source(
        id=str(raw["id"]),
        role=str(raw["role"]),
        keychain_account=str(raw.get("keychain_account") or ""),
        api_key_env=str(raw.get("api_key_env") or ""),
        label=str(raw.get("label") or ""),
    )


def validate_source(source: Source) -> Source:
    """Return ``source`` unchanged, or raise SourceError if it is invalid.

    Never inspects a key value — there is none to inspect. What it does
    enforce is that at least one *reference* is present: a source with
    neither a Keychain account nor an env-var name can never resolve, and
    would sit in the UI reporting "not connected" with no way to fix it.
    """
    if not SOURCE_ID_RE.fullmatch(source.id):
        raise SourceError(
            f"invalid source id {source.id!r}: must match "
            r"^[a-z0-9][a-z0-9_-]{0,31}$"
        )
    if source.role not in SOURCE_ROLES:
        raise SourceError(
            f"invalid role {source.role!r}: expected one of {SOURCE_ROLES}"
        )
    if source.keychain_account and not ACCOUNT_RE.fullmatch(source.keychain_account):
        raise SourceError(
            f"invalid keychain_account {source.keychain_account!r}: must match "
            r"^[a-z0-9][a-z0-9._-]{0,63}$"
        )
    if source.api_key_env and not _ENV_NAME_RE.fullmatch(source.api_key_env):
        raise SourceError(
            f"invalid api_key_env {source.api_key_env!r}: must be an "
            r"environment-variable name matching ^[A-Z][A-Z0-9_]*$"
        )
    if not source.keychain_account and not source.api_key_env:
        raise SourceError(
            "a source needs either a keychain_account or an api_key_env; "
            "neither stores a key, but one of them has to say where it lives"
        )
    return source


def resolve_source_key(source: Source) -> Optional[str]:
    """Read the source's key at call time; None when it is not configured.

    The ONLY place a publisher key enters the process from configuration.
    Returns None rather than raising: a missing key means "not connected",
    which the rest of the system handles by collecting open metadata from the
    five keyless sources exactly as before.
    """
    return resolve_key(source.keychain_account, source.api_key_env)


def load_sources(data_dir: Path | str) -> list[Source]:
    """Load all registered sources; fail soft to ``[]`` on any problem.

    A corrupt registry must not block a research run. Losing publisher access
    costs full text; raising here would cost the user the five open sources
    as well.
    """
    path = sources_path(data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    entries = raw.get("sources") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    sources: list[Source] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            sources.append(_source_from_dict(entry))
        except (KeyError, TypeError, ValueError):
            # One malformed entry never sinks the whole registry.
            continue
    return sources


def save_sources(data_dir: Path | str, sources: list[Source]) -> None:
    """Atomically write the registry (``.tmp`` + replace, like providers.py)."""
    path = sources_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sources": [s.to_dict() for s in sources]}
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def get_source(data_dir: Path | str, source_id: str) -> Optional[Source]:
    """Return the registered source with ``source_id`` or ``None``."""
    for source in load_sources(data_dir):
        if source.id == source_id:
            return source
    return None


def add_source(data_dir: Path | str, source: Source) -> None:
    """Validate then upsert ``source`` by id (replacing any existing one)."""
    validate_source(source)
    sources = [s for s in load_sources(data_dir) if s.id != source.id]
    sources.append(source)
    save_sources(data_dir, sources)


def remove_source(data_dir: Path | str, source_id: str) -> bool:
    """Remove the source with ``source_id``; return whether one was removed.

    Deliberately does NOT delete the Keychain item. Removing a registry entry
    is a configuration change; destroying the user's stored credential is
    not, and the two should not be one click.
    """
    sources = load_sources(data_dir)
    remaining = [s for s in sources if s.id != source_id]
    if len(remaining) == len(sources):
        return False
    save_sources(data_dir, remaining)
    return True


def source_public(source: Source) -> dict:
    """The browser-facing view: connected or not, never the key.

    Mirrors `routes._provider_public`. `key_present` is computed by actually
    resolving the key and throwing it away, because the alternative —
    reporting "configured" from the registry alone — would say "connected"
    for a source whose Keychain item was deleted out from under it.
    """
    return {
        **source.to_dict(),
        "key_present": resolve_source_key(source) is not None,
    }


__all__ = [
    "SOURCE_ID_RE",
    "SOURCE_ROLES",
    "Source",
    "SourceError",
    "add_source",
    "get_source",
    "load_sources",
    "remove_source",
    "resolve_source_key",
    "save_sources",
    "source_public",
    "validate_source",
]
