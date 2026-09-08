"""Final Task12 sidecar authority generation after immutable DMG creation."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from scripts.internal_deployment_fs import sha256_file, tree_sha256
from scripts.internal_deployment_removal_receipt import load_identity
from scripts.internal_deployment_types import (
    ArtifactReceipt,
    DeploymentRefused,
    Task12ReleaseAuthority,
)


@dataclass(frozen=True, slots=True)
class Task12AuthorityRequest:
    final_dmg: Path
    final_zip: Path
    install_receipt: Path
    final_app: Path
    output: Path


@dataclass(frozen=True, slots=True)
class GeneratedTask12Authority:
    path: Path
    sha256: str


def generate_task12_release_authority(
    request: Task12AuthorityRequest,
) -> GeneratedTask12Authority:
    """Write the non-circular external sidecar after all release bytes are final."""
    try:
        install_receipt = ArtifactReceipt.model_validate_json(
            request.install_receipt.read_bytes(), strict=True
        )
    except (OSError, ValidationError) as exc:
        raise DeploymentRefused("install_receipt_malformed") from exc
    app_sha256 = tree_sha256(request.final_app)
    if install_receipt.app_tree_sha256 != app_sha256:
        raise DeploymentRefused("install_receipt_app_mismatch")
    identity = load_identity(request.final_app)
    authority = Task12ReleaseAuthority(
        schema="ontologylab.task12-release-authority.v1",
        final_dmg_sha256=sha256_file(request.final_dmg),
        zip_sha256=sha256_file(request.final_zip),
        install_receipt_sha256=sha256_file(request.install_receipt),
        final_app_tree_sha256=app_sha256,
        deployment_executable_relative_path=identity.executable_path,
        deployment_executable_sha256=identity.executable_sha256,
        version=identity.version,
        architecture=identity.architecture,
        tree_hash_schema="ontologylab.internal-deployment-tree-sha256.v1",
    )
    payload = authority.model_dump_json(by_alias=True).encode() + b"\n"
    try:
        descriptor = os.open(
            request.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(
            request.output.parent, os.O_RDONLY | os.O_DIRECTORY
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise DeploymentRefused("release_authority_write") from exc
    return GeneratedTask12Authority(
        request.output, hashlib.sha256(payload).hexdigest()
    )
