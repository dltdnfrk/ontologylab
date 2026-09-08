"""Controller-side synthetic authority and anchor helpers for no-delete tests."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from scripts.internal_deployment import (
    apply_retained_uninstall,
    prepare_retained_uninstall,
)
from scripts.internal_deployment_fs import tree_sha256
from scripts.internal_deployment_types import (
    ApplyRetainedUninstallRequest,
    PrepareRetainedUninstallRequest,
    UninstallRequest,
)
from tests.test_internal_deployment import _app


def installed(root: Path) -> tuple[Path, Path, Path, Path]:
    """Create an app/runtime pair whose embedded installer matches this process."""
    app = _app(root / "Applications")
    executable = app / "Contents/MacOS/ontologylab-internal-deploy"
    executable.write_bytes(Path(sys.executable).read_bytes())
    executable.chmod(0o755)
    (app / "Contents/Resources/internal-deployment.json").write_text(
        json.dumps(
            {
                "architecture": "arm64",
                "executable_path": "Contents/MacOS/ontologylab-internal-deploy",
                "executable_sha256": hashlib.sha256(
                    executable.read_bytes()
                ).hexdigest(),
                "schema": "ontologylab.internal-deployment-build.v1",
                "version": "0.1.0",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    home = root / "home"
    runtime = home / "Library/Caches/ontologylab/runtime"
    data = home / "Library/Application Support/ontologylab/data"
    runtime.mkdir(parents=True)
    data.mkdir(parents=True)
    (runtime / "state").write_text("runtime", encoding="utf-8")
    (data / "kg.sqlite").write_text("canonical", encoding="utf-8")
    retained = root / "retained-removals"
    retained.mkdir(mode=0o700)
    return app, home, runtime, retained


def controller_anchor(app: Path, home: Path, retained: Path) -> str:
    """Capture or load the controller-held value outside retained root."""
    authority_dir = retained.parent / "Task12-authority"
    authority = authority_dir / "OntologyLab.task12-release-authority.json"
    controller_path = retained.parent / "controller-prepared-anchor.txt"
    if not controller_path.is_file():
        identity = json.loads(
            (app / "Contents/Resources/internal-deployment.json").read_text(
                encoding="utf-8"
            )
        )
        release_dmg = retained.parent / "OntologyLab.dmg"
        release_dmg.write_bytes(b"final-dmg")
        release_zip = retained.parent / "OntologyLab.zip"
        release_zip.write_bytes(b"final-zip")
        install_receipt = retained.parent / "OntologyLab.receipt.json"
        install_receipt.write_text(
            json.dumps(
                {
                    "app_tree_sha256": tree_sha256(app),
                    "artifact_name": "OntologyLab.app",
                    "schema": "ontologylab.internal-artifact-receipt.v1",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        authority_dir.mkdir()
        authority.write_text(
            json.dumps(
                {
                    "architecture": identity["architecture"],
                    "deployment_executable_relative_path": identity["executable_path"],
                    "deployment_executable_sha256": identity["executable_sha256"],
                    "final_app_tree_sha256": tree_sha256(app),
                    "final_dmg_sha256": hashlib.sha256(
                        release_dmg.read_bytes()
                    ).hexdigest(),
                    "zip_sha256": hashlib.sha256(
                        release_zip.read_bytes()
                    ).hexdigest(),
                    "install_receipt_sha256": hashlib.sha256(
                        install_receipt.read_bytes()
                    ).hexdigest(),
                    "schema": "ontologylab.task12-release-authority.v1",
                    "tree_hash_schema": "ontologylab.internal-deployment-tree-sha256.v1",
                    "version": identity["version"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        authority_sha256 = hashlib.sha256(authority.read_bytes()).hexdigest()
        (authority_dir / "OntologyLab.task12-release-authority.sha256").write_text(
            f"{authority_sha256}\n", encoding="ascii"
        )
        (authority_dir / "OntologyLab.task12-release-authority.complete").write_bytes(
            b"ontologylab.task12-release-authority.complete.v1\n"
        )
        prepared = prepare_retained_uninstall(
            PrepareRetainedUninstallRequest(
                app,
                home,
                retained,
                authority,
                authority_sha256,
                release_dmg,
                release_zip,
                install_receipt,
                Path(sys.executable),
            )
        )
        controller_path.write_text(prepared.prepared_anchor, encoding="ascii")
    return controller_path.read_text(encoding="ascii")


def uninstall_request(app: Path, home: Path, retained: Path) -> UninstallRequest:
    """Build the internal apply request with controller-held state."""
    return UninstallRequest(
        app,
        home,
        False,
        None,
        False,
        None,
        retain_removals_under=retained,
        prepared_anchor=controller_anchor(app, home, retained),
    )


def anchored_uninstall(app: Path, home: Path, retained: Path) -> Path:
    """Apply or replay using independently retained controller state."""
    return apply_retained_uninstall(
        ApplyRetainedUninstallRequest(
            app,
            home,
            retained,
            controller_anchor(app, home, retained),
            Path(sys.executable),
        )
    )
