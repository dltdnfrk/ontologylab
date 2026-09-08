"""Controlled install, uninstall, and support operations for internal builds."""

from __future__ import annotations

import fcntl
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from scripts.internal_deployment_fs import atomic_copy_app, sha256_file, tree_sha256
from scripts.internal_deployment_removal_apply import apply_retained_uninstall as _apply
from scripts.internal_deployment_removal_prepare import prepare_retained_uninstall as _prepare
from scripts.internal_deployment_types import (
    ApplyRetainedUninstallRequest,
    ArtifactReceipt,
    CredentialRegistry,
    DeploymentRefused,
    InstallRequest,
    InstallResult,
    PlatformInfo,
    PreparedRetainedUninstall,
    PrepareRetainedUninstallRequest,
    SupportRequest,
    UninstallRequest,
)

_DATA_CONFIRMATION: Final = "REMOVE-ONTOLOGYLAB-DATA"
_CREDENTIALS_CONFIRMATION: Final = "REMOVE-ONTOLOGYLAB-CREDENTIALS"


def _paths(home: Path) -> tuple[Path, Path, Path]:
    support = home / "Library/Application Support/ontologylab"
    runtime = home / "Library/Caches/ontologylab/runtime"
    logs = home / "Library/Logs/ontologylab"
    return support, runtime, logs


def _require_quiescent(home: Path) -> None:
    _support, runtime, _logs = _paths(home)
    lock = runtime / "supervisor.lock"
    if not lock.exists():
        return
    try:
        with lock.open("r+") as stream:
            try:
                fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DeploymentRefused("active_backend") from exc
    except PermissionError as exc:
        raise DeploymentRefused("runtime_lock_unreadable") from exc


def _load_receipt(path: Path, expected_sha256: str) -> ArtifactReceipt:
    if sha256_file(path) != expected_sha256:
        raise DeploymentRefused("receipt_sha256_mismatch")
    try:
        return ArtifactReceipt.model_validate_json(path.read_bytes(), strict=True)
    except (OSError, ValidationError) as exc:
        raise DeploymentRefused("receipt_malformed") from exc


def _preflight(home: Path) -> None:
    support, _runtime, _logs = _paths(home)
    command = (
        sys.executable,
        "-m",
        "ontologylab.storage_compatibility",
        "--data-dir",
        str(support / "data"),
        "--packs-dir",
        str(support / "packs"),
    )
    try:
        result = subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=15
        )
    except subprocess.TimeoutExpired as exc:
        raise DeploymentRefused("compatibility_preflight_timeout") from exc
    if result.returncode != 0:
        raise DeploymentRefused("compatibility_preflight")


def install_app(request: InstallRequest, platform_info: PlatformInfo) -> InstallResult:
    """Validate every trust and compatibility gate before atomic app mutation."""
    if not request.acknowledge_unnotarized:
        raise DeploymentRefused("acknowledgement_required")
    if platform_info.architecture != "arm64":
        raise DeploymentRefused("architecture")
    if platform_info.macos_major < 15:
        raise DeploymentRefused("macos_version")
    receipt = _load_receipt(request.receipt, request.receipt_sha256)
    actual_hash = tree_sha256(request.app)
    if receipt.app_tree_sha256 != actual_hash:
        raise DeploymentRefused("artifact_sha256_mismatch")
    _require_quiescent(request.home)
    _preflight(request.home)
    existed = atomic_copy_app(request.app, request.destination, actual_hash)
    return InstallResult("updated" if existed else "installed", actual_hash)


def _credential_accounts(support: Path, explicit: tuple[str, ...]) -> tuple[str, ...]:
    accounts = set(explicit)
    registry = support / "data/sources.json"
    if not registry.is_file():
        return tuple(sorted(accounts))
    try:
        parsed = CredentialRegistry.model_validate_json(
            registry.read_bytes(), strict=True
        )
    except (OSError, ValidationError) as exc:
        raise DeploymentRefused("credential_registry_malformed") from exc
    accounts.update(
        source.keychain_account for source in parsed.sources if source.keychain_account
    )
    return tuple(sorted(accounts))


