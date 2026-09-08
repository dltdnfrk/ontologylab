"""Generic manifest-derived source closure for Task 11 fixtures and staging."""

from __future__ import annotations

import json
import subprocess
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest

from ontologylab.release_policy import load_policy, read_version
from ontologylab.release_snapshot import write_snapshot
from ontologylab.release_source_exclusions import source_exclusion_reason
from release.candidate_source_closure import (
    copy_source_closure,
    verify_source_closure,
)
from release.candidate_types import CandidateRefused
from tests.macos_candidate_source_policy_support import (
    ROOT,
    covered,
    matching_authoritative_tests,
    matching_candidate_modules,
    matching_internal_deployment_sources,
    task11_policy_coverage,
)
from tests.macos_candidate_test_support import source_fixture


def test_task11_policy_covers_every_authoritative_path_class() -> None:
    # Given all Task 11 naming classes, build inputs, local imports, gates, and master files.
    audit = task11_policy_coverage()

    # When policy coverage is evaluated, then every exact file is safely declared.
    assert not audit.missing, sorted(audit.missing)
    assert (
        len(audit.declared),
        len(audit.authoritative),
        len(audit.task10_authoritative),
        len(audit.missing),
        len(audit.generated_violations),
    ) == (101, 95, 27, 0, 0)
    assert not audit.generated_violations
    assert covered("ontologylab/storage-compatibility.json", audit.declared)
    assert not any(
        "__pycache__" in rel
        or rel.startswith(("build/", ".omo/", "evidence/", "artifacts/"))
        for rel in audit.authoritative
    )


def test_task10_master_and_internal_deployment_classes_are_policy_covered() -> None:
    # Given Task 10 master hashes plus module and invoked-entrypoint naming classes.
    audit = task11_policy_coverage()
    master = json.loads(
        (
            ROOT
            / ".omo/evidence/mac-desktop-deployment-roadmap/task-10"
            / "task-10-mac-desktop-deployment-roadmap.json"
        ).read_text(encoding="utf-8")
    )

    # When compared, historical master paths remain within current discovered closure.
    master_paths = set(master["files"])
    assert master_paths <= audit.task10_authoritative
    assert all(covered(rel, audit.declared) for rel in audit.task10_authoritative)


def test_snapshot_excludes_swiftpm_build_products_but_keeps_package_sources(
    tmp_path: Path,
) -> None:
    # Given: a declared Swift package containing source plus generated build products.
    root = tmp_path / "fixture"
    root.mkdir()
    for rel, body in {
        "pyproject.toml": '[project]\nname="fixture"\nversion="0.1.0"\n',
        "uv.lock": "lock\n",
        "ontologylab/__init__.py": "",
        "web/index.html": "",
        "launcher/supervisor/Package.swift": "// package\n",
        "launcher/supervisor/Sources/App/main.swift": "print(1)\n",
        "launcher/supervisor/.build/debug/App": "generated\n",
        "launcher/supervisor/.build/index/store/record": "generated\n",
        "release/licenses/NOTICE": "notice\n",
        "tests/fixtures/wave21/perf-v1.json": "{}\n",
        "release/ingestion-performance-protocol.json": "{}\n",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    policy_payload = json.loads((ROOT / "release/release-policy.json").read_text())
    policy_payload["source_inputs"] = [
        "pyproject.toml",
        "uv.lock",
        "ontologylab",
        "web",
        "launcher",
        "release/licenses",
        "release/release-policy.json",
        "tests/fixtures/wave21/perf-v1.json",
        "release/ingestion-performance-protocol.json",
    ]
    (root / "release/release-policy.json").write_text(
        json.dumps(policy_payload), encoding="utf-8"
    )
    subprocess.run(("git", "-C", str(root), "init", "-q"), check=True)

    # When: the production snapshot expands the declared launcher root.
    policy = load_policy(root)
    manifest = write_snapshot(root, policy, read_version(root, policy))
    paths = {entry.path for entry in manifest.files}

    # Then: Swift source/manifests remain authoritative and .build is classified out.
    assert "launcher/supervisor/Package.swift" in paths
    assert "launcher/supervisor/Sources/App/main.swift" in paths
    assert not any("/.build/" in path for path in paths)
    assert (
        source_exclusion_reason("launcher/supervisor/.build/debug/App")
        == "swiftpm-build-output"
    )


def test_new_matching_task10_source_requires_policy_declaration(
    tmp_path: Path,
) -> None:
    # Given one future module matching the authoritative Task 10 naming class.
    future = tmp_path / "scripts" / "internal_deployment_future.py"
    future.parent.mkdir()
    future.write_text("FUTURE = True\n", encoding="utf-8")
    discovered = matching_internal_deployment_sources(tmp_path)
    declared = task11_policy_coverage().declared

    # When coverage runs before declaration, then the new source is uncovered.
    assert discovered == {"scripts/internal_deployment_future.py"}
    assert not covered("scripts/internal_deployment_future.py", declared)


def test_new_matching_candidate_module_requires_policy_declaration(
    tmp_path: Path,
) -> None:
    # Given one future module matching the authoritative Task 11 naming class.
    future = tmp_path / "release" / "candidate_future.py"
    future.parent.mkdir()
    future.write_text("FUTURE = True\n", encoding="utf-8")
    discovered = matching_candidate_modules(tmp_path)
    declared = task11_policy_coverage().declared

    # When coverage is checked before policy update, then the new module is uncovered.
    assert discovered == {"release/candidate_future.py"}
    assert not covered("release/candidate_future.py", declared)


def test_new_matching_product_contracts_require_policy_declaration(
    tmp_path: Path,
) -> None:
    # Given future UI, auth, causal release, and unrelated contract tests.
    tests = tmp_path / "tests"
    tests.mkdir()
    for name in (
        "test_p3_ui_ux_contract.py",
        "test_workspace_api_auth.py",
        "test_release_authorization_binding.py",
        "test_release_performance_evidence.py",
        "test_unrelated_contract.py",
    ):
        (tests / name).write_text("FUTURE = True\n", encoding="utf-8")

    # When authoritative test classes are discovered, only semantic matches are selected.
    assert matching_authoritative_tests(tmp_path) == {
        "tests/test_p3_ui_ux_contract.py",
        "tests/test_release_authorization_binding.py",
        "tests/test_release_performance_evidence.py",
        "tests/test_workspace_api_auth.py",
    }


def test_authoritative_closure_copies_all_current_required_inputs(
    tmp_path: Path,
) -> None:
    # Given a newly minted authority from the current policy closure.
    authority = source_fixture(tmp_path / "minted")
    destination = tmp_path / "source"

    # When Task 11 materializes its disposable source closure.
    copy_source_closure(authority, destination)

    # Then protocol, fixture, matrix, and vendored licenses are exact-bound inputs.
    required = (
        "release/ingestion-performance-protocol.json",
        "tests/fixtures/wave21/perf-v1.json",
        "ontologylab/storage-compatibility.json",
        "release/licenses/sqlite-vec/0.1.9/LICENSE-MIT",
        "release/licenses/sqlite-vec/0.1.9/LICENSE-APACHE",
        "release/licenses/sqlite-vec/0.1.9/provenance.json",
    )
    assert all(
        (destination / rel).read_bytes() == (authority / rel).read_bytes()
        for rel in required
    )
    verify_source_closure(authority, destination)


def test_new_manifest_declared_file_copies_without_hard_coded_edit(
    tmp_path: Path,
) -> None:
    # Given an authority cloned from the current closure with one future declared file.
    authority = source_fixture(tmp_path / "minted")
    future_rel = "release/future-required.txt"
    future = authority / future_rel
    future.write_text("future input\n", encoding="utf-8")
    policy_path = authority / "release" / "release-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["source_inputs"].append(future_rel)
    policy_path.write_text(
        json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    subprocess.run(
        ("git", "-C", str(authority), "init", "-q"),
        check=True,
        capture_output=True,
    )
    parsed = load_policy(authority)
    write_snapshot(authority, parsed, read_version(authority, parsed))

    # When the unchanged generic copier consumes the new policy and manifest.
    destination = tmp_path / "future-source"
    copy_source_closure(authority, destination)

    # Then the newly declared byte is copied and bound without a filename rule.
    assert (destination / future_rel).read_bytes() == b"future input\n"
    verify_source_closure(authority, destination)


@unique
class ClosureMutation(StrEnum):
    MISSING = "missing"
    TAMPERED = "tampered"
    EXTRA = "extra"


@pytest.mark.parametrize("mutation", list(ClosureMutation))
def test_source_closure_refuses_missing_tampered_and_extra(
    tmp_path: Path, mutation: ClosureMutation
) -> None:
    # Given one exact disposable closure.
    authority = source_fixture(tmp_path / "minted")
    destination = tmp_path / "source"
    copy_source_closure(authority, destination)
    match mutation:
        case ClosureMutation.MISSING:
            (destination / "release" / "ingestion-performance-protocol.json").unlink()
            refusal = "source_closure_missing"
        case ClosureMutation.TAMPERED:
            target = destination / "ontologylab" / "storage-compatibility.json"
            target.write_bytes(target.read_bytes() + b"tampered")
            refusal = "source_closure_changed"
        case ClosureMutation.EXTRA:
            (destination / "runtime-generated.tmp").write_text(
                "extra\n", encoding="utf-8"
            )
            refusal = "source_closure_extra"
        case unreachable:
            assert_never(unreachable)

    # When closure verification reruns, then every non-exact state typed-refuses.
    with pytest.raises(CandidateRefused, match=refusal):
        verify_source_closure(authority, destination)
