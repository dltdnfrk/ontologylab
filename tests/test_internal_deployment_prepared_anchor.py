from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.internal_deployment_cli import main as deployment_main
from scripts.internal_deployment_fs import tree_sha256
from tests.test_internal_deployment import _app


@dataclass(frozen=True, slots=True)
class PreparedFixture:
    app: Path
    home: Path
    runtime: Path
    retained: Path
    authority: Path
    authority_sha256: str
    release_dmg: Path
    release_zip: Path
    install_receipt: Path


def _prepared_fixture(root: Path) -> PreparedFixture:
    app = _app(root / "Applications")
    executable = app / "Contents/MacOS/ontologylab-internal-deploy"
    executable.write_bytes(Path(sys.executable).read_bytes())
    executable.chmod(0o755)
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    (app / "Contents/Resources/internal-deployment.json").write_text(
        json.dumps(
            {
                "architecture": "arm64",
                "executable_path": "Contents/MacOS/ontologylab-internal-deploy",
                "executable_sha256": executable_sha256,
                "schema": "ontologylab.internal-deployment-build.v1",
                "version": "0.1.0",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    home = root / "home"
    runtime = home / "Library/Caches/ontologylab/runtime"
    runtime.mkdir(parents=True)
    (runtime / "state").write_text("runtime", encoding="utf-8")
    retained = root / "retained"
    retained.mkdir(mode=0o700)
    release_dmg = root / "OntologyLab.dmg"
    release_dmg.write_bytes(b"final-dmg")
    release_zip = root / "OntologyLab.zip"
    release_zip.write_bytes(b"final-zip")
    install_receipt = root / "OntologyLab.receipt.json"
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
    authority_dir = root / "Task12-authority"
    authority_dir.mkdir()
    authority = authority_dir / "OntologyLab.task12-release-authority.json"
    authority.write_text(
        json.dumps(
            {
                "architecture": "arm64",
                "deployment_executable_relative_path": "Contents/MacOS/ontologylab-internal-deploy",
                "deployment_executable_sha256": executable_sha256,
                "final_app_tree_sha256": tree_sha256(app),
                "final_dmg_sha256": hashlib.sha256(
                    release_dmg.read_bytes()
                ).hexdigest(),
                "zip_sha256": hashlib.sha256(release_zip.read_bytes()).hexdigest(),
                "install_receipt_sha256": hashlib.sha256(
                    install_receipt.read_bytes()
                ).hexdigest(),
                "schema": "ontologylab.task12-release-authority.v1",
                "tree_hash_schema": "ontologylab.internal-deployment-tree-sha256.v1",
                "version": "0.1.0",
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
    return PreparedFixture(
        app,
        home,
        runtime,
        retained,
        authority,
        authority_sha256,
        release_dmg,
        release_zip,
        install_receipt,
    )


def _prepare_arguments(fixture: PreparedFixture) -> list[str]:
    return [
        "prepare-retained-uninstall",
        "--app",
        str(fixture.app),
        "--home",
        str(fixture.home),
        "--retain-removals-under",
        str(fixture.retained),
        "--release-authority",
        str(fixture.authority),
        "--release-authority-sha256",
        fixture.authority_sha256,
        "--release-dmg",
        str(fixture.release_dmg),
        "--release-zip",
        str(fixture.release_zip),
        "--install-receipt",
        str(fixture.install_receipt),
    ]


def _apply_arguments(fixture: PreparedFixture, anchor: str) -> list[str]:
    return [
        "apply-retained-uninstall",
        "--app",
        str(fixture.app),
        "--home",
        str(fixture.home),
        "--retain-removals-under",
        str(fixture.retained),
        "--prepared-anchor",
        anchor,
    ]


def test_prepare_retained_uninstall_returns_external_anchor_without_rename(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given a strict synthetic Task12 authority and matching installed app/installer.
    fixture = _prepared_fixture(tmp_path)
    app_sha256 = tree_sha256(fixture.app)
    runtime_sha256 = tree_sha256(fixture.runtime)

    # When the real source CLI prepares retained uninstall.
    result = deployment_main(_prepare_arguments(fixture))

    # Then only the canonical prepared journal exists and the controller gets its anchor.
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output["prepared_anchor"]) == 64
    assert output["journal"] == str(
        fixture.retained / "retained-removal-journal.jsonl"
    )
    assert tree_sha256(fixture.app) == app_sha256
    assert tree_sha256(fixture.runtime) == runtime_sha256
    assert tuple(path.name for path in fixture.retained.iterdir()) == (
        "retained-removal-journal.jsonl",
    )


def test_one_step_retained_uninstall_refuses_without_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given the retired one-step retained-uninstall selection.
    fixture = _prepared_fixture(tmp_path)

    # When it is invoked without the two-step authority protocol.
    result = deployment_main(
        [
            "uninstall",
            "--app",
            str(fixture.app),
            "--home",
            str(fixture.home),
            "--retain-removals-under",
            str(fixture.retained),
        ]
    )

    # Then it typed-refuses and preserves both active trees.
    assert result == 2
    assert "retained_removal_requires_prepare" in capsys.readouterr().err
    assert fixture.app.is_dir()
    assert fixture.runtime.is_dir()
    assert not tuple(fixture.retained.iterdir())


def test_apply_retained_uninstall_requires_controller_anchor_and_completes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given a prepared transaction whose anchor is held by the controller.
    fixture = _prepared_fixture(tmp_path)
    assert deployment_main(_prepare_arguments(fixture)) == 0
    prepared = json.loads(capsys.readouterr().out)

    # When apply receives that original anchor through the real source CLI.
    result = deployment_main(
        _apply_arguments(fixture, prepared["prepared_anchor"])
    )

    # Then both exact trees move and the receipt binds external authorities.
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    receipt = json.loads(Path(output["retained_removal_receipt"]).read_text())
    assert not fixture.app.exists()
    assert not fixture.runtime.exists()
    assert receipt["prepared_anchor"] == prepared["prepared_anchor"]
    assert receipt["release_authority_sha256"] == fixture.authority_sha256
