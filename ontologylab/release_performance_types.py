"""Typed toolchain and benchmark-output values shared by release evidence."""

from __future__ import annotations

from dataclasses import dataclass

from ontologylab.release_policy_types import (
    JsonValue,
    ReleasePolicyCode,
    as_object,
    refuse,
)


@dataclass(frozen=True, slots=True)
class ToolchainIdentity:
    implementation: str
    python: str
    machine: str
    platform: str


@dataclass(frozen=True, slots=True)
class OutputCount:
    entries: int
    created: int
    conflicts: int
    failures: int


@dataclass(frozen=True, slots=True)
class OutputSummary:
    create: OutputCount
    duplicate: OutputCount


@dataclass(frozen=True, slots=True)
class MutationCausality:
    metric: str
    fixture_documents: int
    normal_expected_finalizations: int
    mutant_observed_finalizations: int
    delta: int
    relation: str
    test_failure: str
    normal_outputs: OutputSummary
    mutant_outputs: OutputSummary


def _exact(value: JsonValue, keys: frozenset[str], member: str) -> dict[str, JsonValue]:
    obj = as_object(value, member, ReleasePolicyCode.RECEIPT_MALFORMED)
    if set(obj) != keys:
        refuse(ReleasePolicyCode.RECEIPT_MALFORMED, member)
    return obj


def _string(obj: dict[str, JsonValue], key: str, member: str) -> str:
    value = obj[key]
    if not isinstance(value, str) or not value:
        refuse(ReleasePolicyCode.RECEIPT_MALFORMED, member)
    return value


def parse_toolchain(value: JsonValue, member: str) -> ToolchainIdentity:
    obj = _exact(
        value,
        frozenset({"implementation", "python", "machine", "platform"}),
        member,
    )
    return ToolchainIdentity(
        implementation=_string(obj, "implementation", f"{member}.implementation"),
        python=_string(obj, "python", f"{member}.python"),
        machine=_string(obj, "machine", f"{member}.machine"),
        platform=_string(obj, "platform", f"{member}.platform"),
    )


def _output(value: JsonValue, member: str) -> OutputCount:
    obj = _exact(
        value,
        frozenset({"entries", "created", "conflicts", "failures"}),
        member,
    )
    values: list[int] = []
    for key in ("entries", "created", "conflicts", "failures"):
        raw = obj[key]
        if type(raw) is not int or raw < 0:
            refuse(ReleasePolicyCode.RECEIPT_MALFORMED, f"{member}.{key}")
        values.append(raw)
    return OutputCount(*values)


def parse_outputs(value: JsonValue, member: str) -> OutputSummary:
    obj = _exact(value, frozenset({"create", "duplicate"}), member)
    return OutputSummary(
        create=_output(obj["create"], f"{member}.create"),
        duplicate=_output(obj["duplicate"], f"{member}.duplicate"),
    )


def parse_mutation_causality(value: JsonValue, member: str) -> MutationCausality:
    keys = frozenset(
        {
            "metric",
            "fixture_documents",
            "normal_expected_finalizations",
            "mutant_observed_finalizations",
            "delta",
            "relation",
            "test_failure",
            "normal_outputs",
            "mutant_outputs",
        }
    )
    obj = _exact(value, keys, member)
    integers: list[int] = []
    for key in (
        "fixture_documents",
        "normal_expected_finalizations",
        "mutant_observed_finalizations",
        "delta",
    ):
        raw = obj[key]
        if type(raw) is not int or raw < 0:
            refuse(ReleasePolicyCode.RECEIPT_MALFORMED, f"{member}.{key}")
        integers.append(raw)
    return MutationCausality(
        metric=_string(obj, "metric", f"{member}.metric"),
        fixture_documents=integers[0],
        normal_expected_finalizations=integers[1],
        mutant_observed_finalizations=integers[2],
        delta=integers[3],
        relation=_string(obj, "relation", f"{member}.relation"),
        test_failure=_string(obj, "test_failure", f"{member}.test_failure"),
        normal_outputs=parse_outputs(obj["normal_outputs"], f"{member}.normal_outputs"),
        mutant_outputs=parse_outputs(obj["mutant_outputs"], f"{member}.mutant_outputs"),
    )
