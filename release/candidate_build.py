"""Public Task 11 candidate identity, inventory, and sealing facade."""

from __future__ import annotations

from ontologylab.release_policy_types import ReleasePolicy

from .candidate_receipt import seal_candidate
from .candidate_source import verify_retained_snapshot, verify_source
from .candidate_tree import (
    canonical_sha,
    freeze_tree,
    normalized_tree_manifest,
    sha256_file,
    tree_manifest,
    verify_normalized_match,
    write_json,
)
from .candidate_types import (
    BuildMetadata,
    CandidateRefused,
    HostProbe,
    SourceIdentity,
    TreeEntry,
)

__all__ = (
    "BuildMetadata",
    "CandidateRefused",
    "HostProbe",
    "SourceIdentity",
    "TreeEntry",
    "canonical_sha",
    "freeze_tree",
    "normalized_tree_manifest",
    "seal_candidate",
    "sha256_file",
    "tree_manifest",
    "verify_event",
    "verify_host",
    "verify_normalized_match",
    "verify_retained_snapshot",
    "verify_source",
    "write_json",
)


def verify_host(policy: ReleasePolicy, probe: HostProbe) -> None:
    """Refuse hosts outside the frozen architecture and minimum macOS policy."""
    if probe.architecture != policy.arch:
        raise CandidateRefused("host_architecture", probe.architecture)
    minimum = int(policy.min_macos.split(".", 1)[0])
    if probe.macos_major < minimum:
        raise CandidateRefused("host_macos", str(probe.macos_major))


def verify_event(event_name: str | None) -> None:
    """Allow local and controlled dispatches, never pull-request execution."""
    if event_name not in {None, "", "workflow_dispatch"}:
        raise CandidateRefused("untrusted_event", event_name or "missing")
