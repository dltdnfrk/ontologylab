"""Path derivation for ontologylab (successor to drylab's config.py).

Owns the project ROOT and the standard locations of the working data area
(``data/``: the mutable knowledge graph, raw documents, per-job dirs) and the
shipped artifacts area (``packs/``: immutable knowledge packs). Standard
library only.
"""

from __future__ import annotations

import time
from pathlib import Path

# ROOT is the ontologylab project root: the parent directory of the
# `ontologylab` package itself.
ROOT: Path = Path(__file__).resolve().parent.parent

DEFAULT_ENGINE: str = "claude"
DEFAULT_MODEL: str = "claude-fable-5"
DEFAULT_SEED: int = 7

# Extraction-job safety defaults (consumed by safety.Caps via a config object).
DEFAULT_MAX_ENGINE_CALLS: int = 200
DEFAULT_TIME_BUDGET_S: float = 1800.0


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
