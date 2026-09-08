"""Verify release-bound outer application resources before candidate sealing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ontologylab.release_policy_types import JsonValue
from ontologylab.release_snapshot import SnapshotManifest

from .candidate_tree import canonical_sha, sha256_file
from .candidate_types import CandidateRefused

_SOURCE_PATH: Final = "ontologylab/storage-compatibility.json"
_PAYLOAD_PATH: Final = "Contents/Resources/storage-compatibility.json"
_SCHEMA: Final = "ontologylab.storage-compatibility.v1"
_DEPLOYMENT_EXECUTABLE: Final = "Contents/MacOS/ontologylab-internal-deploy"
_DEPLOYMENT_MANIFEST: Final = "Contents/Resources/internal-deployment.json"
_NATIVE_INVENTORY: Final = "Contents/Resources/native-inventory.json"
_RUNTIME_MATRIX: Final = (
    "Contents/Resources/runtime/_internal/ontologylab/storage-compatibility.json"
)
_SBOM: Final = "Contents/Resources/runtime/sbom.json"


class StorageResource(TypedDict):
    source_path: str
    source_sha256: str
    payload_path: str
    payload_sha256: str
    bytes: int
    schema: str
    release_version: str
    current_storage_version: int


class InternalDeploymentResource(TypedDict):
    executable_path: str
    executable_sha256: str
    executable_bytes: int
    architecture: str
    version: str
    build_manifest_path: str
    build_manifest_sha256: str
    native_inventory_path: str
    sbom_path: str
    sbom_sha256: str
    license_inventory_sha256: str
    preflight_matrix_path: str
    preflight_matrix_sha256: str


def verify_internal_deployment_resource(
    payload: Path,
    release_version: str,
    license_inventory: dict[str, JsonValue],
) -> InternalDeploymentResource:
    """Bind the clean-Mac executable to native, version, preflight, and legal inputs."""
    executable = payload / _DEPLOYMENT_EXECUTABLE
    if executable.is_symlink() or not executable.is_file():
        raise CandidateRefused("internal_deployment_missing", _DEPLOYMENT_EXECUTABLE)
    manifest_path = payload / _DEPLOYMENT_MANIFEST
    native_path = payload / _NATIVE_INVENTORY
    sbom = payload / _SBOM
    matrix = payload / _RUNTIME_MATRIX
    for path, member in (
        (manifest_path, "manifest"),
        (native_path, "native_inventory"),
        (sbom, "sbom"),
        (matrix, "preflight_matrix"),
    ):
        if path.is_symlink() or not path.is_file():
            raise CandidateRefused(f"internal_deployment_{member}", str(path))
    try:
        manifest: JsonValue = json.loads(manifest_path.read_text(encoding="utf-8"))
        native: JsonValue = json.loads(native_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CandidateRefused("internal_deployment_manifest", "malformed") from None
    if not isinstance(manifest, dict) or set(manifest) != {
        "architecture",
        "executable_path",
        "executable_sha256",
        "schema",
        "version",
    }:
        raise CandidateRefused("internal_deployment_manifest", "shape")
    executable_sha256 = sha256_file(executable)
    if (
        manifest.get("schema") != "ontologylab.internal-deployment-build.v1"
        or manifest.get("architecture") != "arm64"
        or manifest.get("executable_path") != _DEPLOYMENT_EXECUTABLE
        or manifest.get("executable_sha256") != executable_sha256
    ):
        raise CandidateRefused("internal_deployment_identity", _DEPLOYMENT_EXECUTABLE)
    if manifest.get("version") != release_version:
        raise CandidateRefused(
            "internal_deployment_version", str(manifest.get("version"))
        )
    if not isinstance(native, dict) or native.get("architecture") != "arm64":
        raise CandidateRefused("internal_deployment_architecture", "inventory")
    files = native.get("files")
    matches = (
        [
            item
            for item in files
            if isinstance(item, dict) and item.get("path") == _DEPLOYMENT_EXECUTABLE
        ]
        if isinstance(files, list)
        else []
    )
    if len(matches) != 1 or matches[0].get("architecture") != "arm64":
        raise CandidateRefused(
            "internal_deployment_architecture", _DEPLOYMENT_EXECUTABLE
        )
    matrix_sha256 = sha256_file(matrix)
    outer_matrix = payload / _PAYLOAD_PATH
    if matrix_sha256 != sha256_file(outer_matrix):
        raise CandidateRefused("internal_deployment_preflight_matrix", _RUNTIME_MATRIX)
    return {
        "executable_path": _DEPLOYMENT_EXECUTABLE,
        "executable_sha256": executable_sha256,
        "executable_bytes": executable.stat().st_size,
        "architecture": "arm64",
        "version": release_version,
        "build_manifest_path": _DEPLOYMENT_MANIFEST,
        "build_manifest_sha256": sha256_file(manifest_path),
        "native_inventory_path": _NATIVE_INVENTORY,
        "sbom_path": _SBOM,
        "sbom_sha256": sha256_file(sbom),
        "license_inventory_sha256": canonical_sha(license_inventory),
        "preflight_matrix_path": _RUNTIME_MATRIX,
        "preflight_matrix_sha256": matrix_sha256,
    }


def verify_storage_matrix_resource(
    payload: Path, manifest: SnapshotManifest, release_version: str
) -> StorageResource:
    """Bind the exact outer matrix to source manifest bytes and release version."""
    entries = [entry for entry in manifest.files if entry.path == _SOURCE_PATH]
    if len(entries) != 1:
        raise CandidateRefused("storage_matrix_source", _SOURCE_PATH)
    source = entries[0]
    target = payload / _PAYLOAD_PATH
    if target.is_symlink() or not target.is_file():
        raise CandidateRefused("storage_matrix_missing", _PAYLOAD_PATH)
    try:
        raw: JsonValue = json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CandidateRefused("storage_matrix_malformed", _PAYLOAD_PATH) from None
    if not isinstance(raw, dict):
        raise CandidateRefused("storage_matrix_malformed", _PAYLOAD_PATH)
    schema = raw.get("schema")
    version = raw.get("release_version")
    current = raw.get("current_storage_version")
    if not isinstance(schema, str) or schema != _SCHEMA:
        raise CandidateRefused("storage_matrix_schema", str(schema))
    if not isinstance(version, str) or version != release_version:
        raise CandidateRefused("storage_matrix_version", str(version))
    if type(current) is not int or current < 0:
        raise CandidateRefused("storage_matrix_version", str(current))
    payload_sha256 = sha256_file(target)
    if target.stat().st_size != source.bytes or payload_sha256 != source.sha256:
        raise CandidateRefused("storage_matrix_hash", _PAYLOAD_PATH)
    return {
        "source_path": _SOURCE_PATH,
        "source_sha256": source.sha256,
        "payload_path": _PAYLOAD_PATH,
        "payload_sha256": payload_sha256,
        "bytes": source.bytes,
        "schema": schema,
        "release_version": version,
        "current_storage_version": current,
    }
