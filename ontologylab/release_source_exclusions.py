"""Classifier for generated paths excluded from release source authority."""

from __future__ import annotations

from pathlib import Path


def source_exclusion_reason(relative_path: str) -> str | None:
    """Name why a generated source-tree path is not a build input."""
    if ".build" in Path(relative_path).parts:
        return "swiftpm-build-output"
    return None
