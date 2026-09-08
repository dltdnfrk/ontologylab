"""Task 11 build-completion drift and final frozen payload integrity."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest

from release import candidate_build as candidate
from release import candidate_cli
from release.candidate_source_closure import copy_source_closure, verify_source_closure
from release.candidate_stage import (
    StageLayout,
    build_input_payload,
    derive_build_work,
    prepare_stage,
    verify_overlay,
)
from tests.macos_candidate_test_support import (
    add_license_fixture,
    metadata,
    source_fixture,
)


@unique
class Mutation(StrEnum):
    APPROVED_SOURCE = "approved-source"
    STATUS = "status"


@pytest.mark.parametrize("mutation", list(Mutation))
def test_build_refuses_full_context_mutation_at_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Mutation,
) -> None:
    # Given a bounded build with an exact mutation at its completion event.
    root = source_fixture(tmp_path)
    output = tmp_path / "candidate"
    contexts = iter((metadata("a"), metadata("b")))
    monkeypatch.setattr(
        candidate_cli,
        "_host_probe",
        lambda _root: candidate.HostProbe("arm64", 15, "fixture"),
    )
    monkeypatch.setattr(candidate_cli, "verify_host", lambda _policy, _probe: None)
    monkeypatch.setattr(candidate_cli, "_metadata", lambda _root, _dir: next(contexts))
    monkeypatch.setattr(candidate_cli, "verify_overlay", lambda _layout: None)
    monkeypatch.setattr(candidate_cli, "_venv_leaks", lambda _root: [])

    def _prepare(_root: Path, stage: Path) -> StageLayout:
        source_root = stage / "source_stage"
        build_root = stage / "build_work"
        (stage.parent / "candidate" / "metadata").mkdir(parents=True)
        builder = build_root / "scripts" / "build-macos-runtime.sh"
        builder.parent.mkdir(parents=True)
        builder.write_text("#!/bin/sh\n", encoding="utf-8")
        manifest = stage / "build-overlay-manifest.json"
        manifest.write_text("{}\n", encoding="utf-8")
        return StageLayout(
            source_root=source_root,
            build_root=build_root,
            builder=builder,
            overlay_manifest_path=manifest,
            overlay={
                "schema": "fixture",
                "source_script_sha256": "a" * 64,
                "generator_sha256": "b" * 64,
                "uv_lock_sha256": "c" * 64,
                "typer_version": "0.0.0",
                "extra_swift_sources": [],
                "supervisor_inventory_sha256": "d" * 64,
                "overlay_sha256": "e" * 64,
                "overlay_bytes": 10,
                "overlay_mode": "0o555",
            },
        )

    def _mutate_at_completion(
        request: candidate_cli.PayloadRun,
    ) -> subprocess.CompletedProcess[str]:
        command = request.command
        runtime_output = Path(command[command.index("--out") + 1])
        app = runtime_output / "OntologyLab.app"
        app.mkdir(parents=True)
        (app / "payload.txt").write_text("built\n", encoding="utf-8")
        match mutation:
            case Mutation.APPROVED_SOURCE:
                (root / "ontologylab" / "__init__.py").write_text(
                    "fixture = False\n", encoding="utf-8"
                )
            case Mutation.STATUS:
                (root / "status-drift.txt").write_text("drift\n", encoding="utf-8")
            case unreachable:
                assert_never(unreachable)
        return subprocess.CompletedProcess(command, 0, "complete\n", "")

    def _seal(
        candidate_root: Path,
        _source: candidate.SourceIdentity,
        _build: candidate.BuildMetadata,
    ) -> Path:
        receipt = candidate_root / "candidate-receipt.json"
        receipt.write_text("{}\n", encoding="utf-8")
        return receipt

    monkeypatch.setattr(candidate_cli, "prepare_stage", _prepare)
    monkeypatch.setattr(candidate_cli, "run_payload", _mutate_at_completion)
    monkeypatch.setattr(candidate_cli, "seal_candidate", _seal)

    # When completion is observed, then drift refuses before receipt and removes output.
    with pytest.raises(candidate.CandidateRefused, match="build_context_changed"):
        candidate_cli.build(candidate_cli.BuildRequest(root, output, 30, None))
    assert not output.exists()


def test_authoritative_stage_tamper_refuses_before_overlay(tmp_path: Path) -> None:
    # Given an exact source stage changed before build derivation.
    root = source_fixture(tmp_path)
    source_stage = tmp_path / "staging" / "source_stage"
    copy_source_closure(root, source_stage)
    script = source_stage / "scripts" / "build-macos-runtime.sh"
    script.write_bytes(script.read_bytes() + b"tampered")

    # When build work derivation starts, then source verification refuses first.
    with pytest.raises(candidate.CandidateRefused, match="source_closure_changed"):
        derive_build_work(root, source_stage, tmp_path / "staging")


def test_overlay_is_separate_traceable_and_source_stage_stays_exact(
    tmp_path: Path,
) -> None:
    # Given one exact source authority.
    root = source_fixture(tmp_path)
    source_sha = hashlib.sha256(
        (root / "scripts" / "build-macos-runtime.sh").read_bytes()
    ).hexdigest()

    # When source staging and overlay derivation complete.
    layout = prepare_stage(root, tmp_path / "staging")
    verify_overlay(layout)
    verify_source_closure(root, layout.source_root)
    build_inputs = build_input_payload(root).get("files")
    assert isinstance(build_inputs, list)
    generated = {item["path"]: item for item in build_inputs}

    # Then source bytes stay exact and overlay script/manifest are independently bound.
    assert layout.overlay["source_script_sha256"] == source_sha
    assert (
        hashlib.sha256(layout.builder.read_bytes()).hexdigest()
        == layout.overlay["overlay_sha256"]
    )
    assert (
        layout.builder.read_bytes()
        != (layout.source_root / "scripts" / "build-macos-runtime.sh").read_bytes()
    )
    assert (
        generated["generated/scripts/build-macos-runtime.sh"]["sha256"]
        == layout.overlay["overlay_sha256"]
    )
    assert "generated/build-overlay-manifest.json" in generated


@unique
class OverlayMutation(StrEnum):
    BYTES = "bytes"
    OPTIONS = "options"


@pytest.mark.parametrize("mutation", list(OverlayMutation))
def test_overlay_or_bound_options_drift_refuses(
    tmp_path: Path, mutation: OverlayMutation
) -> None:
    # Given one verified derived build overlay.
    root = source_fixture(tmp_path)
    layout = prepare_stage(root, tmp_path / "staging")
    match mutation:
        case OverlayMutation.BYTES:
            layout.builder.chmod(0o755)
            layout.builder.write_bytes(layout.builder.read_bytes() + b"drift")
        case OverlayMutation.OPTIONS:
            layout.overlay_manifest_path.chmod(0o644)
            layout.overlay_manifest_path.write_bytes(b"{}\n")
        case unreachable:
            assert_never(unreachable)

    # When overlay authority is rechecked, then drift refuses before execution.
    with pytest.raises(candidate.CandidateRefused, match="build_overlay"):
        verify_overlay(layout)


def test_payload_tree_inventory_matches_modes_after_final_freeze(
    tmp_path: Path,
) -> None:
    # Given an executable payload sealed by the candidate boundary.
    root = source_fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    payload = candidate_root / "payload" / "OntologyLab.app"
    payload.mkdir(parents=True)
    executable = payload / "helper"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    add_license_fixture(payload)

    # When the delivered frozen tree is recomputed from disk.
    receipt_path = candidate.seal_candidate(
        candidate_root, candidate.verify_source(root), metadata()
    )
    inventory = json.loads(
        (candidate_root / "inventories" / "payload-tree.json").read_text(
            encoding="utf-8"
        )
    )
    delivered = candidate.tree_manifest(payload)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    final_payload = {**inventory, "entries": delivered}
    final_sha = hashlib.sha256(
        json.dumps(final_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    # Then paths, kinds, bytes, modes, and hash exactly describe delivered payload.
    assert inventory["entries"] == delivered
    assert receipt["payload_tree_sha256"] == final_sha
    assert executable.stat().st_mode & stat.S_IXUSR
    assert all(entry["mode"] in {"0o444", "0o555"} for entry in delivered)
