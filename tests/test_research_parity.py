from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontologylab import research_spec
from ontologylab.research_plan import PlannerReading
from tests.research_contract_fixtures import load_fixture
from tests.research_route_contract_helpers import build_start_input

_FIXTURE = Path(__file__).parent / "fixtures/research/chat-direct-parity.jsonl"
_PARITY_ROWS = load_fixture(_FIXTURE)


def _reading(goal: str) -> PlannerReading:
    normalized = " ".join(goal.split())
    need = research_spec.build_evidence_need(
        research_spec.EvidenceNeedDraft(
            research_spec.EvidenceNeedKind.GENERAL,
            normalized,
            True,
            research_spec.ContentClass.ABSTRACT,
        )
    )
    return PlannerReading(normalized, (need,), (), (), None)


@pytest.mark.parametrize(
    "row", _PARITY_ROWS, ids=[str(row["id"]) for row in _PARITY_ROWS]
)
def test_all_40_chat_direct_pairs_compile_to_equal_semantics(row) -> None:
    direct_topic = row["direct_topic"]
    chat_topic = row["chat_topic"]
    expected_goal = row["expected_normalized_goal"]
    controls = row["direct_controls"]
    assert isinstance(direct_topic, str)
    assert isinstance(chat_topic, str)
    assert isinstance(expected_goal, str)
    assert isinstance(controls, dict)
    execution = research_spec.parse_execution_controls(json.dumps(controls))

    direct = build_start_input(
        topic=direct_topic,
        origin=research_spec.ResearchOrigin.DIRECT_API,
        decision=research_spec.InteractionDecision.EXECUTE,
        controls=execution,
    )
    chat = build_start_input(
        topic=chat_topic,
        origin=research_spec.ResearchOrigin.CHAT,
        decision=research_spec.InteractionDecision.EXECUTE,
        controls=execution,
    )
    direct_spec = direct.compile(_reading(direct.topic))
    chat_spec = chat.compile(_reading(chat.topic))

    assert direct.topic == chat.topic == expected_goal
    assert direct.controls.to_json_value() == controls
    assert set(direct.controls.to_json_value()) == set(
        research_spec.ResearchExecutionControls.field_names()
    )
    assert direct.origin is research_spec.ResearchOrigin.DIRECT_API
    assert direct.interaction_policy is research_spec.InteractionPolicy.NEVER
    assert chat.origin is research_spec.ResearchOrigin.CHAT
    assert (
        chat.interaction_policy
        is research_spec.InteractionPolicy.CHAT_SELECTIVE
    )
    assert direct_spec.goal == chat_spec.goal == expected_goal
    assert research_spec.research_specs_semantically_equal(
        direct_spec, chat_spec
    )
