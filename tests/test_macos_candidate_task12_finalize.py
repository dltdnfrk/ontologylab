from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.internal_deployment_fs import tree_sha256
from tests.test_internal_deployment_prepared_anchor import _prepared_fixture


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "missing",
    ("dmg", "zip", "app", "install_receipt", "installer"),
)
def test_task12_workflow_typed_refuses_each_missing_final(
    tmp_path: Path, missing: str
) -> None:
    # Given final paths where exactly one required artifact or installer is absent.
    fixture = _prepared_fixture(tmp_path)
    final_dmg = tmp_path / "OntologyLab.dmg"
    final_zip = tmp_path / "OntologyLab.zip"
    final_dmg.write_bytes(b"final-dmg")
    final_zip.write_bytes(b"final-zip")
    final_app = fixture.app
    if missing == "app":
        final_app = tmp_path / "missing.app"
    elif missing == "installer":
        final_app = tmp_path / "installer-missing.app"
        resources = final_app / "Contents/Resources"
        resources.mkdir(parents=True)
        (resources / "internal-deployment.json").write_text(
            json.dumps(
                {
                    "architecture": "arm64",
                    "executable_path": "Contents/MacOS/ontologylab-internal-deploy",
                    "executable_sha256": "a" * 64,
                    "schema": "ontologylab.internal-deployment-build.v1",
                    "version": "0.1.0",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    install_receipt = tmp_path / "OntologyLab.receipt.json"
    install_receipt.write_text(
        json.dumps(
            {
                "app_tree_sha256": (
                    tree_sha256(final_app) if final_app.is_dir() else "a" * 64
                ),
                "artifact_name": "OntologyLab.app",
                "schema": "ontologylab.internal-artifact-receipt.v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    selected = {
        "dmg": tmp_path / "missing.dmg",
        "zip": tmp_path / "missing.zip",
        "app": final_app,
        "install_receipt": tmp_path / "missing-receipt.json",
        "installer": final_app,
    }
    args = (
        sys.executable,
        "-m",
        "release.task12_workflow",
        "--final-dmg",
        str(selected[missing] if missing == "dmg" else final_dmg),
        "--final-zip",
        str(selected[missing] if missing == "zip" else final_zip),
        "--final-app",
        str(selected[missing] if missing in {"app", "installer"} else final_app),
        "--install-receipt",
        str(selected[missing] if missing == "install_receipt" else install_receipt),
        "--external-receipts-dir",
        str(tmp_path / "authority"),
    )

    # When the external workflow runs, then it exits 2 without traceback or authority.
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=os.environ | {"HOME": str(tmp_path / "home")},
    )
    assert result.returncode == 2
    assert "internal deployment refused:" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "authority").exists()


def test_task12_finalize_cli_emits_external_authority_without_artifact_drift(
    tmp_path: Path,
) -> None:
    # Given finalized DMG, ZIP, signed app, install receipt, and external receipt root.
    fixture = _prepared_fixture(tmp_path)
    final_dmg = tmp_path / "OntologyLab-0.1.0-internal-arm64.dmg"
    final_zip = tmp_path / "OntologyLab-0.1.0-internal-arm64.zip"
    final_dmg.write_bytes(b"final-dmg-bytes")
    final_zip.write_bytes(b"final-zip-bytes")
    install_receipt = tmp_path / "OntologyLab.receipt.json"
    install_receipt.write_text(
        json.dumps(
            {
                "app_tree_sha256": tree_sha256(fixture.app),
                "artifact_name": "OntologyLab.app",
                "schema": "ontologylab.internal-artifact-receipt.v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    external = tmp_path / "external-receipts"
    before = (
        _sha256(final_dmg),
        _sha256(final_zip),
        tree_sha256(fixture.app),
        _sha256(install_receipt),
    )

    # When the real post-final-DMG Task12 production CLI runs.
    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "release.task12_workflow",
            "--final-dmg",
            str(final_dmg),
            "--final-zip",
            str(final_zip),
            "--final-app",
            str(fixture.app),
            "--install-receipt",
            str(install_receipt),
            "--external-receipts-dir",
            str(external),
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=os.environ | {
            "HOME": str(tmp_path / "home-sandbox"),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )

    # Then strict external sidecars bind finals while every artifact hash stays exact.
    assert result.returncode == 0, result.stderr
    emitted = json.loads(result.stdout)
    authority = external / "OntologyLab.task12-release-authority.json"
    digest = external / "OntologyLab.task12-release-authority.sha256"
    payload = json.loads(authority.read_text(encoding="utf-8"))
    assert emitted["authority"] == str(authority)
    assert emitted["authority_sha256"] == _sha256(authority)
    assert digest.read_text(encoding="ascii") == f"{_sha256(authority)}\n"
    assert payload["final_dmg_sha256"] == before[0]
    assert payload["zip_sha256"] == before[1]
    assert payload["final_app_tree_sha256"] == before[2]
    assert payload["install_receipt_sha256"] == before[3]
    assert payload["deployment_executable_relative_path"] == (
        "Contents/MacOS/ontologylab-internal-deploy"
    )
    embedded = fixture.app / payload["deployment_executable_relative_path"]
    assert payload["deployment_executable_sha256"] == _sha256(embedded)
    assert payload["version"] == "0.1.0"
    assert payload["architecture"] == "arm64"
    assert payload["tree_hash_schema"] == (
        "ontologylab.internal-deployment-tree-sha256.v1"
    )
    assert before == (
        _sha256(final_dmg),
        _sha256(final_zip),
        tree_sha256(fixture.app),
        _sha256(install_receipt),
    )
