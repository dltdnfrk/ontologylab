"""Immutable semantic research intent and non-semantic execution controls."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

from ontologylab.research_spec_codec import (
    _canonical,
    _enum_value,
    _error,
    _json,
    _spec_value,
    _text,
    build_evidence_need,
    build_research_spec,
    canonical_execution_controls,
    canonical_research_spec,
    execution_controls_hash,
    parse_execution_controls,
    parse_research_spec,
    research_spec_hash,
)
from ontologylab.research_spec_types import (
    ContentClass,
    EvidenceNeed,
    EvidenceNeedDraft,
    EvidenceNeedKind,
    EvidenceRecordClass,
    InteractionDecision,
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

__all__ = [
    "ContentClass",
    "EvidenceNeed",
    "EvidenceNeedDraft",
    "EvidenceNeedKind",
    "EvidenceRecordClass",
    "InteractionDecision",
    "InteractionPolicy",
    "JsonObject",
    "JsonValue",
    "ResearchExecutionControls",
    "ResearchOrigin",
    "ResearchSpec",
    "ResearchSpecDraft",
    "ResearchSpecParseError",
    "SourceEligibilityPolicy",
    "build_evidence_need",
    "build_research_spec",
    "canonical_execution_controls",
    "canonical_research_spec",
    "decide_interaction",
    "execution_controls_hash",
    "parse_execution_controls",
    "parse_research_spec",
    "research_spec_hash",
    "research_specs_semantically_equal",
]

_AMBIGUITIES: Final = frozenset(
    {"none", "multi_goal", "missing_topic", "unsafe_request", "unsupported_scope"}
)


def decide_interaction(origin: ResearchOrigin, ambiguity_kind: str) -> InteractionDecision:
    """Return the approved deterministic disposition; direct mode never clarifies."""
    if ambiguity_kind not in _AMBIGUITIES:
        raise _error("$.ambiguity_kind", "invalid_enum")
    if origin is ResearchOrigin.DIRECT_API:
        return InteractionDecision.EXECUTE if ambiguity_kind == "none" else InteractionDecision.ABSTAIN
    decisions = {
        "none": InteractionDecision.EXECUTE,
        "multi_goal": InteractionDecision.DECOMPOSE,
        "missing_topic": InteractionDecision.CLARIFY,
        "unsafe_request": InteractionDecision.ABSTAIN,
        "unsupported_scope": InteractionDecision.ABSTAIN,
    }
    return decisions[ambiguity_kind]


def research_specs_semantically_equal(
    left: ResearchSpec,
    right: ResearchSpec,
) -> bool:
    """Compare semantics while excluding lineage, origin, and interaction metadata."""
    excluded = {"spec_id", "parent_spec_id", "origin", "interaction_policy"}
    return {key: value for key, value in _spec_value(left).items() if key not in excluded} == {
        key: value for key, value in _spec_value(right).items() if key not in excluded
    }


def _fixture_receipt(path: Path) -> JsonObject:
    pairs = controls = 0
    for row_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = _json(line)
        required = frozenset(
            {
                "id", "chat_topic", "direct_topic", "direct_controls",
                "expected_normalized_goal",
            }
        )
        allowed = required | {"direct_origin", "direct_decision"}
        unknown = sorted(row.keys() - allowed)
        missing = sorted(required - row.keys())
        if unknown:
            raise _error(f"$[{row_number}].{unknown[0]}", "unknown_field")
        if missing:
            raise _error(f"$[{row_number}].{missing[0]}", "missing_field")
        origin = row.get("direct_origin", ResearchOrigin.DIRECT_API.value)
        decision = row.get("direct_decision", InteractionDecision.EXECUTE.value)
        parsed_origin = ResearchOrigin(
            _enum_value(ResearchOrigin, origin, f"$[{row_number}].direct_origin")
        )
        parsed_decision = InteractionDecision(
            _enum_value(
                InteractionDecision,
                decision,
                f"$[{row_number}].direct_decision",
            )
        )
        if parsed_origin is ResearchOrigin.DIRECT_API and parsed_decision is InteractionDecision.CLARIFY:
            raise _error(
                f"$[{row_number}].direct_decision",
                "direct_clarification_forbidden",
            )
        raw_controls = row["direct_controls"]
        if not isinstance(raw_controls, dict):
            raise _error(f"$[{row_number}].direct_controls", "expected_object")
        parsed_controls = parse_execution_controls(
            json.dumps(raw_controls, ensure_ascii=False, allow_nan=True)
        )
        if parsed_controls.to_json_value() != raw_controls:
            raise _error(f"$[{row_number}].direct_controls", "round_trip_mismatch")
        goal = _text(row["direct_topic"], f"$[{row_number}].direct_topic")
        expected_goal = _text(row["expected_normalized_goal"], f"$[{row_number}].expected_normalized_goal")
        if goal != expected_goal or _text(row["chat_topic"], f"$[{row_number}].chat_topic") != goal:
            raise _error(f"$[{row_number}].expected_normalized_goal", "semantic_mismatch")
        pairs += 1
        controls += 1
    return {"controls_round_tripped": controls, "pairs_semantically_equal": pairs}


def main(arguments: list[str] | None = None) -> int:
    """Validate the approved parity fixture without product-state writes."""
    argv = sys.argv[1:] if arguments is None else arguments
    if len(argv) != 2 or argv[0] != "--fixture":
        sys.stderr.write("$: expected --fixture PATH\n")
        return 2
    try:
        receipt = _fixture_receipt(Path(argv[1]))
    except (OSError, ResearchSpecParseError) as error:
        sys.stderr.write(f"{error}\n")
        return 2
    sys.stdout.buffer.write(_canonical(receipt) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
