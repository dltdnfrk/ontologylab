"""Typed contracts for controlled internal macOS deployment operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


class CredentialSource(BaseModel):
    """Only the non-secret Keychain locator needed during explicit deletion."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    keychain_account: str = ""


class CredentialRegistry(BaseModel):
    """Narrow parser for the canonical source registry boundary."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    sources: tuple[CredentialSource, ...] = ()


class ActivationJournal(BaseModel):
    """Crash-recovery record written before one atomic app exchange."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ontologylab.atomic-activation.v1"] = Field(alias="schema")
    stage_name: str = Field(
        pattern=r"^\.[A-Za-z0-9][A-Za-z0-9._-]*\.install-[0-9a-f]{32}$"
    )
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class InstalledDeploymentIdentity(BaseModel):
    """Validated identity embedded beside the standalone deployment executable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ontologylab.internal-deployment-build.v1"] = Field(
        alias="schema"
    )
    architecture: Literal["arm64"]
    executable_path: Literal["Contents/MacOS/ontologylab-internal-deploy"]
    executable_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class JournalPathIdentity(BaseModel):
    """Source identity captured before the first retained rename."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_path: str
    retained_path: str
    inode: int
    device: int
    mode: int
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Task12ReleaseAuthority(BaseModel):
    """External final-release identity supplied through a trusted channel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ontologylab.task12-release-authority.v1"] = Field(
        alias="schema"
    )
    final_dmg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    zip_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    install_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_app_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment_executable_relative_path: Literal[
        "Contents/MacOS/ontologylab-internal-deploy"
    ]
    deployment_executable_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    architecture: Literal["arm64"]
    tree_hash_schema: Literal[
        "ontologylab.internal-deployment-tree-sha256.v1"
    ]


class PreparedRemovalJournal(BaseModel):
    """Authoritative initial state for one retained-removal transaction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ontologylab.retained-removal-journal.v3"] = Field(
        alias="schema"
    )
    event: Literal["prepared"]
    event_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    timestamp_utc: str
    release_authority: Task12ReleaseAuthority
    release_authority_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact: InstalledDeploymentIdentity
    app: JournalPathIdentity
    runtime: JournalPathIdentity


class RemovalJournalProgress(BaseModel):
    """Hash-chained durable retained-removal transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ontologylab.retained-removal-journal.v3"] = Field(
        alias="schema"
    )
    event: Literal[
        "app_retained", "forward_recovery_required", "runtime_retained"
    ]
    event_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    previous_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CompletedRemovalJournal(BaseModel):
    """Terminal transition binding the finalized machine receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ontologylab.retained-removal-journal.v3"] = Field(
        alias="schema"
    )
    event: Literal["completed"]
    event_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    previous_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prepared_anchor: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_authority_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


RemovalJournalRecord: TypeAlias = (
    PreparedRemovalJournal | RemovalJournalProgress | CompletedRemovalJournal
)


class RetainedPathReceipt(BaseModel):
    """Identity proof for one renamed tree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_path: str
    source_inode: int
    source_device: int
    source_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_mode: int
    retained_path: str
    retained_inode: int
    retained_device: int
    retained_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retained_mode: int
    active_path_absent: Literal[True]


class RetainedRemovalReceipt(BaseModel):
    """Machine receipt for one complete retained uninstall."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ontologylab.retained-removal-receipt.v2"] = Field(
        alias="schema"
    )
    event: Literal["retained_uninstall_completed"]
    event_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    timestamp_utc: str
    artifact: InstalledDeploymentIdentity
    app_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prepared_anchor: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_authority_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paths: tuple[RetainedPathReceipt, RetainedPathReceipt]


class ArtifactReceipt(BaseModel):
    """Validated trust-boundary receipt for one exact application tree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ontologylab.internal-artifact-receipt.v1"] = Field(
        alias="schema"
    )
    artifact_name: Literal["OntologyLab.app"]
    app_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class DeploymentRefused(Exception):
    reason: str

    def __str__(self) -> str:
        return f"internal deployment refused: {self.reason}"


@dataclass(frozen=True, slots=True)
class PlatformInfo:
    architecture: str
    macos_major: int


@dataclass(frozen=True, slots=True)
class InstallRequest:
    app: Path
    receipt: Path
    receipt_sha256: str
    destination: Path
    home: Path
    acknowledge_unnotarized: bool


@dataclass(frozen=True, slots=True)
class InstallResult:
    operation: Literal["installed", "updated"]
    app_tree_sha256: str


@dataclass(frozen=True, slots=True)
class UninstallRequest:
    app: Path
    home: Path
    remove_data: bool
    data_confirmation: str | None
    remove_credentials: bool
    credentials_confirmation: str | None
    credential_accounts: tuple[str, ...] = ()
    retain_removals_under: Path | None = None
    prepared_anchor: str | None = None


@dataclass(frozen=True, slots=True)
class PrepareRetainedUninstallRequest:
    app: Path
    home: Path
    retained_root: Path
    release_authority: Path
    release_authority_sha256: str
    release_dmg: Path
    release_zip: Path
    install_receipt: Path
    running_executable: Path


@dataclass(frozen=True, slots=True)
class PreparedRetainedUninstall:
    journal: Path
    prepared: PreparedRemovalJournal
    release_authority_sha256: str
    prepared_anchor: str


@dataclass(frozen=True, slots=True)
class ApplyRetainedUninstallRequest:
    app: Path
    home: Path
    retained_root: Path
    prepared_anchor: str | None
    running_executable: Path


@dataclass(frozen=True, slots=True)
class SupportRequest:
    home: Path
    app: Path
    output: Path
