"""Cross-check every release-critical eligibility claim against local truth."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

from ontologylab.release_eligibility_types import EligibilityClaim
from ontologylab.release_performance_evidence import verify_performance_files
from ontologylab.release_performance_types import (
    OutputCount,
    OutputSummary,
    ToolchainIdentity,
    parse_outputs,
)
from ontologylab.release_policy_types import (
    JsonValue,
    ReleasePolicy,
    ReleasePolicyCode,
    as_object,
    read_json,
    refuse,
)
from ontologylab.release_snapshot import SnapshotManifest
from ontologylab.release_task10_authority import verify_task10_authority

_CEILING_MS = 10195.704249618575
_STATISTIC = "nearest-rank-p95"
_EXPECTED_OPERATIONS = {
    "fixture_create_open_noop": ("existing", 3),
    "legacy_noop_migration_open": ("existing", 5),
    "current_ingest_create_and_duplicate": ("existing", 3),
    "current_pack_build": ("existing", 3),
}
_EXPECTED_OUTPUTS = OutputSummary(
    create=OutputCount(entries=9500, created=9500, conflicts=500, failures=0),
    duplicate=OutputCount(entries=9500, created=0, conflicts=500, failures=0),
)


def _sha(path: Path) -> str:
    if not path.is_file():
        refuse(ReleasePolicyCode.ELIGIBILITY_FIELD_DRIFT, path.as_posix())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _drift(actual, expected, member: str) -> None:
    if type(actual) is not type(expected) or actual != expected:
        refuse(ReleasePolicyCode.ELIGIBILITY_FIELD_DRIFT, member)


def _exact(
    value: JsonValue,
    keys: frozenset[str],
    member: str,
    code: ReleasePolicyCode,
) -> dict[str, JsonValue]:
    obj = as_object(value, member, code)
    if set(obj) != keys:
        refuse(code, member)
    return obj


def _fixture_semantics(root: Path, policy: ReleasePolicy) -> str:
    code = ReleasePolicyCode.FIXTURE_DRIFT
    raw = read_json(root, policy.fixture_manifest_path, code, code)
    obj = as_object(raw, policy.fixture_manifest_path, code)
    dataset = as_object(obj.get("dataset"), "dataset", code)
    if (
        obj.get("recipe_id") != "wave21-perf-v1"
        or obj.get("seed") != 20260820
        or dataset.get("documents") != 10000
        or dataset.get("legacy_doi_resolver_rows") != 500
        or dataset.get("doi_collision_ratio") != 0.05
        or dataset.get("same_bytes_different_doi_ratio") != 0.05
    ):
        refuse(code, "fixture.semantics")
    listed = obj.get("operations")
    if not isinstance(listed, list):
        refuse(code, "fixture.operations")
    operations: dict[str, tuple[str, int]] = {}
    for item in listed:
        operation = as_object(item, "fixture.operations", code)
        operation_id = operation.get("id")
        kind = operation.get("kind")
        samples = operation.get("n")
        if (
            not isinstance(operation_id, str)
            or not isinstance(kind, str)
            or type(samples) is not int
        ):
            refuse(code, "fixture.operations")
        operations[operation_id] = (kind, samples)
    if operations != _EXPECTED_OPERATIONS:
        refuse(code, "fixture.operations")
    forbidden = obj.get("forbidden")
    if not isinstance(forbidden, list):
        refuse(code, "fixture.forbidden")
    parsed_forbidden: list[str] = []
    for item in forbidden:
        if not isinstance(item, str):
            refuse(code, "fixture.forbidden")
        parsed_forbidden.append(item)
    semantics = {
        "recipe_id": obj["recipe_id"],
        "seed": obj["seed"],
        "dataset": {
            "documents": dataset["documents"],
            "legacy_doi_resolver_rows": dataset["legacy_doi_resolver_rows"],
            "doi_collision_ratio": dataset["doi_collision_ratio"],
            "same_bytes_different_doi_ratio": dataset["same_bytes_different_doi_ratio"],
        },
        "operations": {key: operations[key] for key in sorted(operations)},
        "forbidden": sorted(parsed_forbidden),
    }
    encoded = json.dumps(semantics, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _protocol(
    root: Path, policy: ReleasePolicy, semantics_sha256: str
) -> OutputSummary:
    code = ReleasePolicyCode.PROTOCOL_DRIFT
    raw = read_json(root, policy.benchmark_protocol_path, code, code)
    keys = frozenset(
        {
            "schema",
            "operation",
            "fixture_path",
            "recipe_id",
            "seed",
            "documents",
            "samples",
            "scratch",
            "statistic",
            "ceiling_ms",
            "outputs",
            "fixture_semantics_sha256",
        }
    )
    obj = _exact(raw, keys, "benchmark_protocol", code)
    expected = {
        "schema": "ontologylab.ingestion-performance-protocol.v1",
        "operation": "current_ingest_create_and_duplicate",
        "fixture_path": policy.fixture_manifest_path,
        "recipe_id": "wave21-perf-v1",
        "seed": 20260820,
        "documents": 10000,
        "samples": 3,
        "statistic": _STATISTIC,
        "ceiling_ms": _CEILING_MS,
        "fixture_semantics_sha256": semantics_sha256,
    }
    for key, value in expected.items():
        if obj.get(key) != value:
            refuse(code, f"benchmark_protocol.{key}")
    if obj.get("scratch") != {
        "cloud_sync": False,
        "filesystem": "apfs",
        "path_prefix": "/private/tmp",
    }:
        refuse(code, "benchmark_protocol.scratch")
    outputs = parse_outputs(obj["outputs"], "benchmark_protocol.outputs")
    if outputs != _EXPECTED_OUTPUTS:
        refuse(code, "benchmark_protocol.outputs")
    return outputs


def _toolchain() -> ToolchainIdentity:
    return ToolchainIdentity(
        implementation=platform.python_implementation(),
        python=platform.python_version(),
        machine=platform.machine(),
        platform=platform.platform(),
    )


def verify_eligibility(
    root: Path,
    policy: ReleasePolicy,
    manifest: SnapshotManifest,
    claim: EligibilityClaim,
) -> None:
    """Cross-check a structurally parsed GO against source and evidence truth."""
    verify_task10_authority(root, policy.task10_authority, claim.task10_authority)
    source = claim.source
    source_expected = {
        "snapshot_sha256": manifest.snapshot_sha256,
        "inventory_sha256": manifest.inventory_sha256,
        "git_status_sha256": manifest.git_status_sha256,
        "git_staged_diff_sha256": manifest.git_staged_diff_sha256,
        "git_unstaged_diff_sha256": manifest.git_unstaged_diff_sha256,
        "uv_lock_sha256": manifest.uv_lock.sha256,
        "policy_sha256": manifest.policy_sha256,
        "snapshot_manifest_sha256": _sha(root / policy.snapshot_manifest_path),
    }
    for key, expected in source_expected.items():
        _drift(getattr(source, key), expected, f"source.{key}")
    _drift(
        claim.source_snapshot_sha256, manifest.snapshot_sha256, "source_snapshot_sha256"
    )
    fixture_path = root / policy.fixture_manifest_path
    _drift(_sha(fixture_path), claim.fixture_manifest_sha256, "fixture.manifest_sha256")
    semantics_sha256 = _fixture_semantics(root, policy)
    _drift(semantics_sha256, claim.fixture_semantics_sha256, "fixture.semantics_sha256")
    _protocol(root, policy, semantics_sha256)
    _drift(
        _sha(root / policy.benchmark_protocol_path),
        claim.benchmark_protocol_sha256,
        "benchmark.protocol_sha256",
    )
    if claim.toolchain != _toolchain():
        refuse(ReleasePolicyCode.TOOLCHAIN_DRIFT, "toolchain")
    performance = claim.performance
    _drift(performance.ceiling_ms, _CEILING_MS, "performance.ceiling_ms")
    _drift(performance.statistic, _STATISTIC, "performance.statistic")
    if len(performance.samples_ms) != 3:
        refuse(ReleasePolicyCode.ELIGIBILITY_FIELD_DRIFT, "performance.samples_ms")
    ordered = sorted(performance.samples_ms)
    p95 = ordered[round(0.95 * (len(ordered) - 1))]
    _drift(performance.p95_ms, p95, "performance.p95_ms")
    if p95 > _CEILING_MS or performance.outputs != _EXPECTED_OUTPUTS:
        refuse(ReleasePolicyCode.ELIGIBILITY_FIELD_DRIFT, "performance")
    verify_performance_files(
        root,
        policy,
        manifest,
        claim,
        _EXPECTED_OUTPUTS,
        _CEILING_MS,
    )
