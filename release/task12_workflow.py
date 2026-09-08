"""Task12 packaging workflow terminal authority publication entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from release.task12_finalize import (
    Task12FinalizeRequest,
    finalize_task12_release,
)
from scripts.internal_deployment_removal_receipt import load_identity
from scripts.internal_deployment_types import DeploymentRefused


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ontologylab-task12-workflow")
    parser.add_argument("--final-dmg", required=True, type=Path)
    parser.add_argument("--final-zip", required=True, type=Path)
    parser.add_argument("--final-app", required=True, type=Path)
    parser.add_argument("--install-receipt", required=True, type=Path)
    parser.add_argument("--external-receipts-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run authority finalization as the terminal Task12 packaging operation."""
    args = _parser().parse_args(argv)
    try:
        for path in (args.final_dmg, args.final_zip, args.install_receipt):
            resolved = path.resolve(strict=True)
            if not resolved.is_file():
                raise DeploymentRefused("task12_final_path")
        final_app = args.final_app.resolve(strict=True)
        if not final_app.is_dir():
            raise DeploymentRefused("task12_final_path")
        load_identity(final_app)
    except OSError as exc:
        print(str(DeploymentRefused("task12_final_path")), file=sys.stderr)
        return 2
    except DeploymentRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        result = finalize_task12_release(
            Task12FinalizeRequest(
                args.final_dmg,
                args.final_zip,
                args.final_app,
                args.install_receipt,
                args.external_receipts_dir,
            )
        )
    except DeploymentRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "authority": str(result.authority),
                "authority_digest": str(result.authority_digest),
                "authority_sha256": result.authority_sha256,
                "final_hashes": {
                    "app_tree_sha256": result.final_hashes.app_tree_sha256,
                    "dmg_sha256": result.final_hashes.dmg_sha256,
                    "install_receipt_sha256": (
                        result.final_hashes.install_receipt_sha256
                    ),
                    "installer_sha256": result.final_hashes.installer_sha256,
                    "zip_sha256": result.final_hashes.zip_sha256,
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
