"""Path derivation for ontologylab (successor to drylab's config.py).

Owns the project ROOT and the standard locations of the working data area
(``data/``: the mutable knowledge graph, raw documents, per-job dirs) and the
shipped artifacts area (``packs/``: immutable knowledge packs). Standard
library only.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

# ROOT is the ontologylab project root: the parent directory of the
# `ontologylab` package itself.
ROOT: Path = Path(__file__).resolve().parent.parent

DEFAULT_ENGINE: str = "claude"
DEFAULT_MODEL: str = "claude-fable-5"
# Critic triage is advisory-only (it pre-scores the review queue, never
# approves), so it runs on a cheaper/faster Haiku-class tier instead of the
# extraction anchor model. Explicit --model still overrides. Only the claude
# engine consumes this (see critic.resolve_critic_model).
CRITIC_MODEL: str = "claude-haiku-4-5-20251001"
DEFAULT_SEED: int = 7

# Extraction-job safety defaults (consumed by safety.Caps via a config object).
# The server layer (schemas.ExtractRequest) and the dashboard's extract form
# mirror these — change them HERE, not at the call sites.
DEFAULT_MAX_ENGINE_CALLS: int = 500
DEFAULT_TIME_BUDGET_S: float = 7200.0

# Audit-trail actor recorded on approve/reject/merge/invalidate when the
# caller doesn't name one (single-user local deployment).
DEFAULT_ACTOR: str = "local-user"


def default_data_dir(root: Path | None = None) -> Path:
    """Return the mutable working data directory (ROOT/data)."""
    return (root or ROOT) / "data"


def default_packs_dir(root: Path | None = None) -> Path:
    """Return the immutable knowledge-pack output directory (ROOT/packs)."""
    return (root or ROOT) / "packs"


def kg_db_path(data_dir: Path | str) -> Path:
    """Return the working knowledge-graph sqlite file under ``data_dir``."""
    return Path(data_dir) / "kg.sqlite"


def documents_dir(data_dir: Path | str) -> Path:
    """Return the raw-document storage directory under ``data_dir``."""
    return Path(data_dir) / "documents"


def jobs_dir(data_dir: Path | str) -> Path:
    """Return the per-job (collect/extract/build-pack) directory root."""
    return Path(data_dir) / "jobs"


def providers_path(data_dir: Path | str) -> Path:
    """Return the configurable-provider registry file under ``data_dir``.

    Lives inside the gitignored working data area (like kg.sqlite and
    settings.json), so the registry — which stores only the *name* of each
    provider's API-key env var, never a key — is never committed.
    """
    return Path(data_dir) / "providers.json"


# Global network kill switch. When ``ONTOLOGYLAB_OFFLINE`` is set to a truthy
# value the app refuses every outbound network egress (API-backed LLM engines
# and the paper/web connectors) — a hard, auditable guarantee that private
# notes never leave the machine, independent of which engine is configured.
# Default (unset) preserves existing behavior.
_OFFLINE_TRUTHY = frozenset({"1", "true", "yes", "on"})


def offline_mode() -> bool:
    """True iff the ONTOLOGYLAB_OFFLINE kill switch is engaged."""
    return os.environ.get("ONTOLOGYLAB_OFFLINE", "").strip().lower() in _OFFLINE_TRUTHY


class NetworkBlocked(RuntimeError):
    """Raised when an outbound network egress is attempted in offline mode."""


def assert_network_allowed(what: str) -> None:
    """Raise :class:`NetworkBlocked` if offline mode forbids network egress.

    ``what`` names the egress point (engine/connector) for the error message.
    """
    if offline_mode():
        raise NetworkBlocked(
            f"offline mode (ONTOLOGYLAB_OFFLINE) blocks network egress: {what}"
        )


def new_job_dir(data_dir: Path | str, stage: str) -> Path:
    """Create and return a fresh job directory ``data/jobs/<stage>-<ts>/``."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = jobs_dir(data_dir)
    job_dir = base / f"{stage}-{stamp}"
    suffix = 1
    while job_dir.exists():
        suffix += 1
        job_dir = base / f"{stage}-{stamp}-{suffix}"
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir
