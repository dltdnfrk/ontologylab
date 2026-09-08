"""Validate measured performance and causal mutation evidence files."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import assert_never

from ontologylab.release_eligibility_types import EligibilityClaim
from ontologylab.release_performance_types import (
    OutputCount,
    OutputSummary,
    parse_mutation_causality,
    parse_outputs,
    parse_toolchain,
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


def _sha(path: Path) -> str:
    if not path.is_file():
        refuse(ReleasePolicyCode.ELIGIBILITY_FIELD_DRIFT, path.as_posix())
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def verify_performance_files(
    root: Path,
    policy: ReleasePolicy,
    manifest: SnapshotManifest,
    claim: EligibilityClaim,
    expected_outputs: OutputSummary,
    ceiling_ms: float,
) -> None:
    """Bind raw samples and a killed/restored slow-path mutant to the GO."""
    performance = claim.performance
    evidence_path = root / policy.performance_evidence_path
    mutation_path = root / policy.mutation_receipt_path
    if _sha(evidence_path) != performance.evidence_sha256:
        refuse(ReleasePolicyCode.ELIGIBILITY_FIELD_DRIFT, "performance.evidence_sha256")
    if _sha(mutation_path) != performance.mutation_receipt_sha256:
        refuse(
            ReleasePolicyCode.ELIGIBILITY_FIELD_DRIFT,
            "performance.mutation_receipt_sha256",
        )
    evidence = read_json(
        root,
        policy.performance_evidence_path,
        ReleasePolicyCode.PERFORMANCE_EVIDENCE_INVALID,
        ReleasePolicyCode.PERFORMANCE_EVIDENCE_INVALID,
    )
    evidence_obj = _exact(
        evidence,
        frozenset(
            {
                "schema",
                "source_snapshot_sha256",
                "fixture_manifest_sha256",
                "benchmark_protocol_sha256",
                "toolchain",
                "samples_ms",
                "statistic",
                "p95_ms",
                "ceiling_ms",
                "outputs",
                "status",
            }
        ),
        "performance_evidence",
        ReleasePolicyCode.PERFORMANCE_EVIDENCE_INVALID,
    )
    comparisons = {
        "schema": "ontologylab.ingestion-performance-evidence.v1",
        "source_snapshot_sha256": manifest.snapshot_sha256,
        "fixture_manifest_sha256": claim.fixture_manifest_sha256,
        "benchmark_protocol_sha256": claim.benchmark_protocol_sha256,
        "samples_ms": list(performance.samples_ms),
        "statistic": performance.statistic,
        "p95_ms": performance.p95_ms,
        "ceiling_ms": performance.ceiling_ms,
        "status": "pass",
    }
    for key, expected in comparisons.items():
        if evidence_obj.get(key) != expected:
            refuse(ReleasePolicyCode.PERFORMANCE_EVIDENCE_INVALID, key)
    evidence_toolchain = parse_toolchain(
        evidence_obj["toolchain"], "performance_evidence.toolchain"
    )
    evidence_outputs = parse_outputs(
        evidence_obj["outputs"], "performance_evidence.outputs"
    )
    if evidence_toolchain != claim.toolchain or evidence_outputs != expected_outputs:
        refuse(ReleasePolicyCode.PERFORMANCE_EVIDENCE_INVALID, "measured_contract")
    mutation = read_json(
        root,
        policy.mutation_receipt_path,
        ReleasePolicyCode.MUTATION_RECEIPT_INVALID,
        ReleasePolicyCode.MUTATION_RECEIPT_INVALID,
    )
    mutation_obj = _exact(
        mutation,
        frozenset(
            {
                "schema",
                "source_snapshot_sha256",
                "fixture_manifest_sha256",
                "benchmark_protocol_sha256",
                "mutation_id",
                "p95_ms",
                "ceiling_ms",
                "test_exit",
                "outputs",
                "restored",
                "causality",
            }
        ),
        "mutation_receipt",
        ReleasePolicyCode.MUTATION_RECEIPT_INVALID,
    )
    p95 = mutation_obj.get("p95_ms")
    match p95:
        case bool():
            mutation_p95 = None
        case (int() | float()) as value:
            mutation_p95 = float(value)
        case str() | list() | dict() | None:
            mutation_p95 = None
        case unreachable:
            assert_never(unreachable)
    if (
        mutation_obj.get("schema") != "ontologylab.ingestion-performance-mutation.v2"
        or mutation_obj.get("source_snapshot_sha256") != manifest.snapshot_sha256
        or mutation_obj.get("fixture_manifest_sha256") != claim.fixture_manifest_sha256
        or mutation_obj.get("benchmark_protocol_sha256")
        != claim.benchmark_protocol_sha256
        or mutation_obj.get("mutation_id")
        != "restore-unbatched-duplicate-refinalization"
        or mutation_obj.get("ceiling_ms") != ceiling_ms
        or type(mutation_obj.get("test_exit")) is not int
        or mutation_obj.get("test_exit") == 0
        or mutation_obj.get("restored") is not True
        or mutation_p95 is None
        or (mutation_p95 is not None and mutation_p95 <= 0)
    ):
        refuse(ReleasePolicyCode.MUTATION_RECEIPT_INVALID, "mutation_receipt")
    mutation_outputs = parse_outputs(
        mutation_obj["outputs"], "mutation_receipt.outputs"
    )
    if mutation_outputs != expected_outputs:
        refuse(ReleasePolicyCode.MUTATION_RECEIPT_INVALID, "outputs")
    causality = parse_mutation_causality(
        mutation_obj["causality"], "mutation_receipt.causality"
    )
    causal_outputs = OutputSummary(
        create=OutputCount(entries=38, created=38, conflicts=2, failures=0),
        duplicate=OutputCount(entries=38, created=0, conflicts=2, failures=0),
    )
    if (
        causality.metric != "finalize_representation_calls"
        or causality.fixture_documents != 40
        or causality.normal_expected_finalizations != 38
        or causality.mutant_observed_finalizations
        <= causality.normal_expected_finalizations
        or causality.delta
        != causality.mutant_observed_finalizations
        - causality.normal_expected_finalizations
        or causality.relation != "mutant_observed_gt_normal_expected"
        or causality.test_failure != "finalization_count_mismatch"
        or causality.normal_outputs != causal_outputs
        or causality.mutant_outputs != causality.normal_outputs
    ):
        refuse(ReleasePolicyCode.MUTATION_RECEIPT_INVALID, "causality")
