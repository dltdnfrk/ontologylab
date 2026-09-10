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

from ontologylab.legacy_retirement import (
    LEGACY_LAUNCHD_LABEL,
    LegacyRetirementError,
    LocalRetirementSystem,
    RetirementPaths,
    RetirementRequest,
    RetirementSystem,
    retire_legacy_ownership,
)
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
# Mirrors ontologylab.keychain: new items live under the v2 service, but a
# never-migrated account still holds its secret under the pre-helper name.
_KEYCHAIN_SERVICE: Final = "ontologylab.v2"
_LEGACY_KEYCHAIN_SERVICE: Final = "ontologylab"
_SECURITY_BIN: Final = "/usr/bin/security"


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


def _retirement_system() -> RetirementSystem:
    """Seam so tests never reach the real launchctl on the developer's machine.

    `LEGACY_LAUNCHD_LABEL` is a live service on machines that ran the old
    launcher, so a test that constructs the production adapter would boot out
    a real server.
    """
    return LocalRetirementSystem()


def _retire_legacy(home: Path) -> None:
    """Boot out the pre-supervisor launchd ownership as the app is removed.

    The old launcher installed `at.ontologylab.server` as a user LaunchAgent.
    Uninstalling the app without retiring it leaves a service that keeps
    respawning a binary that is no longer there, which is how a "clean"
    uninstall turns into a broken machine. Only the exact label and the exact
    plist are addressed; `absent` is the normal outcome on a machine that never
    ran the old launcher.
    """
    paths = RetirementPaths(
        launch_agent=home / "Library/LaunchAgents" / f"{LEGACY_LAUNCHD_LABEL}.plist",
        source_runtime_files=(),
    )
    try:
        retire_legacy_ownership(
            RetirementRequest(paths=paths, uid=os.getuid(), source_pid=None),
            _retirement_system(),
        )
    except LegacyRetirementError as exc:
        raise DeploymentRefused(f"legacy_retirement_{exc.kind}") from exc


def _delete_legacy_credential(account: str) -> None:
    """Remove the pre-helper item the bundled helper cannot address.

    Deliberately a copy of `ontologylab.keychain._delete_legacy` rather than an
    import, because scripts/ stays self-contained. The helper inside the bundle
    being removed only knows the v2 service, so without this a confirmed
    REMOVE-ONTOLOGYLAB-CREDENTIALS left the legacy secret live in the Keychain.
    `security` exit 44 means "not found", which is the success case here, so
    neither exit is treated as a failure.
    """
    if shutil.which(_SECURITY_BIN) is None:
        return
    try:
        subprocess.run(
            [
                _SECURITY_BIN,
                "delete-generic-password",
                "-s",
                _LEGACY_KEYCHAIN_SERVICE,
                "-a",
                account,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return


def _delete_credentials(app: Path, accounts: tuple[str, ...]) -> None:
    helper = app / "Contents/Resources/keychain-helper"
    if accounts and not os.access(helper, os.X_OK):
        raise DeploymentRefused("credential_helper_missing")
    for account in accounts:
        payload = json.dumps(
            {"operation": "delete", "service": _KEYCHAIN_SERVICE, "account": account}
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
        # The helper only knows the v2 service. An account that was never
        # migrated still has its secret under the pre-helper `ontologylab`
        # service, and leaving it there means a user who typed
        # REMOVE-ONTOLOGYLAB-CREDENTIALS keeps a live secret after the app is
        # gone. Measured on the exact signed app before this line existed.
        _delete_legacy_credential(account)


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
    # Before the bundle goes: a legacy LaunchAgent left loaded would keep
    # respawning a binary this call is about to delete.
    _retire_legacy(request.home)
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
