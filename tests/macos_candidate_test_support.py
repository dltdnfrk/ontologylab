"""Shared deterministic fixtures for Task 11 candidate verifier tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ontologylab.release_policy import load_policy, read_version
from ontologylab.release_snapshot import write_snapshot
from release import candidate_build as candidate
from release.candidate_source_closure import copy_policy_inputs
from tests.macos_candidate_deployment_support import (
    add_license_fixture,
    add_storage_matrix,
)
from tests.macos_candidate_source_policy_support import ROOT

__all__ = ("add_license_fixture", "add_storage_matrix")


def source_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    copy_policy_inputs(ROOT, root)
    subprocess.run(
        ("git", "-C", str(root), "init", "-q"),
        check=True,
        capture_output=True,
    )
    policy = load_policy(root)
    report = root / policy.task10_authority.report_path
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes((ROOT / policy.task10_authority.report_path).read_bytes())
    write_snapshot(root, policy, read_version(root, policy))
    return root


def metadata(status: str = "a") -> candidate.BuildMetadata:
    return candidate.BuildMetadata(
        head="1" * 40,
        head_ref="refs/heads/main",
        status_diff_sha256=status * 64,
        toolchain_sha256="3" * 64,
        build_inputs_sha256="4" * 64,
    )


def seal_fixture(root: Path, candidate_root: Path) -> Path:
    payload = candidate_root / "payload" / "OntologyLab.app"
    payload.mkdir(parents=True)
    (payload / "asset.txt").write_text("payload\n", encoding="utf-8")
    add_license_fixture(payload)
    return candidate.seal_candidate(
        candidate_root,
        candidate.verify_source(root),
        metadata(),
    )
