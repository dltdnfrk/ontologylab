"""Strict machine boundary for exact-source release eligibility receipts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from ontologylab.release_performance_types import (
    OutputSummary,
    ToolchainIdentity,
    parse_outputs,
    parse_toolchain,
)
from ontologylab.release_policy_types import (
    JsonValue,
    ReleasePolicyCode,
    Task10Authority,
    as_object,
    read_json,
    refuse,
)
from ontologylab.release_task10_authority import parse_task10_authority


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    snapshot_sha256: str
    snapshot_manifest_sha256: str
    inventory_sha256: str
    git_status_sha256: str
    git_staged_diff_sha256: str
    git_unstaged_diff_sha256: str
    uv_lock_sha256: str
    policy_sha256: str


@dataclass(frozen=True, slots=True)
class PerformanceClaim:
    evidence_sha256: str
    mutation_receipt_sha256: str
    samples_ms: tuple[float, ...]
    statistic: str
    p95_ms: float
    ceiling_ms: float
    outputs: OutputSummary


@dataclass(frozen=True, slots=True)
class EligibilityClaim:
    version: str
    source_snapshot_sha256: str
    source: SourceIdentity
    task10_authority: Task10Authority
    fixture_manifest_sha256: str
    fixture_semantics_sha256: str
    benchmark_protocol_sha256: str
    toolchain: ToolchainIdentity
    performance: PerformanceClaim
    go: bool
    production_authorized: bool
    reasons: tuple[str, ...]


def _exact(
    value: JsonValue, keys: frozenset[str], member: str, code: ReleasePolicyCode
) -> dict[str, JsonValue]:
    obj = as_object(value, member, code)
    if set(obj) != keys:
        refuse(code, member)
    return obj


def _string(obj: dict[str, JsonValue], key: str, member: str) -> str:
    value = obj[key]
    if not isinstance(value, str) or not value:
        refuse(ReleasePolicyCode.RECEIPT_MALFORMED, member)
    return value


def _hash(obj: dict[str, JsonValue], key: str, member: str) -> str:
    value = _string(obj, key, member)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        refuse(ReleasePolicyCode.RECEIPT_MALFORMED, member)
    return value


def _number(obj: dict[str, JsonValue], key: str, member: str) -> float:
    match obj[key]:
        case bool():
            refuse(ReleasePolicyCode.RECEIPT_MALFORMED, member)
        case (int() | float()) as value:
            number = float(value)
        case str() | list() | dict() | None:
            refuse(ReleasePolicyCode.RECEIPT_MALFORMED, member)
        case unreachable:
            assert_never(unreachable)
    if not math.isfinite(number):
        refuse(ReleasePolicyCode.RECEIPT_MALFORMED, member)
    return number


def _source(value: JsonValue) -> SourceIdentity:
    ordered = (
        "snapshot_sha256",
        "snapshot_manifest_sha256",
        "inventory_sha256",
        "git_status_sha256",
        "git_staged_diff_sha256",
        "git_unstaged_diff_sha256",
        "uv_lock_sha256",
        "policy_sha256",
    )
    obj = _exact(
        value, frozenset(ordered), "source", ReleasePolicyCode.RECEIPT_MALFORMED
    )
    return SourceIdentity(*(_hash(obj, key, f"source.{key}") for key in ordered))


def _performance(value: JsonValue) -> PerformanceClaim:
    keys = frozenset(
        {
            "evidence_sha256",
            "mutation_receipt_sha256",
            "samples_ms",
            "statistic",
            "p95_ms",
            "ceiling_ms",
            "outputs",
        }
    )
    obj = _exact(value, keys, "performance", ReleasePolicyCode.RECEIPT_MALFORMED)
    listed = obj["samples_ms"]
    if not isinstance(listed, list) or not listed:
        refuse(ReleasePolicyCode.RECEIPT_MALFORMED, "performance.samples_ms")
    samples: list[float] = []
    for item in listed:
        match item:
            case bool():
                refuse(
                    ReleasePolicyCode.RECEIPT_MALFORMED,
                    "performance.samples_ms",
                )
            case (int() | float()) as value:
                sample = float(value)
            case str() | list() | dict() | None:
                refuse(
                    ReleasePolicyCode.RECEIPT_MALFORMED,
                    "performance.samples_ms",
                )
            case unreachable:
                assert_never(unreachable)
        if sample <= 0 or not math.isfinite(sample):
            refuse(ReleasePolicyCode.RECEIPT_MALFORMED, "performance.samples_ms")
        samples.append(sample)
    return PerformanceClaim(
        evidence_sha256=_hash(obj, "evidence_sha256", "performance.evidence_sha256"),
        mutation_receipt_sha256=_hash(
            obj, "mutation_receipt_sha256", "performance.mutation_receipt_sha256"
        ),
        samples_ms=tuple(samples),
        statistic=_string(obj, "statistic", "performance.statistic"),
        p95_ms=_number(obj, "p95_ms", "performance.p95_ms"),
        ceiling_ms=_number(obj, "ceiling_ms", "performance.ceiling_ms"),
        outputs=parse_outputs(obj["outputs"], "performance.outputs"),
    )


def parse_eligibility_claim(
    root: Path, receipt_rel: str, version: str
) -> EligibilityClaim:
    """Parse every authority-bearing receipt field before any GO decision."""
    code = ReleasePolicyCode.RECEIPT_MALFORMED
    raw = read_json(root, receipt_rel, ReleasePolicyCode.RECEIPT_MISSING, code)
    keys = frozenset(
        {
            "schema",
            "version",
            "source_snapshot_sha256",
            "source",
            "task10_authority",
            "fixture",
            "benchmark",
            "toolchain",
            "performance",
            "release",
        }
    )
    obj = _exact(raw, keys, receipt_rel, code)
    if _string(obj, "schema", "schema") != "ontologylab.release.eligibility.v2":
        refuse(code, "schema")
    receipt_version = _string(obj, "version", "version")
    if receipt_version != version:
        refuse(ReleasePolicyCode.VERSION_DRIFT, "receipt.version")
    fixture = _exact(
        obj["fixture"],
        frozenset({"manifest_sha256", "semantics_sha256"}),
        "fixture",
        code,
    )
    benchmark = _exact(
        obj["benchmark"], frozenset({"protocol_sha256"}), "benchmark", code
    )
    release = _exact(
        obj["release"],
        frozenset({"go", "production_authorized", "reasons"}),
        "release",
        code,
    )
    go = release["go"]
    authorized = release["production_authorized"]
    reasons = release["reasons"]
    if type(go) is not bool:
        refuse(ReleasePolicyCode.PRODUCTION_FLAG_NULL, "release.go")
    if type(authorized) is not bool:
        refuse(
            ReleasePolicyCode.PRODUCTION_FLAG_NULL,
            "release.production_authorized",
        )
    if not isinstance(reasons, list):
        refuse(code, "release.reasons")
    parsed_reasons: list[str] = []
    for item in reasons:
        if not isinstance(item, str):
            refuse(code, "release.reasons")
        parsed_reasons.append(item)
    return EligibilityClaim(
        version=receipt_version,
        source_snapshot_sha256=_hash(
            obj, "source_snapshot_sha256", "source_snapshot_sha256"
        ),
        source=_source(obj["source"]),
        task10_authority=parse_task10_authority(
            obj["task10_authority"],
            code=code,
            member="task10_authority",
        ),
        fixture_manifest_sha256=_hash(
            fixture, "manifest_sha256", "fixture.manifest_sha256"
        ),
        fixture_semantics_sha256=_hash(
            fixture, "semantics_sha256", "fixture.semantics_sha256"
        ),
        benchmark_protocol_sha256=_hash(
            benchmark, "protocol_sha256", "benchmark.protocol_sha256"
        ),
        toolchain=parse_toolchain(obj["toolchain"], "toolchain"),
        performance=_performance(obj["performance"]),
        go=go,
        production_authorized=authorized,
        reasons=tuple(parsed_reasons),
    )
