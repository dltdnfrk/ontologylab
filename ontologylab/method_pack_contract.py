"""Shared Task 7 Method publication types."""

from __future__ import annotations

from dataclasses import dataclass


SCHEMA_VERSION = "method-v1"
COMPILER_VERSION = "method-compiler-v1"
PUBLICATION_SCHEMA_VERSION = "methodology-publication-v1"


class MethodPackError(ValueError):
    """A selected Method release is not safe to publish."""


@dataclass(frozen=True, slots=True)
class MethodPackSelection:
    release_ids: tuple[str, ...]
    release_hashes: tuple[str, ...]
    method_json_hash: str
    source_index_hash: str
    gate_receipt_hash: str
    selection_input_hash: str
    publication_receipt_hash: str
    source_snapshot_hash: str
