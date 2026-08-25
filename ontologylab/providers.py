"""Configurable model-provider registry (stdlib only, secret-safe).

A *provider* is a networked model backend the user registers so it can be
selected as an engine (``api:<id>``) alongside the built-in CLI engines. Two
kinds are supported: ``anthropic`` (the Anthropic Messages API) and
``openai`` (any OpenAI-compatible ``/chat/completions`` endpoint — OpenAI,
OpenRouter, a local Ollama/LM Studio server, ...).

Secret posture (load-bearing): a provider stores the *name* of an environment
variable (``api_key_env``), never the key itself. That name is not chosen by
the caller — it is bound to the provider origin and id (official Anthropic /
OpenAI / OpenRouter hosts use their dedicated vars; everything else uses
``ONTOLOGYLAB_PROVIDER_<ID>_<12-hex-origin>``). The key is read from ``os.environ`` at call
time (:func:`resolve_api_key`) and never serialized. The registry file lives
in the gitignored working data area (:func:`ontologylab.paths.providers_path`),
so it is never committed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from ontologylab.paths import providers_path

_REGISTRY_FILE_MODE = 0o600
_DATA_DIR_MODE = 0o700

# Provider id: a short slug usable inside an ``api:<id>`` engine name. The
# same pattern gates ``is_valid_engine_name`` in engines.py (imported there).
PROVIDER_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
# Env var name (POSIX-ish): the registry stores this, never the value.
_ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]*")
# http (cleartext) is allowed ONLY for these local hosts, so a local
# Ollama / LM Studio server works without forcing TLS; everything else needs https.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

PROVIDER_KINDS = ("anthropic", "openai")

# Official HTTPS origins (scheme, hostname, default port) own a single env.
_OFFICIAL_ENV_BY_ORIGIN: dict[tuple[str, str, int], str] = {
    ("https", "api.anthropic.com", 443): "ANTHROPIC_API_KEY",
    ("https", "api.openai.com", 443): "OPENAI_API_KEY",
    ("https", "openrouter.ai", 443): "OPENROUTER_API_KEY",
}


class ProviderError(Exception):
    """Raised when a provider definition is invalid or cannot be registered."""


class ProviderCredentialError(ProviderError):
    """The env locator is not the one bound to this provider origin/id."""


@dataclass(frozen=True)
class Provider:
    """One registered model backend.

    ``api_key_env`` is the NAME of an environment variable, not a key —
    resolve the actual key with :func:`resolve_api_key` at call time.
    """

    id: str
    kind: str
    base_url: str
    api_key_env: str
    models: tuple[str, ...] = ()
    label: str = ""

    def to_dict(self) -> dict:
        """Serializable view — id/kind/base_url/api_key_env/models/label only.

        Never includes a resolved key; there is no key field to leak.
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "models": list(self.models),
            "label": self.label,
        }


def _provider_from_dict(raw: dict) -> Provider:
    """Build a Provider from a stored dict, coercing models to a tuple."""
    models = raw.get("models") or []
    if not isinstance(models, list):
        models = []
    return Provider(
        id=str(raw["id"]),
        kind=str(raw["kind"]),
        base_url=str(raw["base_url"]),
        api_key_env=str(raw["api_key_env"]),
        models=tuple(str(m) for m in models),
        label=str(raw.get("label") or ""),
    )


def _url_origin(url: str) -> tuple[str, str, int] | None:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return None
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, host, port


def _normalized_origin(url: str) -> str | None:
    """Exact origin fingerprint: ``scheme://host:port`` (IPv6 bracketed)."""
    origin = _url_origin(url)
    if origin is None:
        return None
    scheme, host, port = origin
    if ":" in host:
        return f"{scheme}://[{host}]:{port}"
    return f"{scheme}://{host}:{port}"


def dedicated_api_key_env(provider_id: str, base_url: str) -> str:
    """Return the only env-var name this provider id + origin may use."""
    origin = _url_origin(base_url)
    if origin is not None:
        official = _OFFICIAL_ENV_BY_ORIGIN.get(origin)
        if official:
            return official
    slug = provider_id.upper().replace("-", "_")
    fingerprint = _normalized_origin(base_url) or base_url
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12].upper()
    return f"ONTOLOGYLAB_PROVIDER_{slug}_{digest}"


