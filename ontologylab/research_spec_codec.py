from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import replace
from enum import StrEnum
from typing import Final

from ontologylab.research_spec_types import (
    _CONTROL_FIELDS,
    ContentClass,
    EvidenceNeed,
    EvidenceNeedDraft,
    EvidenceNeedKind,
    InteractionPolicy,
    JsonObject,
    JsonValue,
    ResearchExecutionControls,
    ResearchOrigin,
    ResearchSpec,
    ResearchSpecDraft,
    ResearchSpecParseError,
    SourceEligibilityPolicy,
)

_SPEC_FIELDS: Final = frozenset([
    "schema_version", "spec_id", "parent_spec_id", "origin", "goal", "explicit_constraints",
    "evidence_needs", "assumptions",
    "interaction_policy", "source_eligibility_policy",
])


def _error(path: str, code: str) -> ResearchSpecParseError:
    return ResearchSpecParseError(path, code)


def _text(value: JsonValue, path: str) -> str:
    if not isinstance(value, str):
        raise _error(path, "expected_string")
    result = " ".join(unicodedata.normalize("NFC", value).split())
    if not result:
        raise _error(path, "empty_string")
    return result


def _ordered_text(values: JsonValue, path: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise _error(path, "expected_array")
    result: list[str] = []
    for index, value in enumerate(values):
        item = _text(value, f"{path}[{index}]")
        if item not in result:
            result.append(item)
    return tuple(result)


def _control_strings(values: JsonValue, path: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise _error(path, "expected_array")
    return tuple(_text(value, f"{path}[{index}]") for index, value in enumerate(values))


def _json(raw: str | bytes) -> JsonObject:
    try:
        value: JsonValue = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise _error("$", "invalid_json") from error
    if not isinstance(value, dict):
        raise _error("$", "expected_object")
    return value


def _exact(payload: JsonObject, fields: frozenset[str], path: str = "$") -> None:
    unknown, missing = sorted(payload.keys() - fields), sorted(fields - payload.keys())
    if unknown:
        raise _error(f"{path}.{unknown[0]}", "unknown_field")
    if missing:
        raise _error(f"{path}.{missing[0]}", "missing_field")


def _integer(value: JsonValue, path: str) -> int:
    if isinstance(value, float) and not math.isfinite(value):
        raise _error(path, "non_finite_number")
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(path, "expected_number")
    return value


def _number(value: JsonValue, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(path, "expected_number")
    result = float(value)
    if not math.isfinite(result):
        raise _error(path, "non_finite_number")
    return result


def _canonical(payload: JsonObject) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _need_value(need: EvidenceNeed) -> JsonObject:
    return {
        "need_id": need.need_id,
        "kind": need.kind.value,
        "description": need.description,
        "mandatory": need.mandatory,
        "minimum_content": need.minimum_content.value,
    }


def _spec_value(spec: ResearchSpec, *, identity: bool = True) -> JsonObject:
    payload: JsonObject = {
        "schema_version": spec.schema_version, "parent_spec_id": spec.parent_spec_id,
        "origin": spec.origin.value, "goal": spec.goal,
        "explicit_constraints": list(spec.explicit_constraints),
        "evidence_needs": [_need_value(need) for need in spec.evidence_needs],
        "assumptions": list(spec.assumptions),
        "interaction_policy": spec.interaction_policy.value,
        "source_eligibility_policy": {
            "policy_version": spec.source_eligibility_policy.policy_version
        },
    }
    if identity:
        payload["spec_id"] = spec.spec_id
    return payload


def build_evidence_need(draft: EvidenceNeedDraft) -> EvidenceNeed:
    """Normalize a need and derive its stable ID, honoring an explicit override."""
    description = _text(draft.description, "$.evidence_need.description")
    minimum = draft.minimum_content_override
    if minimum is None:
        minimum = SourceEligibilityPolicy().minimum_content(draft.kind)
    payload: JsonObject = {
        "kind": draft.kind.value,
        "description": description,
        "mandatory": draft.mandatory,
        "minimum_content": minimum.value,
    }
    need_id = "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()
    return EvidenceNeed(need_id, draft.kind, description, draft.mandatory, minimum)


def build_research_spec(draft: ResearchSpecDraft) -> ResearchSpec:
    """Normalize semantic text and derive an ID over the payload without its ID."""
    if draft.interaction_policy is not InteractionPolicy.for_origin(draft.origin):
        raise _error("$.interaction_policy", "origin_policy_mismatch")
    needs = tuple(
        build_evidence_need(EvidenceNeedDraft(
            need.kind, need.description, need.mandatory, need.minimum_content,
        ))
        for need in draft.evidence_needs
    )
    provisional = ResearchSpec(
        _text(draft.schema_version, "$.schema_version"), "", draft.parent_spec_id,
        draft.origin, _text(draft.goal, "$.goal"),
        _ordered_text(list(draft.explicit_constraints), "$.explicit_constraints"),
        needs, _ordered_text(list(draft.assumptions), "$.assumptions"),
        draft.interaction_policy, draft.source_eligibility_policy,
    )
    identity = hashlib.sha256(_canonical(_spec_value(provisional, identity=False)))
    return replace(provisional, spec_id="sha256:" + identity.hexdigest())


def canonical_research_spec(spec: ResearchSpec) -> bytes:
    """Return deterministic sorted-key UTF-8 JSON with no timestamps."""
    return _canonical(_spec_value(spec))


def research_spec_hash(spec: ResearchSpec) -> str:
    """Hash the complete canonical artifact, including its verified identity."""
    return "sha256:" + hashlib.sha256(canonical_research_spec(spec)).hexdigest()


def canonical_execution_controls(controls: ResearchExecutionControls) -> bytes:
    """Return deterministic sorted-key UTF-8 JSON for execution controls."""
    return _canonical(controls.to_json_value())


def execution_controls_hash(controls: ResearchExecutionControls) -> str:
    """Hash the complete canonical execution-control payload."""
    return "sha256:" + hashlib.sha256(canonical_execution_controls(controls)).hexdigest()


def parse_execution_controls(raw: str | bytes) -> ResearchExecutionControls:
    """Strictly parse every direct execution control without defaults."""
    payload = _json(raw)
    _exact(payload, frozenset(_CONTROL_FIELDS))
    sources = _control_strings(payload["sources"], "$.sources")
    fulltext, citations = payload["fulltext"], payload["citation_expansion"]
    if not isinstance(fulltext, bool):
        raise _error("$.fulltext", "expected_boolean")
    if not isinstance(citations, bool):
        raise _error("$.citation_expansion", "expected_boolean")
    model = payload["model"]
    if model is not None:
        model = _text(model, "$.model")
    return ResearchExecutionControls(
        sources, _integer(payload["limit"], "$.limit"),
        _integer(payload["max_queries"], "$.max_queries"), fulltext, citations,
        _integer(payload["citation_seed_count"], "$.citation_seed_count"),
        _integer(payload["citation_limit"], "$.citation_limit"),
        _text(payload["engine"], "$.engine"), model,
        _integer(payload["max_engine_calls"], "$.max_engine_calls"),
        _number(payload["time_budget"], "$.time_budget"),
        _integer(payload["seed"], "$.seed"),
    )


def _enum_value(enum_type: type[StrEnum], value: JsonValue, path: str) -> StrEnum:
    try:
        return enum_type(_text(value, path))
    except ValueError as error:
        raise _error(path, "invalid_enum") from error


def parse_research_spec(raw: str | bytes) -> ResearchSpec:
    """Strictly parse, normalize, and verify a canonical ResearchSpec."""
    payload = _json(raw)
    _exact(payload, _SPEC_FIELDS)
    raw_needs = payload["evidence_needs"]
    if not isinstance(raw_needs, list):
        raise _error("$.evidence_needs", "expected_array")
    needs: list[EvidenceNeed] = []
    for index, raw_need in enumerate(raw_needs):
        if not isinstance(raw_need, dict):
            raise _error(f"$.evidence_needs[{index}]", "expected_object")
        need_path = f"$.evidence_needs[{index}]"
        _exact(
            raw_need,
            frozenset(
                {"need_id", "kind", "description", "mandatory", "minimum_content"}
            ),
            need_path,
        )
        mandatory = raw_need["mandatory"]
        if not isinstance(mandatory, bool):
            raise _error(f"{need_path}.mandatory", "expected_boolean")
        kind = EvidenceNeedKind(
            _enum_value(EvidenceNeedKind, raw_need["kind"], f"{need_path}.kind")
        )
        minimum = ContentClass(
            _enum_value(
                ContentClass, raw_need["minimum_content"],
                f"{need_path}.minimum_content",
            )
        )
        need = build_evidence_need(
            EvidenceNeedDraft(
                kind, _text(raw_need["description"], f"{need_path}.description"),
                mandatory, minimum,
            )
        )
        if raw_need["need_id"] != need.need_id:
            raise _error(f"{need_path}.need_id", "hash_mismatch")
        needs.append(need)
    raw_policy = payload["source_eligibility_policy"]
    if not isinstance(raw_policy, dict):
        raise _error("$.source_eligibility_policy", "expected_object")
    _exact(raw_policy, frozenset({"policy_version"}), "$.source_eligibility_policy")
    policy_path = "$.source_eligibility_policy.policy_version"
    policy_version = _text(raw_policy["policy_version"], policy_path)
    if policy_version != "source-eligibility-v1":
        raise _error(policy_path, "invalid_enum")
    origin = ResearchOrigin(_enum_value(ResearchOrigin, payload["origin"], "$.origin"))
    policy = InteractionPolicy(
        _enum_value(InteractionPolicy, payload["interaction_policy"], "$.interaction_policy")
    )
    parent = payload["parent_spec_id"]
    if parent is not None and not isinstance(parent, str):
        raise _error("$.parent_spec_id", "expected_string_or_null")
    draft = ResearchSpecDraft(
        _text(payload["schema_version"], "$.schema_version"), parent, origin,
        _text(payload["goal"], "$.goal"),
        _ordered_text(payload["explicit_constraints"], "$.explicit_constraints"),
        tuple(needs), _ordered_text(payload["assumptions"], "$.assumptions"),
        policy, SourceEligibilityPolicy(policy_version),
    )
    spec = build_research_spec(draft)
    if payload["spec_id"] != spec.spec_id:
        raise _error("$.spec_id", "hash_mismatch")
    return spec
