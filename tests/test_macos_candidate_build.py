"""Task 11 contracts for reproducible, credential-free macOS candidates."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from ontologylab.release_policy import load_policy
from ontologylab.release_policy_types import ReleasePolicyCode, ReleasePolicyRefused
from release import candidate_build as candidate
from release.candidate_stage import prepare_stage
from tests.macos_candidate_deployment_support import add_internal_deployment_fixture
from tests.macos_candidate_test_support import source_fixture

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_MODULE = ROOT / "release" / "candidate_build.py"
ENTRY = ROOT / "scripts" / "build-macos-candidate.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "macos-candidate.yml"


def _snapshot_fixture(tmp_path: Path) -> Path:
    return source_fixture(tmp_path)


def test_candidate_entry_and_workflow_are_present() -> None:
    # Given the release surfaces named by Task 11.
    # When the repository is inspected, then both controlled entries exist.
    assert ENTRY.is_file() and CANDIDATE_MODULE.is_file() and WORKFLOW.is_file()


def test_source_identity_refuses_post_snapshot_change_and_missing_lock(
    tmp_path: Path,
) -> None:
    # Given one immutable Task 1 snapshot.
    root = _snapshot_fixture(tmp_path)

    # When a snapshotted source byte changes, then candidate verification refuses it.
    source = root / "ontologylab" / "__init__.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8"
    )
    with pytest.raises(ReleasePolicyRefused) as changed:
        candidate.verify_source(root)
    assert changed.value.code is ReleasePolicyCode.SOURCE_CHANGED

    # Given a fresh snapshot whose lock disappears.
    root = _snapshot_fixture(tmp_path / "missing")
    (root / "uv.lock").unlink()
    # When verification runs, then absence is not reported as generic drift.
    with pytest.raises(ReleasePolicyRefused) as missing:
        candidate.verify_source(root)
    assert missing.value.code is ReleasePolicyCode.LOCK_MISSING


def test_source_identity_refuses_policy_and_version_drift(tmp_path: Path) -> None:
    # Given one immutable Task 1 snapshot.
    root = _snapshot_fixture(tmp_path)

    # When policy bytes drift, then the policy-specific refusal is emitted.
    policy = root / "release" / "release-policy.json"
    policy.write_bytes(policy.read_bytes() + b" ")
    with pytest.raises(ReleasePolicyRefused) as stale_policy:
        candidate.verify_source(root)
    assert stale_policy.value.code is ReleasePolicyCode.POLICY_CHANGED

    # Given a fresh snapshot whose version source drifts.
    root = _snapshot_fixture(tmp_path / "version")
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'version = "0.1.0"', 'version = "0.1.1"'
        ),
        encoding="utf-8",
    )
    # When verification runs, then version drift has a stable typed code.
    with pytest.raises(ReleasePolicyRefused) as stale_version:
        candidate.verify_source(root)
    assert stale_version.value.code is ReleasePolicyCode.VERSION_DRIFT


def test_host_gate_refuses_x86_and_old_macos(tmp_path: Path) -> None:
    # Given the arm64 macOS 15+ release policy.
    policy = load_policy(_snapshot_fixture(tmp_path))

    # When either architecture or OS is outside policy, then the host is refused.
    with pytest.raises(candidate.CandidateRefused, match="host_architecture"):
        candidate.verify_host(policy, candidate.HostProbe("x86_64", 15, "fixture"))
    with pytest.raises(candidate.CandidateRefused, match="host_macos"):
        candidate.verify_host(policy, candidate.HostProbe("arm64", 14, "fixture"))


def test_two_payloads_have_identical_normalized_manifests(tmp_path: Path) -> None:
    # Given two builds whose native/ad-hoc bytes differ but static bytes match.
    outputs: list[dict[str, str | list[candidate.TreeEntry]]] = []
    for name, native in (("a", b"native-a"), ("b", b"native-b")):
        payload = tmp_path / name
        (payload / "Contents" / "MacOS").mkdir(parents=True)
        (payload / "Contents" / "Resources").mkdir()
        (payload / "Contents" / "MacOS" / "helper").write_bytes(native)
        (payload / "Contents" / "Resources" / "asset.js").write_text(
            "const stable = true;\n", encoding="utf-8"
        )
        (payload / "Contents" / "Resources" / "keychain-helper.requirement").write_text(
            f"cdhash {name}\n", encoding="utf-8"
        )
        outputs.append(
            candidate.normalized_tree_manifest(
                payload,
                frozenset(
                    {
                        "Contents/MacOS/helper",
                        "Contents/Resources/keychain-helper.requirement",
                    }
                ),
            )
        )

    # When normalized unsigned manifests are compared, then they are identical.
    assert outputs[0] == outputs[1]


def test_nondeterministic_static_asset_is_refused(tmp_path: Path) -> None:
    # Given a baseline normalized manifest and a changed static asset.
    payload = tmp_path / "payload"
    payload.mkdir()
    asset = payload / "asset.js"
    asset.write_text("const value = 1;\n", encoding="utf-8")
    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps(
            candidate.normalized_tree_manifest(payload, frozenset()), sort_keys=True
        ),
        encoding="utf-8",
    )
    asset.write_text("const value = 2;\n", encoding="utf-8")
    actual = tmp_path / "actual.json"
    actual.write_text(
        json.dumps(
            candidate.normalized_tree_manifest(payload, frozenset()), sort_keys=True
        ),
        encoding="utf-8",
    )

    # When reproducibility comparison runs, then the changed asset is refused.
    with pytest.raises(candidate.CandidateRefused, match="normalized_manifest_drift"):
        candidate.verify_normalized_match(actual, expected)


def _add_license_fixture(payload: Path) -> None:
    resources = payload / "Contents" / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "storage-compatibility.json").write_bytes(
        (ROOT / "ontologylab" / "storage-compatibility.json").read_bytes()
    )
    runtime = resources / "runtime"
    metadata_dir = runtime / "_internal" / "fixture-1.0.dist-info"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "METADATA").write_text(
        "Name: fixture\nVersion: 1.0\nLicense: MIT\n", encoding="utf-8"
    )
    license_path = metadata_dir / "LICENSE"
    license_path.write_text("fixture license\n", encoding="utf-8")
    (runtime / "sbom.json").write_text(
        json.dumps(
            {
                "components": [{"name": "fixture", "version": "1.0", "license": "MIT"}],
                "licenses": [],
            }
        ),
        encoding="utf-8",
    )
    add_internal_deployment_fixture(payload)


def test_receipt_binds_identities_and_tree_is_frozen(tmp_path: Path) -> None:
    # Given a verified snapshot and assembled payload.
    root = _snapshot_fixture(tmp_path)
    source_identity = candidate.verify_source(root)
    candidate_root = tmp_path / "candidate"
    payload = candidate_root / "payload" / "OntologyLab.app"
    payload.mkdir(parents=True)
    (payload / "asset.txt").write_text("stable\n", encoding="utf-8")
    _add_license_fixture(payload)
    metadata = candidate.BuildMetadata(
        head="a" * 40,
        head_ref="refs/heads/main",
        status_diff_sha256="b" * 64,
        toolchain_sha256="c" * 64,
        build_inputs_sha256="d" * 64,
        overlay_manifest_sha256="e" * 64,
    )

    # When receipt generation completes.
    receipt_path = candidate.seal_candidate(candidate_root, source_identity, metadata)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    # Then source/lock/policy/HEAD/status/toolchain/build/tree identities are bound.
    assert receipt["source"]["snapshot_sha256"] == source_identity.snapshot_sha256
    assert receipt["source"]["uv_lock_sha256"] == source_identity.uv_lock_sha256
    assert receipt["source"]["policy_sha256"] == source_identity.policy_sha256
    assert receipt["git"]["head"] == metadata.head
    assert receipt["git"]["status_diff_sha256"] == metadata.status_diff_sha256
    assert receipt["toolchain_sha256"] == metadata.toolchain_sha256
    assert receipt["build_inputs_sha256"] == metadata.build_inputs_sha256
    assert receipt["build_overlay_manifest_sha256"] == metadata.overlay_manifest_sha256
    assert len(receipt["payload_tree_sha256"]) == 64
    assert not os.stat(candidate_root).st_mode & stat.S_IWUSR


def test_untrusted_pr_context_cannot_build_or_publish() -> None:
    # Given an untrusted pull-request event.
    # When publish eligibility is checked, then the event is refused.
    with pytest.raises(candidate.CandidateRefused, match="untrusted_event"):
        candidate.verify_event("pull_request")

    # Then workflow routing gives PRs validation only and no credential surface.
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow


def test_snapshot_symlink_is_refused_as_mutable_input(tmp_path: Path) -> None:
    # Given a valid snapshot reached through a mutable symlink.
    root = _snapshot_fixture(tmp_path)
    manifest = root / "release" / "source-snapshot.json"
    real = root / "release" / "source-snapshot.real.json"
    manifest.rename(real)
    manifest.symlink_to(real.name)

    # When source identity is consumed, then mutable indirection is refused.
    with pytest.raises(candidate.CandidateRefused, match="snapshot_indirection"):
        candidate.verify_source(root)


def test_stage_integrates_current_supervisor_without_editing_task4(
    tmp_path: Path,
) -> None:
    # Given the frozen Task 4 builder and a current immutable source snapshot.
    root = _snapshot_fixture(tmp_path)
    task4_builder = root / "scripts" / "build-macos-runtime.sh"
    original = task4_builder.read_bytes()

    # When Task 11 materializes its build stage.
    layout = prepare_stage(root, tmp_path / "stage")

    # Then derived build work sees the overlay while immutable source is untouched.
    staged_text = layout.builder.read_text(encoding="utf-8")
    assert "StorageQuiescence.swift" in staged_text
    assert '--with "typer==0.27.1"' in staged_text
    assert (root / "scripts" / "build-macos-runtime.sh").read_bytes() == original
    assert (
        layout.source_root / "scripts" / "build-macos-runtime.sh"
    ).read_bytes() == original


def test_candidate_entry_is_bounded_and_offline() -> None:
    # Given the local controlled build entry.
    assert ENTRY.is_file(), "local candidate build entry is absent"
    # When its orchestration is inspected, then hangs and network resolution are gated.
    text = ENTRY.read_text(encoding="utf-8")
    assert "UV_OFFLINE=1" in text
    assert "UV_FROZEN=1" in text
    assert "timeout" in text
    orchestration = "\n".join(
        (ROOT / "release" / name).read_text(encoding="utf-8")
        for name in ("candidate_cli.py", "candidate_stage.py")
    )
    assert "build-macos-runtime.sh" in orchestration
