"""Official immutable sqlite-vec 0.1.9 license override contract."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest

from ontologylab.release_policy_types import JsonValue
from release import candidate_licenses as licenses
from release.candidate_types import CandidateRefused

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = ROOT / "release" / "licenses" / "sqlite-vec" / "0.1.9"


def _runtime(tmp_path: Path, version: str = "0.1.9") -> Path:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "sbom.json").write_text(
        json.dumps(
            {
                "components": [
                    {
                        "name": "sqlite-vec",
                        "version": version,
                        "license": "MIT License, Apache License, Version 2.0",
                    }
                ],
                "licenses": [],
            }
        ),
        encoding="utf-8",
    )
    return runtime


def _override(tmp_path: Path) -> Path:
    destination = tmp_path / "override"
    shutil.copytree(OFFICIAL, destination)
    return destination


def _edit_provenance(
    root: Path, mutate: Callable[[dict[str, JsonValue]], None]
) -> None:
    target = root / "provenance.json"
    payload: JsonValue = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    mutate(payload)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_wheel_without_license_and_without_override_refuses(tmp_path: Path) -> None:
    # Given sqlite-vec wheel metadata with no distributed license files.
    runtime = _runtime(tmp_path)

    # When completeness runs without an approved override, then it refuses.
    with pytest.raises(CandidateRefused, match="license_evidence_missing.*sqlite-vec"):
        licenses.verify_license_completeness(runtime)


def test_unapproved_loose_override_text_refuses(tmp_path: Path) -> None:
    # Given a matching filename that was neither wheel-distributed nor approved.
    runtime = _runtime(tmp_path)
    loose = runtime / "licenses" / "sqlite-vec-0.1.9-LICENSE"
    loose.parent.mkdir()
    loose.write_text("unapproved text\n", encoding="utf-8")

    # When completeness runs, then filename resemblance cannot authorize evidence.
    with pytest.raises(CandidateRefused, match="license_evidence_missing.*sqlite-vec"):
        licenses.verify_license_completeness(runtime)


def test_exact_official_override_copies_both_texts_and_resolves_ambiguity(
    tmp_path: Path,
) -> None:
    # Given exact immutable upstream evidence for locked sqlite-vec 0.1.9.
    runtime = _runtime(tmp_path)
    override = _override(tmp_path)

    # When the offline override is applied and inventoried.
    licenses.apply_official_override(runtime, override)
    inventory = licenses.verify_license_completeness(runtime)
    components = inventory.get("components")
    assert isinstance(components, list) and len(components) == 1
    record = components[0]
    assert isinstance(record, dict)
    evidence = record.get("evidence")
    upstream = record.get("official_upstream_override")
    assert isinstance(evidence, list) and len(evidence) == 2
    assert isinstance(upstream, dict)

    # Then both exact texts and official provenance resolve the dual-license choice.
    assert record.get("resolved_license_expression") == "MIT OR Apache-2.0"
    assert record.get("declared_license_ambiguous") is True
    for item in evidence:
        assert isinstance(item, dict)
        source = item.get("source")
        assert isinstance(source, str)
        assert source.startswith("official-upstream-override:")
    assert upstream.get("commit") == "e9f598abfa0c06b328d8fe5da9c3760cce74be10"


def _wrong_tag(payload: dict[str, JsonValue]) -> None:
    payload["tag"] = "v0.1.8"


def _wrong_commit(payload: dict[str, JsonValue]) -> None:
    payload["commit"] = "0" * 40


def _wrong_version_hash(payload: dict[str, JsonValue]) -> None:
    version = payload["version_file"]
    assert isinstance(version, dict)
    version["sha256"] = "0" * 64


def _unapproved_schema(payload: dict[str, JsonValue]) -> None:
    payload["schema"] = "ontologylab.unapproved-license-override.v1"


@pytest.mark.parametrize(
    "mutate",
    [_wrong_tag, _wrong_commit, _wrong_version_hash, _unapproved_schema],
    ids=["tag", "commit", "version-hash", "unapproved"],
)
def test_wrong_or_unapproved_provenance_refuses(
    tmp_path: Path, mutate: Callable[[dict[str, JsonValue]], None]
) -> None:
    # Given one altered field in otherwise official provenance.
    runtime = _runtime(tmp_path)
    override = _override(tmp_path)
    _edit_provenance(override, mutate)

    # When the override boundary parses it, then it refuses before copying.
    with pytest.raises(CandidateRefused, match="license_override"):
        licenses.apply_official_override(runtime, override)


def test_wrong_package_version_refuses(tmp_path: Path) -> None:
    # Given exact evidence applied to a different resolved package version.
    runtime = _runtime(tmp_path, version="0.1.8")

    # When override application runs, then package/version mismatch refuses.
    with pytest.raises(CandidateRefused, match="license_override_package"):
        licenses.apply_official_override(runtime, _override(tmp_path))


@unique
class TextMutation(StrEnum):
    HASH = "hash"
    MISSING = "missing"


@pytest.mark.parametrize("mutation", list(TextMutation))
def test_wrong_or_missing_license_text_refuses(
    tmp_path: Path, mutation: TextMutation
) -> None:
    # Given one altered or absent official license text.
    runtime = _runtime(tmp_path)
    override = _override(tmp_path)
    target = override / "LICENSE-APACHE"
    match mutation:
        case TextMutation.HASH:
            target.write_bytes(target.read_bytes() + b"altered")
        case TextMutation.MISSING:
            target.unlink()
        case unreachable:
            assert_never(unreachable)

    # When override application runs, then exact-byte enforcement refuses.
    with pytest.raises(CandidateRefused, match="license_override"):
        licenses.apply_official_override(runtime, override)


def test_vendored_override_is_bound_by_snapshot_and_build_input_policy() -> None:
    # Given release-owned immutable override source.
    policy = json.loads(
        (ROOT / "release" / "release-policy.json").read_text(encoding="utf-8")
    )
    build_inputs = (ROOT / "release" / "candidate_stage.py").read_text(encoding="utf-8")

    # When Task 1 and Task 11 inputs are inspected, then both include its bytes.
    assert "release/licenses" in policy["source_inputs"]
    assert '"release/licenses",' in build_inputs
