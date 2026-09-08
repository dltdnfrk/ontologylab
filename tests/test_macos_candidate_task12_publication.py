from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

import release.task12_finalize as finalizer
from release.task12_finalize import Task12FinalizeRequest, finalize_task12_release
from release.task12_workflow import main as task12_workflow_main
from scripts.internal_deployment import prepare_retained_uninstall
from scripts.internal_deployment_fs import tree_sha256
from scripts.internal_deployment_types import (
    DeploymentRefused,
    PrepareRetainedUninstallRequest,
    Task12ReleaseAuthority,
)
from tests.test_internal_deployment_prepared_anchor import _prepared_fixture


def _request(root: Path) -> Task12FinalizeRequest:
    fixture = _prepared_fixture(root)
    final_dmg = root / "OntologyLab.dmg"
    final_zip = root / "OntologyLab.zip"
    receipt = root / "OntologyLab.receipt.json"
    final_dmg.write_bytes(b"final-dmg")
    final_zip.write_bytes(b"final-zip")
    receipt.write_text(
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
    return Task12FinalizeRequest(
        final_dmg, final_zip, fixture.app, receipt, root / "authority"
    )


def _retained_stages(root: Path) -> tuple[Path, ...]:
    return tuple(root.glob(".authority.retained-stage-*"))


def _retained_failures(root: Path) -> tuple[Path, ...]:
    return tuple(root.glob(".authority.retained-failure-*"))


def test_task12_publication_is_complete_and_strict(tmp_path: Path) -> None:
    # Given complete immutable finals and an absent authoritative destination.
    request = _request(tmp_path)

    # When finalization reaches its terminal publication operation.
    result = finalize_task12_release(request)

    # Then one complete strict directory appears atomically.
    assert request.external_receipts_dir.is_dir()
    assert {path.name for path in request.external_receipts_dir.iterdir()} == {
        "OntologyLab.task12-release-authority.complete",
        "OntologyLab.task12-release-authority.json",
        "OntologyLab.task12-release-authority.sha256",
    }
    parsed = Task12ReleaseAuthority.model_validate_json(
        result.authority.read_bytes(), strict=True
    )
    assert parsed.zip_sha256 == result.final_hashes.zip_sha256
    assert (
        request.external_receipts_dir
        / "OntologyLab.task12-release-authority.complete"
    ).read_bytes() == b"ontologylab.task12-release-authority.complete.v1\n"
    assert not _retained_stages(tmp_path)
    assert not _retained_failures(tmp_path)


def test_task12_mutation_before_publication_retains_stale_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given the final ZIP mutates after prepublication hashes but before rename.
    request = _request(tmp_path)
    original = finalizer._rename_exclusive

    def mutate_then_publish(source: Path, destination: Path) -> None:
        request.final_zip.write_bytes(b"prepublication-race")
        original(source, destination)

    monkeypatch.setattr(finalizer, "_rename_exclusive", mutate_then_publish)

    # When the external workflow runs, then stale authority leaves canonical scope.
    result = task12_workflow_main(
        [
            "--final-dmg",
            str(request.final_dmg),
            "--final-zip",
            str(request.final_zip),
            "--final-app",
            str(request.final_app),
            "--install-receipt",
            str(request.install_receipt),
            "--external-receipts-dir",
            str(request.external_receipts_dir),
        ]
    )
    if result == 0:
        stale = Task12ReleaseAuthority.model_validate_json(
            (
                request.external_receipts_dir
                / "OntologyLab.task12-release-authority.json"
            ).read_bytes(),
            strict=True,
        )
        assert stale.zip_sha256 != finalizer.sha256_file(request.final_zip)
        pytest.fail("workflow exited 0 with stale authority at canonical path")
    assert result == 2
    assert "task12_postpublication_validation" in capsys.readouterr().err
    assert not request.external_receipts_dir.exists()
    retained = _retained_failures(tmp_path)
    assert len(retained) == 1
    parsed = Task12ReleaseAuthority.model_validate_json(
        (retained[0] / "OntologyLab.task12-release-authority.json").read_bytes(),
        strict=True,
    )
    assert parsed.zip_sha256 != finalizer.sha256_file(request.final_zip)


def test_task12_mutation_immediately_after_publication_is_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given the final ZIP mutates immediately after the exclusive publication.
    request = _request(tmp_path)
    original = finalizer._rename_exclusive

    def publish_then_mutate(source: Path, destination: Path) -> None:
        original(source, destination)
        if destination == request.external_receipts_dir:
            request.final_zip.write_bytes(b"postpublication-race")

    monkeypatch.setattr(finalizer, "_rename_exclusive", publish_then_mutate)

    # When canonical postvalidation runs, then canonical authority disappears.
    with pytest.raises(DeploymentRefused, match="task12_postpublication_validation"):
        finalize_task12_release(request)
    assert not request.external_receipts_dir.exists()
    assert len(_retained_failures(tmp_path)) == 1


def test_task12_postpublication_read_failure_retains_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given reopening final inputs fails only after authority publication.
    request = _request(tmp_path)
    original = finalizer._final_hashes
    calls = 0

    def fail_postpublication(
        value: Task12FinalizeRequest,
    ) -> finalizer.FinalArtifactHashes:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise DeploymentRefused("injected_postpublication_read_failure")
        return original(value)

    monkeypatch.setattr(finalizer, "_final_hashes", fail_postpublication)

    # When canonical postvalidation cannot read finals, then authority is retained.
    with pytest.raises(DeploymentRefused, match="task12_postpublication_validation"):
        finalize_task12_release(request)
    assert not request.external_receipts_dir.exists()
    assert len(_retained_failures(tmp_path)) == 1


def test_task12_failed_retention_collision_uses_fresh_exclusive_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given drift plus a collision at the first generated failed-retention name.
    request = _request(tmp_path)
    values = iter(("stage", "collision", "fresh"))

    class FixedUuid:
        @property
        def hex(self) -> str:
            return next(values)

    collision = tmp_path / ".authority.retained-failure-collision"
    collision.mkdir()
    original = finalizer._rename_exclusive

    def publish_then_mutate(source: Path, destination: Path) -> None:
        original(source, destination)
        if destination == request.external_receipts_dir:
            request.final_zip.write_bytes(b"collision-race")

    monkeypatch.setattr(finalizer.uuid, "uuid4", FixedUuid)
    monkeypatch.setattr(finalizer, "_rename_exclusive", publish_then_mutate)

    # When failure retention collides, then a fresh exclusive sibling is retained.
    with pytest.raises(DeploymentRefused, match="task12_postpublication_validation"):
        finalize_task12_release(request)
    assert not request.external_receipts_dir.exists()
    assert collision.is_dir()
    assert (tmp_path / ".authority.retained-failure-fresh").is_dir()


def test_prepare_refuses_authority_after_final_zip_mutation(
    tmp_path: Path,
) -> None:
    # Given complete authority followed by mutation of its bound final ZIP.
    request = _request(tmp_path)
    result = finalize_task12_release(request)
    request.final_zip.write_bytes(b"mutated-final-zip")
    prepare = PrepareRetainedUninstallRequest(
        app=request.final_app,
        home=tmp_path / "home",
        retained_root=tmp_path / "retained",
        release_authority=result.authority,
        release_authority_sha256=result.authority_sha256,
        release_dmg=request.final_dmg,
        release_zip=request.final_zip,
        install_receipt=request.install_receipt,
        running_executable=Path(sys.executable),
    )

    # When retained prepare authenticates the ZIP, then no journal is created.
    with pytest.raises(DeploymentRefused, match="release_authority_zip_mismatch"):
        prepare_retained_uninstall(prepare)
    assert not tuple((tmp_path / "retained").iterdir())


def test_task12_publication_refuses_authoritative_collision(tmp_path: Path) -> None:
    # Given an existing authoritative path, even when it is empty.
    request = _request(tmp_path)
    request.external_receipts_dir.mkdir()

    # When finalization starts, then collision refuses without sidecars.
    with pytest.raises(DeploymentRefused, match="task12_authority_collision"):
        finalize_task12_release(request)
    assert not tuple(request.external_receipts_dir.iterdir())


def test_task12_drift_retains_non_authoritative_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a second hash pass that observes final ZIP drift after staging.
    request = _request(tmp_path)
    original = finalizer._final_hashes
    calls = 0

    def drifting(value: Task12FinalizeRequest) -> finalizer.FinalArtifactHashes:
        nonlocal calls
        calls += 1
        hashes = original(value)
        if calls == 2:
            return dataclasses.replace(hashes, zip_sha256="f" * 64)
        return hashes

    monkeypatch.setattr(finalizer, "_final_hashes", drifting)

    # When drift is detected, then authority remains absent and staging is retained.
    with pytest.raises(DeploymentRefused, match="task12_final_artifact_drift"):
        finalize_task12_release(request)
    assert not request.external_receipts_dir.exists()
    assert len(_retained_stages(tmp_path)) == 1


def test_task12_partial_write_retains_non_authoritative_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a digest write refusal after staged authority creation.
    request = _request(tmp_path)

    def refuse_digest(_path: Path, _digest: str) -> None:
        raise DeploymentRefused("injected_partial_write")

    monkeypatch.setattr(finalizer, "_write_digest", refuse_digest)

    # When staging fails, then no authoritative path exists and bytes remain retained.
    with pytest.raises(DeploymentRefused, match="injected_partial_write"):
        finalize_task12_release(request)
    assert not request.external_receipts_dir.exists()
    stages = _retained_stages(tmp_path)
    assert len(stages) == 1
    assert tuple(stages[0].iterdir())