def _delete_credentials(app: Path, accounts: tuple[str, ...]) -> None:
    helper = app / "Contents/Resources/keychain-helper"
    if accounts and not os.access(helper, os.X_OK):
        raise DeploymentRefused("credential_helper_missing")
    for account in accounts:
        payload = json.dumps(
            {"operation": "delete", "service": "ontologylab.v2", "account": account}
        )
        try:
            result = subprocess.run(
                [str(helper)],
                input=payload,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DeploymentRefused("credential_helper_timeout") from exc
        if result.returncode != 0:
            raise DeploymentRefused("credential_delete_failed")


def apply_retained_uninstall(request: ApplyRetainedUninstallRequest) -> Path:
    """Require quiescence before authenticated forward-only mutation."""
    _require_quiescent(request.home)
    return _apply(request)


def prepare_retained_uninstall(
    request: PrepareRetainedUninstallRequest,
) -> PreparedRetainedUninstall:
    """Require quiescence before creating the pre-mutation controller anchor."""
    _require_quiescent(request.home)
    return _prepare(request)


def uninstall_app(request: UninstallRequest) -> Path | None:
    """Remove app/runtime by default; retain them only in the explicit safe mode."""
    if request.remove_data and request.data_confirmation != _DATA_CONFIRMATION:
        raise DeploymentRefused("data_confirmation_required")
    if (
        request.remove_credentials
        and request.credentials_confirmation != _CREDENTIALS_CONFIRMATION
    ):
        raise DeploymentRefused("credentials_confirmation_required")
    if request.retain_removals_under is not None and (
        request.remove_data or request.remove_credentials
    ):
        raise DeploymentRefused("retained_removal_preserves_data_and_credentials")
    _require_quiescent(request.home)
    support, runtime, _logs = _paths(request.home)
    if request.retain_removals_under is not None:
        if request.prepared_anchor is None:
            raise DeploymentRefused("retained_removal_requires_prepare")
        return _apply(
            ApplyRetainedUninstallRequest(
                request.app,
                request.home,
                request.retain_removals_under,
                request.prepared_anchor,
                Path(sys.executable),
            )
        )
    if request.remove_credentials:
        _delete_credentials(
            request.app, _credential_accounts(support, request.credential_accounts)
        )
    if request.app.exists():
        shutil.rmtree(request.app)
    if runtime.exists():
        shutil.rmtree(runtime)
    if request.remove_data and support.exists():
        shutil.rmtree(support)
    return None


def build_support_bundle(request: SupportRequest) -> Path:
    """Write a local metadata-only archive; no document, log, env, or secret bytes."""
    support, runtime, logs = _paths(request.home)
    documents = support / "data/documents"
    payload = {
        "schema": "ontologylab.internal-support.v1",
        "platform": {
            "architecture": platform.machine(),
            "macos": platform.mac_ver()[0],
        },
        "app": {"installed": request.app.is_dir()},
        "data": {
            "present": (support / "data").is_dir(),
            "database_present": (support / "data/kg.sqlite").is_file(),
            "document_count": sum(1 for item in documents.rglob("*") if item.is_file())
            if documents.is_dir()
            else 0,
            "pack_count": sum(
                1
                for item in (support / "packs").glob("*/pack.sqlite")
                if item.is_file()
            ),
        },
        "runtime": {"present": runtime.is_dir()},
        "logs": {
            "file_count": sum(1 for item in logs.rglob("*") if item.is_file())
            if logs.is_dir()
            else 0
        },
    }
    request.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        request.output, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr(
            "support.json", json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )
    return request.output


__all__ = [
    "DeploymentRefused",
    "InstallRequest",
    "PlatformInfo",
    "SupportRequest",
    "UninstallRequest",
    "build_support_bundle",
    "install_app",
    "tree_sha256",
    "uninstall_app",
]
