from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontologylab.research_spec import (
    InteractionDecision,
    InteractionPolicy,
    ResearchOrigin,
    ResearchSpecParseError,
    decide_interaction,
)
from ontologylab.research_spec import main as research_spec_main
from tests.research_contract_fixtures import load_fixture

_FIXTURE = Path(__file__).parent / "fixtures/research/interaction-policy.jsonl"
_PARITY_FIXTURE = Path(__file__).parent / "fixtures/research/chat-direct-parity.jsonl"


def test_all_approved_interaction_cases_have_the_typed_decision() -> None:
    # Given: all 60 approved chat/direct policy cases
    rows = load_fixture(_FIXTURE)

    # When: each case crosses the deterministic interaction policy
    actual: list[str] = []
    expected: list[str] = []
    for row in rows:
        origin = row["origin"]
        ambiguity = row["ambiguity_kind"]
        decision = row["expected_decision"]
        assert isinstance(origin, str)
        assert isinstance(ambiguity, str)
        assert isinstance(decision, str)
        actual.append(decide_interaction(ResearchOrigin(origin), ambiguity).value)
        expected.append(decision)

    # Then: every machine-consumed fixture decision matches
    assert actual == expected


def test_direct_policy_is_never_and_cannot_clarify() -> None:
    # Given/When: direct Research is missing material topic detail
    decision = decide_interaction(ResearchOrigin.DIRECT_API, "missing_topic")

    # Then: noninteractive policy abstains instead of asking
    assert InteractionPolicy.for_origin(ResearchOrigin.DIRECT_API) is InteractionPolicy.NEVER
    assert decision is InteractionDecision.ABSTAIN
    assert decision is not InteractionDecision.CLARIFY


@pytest.mark.parametrize(
    "ambiguity",
    ["none", "multi_goal", "missing_topic", "unsafe_request", "unsupported_scope"],
)
def test_chat_policy_is_selective_and_exhaustive(ambiguity: str) -> None:
    # Given/When/Then: every supported chat class returns one closed decision
    assert InteractionPolicy.for_origin(ResearchOrigin.CHAT) is InteractionPolicy.CHAT_SELECTIVE
    assert decide_interaction(ResearchOrigin.CHAT, ambiguity) in InteractionDecision


def test_fixture_cli_rejects_direct_clarification(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: one otherwise valid parity row requesting direct clarification
    row = json.loads(_PARITY_FIXTURE.read_text(encoding="utf-8").splitlines()[0])
    row["direct_decision"] = "clarify"
    fixture = tmp_path / "direct-clarify.jsonl"
    fixture.write_text(json.dumps(row) + "\n", encoding="utf-8")

    # When: the real fixture CLI crosses the noninteractive boundary
    exit_code = research_spec_main(["--fixture", str(fixture)])
    output = capsys.readouterr()

    # Then: it exits 2 with no partial success bytes
    assert exit_code == 2
    assert output.out == ""
    assert "$[1].direct_decision: direct_clarification_forbidden" in output.err


def test_fixture_cli_reports_nan_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: one parity row with NaN in a numeric direct control
    row = json.loads(_PARITY_FIXTURE.read_text(encoding="utf-8").splitlines()[0])
    row["direct_controls"]["limit"] = float("nan")
    fixture = tmp_path / "nan.jsonl"
    fixture.write_text(json.dumps(row, allow_nan=True) + "\n", encoding="utf-8")

    # When: the real fixture CLI parses the malformed control
    exit_code = research_spec_main(["--fixture", str(fixture)])
    output = capsys.readouterr()

    # Then: it exits 2 at the stable field path without partial output
    assert exit_code == 2
    assert output.out == ""
    assert "$.limit: non_finite_number" in output.err


def test_interaction_policy_rejects_unknown_ambiguity() -> None:
    # Given/When: an unapproved classifier result crosses the policy boundary
    with pytest.raises(ResearchSpecParseError) as raised:
        decide_interaction(ResearchOrigin.CHAT, "invented")

    # Then: failure has a stable machine-readable path
    assert (raised.value.path, raised.value.code) == ("$.ambiguity_kind", "invalid_enum")
