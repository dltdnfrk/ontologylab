"""Typed values shared by Task 11 candidate build boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict


@dataclass(frozen=True, slots=True)
class CandidateRefused(Exception):
    """Stable machine-readable candidate refusal."""

    member: str
    detail: str

    def __str__(self) -> str:
        return f"candidate_build_refused member={self.member} detail={self.detail}"


@dataclass(frozen=True, slots=True)
class HostProbe:
    """Controlled host facts used by the platform gate."""

    architecture: str
    macos_major: int
    description: str


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Task 1 identity and exact authority bytes consumed by one build."""

    version: str
    snapshot_sha256: str
    manifest_sha256: str
    uv_lock_sha256: str
    policy_sha256: str
    manifest_bytes: bytes
    uv_lock_bytes: bytes
    policy_bytes: bytes
    version_source_bytes: bytes


@dataclass(frozen=True, slots=True)
class BuildMetadata:
    """Immutable host, git, toolchain, and orchestration identities."""

    head: str
    head_ref: str
    status_diff_sha256: str
    toolchain_sha256: str
    build_inputs_sha256: str
    overlay_manifest_sha256: str = ""


class TreeEntry(TypedDict):
    path: str
    kind: Literal["file", "directory"]
    bytes: int
    mode: str
    sha256: str
