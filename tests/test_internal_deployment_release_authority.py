from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from scripts.internal_deployment import prepare_retained_uninstall
from scripts.internal_deployment_release_authority import (
    Task12AuthorityRequest,
    generate_task12_release_authority,
)
from scripts.internal_deployment_types import (
    DeploymentRefused,
    PrepareRetainedUninstallRequest,
)
from tests.test_internal_deployment_prepared_anchor import _prepared_fixture


def test_task12_final_sidecar_binds_dmg_receipt_app_and_installer(
    tmp_path: Path,
) -> None:
    # Given final DMG, install receipt, app, and embedded deployment identity.
    fixture = _prepared_fixture(tmp_path)
    final_dmg = tmp_path / "OntologyLab.dmg"
    final_dmg.write_bytes(b"final-dmg")
    final_zip = tmp_path / "OntologyLab.zip"
    final_zip.write_bytes(b"final-zip")
    install_receipt = tmp_path / "OntologyLab.receipt.json"
    authority_input = json.loads(fixture.authority.read_text(encoding="utf-8"))
    install_receipt.write_text(
        json.dumps(
            {
                "app_tree_sha256": authority_input["final_app_tree_sha256"],
                "artifact_name": "OntologyLab.app",
                "schema": "ontologylab.internal-artifact-receipt.v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "OntologyLab.task12-release-authority.json"

    # When Task12 generates its external authority after DMG finalization.
    generated = generate_task12_release_authority(
        Task12AuthorityRequest(
            final_dmg, final_zip, install_receipt, fixture.app, output
        )
    )

    # Then every final release identity needed by prepare is exact-bound.
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert generated.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert payload["final_dmg_sha256"] == hashlib.sha256(b"final-dmg").hexdigest()
    assert payload["zip_sha256"] == hashlib.sha256(b"final-zip").hexdigest()
    assert payload["install_receipt_sha256"] == hashlib.sha256(
        install_receipt.read_bytes()
    ).hexdigest()
    assert payload["final_app_tree_sha256"] == authority_input["final_app_tree_sha256"]
    assert payload["deployment_executable_sha256"] == authority_input[
        "deployment_executable_sha256"
    ]


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("release_dmg", "release_authority_dmg_mismatch"),
        ("install_receipt", "release_authority_receipt_mismatch"),
    ),
)
def test_prepare_rehashes_every_final_input(
    tmp_path: Path, field: str, reason: str
) -> None:
    # Given canonical terminal authority followed by one final-input mutation.
    fixture = _prepared_fixture(tmp_path)
    target = getattr(fixture, field)
    assert isinstance(target, Path)
    target.write_bytes(target.read_bytes() + b"mutation")
    request = PrepareRetainedUninstallRequest(
        app=fixture.app,
        home=fixture.home,
        retained_root=fixture.retained,
        release_authority=fixture.authority,
        release_authority_sha256=fixture.authority_sha256,
        release_dmg=fixture.release_dmg,
        release_zip=fixture.release_zip,
        install_receipt=fixture.install_receipt,
        running_executable=Path(sys.executable),
    )

    # When prepare consumes authority, then mutation refuses before journaling.
    with pytest.raises(DeploymentRefused, match=reason):
        prepare_retained_uninstall(request)
    assert not tuple(fixture.retained.iterdir())


def test_prepare_refuses_nonterminal_and_failure_retained_authority(
    tmp_path: Path,
) -> None:
    # Given a complete authority directory renamed to failure-retained scope.
    fixture = _prepared_fixture(tmp_path)
    canonical = fixture.authority.parent
    retained = canonical.parent / f".{canonical.name}.retained-failure-probe"
    os.rename(canonical, retained)
    request = PrepareRetainedUninstallRequest(
        app=fixture.app,
        home=fixture.home,
        retained_root=fixture.retained,
        release_authority=retained / fixture.authority.name,
        release_authority_sha256=fixture.authority_sha256,
        release_dmg=fixture.release_dmg,
        release_zip=fixture.release_zip,
        install_receipt=fixture.install_receipt,
        running_executable=Path(sys.executable),
    )

    # When prepare sees retained-failure scope, then it cannot become authoritative.
    with pytest.raises(DeploymentRefused, match="release_authority_directory_unsafe"):
        prepare_retained_uninstall(request)
    assert not tuple(fixture.retained.iterdir())


def test_prepare_refuses_authority_without_terminal_marker(tmp_path: Path) -> None:
    # Given canonical authority whose terminal marker was retained under another name.
    fixture = _prepared_fixture(tmp_path)
    marker = fixture.authority.parent / "OntologyLab.task12-release-authority.complete"
    os.rename(marker, fixture.authority.parent / ".retained-incomplete-marker")
    request = PrepareRetainedUninstallRequest(
        app=fixture.app,
        home=fixture.home,
        retained_root=fixture.retained,
        release_authority=fixture.authority,
        release_authority_sha256=fixture.authority_sha256,
        release_dmg=fixture.release_dmg,
        release_zip=fixture.release_zip,
        install_receipt=fixture.install_receipt,
        running_executable=Path(sys.executable),
    )

    # When prepare sees no canonical terminal marker, then it refuses before journaling.
    with pytest.raises(
        DeploymentRefused, match="release_authority_directory_incomplete"
    ):
        prepare_retained_uninstall(request)
    assert not tuple(fixture.retained.iterdir())


def test_prepare_refuses_genuine_authority_with_substituted_app(
    tmp_path: Path,
) -> None:
    # Given genuine authority bytes supplied with a different post-release app.
    genuine = _prepared_fixture(tmp_path / "genuine")
    substituted = _prepared_fixture(tmp_path / "substituted")
    (substituted.app / "Contents/Resources/substitution").write_text(
        "different", encoding="utf-8"
    )
    request = PrepareRetainedUninstallRequest(
        app=substituted.app,
        home=substituted.home,
        retained_root=substituted.retained,
        release_authority=genuine.authority,
        release_authority_sha256=genuine.authority_sha256,
        release_dmg=genuine.release_dmg,
        release_zip=genuine.release_zip,
        install_receipt=genuine.install_receipt,
        running_executable=Path(sys.executable),
    )

    # When prepare compares final app identity, then no journal is created.
    with pytest.raises(DeploymentRefused, match="release_authority_app_mismatch"):
        prepare_retained_uninstall(request)
    assert not tuple(substituted.retained.iterdir())


def test_prepare_refuses_substituted_running_executable(
    tmp_path: Path,
) -> None:
    # Given genuine authority/app bytes but a different executable invocation.
    fixture = _prepared_fixture(tmp_path)
    substituted = tmp_path / "substituted-installer"
    substituted.write_bytes(b"different executable")
    request = PrepareRetainedUninstallRequest(
        app=fixture.app,
        home=fixture.home,
        retained_root=fixture.retained,
        release_authority=fixture.authority,
        release_authority_sha256=fixture.authority_sha256,
        release_dmg=fixture.release_dmg,
        release_zip=fixture.release_zip,
        install_receipt=fixture.install_receipt,
        running_executable=substituted,
    )

    # When prepare verifies the actual invocation, then no journal is created.
    with pytest.raises(DeploymentRefused, match="running_installer_sha256_mismatch"):
        prepare_retained_uninstall(request)
    assert not tuple(fixture.retained.iterdir())


def test_prepare_refuses_authority_bytes_changed_after_external_digest(
    tmp_path: Path,
) -> None:
    # Given authority bytes changed after the controller captured their digest.
    fixture = _prepared_fixture(tmp_path)
    fixture.authority.write_bytes(fixture.authority.read_bytes() + b" ")
    request = PrepareRetainedUninstallRequest(
        app=fixture.app,
        home=fixture.home,
        retained_root=fixture.retained,
        release_authority=fixture.authority,
        release_authority_sha256=fixture.authority_sha256,
        release_dmg=fixture.release_dmg,
        release_zip=fixture.release_zip,
        install_receipt=fixture.install_receipt,
        running_executable=Path(sys.executable),
    )

    # When prepare validates bytes first, then local trees remain active.
    with pytest.raises(DeploymentRefused, match="release_authority_digest_mismatch"):
        prepare_retained_uninstall(request)
    assert fixture.app.is_dir()
    assert fixture.runtime.is_dir()