def validate_provider(provider: Provider) -> Provider:
    """Return ``provider`` unchanged, or raise ProviderError if it is invalid.

    Checks: id slug shape, known kind, base_url scheme (https always; http
    only for a local host), a plausible env-var name, and that the env name
    is the one bound to this origin/id. Never inspects a key value (there is
    none to inspect).
    """
    if not PROVIDER_ID_RE.fullmatch(provider.id):
        raise ProviderError(
            f"invalid provider id {provider.id!r}: must match "
            r"^[a-z0-9][a-z0-9_-]{0,31}$"
        )
    if provider.kind not in PROVIDER_KINDS:
        raise ProviderError(
            f"invalid kind {provider.kind!r}: expected one of {PROVIDER_KINDS}"
        )
    parsed = urlparse(provider.base_url)
    if parsed.scheme not in ("https", "http"):
        raise ProviderError(
            f"invalid base_url {provider.base_url!r}: scheme must be https "
            "(or http for localhost)"
        )
    if parsed.scheme == "http" and (parsed.hostname or "") not in _LOCAL_HOSTS:
        raise ProviderError(
            f"invalid base_url {provider.base_url!r}: http is allowed only for "
            f"{sorted(_LOCAL_HOSTS)} — use https for remote hosts"
        )
    if not parsed.netloc:
        raise ProviderError(
            f"invalid base_url {provider.base_url!r}: missing host"
        )
    if not _ENV_NAME_RE.fullmatch(provider.api_key_env):
        raise ProviderError(
            f"invalid api_key_env {provider.api_key_env!r}: must be an "
            r"environment-variable name matching ^[A-Z][A-Z0-9_]*$"
        )
    required = dedicated_api_key_env(provider.id, provider.base_url)
    if provider.api_key_env != required:
        raise ProviderCredentialError(
            "api_key_env is not bound to this provider origin"
        )
    return provider


def resolve_api_key(provider: Provider) -> Optional[str]:
    """Read the provider's API key from the environment at call time.

    Returns the stripped value of ``os.environ[provider.api_key_env]`` or
    ``None`` when the variable is unset or empty. The key is never stored;
    this is the ONLY place it enters the process from configuration.
    """
    value = os.environ.get(provider.api_key_env, "").strip()
    return value or None


def _restrict_dir(path: Path) -> None:
    try:
        if path.is_dir() and stat.S_IMODE(path.stat().st_mode) & 0o077:
            os.chmod(path, _DATA_DIR_MODE)
    except OSError:
        return


def _restrict_file(path: Path) -> None:
    try:
        if path.is_file() and stat.S_IMODE(path.stat().st_mode) & 0o077:
            os.chmod(path, _REGISTRY_FILE_MODE)
    except OSError:
        return


def load_providers(data_dir: Path | str) -> list[Provider]:
    """Load all registered providers; fail soft to ``[]`` on any problem.

    A missing or corrupt registry file yields an empty list rather than an
    error, so the rest of the system (which defaults to ``mock``) is never
    blocked by a bad providers.json.
    """
    path = providers_path(data_dir)
    _restrict_file(path)
    if path.parent.is_dir():
        _restrict_dir(path.parent)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    entries = raw.get("providers") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    providers: list[Provider] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            provider = _provider_from_dict(entry)
        except (KeyError, TypeError, ValueError):
            # One malformed entry never sinks the whole registry.
            continue
        try:
            providers.append(validate_provider(provider))
        except ProviderError:
            # A tampered entry that registration would have refused is
            # dropped here too: disk is not a trusted writer.
            continue
    return providers


def save_providers(data_dir: Path | str, providers: list[Provider]) -> None:
    """Atomically write the registry (``.tmp`` + replace, like settings.py).

    Only id/kind/base_url/api_key_env/models/label are serialized — never a
    resolved key.
    """
    path = providers_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_dir(path.parent)
    payload = {"providers": [p.to_dict() for p in providers]}
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.chmod(_REGISTRY_FILE_MODE)
    tmp_path.replace(path)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        path.chmod(_REGISTRY_FILE_MODE)


def get_provider(data_dir: Path | str, provider_id: str) -> Optional[Provider]:
    """Return the registered provider with ``provider_id`` or ``None``."""
    for provider in load_providers(data_dir):
        if provider.id == provider_id:
            return provider
    return None


def add_provider(data_dir: Path | str, provider: Provider) -> None:
    """Validate then upsert ``provider`` by id (replacing any existing one)."""
    validate_provider(provider)
    providers = [p for p in load_providers(data_dir) if p.id != provider.id]
    providers.append(provider)
    save_providers(data_dir, providers)


def remove_provider(data_dir: Path | str, provider_id: str) -> bool:
    """Remove the provider with ``provider_id``; return whether one was removed."""
    providers = load_providers(data_dir)
    remaining = [p for p in providers if p.id != provider_id]
    if len(remaining) == len(providers):
        return False
    save_providers(data_dir, remaining)
    return True


__all__ = [
    "Provider",
    "ProviderError",
    "ProviderCredentialError",
    "PROVIDER_ID_RE",
    "PROVIDER_KINDS",
    "dedicated_api_key_env",
    "validate_provider",
    "resolve_api_key",
    "load_providers",
    "save_providers",
    "get_provider",
    "add_provider",
    "remove_provider",
]
