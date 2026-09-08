"""Executable parser boundary for controlled internal deployment operations."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import assert_never

from scripts.internal_deployment import (
    apply_retained_uninstall,
    build_support_bundle,
    install_app,
    prepare_retained_uninstall,
    uninstall_app,
)
from scripts.internal_deployment_types import (
    ApplyRetainedUninstallRequest,
    DeploymentRefused,
    InstallRequest,
    PlatformInfo,
    PrepareRetainedUninstallRequest,
    SupportRequest,
    UninstallRequest,
)


def _absolute_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("path must be absolute")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ontologylab-internal-deployment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install")
    install.add_argument("--app", required=True, type=Path)
    install.add_argument("--receipt", required=True, type=Path)
    install.add_argument("--receipt-sha256", required=True)
    install.add_argument(
        "--destination", type=Path, default=Path("/Applications/OntologyLab.app")
    )
    install.add_argument("--home", type=Path, default=Path.home())
    install.add_argument("--acknowledge-unnotarized", action="store_true")
    uninstall = subparsers.add_parser("uninstall")
    uninstall.add_argument("--app", type=Path)
    uninstall.add_argument("--home", type=Path)
    uninstall.add_argument("--retain-removals-under", type=_absolute_path)
    uninstall.add_argument("--remove-data", action="store_true")
    uninstall.add_argument("--confirm-remove-data")
    uninstall.add_argument("--remove-credentials", action="store_true")
    uninstall.add_argument("--confirm-remove-credentials")
    uninstall.add_argument("--credential-account", action="append", default=[])
    prepare = subparsers.add_parser("prepare-retained-uninstall")
    prepare.add_argument("--app", required=True, type=_absolute_path)
    prepare.add_argument("--home", required=True, type=_absolute_path)
    prepare.add_argument(
        "--retain-removals-under", required=True, type=_absolute_path
    )
    prepare.add_argument("--release-authority", required=True, type=_absolute_path)
    prepare.add_argument("--release-authority-sha256", required=True)
    prepare.add_argument("--release-dmg", required=True, type=_absolute_path)
    prepare.add_argument("--release-zip", required=True, type=_absolute_path)
    prepare.add_argument("--install-receipt", required=True, type=_absolute_path)
    apply = subparsers.add_parser("apply-retained-uninstall")
    apply.add_argument("--app", required=True, type=_absolute_path)
    apply.add_argument("--home", required=True, type=_absolute_path)
    apply.add_argument("--retain-removals-under", required=True, type=_absolute_path)
    apply.add_argument("--prepared-anchor")
    support = subparsers.add_parser("support")
    support.add_argument(
        "--app", type=Path, default=Path("/Applications/OntologyLab.app")
    )
    support.add_argument("--home", type=Path, default=Path.home())
    support.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        match args.command:
            case "install":
                version = platform.mac_ver()[0].split(".", 1)[0]
                if not version.isdigit():
                    raise DeploymentRefused("macos_version")
                result = install_app(
                    InstallRequest(
                        args.app,
                        args.receipt,
                        args.receipt_sha256,
                        args.destination,
                        args.home,
                        args.acknowledge_unnotarized,
                    ),
                    PlatformInfo(platform.machine(), int(version)),
                )
                print(
                    json.dumps(
                        {
                            "operation": result.operation,
                            "app_tree_sha256": result.app_tree_sha256,
                        },
                        sort_keys=True,
                    )
                )
            case "uninstall":
                if args.retain_removals_under is not None and args.app is None:
                    raise DeploymentRefused("retained_removal_app_required")
                if args.retain_removals_under is not None and args.home is None:
                    raise DeploymentRefused("retained_removal_home_required")
                app = args.app or Path("/Applications/OntologyLab.app")
                home = args.home or Path.home()
                receipt = uninstall_app(
                    UninstallRequest(
                        app,
                        home,
                        args.remove_data,
                        args.confirm_remove_data,
                        args.remove_credentials,
                        args.confirm_remove_credentials,
                        tuple(args.credential_account),
                        args.retain_removals_under,
                    )
                )
                payload = {"operation": "uninstalled"}
                if receipt is not None:
                    payload["retained_removal_receipt"] = str(receipt)
                print(json.dumps(payload, sort_keys=True))
            case "apply-retained-uninstall":
                receipt = apply_retained_uninstall(
                    ApplyRetainedUninstallRequest(
                        app=args.app,
                        home=args.home,
                        retained_root=args.retain_removals_under,
                        prepared_anchor=args.prepared_anchor,
                        running_executable=Path(sys.executable),
                    )
                )
                print(
                    json.dumps(
                        {
                            "operation": "retained_uninstall_completed",
                            "retained_removal_receipt": str(receipt),
                        },
                        sort_keys=True,
                    )
                )
            case "prepare-retained-uninstall":
                prepared = prepare_retained_uninstall(
                    PrepareRetainedUninstallRequest(
                        app=args.app,
                        home=args.home,
                        retained_root=args.retain_removals_under,
                        release_authority=args.release_authority,
                        release_authority_sha256=args.release_authority_sha256,
                        release_dmg=args.release_dmg,
                        release_zip=args.release_zip,
                        install_receipt=args.install_receipt,
                        running_executable=Path(sys.executable),
                    )
                )
                print(
                    json.dumps(
                        {
                            "journal": str(prepared.journal),
                            "prepared": prepared.prepared.model_dump(
                                by_alias=True, mode="json"
                            ),
                            "prepared_anchor": prepared.prepared_anchor,
                            "release_authority_sha256": (
                                prepared.release_authority_sha256
                            ),
                        },
                        sort_keys=True,
                    )
                )
            case "support":
                output = build_support_bundle(
                    SupportRequest(args.home, args.app, args.output)
                )
                print(
                    json.dumps(
                        {"operation": "support", "path": str(output)}, sort_keys=True
                    )
                )
            case unreachable:
                assert_never(unreachable)
    except DeploymentRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
