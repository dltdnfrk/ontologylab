"""No-delete scratch retention policy for bounded deployment QA."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Final

from scripts.internal_deployment_types import DeploymentRefused

_RETAIN_SCRATCH_ROOT: Final = "ONTOLOGYLAB_RETAIN_SCRATCH_ROOT"


def _retention_root() -> Path | None:
    raw = os.environ.get(_RETAIN_SCRATCH_ROOT)
    if raw is None:
        return None
    root = Path(raw)
    if not root.is_absolute():
        raise DeploymentRefused("retained_scratch_root_not_absolute")
    return root


def require_fresh_retained_destination(destination: Path, journal: Path) -> None:
    """Refuse states whose activation would replace or remove existing paths."""
    parent = destination.parent
    conflicts = (
        destination.exists()
        or journal.exists()
        or any(parent.glob(f".{destination.name}.previous-*"))
        or any(parent.glob(f".{destination.name}.install-*"))
    )
    if _retention_root() is not None and conflicts:
        raise DeploymentRefused("retained_scratch_requires_fresh_destination")


def dispose_stage(stage: Path) -> None:
    """Retain a failed stage when configured; preserve normal cleanup otherwise."""
    retention = _retention_root()
    if retention is None:
        shutil.rmtree(stage)
        return
    retained = retention / f"{stage.name}-{uuid.uuid4().hex}"
    retained.parent.mkdir(parents=True, exist_ok=True)
    os.replace(stage, retained)
