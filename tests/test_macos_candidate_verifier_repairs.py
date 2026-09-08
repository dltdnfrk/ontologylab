"""Task 11 retained-source and component-license verifier regressions."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest

from ontologylab.release_policy_types import ReleasePolicyRefused
from release import candidate_build as candidate
from tests.macos_candidate_deployment_support import add_internal_deployment_fixture
from tests.macos_candidate_test_support import (
    add_license_fixture,
    add_storage_matrix,
    metadata,
    seal_fixture,
    source_fixture,
)
from tests.macos_supervisor_support import build_supervisor, open_arguments, run

ROOT = Path(__file__).resolve().parents[1]


def test_seal_retains_and_task1_recomputes_exact_source_manifest(
    tmp_path: Path,
) -> None:
    # Given a candidate sealed from one exact Task 1 source manifest.
    root = source_fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    seal_fixture(root, candidate_root)
    retained = (
        candidate_root / "receipts" / "source" / "release" / "source-snapshot.json"
    )

    # When retained evidence is inspected and independently recomputed.
    assert (
        retained.read_bytes()
        == (root / "release" / "source-snapshot.json").read_bytes()
    )
    recomputed = candidate.verify_retained_snapshot(candidate_root)

    # Then Task 1's manifest identity equals the receipt's cited identity.
    receipt = json.loads(
        (candidate_root / "candidate-receipt.json").read_text(encoding="utf-8")
    )
    assert recomputed.snapshot_sha256 == receipt["source"]["snapshot_sha256"]


def _retained_fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = source_fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    seal_fixture(root, candidate_root)
    for path in candidate_root.rglob("*"):
        path.chmod(path.stat().st_mode | 0o700)
    retained = (
        candidate_root / "receipts" / "source" / "release" / "source-snapshot.json"
    )
    return candidate_root, retained


def test_retained_source_manifest_missing_refuses(tmp_path: Path) -> None:
    # Given a sealed candidate whose retained Task 1 manifest is removed.
    candidate_root, retained = _retained_fixture(tmp_path)
    retained.unlink()

    # When Task 1 verification reruns, then absence refuses with its typed code.
    with pytest.raises(ReleasePolicyRefused, match="snapshot_missing"):
        candidate.verify_retained_snapshot(candidate_root)


def test_retained_source_manifest_tamper_refuses(tmp_path: Path) -> None:
    # Given a sealed candidate whose retained canonical identity is altered.
    candidate_root, retained = _retained_fixture(tmp_path)
    payload = json.loads(retained.read_text(encoding="utf-8"))
    payload["snapshot_sha256"] = "0" * 64
    retained.write_text(json.dumps(payload), encoding="utf-8")

    # When Task 1 recomputes identity, then canonical tamper refuses.
    with pytest.raises(ReleasePolicyRefused, match="snapshot_malformed"):
        candidate.verify_retained_snapshot(candidate_root)


def test_package_dist_info_license_is_copied_and_hash_bound(tmp_path: Path) -> None:
    # Given texttable license evidence distributed inside its retained dist-info.
    root = source_fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    runtime = (
        candidate_root
        / "payload"
        / "OntologyLab.app"
        / "Contents"
        / "Resources"
        / "runtime"
    )
    metadata_dir = runtime / "_internal" / "texttable-1.7.0.dist-info"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "METADATA").write_text(
        "Name: texttable\nVersion: 1.7.0\nLicense: MIT\n", encoding="utf-8"
    )
    license_text = metadata_dir / "LICENSE"
    license_text.write_text("distributed MIT text\n", encoding="utf-8")
    (runtime / "sbom.json").write_text(
        json.dumps(
            {
                "components": [
                    {"name": "texttable", "version": "1.7.0", "license": "MIT"}
                ],
                "licenses": [],
            }
        ),
        encoding="utf-8",
    )

    add_storage_matrix(candidate_root / "payload" / "OntologyLab.app")
    add_internal_deployment_fixture(candidate_root / "payload" / "OntologyLab.app")

    # When sealing completes, then copied evidence records package source and hash.
    candidate.seal_candidate(candidate_root, candidate.verify_source(root), metadata())
    inventory = json.loads(
        (candidate_root / "inventories" / "licenses.json").read_text(encoding="utf-8")
    )
    record = inventory["components"][0]
    assert record["name"] == "texttable"
    assert record["version"] == "1.7.0"
    assert record["evidence"][0]["source"].endswith("dist-info/LICENSE")
    assert (
        record["evidence"][0]["sha256"]
        == hashlib.sha256(b"distributed MIT text\n").hexdigest()
    )


def _storage_candidate(tmp_path: Path, matrix: str) -> tuple[Path, Path]:
    root = source_fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    payload = candidate_root / "payload" / "OntologyLab.app"
    resources = payload / "Contents" / "Resources"
    resources.mkdir(parents=True)
    add_license_fixture(payload, include_storage_matrix=False)
    if matrix:
        (resources / "storage-compatibility.json").write_text(matrix, encoding="utf-8")
        add_internal_deployment_fixture(payload)
    return root, candidate_root


@unique
class MatrixMutation(StrEnum):
    MISSING = "missing"
    HASH = "hash"
    VERSION = "version"


@pytest.mark.parametrize("mutation", list(MatrixMutation))
def test_candidate_seal_refuses_invalid_storage_matrix(
    tmp_path: Path, mutation: MatrixMutation
) -> None:
    # Given an app with a missing, byte-drifted, or release-drifted matrix.
    source = ROOT / "ontologylab" / "storage-compatibility.json"
    match mutation:
        case MatrixMutation.MISSING:
            matrix = ""
        case MatrixMutation.HASH:
            matrix = "{}\n"
        case MatrixMutation.VERSION:
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["release_version"] = "9.9.9"
            matrix = json.dumps(payload)
        case unreachable:
            assert_never(unreachable)
    root, candidate_root = _storage_candidate(tmp_path, matrix)

    # When the candidate boundary seals, then invalid matrix authority refuses.
    with pytest.raises(candidate.CandidateRefused, match="storage_matrix"):
        candidate.seal_candidate(
            candidate_root, candidate.verify_source(root), metadata()
        )


def test_exact_storage_matrix_is_resource_bound_and_frozen(tmp_path: Path) -> None:
    # Given an app containing the exact source matrix.
    source = ROOT / "ontologylab" / "storage-compatibility.json"
    root, candidate_root = _storage_candidate(
        tmp_path, source.read_text(encoding="utf-8")
    )

    # When the candidate is sealed.
    receipt_path = candidate.seal_candidate(
        candidate_root, candidate.verify_source(root), metadata()
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    resources = receipt["resources"]["storage_compatibility"]
    payload_path = "Contents/Resources/storage-compatibility.json"
    tree = json.loads(
        (candidate_root / "inventories" / "payload-tree.json").read_text(
            encoding="utf-8"
        )
    )
    static = json.loads(
        (candidate_root / "inventories" / "static-assets.json").read_text(
            encoding="utf-8"
        )
    )

    # Then source/payload hashes, manifests, and frozen mode bind the exact resource.
    assert resources["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert resources["payload_sha256"] == resources["source_sha256"]
    entry = next(item for item in tree["entries"] if item["path"] == payload_path)
    assert entry["mode"] == "0o444"
    assert any(item["path"] == payload_path for item in static["files"])


def test_supervisor_missing_storage_matrix_refuses_before_backend(
    tmp_path: Path,
) -> None:
    # Given the exact supervisor surface with its required resource removed.
    app = build_supervisor(tmp_path / "missing-storage-matrix")
    matrix = app.executable.parent.parent / "Resources" / "storage-compatibility.json"
    matrix.unlink()

    # When startup runs, then no backend or browser starts before typed refusal.
    result = run(app, "valid")
    assert result.returncode != 0
    assert "configuration_refused member=storage_matrix" in result.stderr
    assert "BACKEND_PID:" not in result.stderr
    assert open_arguments(result.stdout) == []


def test_seal_refuses_component_without_shipped_license_evidence(
    tmp_path: Path,
) -> None:
    # Given 42 SBOM components where sqlite-vec alone lacks local license evidence.
    root = source_fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    runtime = (
        candidate_root
        / "payload"
        / "OntologyLab.app"
        / "Contents"
        / "Resources"
        / "runtime"
    )
    internal = runtime / "_internal"
    internal.mkdir(parents=True)
    components = [
        {"name": f"component-{index}", "version": "1.0", "license": "MIT"}
        for index in range(40)
    ]
    components.extend(
        (
            {"name": "texttable", "version": "1.7.0", "license": "MIT"},
            {
                "name": "sqlite-vec",
                "version": "0.1.9",
                "license": "MIT License, Apache License, Version 2.0",
            },
        )
    )
    for component in components[:-1]:
        metadata_dir = (
            internal / f"{component['name']}-{component['version']}.dist-info"
        )
        metadata_dir.mkdir()
        (metadata_dir / "METADATA").write_text(
            f"Name: {component['name']}\nVersion: {component['version']}\nLicense: MIT\n",
            encoding="utf-8",
        )
        (metadata_dir / "LICENSE").write_text(
            f"license for {component['name']}\n", encoding="utf-8"
        )
    (runtime / "sbom.json").write_text(
        json.dumps({"components": components, "licenses": []}, sort_keys=True),
        encoding="utf-8",
    )

    add_storage_matrix(candidate_root / "payload" / "OntologyLab.app")

    # When sealing checks all 42 mappings, then missing local evidence refuses.
    with pytest.raises(
        candidate.CandidateRefused, match="license_evidence_missing.*sqlite-vec"
    ):
        candidate.seal_candidate(
            candidate_root,
            candidate.verify_source(root),
            metadata(),
        )
