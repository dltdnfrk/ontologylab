"""Seal exact frozen payload and candidate evidence under one Task 11 receipt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ontologylab.release_policy_types import JsonValue

from .candidate_licenses import verify_license_completeness
from .candidate_resources import (
    verify_internal_deployment_resource,
    verify_storage_matrix_resource,
)
from .candidate_source import (
    retain_source,
    verify_retained_snapshot,
)
from .candidate_tree import (
    canonical_sha,
    freeze_tree,
    normalized_tree_manifest,
    sha256_file,
    tree_manifest,
    write_json,
)
from .candidate_types import (
    BuildMetadata,
    CandidateRefused,
    SourceIdentity,
    TreeEntry,
)

_SCHEMA: Final = "ontologylab.macos-candidate.receipt.v1"
_STATIC_SUFFIXES: Final = (".css", ".html", ".js", ".json", ".woff2")
_TREE_SCHEMA: Final = "ontologylab.macos-candidate.payload-tree.v1"
_TREE_SCOPE: Final = (
    "payload/OntologyLab.app only; excludes receipt, inventories, logs, metadata, "
    "and retained source authority"
)


def _variable_paths(payload: Path) -> frozenset[str]:
    native = payload / "Contents" / "Resources" / "native-inventory.json"
    if not native.is_file():
        paths = frozenset()
    else:
        parsed = json.loads(native.read_text(encoding="utf-8"))
        paths = frozenset(item["path"] for item in parsed["files"])
    return paths | frozenset(
        {
            "Contents/Resources/keychain-helper.requirement",
            "Contents/Resources/runtime/runtime-manifest.json",
            "Contents/Resources/runtime/runtime-manifest.sha256",
        }
    )


def _copy_runtime_inventories(payload: Path, inventories: Path) -> None:
    resources = payload / "Contents" / "Resources"
    for name in ("native-inventory.json",):
        source = resources / name
        if source.is_file():
            (inventories / name).write_bytes(source.read_bytes())
    sbom = resources / "runtime" / "sbom.json"
    if sbom.is_file():
        (inventories / "sbom.json").write_bytes(sbom.read_bytes())


def _write_payload_inventories(
    payload: Path, inventories: Path, entries: list[TreeEntry]
) -> dict[str, str | list[TreeEntry]]:
    raw: dict[str, str | list[TreeEntry]] = {
        "schema": _TREE_SCHEMA,
        "scope": _TREE_SCOPE,
        "entries": entries,
    }
    write_json(inventories / "payload-tree.json", raw)
    write_json(
        inventories / "normalized-unsigned-manifest.json",
        normalized_tree_manifest(payload, _variable_paths(payload)),
    )
    write_json(
        inventories / "static-assets.json",
        {
            "schema": "ontologylab.macos-candidate.static.v1",
            "files": [
                item
                for item in entries
                if item["kind"] == "file" and item["path"].endswith(_STATIC_SUFFIXES)
            ],
        },
    )
    return raw


def seal_candidate(
    candidate_root: Path,
    source: SourceIdentity,
    metadata: BuildMetadata,
) -> Path:
    """Finalize modes, hash delivered payload, retain authority, receipt, and freeze."""
    payload = candidate_root / "payload" / "OntologyLab.app"
    if not payload.is_dir():
        raise CandidateRefused("payload", "OntologyLab.app")
    inventories = candidate_root / "inventories"
    inventories.mkdir(parents=True, exist_ok=True)
    runtime = payload / "Contents" / "Resources" / "runtime"
    retain_source(candidate_root, source)
    retained_manifest = verify_retained_snapshot(candidate_root, source)
    storage_resource = verify_storage_matrix_resource(
        payload, retained_manifest, source.version
    )
    resource_payload: dict[str, JsonValue] = {
        "source_path": storage_resource["source_path"],
        "source_sha256": storage_resource["source_sha256"],
        "payload_path": storage_resource["payload_path"],
        "payload_sha256": storage_resource["payload_sha256"],
        "bytes": storage_resource["bytes"],
        "schema": storage_resource["schema"],
        "release_version": storage_resource["release_version"],
        "current_storage_version": storage_resource["current_storage_version"],
    }
    license_inventory = verify_license_completeness(runtime)
    deployment_resource = verify_internal_deployment_resource(
        payload, source.version, license_inventory
    )
    deployment_payload: dict[str, JsonValue] = {
        "executable_path": deployment_resource["executable_path"],
        "executable_sha256": deployment_resource["executable_sha256"],
        "executable_bytes": deployment_resource["executable_bytes"],
        "architecture": deployment_resource["architecture"],
        "version": deployment_resource["version"],
        "build_manifest_path": deployment_resource["build_manifest_path"],
        "build_manifest_sha256": deployment_resource["build_manifest_sha256"],
        "native_inventory_path": deployment_resource["native_inventory_path"],
        "sbom_path": deployment_resource["sbom_path"],
        "sbom_sha256": deployment_resource["sbom_sha256"],
        "license_inventory_sha256": deployment_resource["license_inventory_sha256"],
        "preflight_matrix_path": deployment_resource["preflight_matrix_path"],
        "preflight_matrix_sha256": deployment_resource["preflight_matrix_sha256"],
    }

    freeze_tree(payload)
    final_files = tree_manifest(payload)
    raw_payload = _write_payload_inventories(payload, inventories, final_files)
    write_json(inventories / "licenses.json", license_inventory)
    write_json(
        inventories / "resources.json",
        {
            "schema": "ontologylab.macos-candidate.resources.v1",
            "storage_compatibility": resource_payload,
            "internal_deployment": deployment_payload,
        },
    )
    _copy_runtime_inventories(payload, inventories)
    inventory_hashes: dict[str, JsonValue] = {
        path.name: sha256_file(path)
        for path in sorted(inventories.iterdir())
        if path.is_file()
    }
    receipt: dict[str, JsonValue] = {
        "schema": _SCHEMA,
        "version": source.version,
        "source": {
            "snapshot_sha256": source.snapshot_sha256,
            "manifest_sha256": source.manifest_sha256,
            "retained_manifest": "receipts/source/release/source-snapshot.json",
            "uv_lock_sha256": source.uv_lock_sha256,
            "policy_sha256": source.policy_sha256,
        },
        "git": {
            "head": metadata.head,
            "head_ref": metadata.head_ref,
            "status_diff_sha256": metadata.status_diff_sha256,
        },
        "toolchain_sha256": metadata.toolchain_sha256,
        "build_inputs_sha256": metadata.build_inputs_sha256,
        "build_overlay_manifest_sha256": metadata.overlay_manifest_sha256,
        "payload_tree_sha256": canonical_sha(raw_payload),
        "payload_tree_scope": _TREE_SCOPE,
        "inventories": inventory_hashes,
        "resources": {
            "storage_compatibility": resource_payload,
            "internal_deployment": deployment_payload,
        },
        "signing": "unsigned-or-ad-hoc",
        "frozen_after_receipt": True,
    }
    receipt_path = candidate_root / "candidate-receipt.json"
    write_json(receipt_path, receipt)
    freeze_tree(candidate_root)
    if tree_manifest(payload) != final_files:
        raise CandidateRefused("final_payload_tree_drift", "mode-or-content")
    return receipt_path
