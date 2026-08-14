"""Pure deterministic Method snapshot payload assembly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SnapshotRows:
    workspace: Mapping[str, Any]
    occurrences: tuple[Mapping[str, Any], ...]
    fragments: tuple[Mapping[str, Any], ...]
    fragment_evidence: tuple[Mapping[str, Any], ...]
    links: tuple[Mapping[str, Any], ...]
    gaps: tuple[Mapping[str, Any], ...]
    bridges: tuple[Mapping[str, Any], ...]
    bridge_evidence: tuple[Mapping[str, Any], ...]
    review_events: tuple[Mapping[str, Any], ...]
    counter_evidence_searches: tuple[Mapping[str, Any], ...]
    extraction_runs: tuple[Mapping[str, Any], ...]
    extraction_chunks: tuple[Mapping[str, Any], ...]
    policy_snapshots: tuple[Mapping[str, Any], ...]
    source_policies: tuple[Mapping[str, Any], ...]
    compilation_attempts: tuple[Mapping[str, Any], ...]
    compilation_gates: tuple[Mapping[str, Any], ...]
    releases: tuple[Mapping[str, Any], ...]


def snapshot_payload(
    rows: SnapshotRows,
    *,
    include_compilation_outputs: bool,
) -> dict[str, Any]:
    names = (
        "occurrences",
        "fragments",
        "fragment_evidence",
        "links",
        "gaps",
        "bridges",
        "bridge_evidence",
        "review_events",
        "counter_evidence_searches",
        "extraction_runs",
        "extraction_chunks",
        "policy_snapshots",
        "source_policies",
    )
    payload = {
        "workspace": dict(rows.workspace),
        **{
            name: list(getattr(rows, name))
            for name in names
        },
    }
    if include_compilation_outputs:
        payload.update(
            compilation_attempts=list(rows.compilation_attempts),
            compilation_gates=list(rows.compilation_gates),
            releases=list(rows.releases),
        )
    return payload
