from __future__ import annotations

import dataclasses
import json
from functools import partial
from pathlib import Path

import pytest

from ontologylab.research_spec import (
    ContentClass,
    EvidenceNeedDraft,
    EvidenceNeedKind,
    EvidenceRecordClass,
    InteractionPolicy,
    ResearchExecutionControls,
    ResearchOrigin,
    ResearchSpecDraft,
    ResearchSpecParseError,
    SourceEligibilityPolicy,
    build_evidence_need,
    build_research_spec,
    canonical_execution_controls,
    canonical_research_spec,
    execution_controls_hash,
    parse_execution_controls,
    parse_research_spec,
    research_spec_hash,
    research_specs_semantically_equal,
)
from tests.research_contract_fixtures import load_fixture

_ELIGIBILITY_FIXTURE = (
    Path(__file__).parent / "fixtures/research/source-eligibility.jsonl"
)


def _draft(origin: ResearchOrigin = ResearchOrigin.CHAT) -> ResearchSpecDraft:
    return ResearchSpecDraft(
        schema_version="research-spec-v1",
        parent_spec_id=None,
        origin=origin,
        goal="  Cafe\u0301   yield\n response  ",
        explicit_constraints=(" orchards ", "NFC Cafe\u0301", "orchards"),
        evidence_needs=(
            build_evidence_need(
                EvidenceNeedDraft(
                    kind=EvidenceNeedKind.RESULT,
                    description=" measured  yield ",
                    mandatory=True,
                    minimum_content_override=None,
                )
            ),
        ),
        assumptions=(" mature trees ", "mature trees"),
        interaction_policy=(
            InteractionPolicy.CHAT_SELECTIVE
            if origin is ResearchOrigin.CHAT
            else InteractionPolicy.NEVER
        ),
        source_eligibility_policy=SourceEligibilityPolicy(),
    )


def _controls() -> dict[str, str | int | float | bool | None | list[str]]:
    return {
        "sources": ["crossref", "openalex", "crossref"],
        "limit": 7,
        "max_queries": 2,
        "fulltext": False,
        "citation_expansion": True,
        "citation_seed_count": 1,
        "citation_limit": 9,
        "engine": "mock",
        "model": "fixture-model",
        "max_engine_calls": 3,
        "time_budget": 45.5,
        "seed": 17,
    }


def test_values_normalize_to_deeply_immutable_canonical_bytes() -> None:
    # Given/When: a draft contains duplicate whitespace and decomposed Unicode
    spec = build_research_spec(_draft())
    reparsed = parse_research_spec(canonical_research_spec(spec))

    # Then: normalized ordered values, bytes, and sha256 identity are stable
    assert spec.goal == "Café yield response"
    assert spec.explicit_constraints == ("orchards", "NFC Café")
    assert spec.assumptions == ("mature trees",)
    assert canonical_research_spec(reparsed) == canonical_research_spec(spec)
    assert spec.spec_id.startswith("sha256:")
    assert research_spec_hash(spec).startswith("sha256:")
    assert b"Caf\xc3\xa9" in canonical_research_spec(spec)
    attempt_goal_mutation = partial(setattr, spec, "goal")
    with pytest.raises(dataclasses.FrozenInstanceError):
        attempt_goal_mutation("changed")


def test_semantic_parity_excludes_origin_and_interaction_metadata_only() -> None:
    # Given: equivalent chat/direct specs and one actual semantic change
    chat = build_research_spec(_draft())
    direct_draft = _draft(ResearchOrigin.DIRECT_API)
    direct = build_research_spec(direct_draft)
    changed = build_research_spec(
        dataclasses.replace(direct_draft, explicit_constraints=("greenhouses",))
    )

    # When/Then: origin/policy/lineage IDs do not mask or invent semantics
    assert chat.spec_id != direct.spec_id
    assert research_specs_semantically_equal(chat, direct)
    assert not research_specs_semantically_equal(chat, changed)


def test_non_null_model_normalizes_to_identical_canonical_controls() -> None:
    # Given: equivalent non-null model names in decomposed and NFC forms
    decomposed = _controls()
    decomposed["model"] = "Cafe\u0301-model"
    composed = _controls()
    composed["model"] = "Café-model"

    # When: both values cross the strict execution-control boundary
    left = parse_execution_controls(json.dumps(decomposed))
    right = parse_execution_controls(json.dumps(composed))

    # Then: model normalization prevents canonical byte/hash drift
    assert left.model == "Café-model"
    assert right.model == "Café-model"
    assert canonical_execution_controls(left) == canonical_execution_controls(right)
    assert execution_controls_hash(left) == execution_controls_hash(right)


def test_every_direct_execution_control_round_trips_losslessly() -> None:
    # Given/When: every direct control differs from its fallback and is parsed
    expected = _controls()
    parsed = parse_execution_controls(json.dumps(expected))
    actual = parsed.to_json_value()

    # Then: no source/query/fulltext/citation/engine/model/time/seed control is lost
    assert actual == expected
    assert set(actual) == set(ResearchExecutionControls.field_names())
    assert parse_execution_controls(canonical_execution_controls(parsed)) == parsed
    assert execution_controls_hash(parsed).startswith("sha256:")


@pytest.mark.parametrize(
    "field",
    [
        "limit",
        "max_queries",
        "citation_seed_count",
        "citation_limit",
        "max_engine_calls",
        "time_budget",
        "seed",
    ],
)
def test_boolean_is_not_accepted_as_a_numeric_control(field: str) -> None:
    # Given: JSON bool, which Python otherwise treats as a number
    payload = _controls()
    payload[field] = True

    # When/Then: strict parsing rejects it at the stable field path
    with pytest.raises(ResearchSpecParseError) as raised:
        parse_execution_controls(json.dumps(payload))
    assert (raised.value.path, raised.value.code) == (
        f"$.{field}",
        "expected_number",
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [("surprise", 1, "unknown_field"), ("limit", float("nan"), "non_finite_number")],
)
def test_controls_reject_unknown_fields_and_nan(
    field: str, value: float, code: str
) -> None:
    # Given/When: malformed control input crosses the strict boundary
    payload = _controls()
    payload[field] = value
    with pytest.raises(ResearchSpecParseError) as raised:
        parse_execution_controls(json.dumps(payload))

    # Then: no value is silently dropped or coerced
    assert (raised.value.path, raised.value.code) == (f"$.{field}", code)


def test_spec_parser_rejects_unknown_enum_and_raw_history_field() -> None:
    # Given: canonical data with malformed boundary values
    payload = json.loads(canonical_research_spec(build_research_spec(_draft())))
    payload["origin"] = "batch"

    # When/Then: enum and unknown field paths remain stable
    with pytest.raises(ResearchSpecParseError) as enum_error:
        parse_research_spec(json.dumps(payload))
    assert (enum_error.value.path, enum_error.value.code) == ("$.origin", "invalid_enum")
    payload["origin"] = "chat"
    payload["raw_request_history"] = []
    with pytest.raises(ResearchSpecParseError) as field_error:
        parse_research_spec(json.dumps(payload))
    assert (field_error.value.path, field_error.value.code) == (
        "$.raw_request_history",
        "unknown_field",
    )


def test_all_approved_source_eligibility_boundaries_match() -> None:
    # Given: every approved need/content/retraction boundary
    rows = load_fixture(_ELIGIBILITY_FIXTURE)
    policy = SourceEligibilityPolicy()

    # When/Then: the explicit requirement and record class reproduce the fixture
    for row in rows:
        raw_kind = row["need_kind"]
        raw_content = row["content_kind"]
        retracted = row["retracted"]
        expected = row["expected_eligible"]
        assert isinstance(raw_kind, str)
        assert isinstance(raw_content, str)
        assert isinstance(retracted, bool)
        assert isinstance(expected, bool)
        requirement = policy.minimum_content(EvidenceNeedKind(raw_kind))
        record = EvidenceRecordClass(ContentClass(raw_content), retracted)
        assert policy.is_eligible(requirement, record) is expected


def test_evidence_need_has_stable_id_and_explicit_minimum_content() -> None:
    # Given: equivalent Unicode descriptions and one degraded fallback override
    default = build_evidence_need(
        EvidenceNeedDraft(EvidenceNeedKind.GENERAL, " Cafe\u0301 context ", True, None)
    )
    equivalent = build_evidence_need(
        EvidenceNeedDraft(EvidenceNeedKind.GENERAL, "Café  context", True, None)
    )
    fallback = build_evidence_need(
        EvidenceNeedDraft(
            EvidenceNeedKind.GENERAL,
            "Café context",
            True,
            ContentClass.ABSTRACT,
        )
    )

    # When/Then: default general remains full text; fallback is explicit and distinct
    assert default.minimum_content is ContentClass.FULLTEXT
    assert fallback.minimum_content is ContentClass.ABSTRACT
    assert default.need_id == equivalent.need_id
    assert default.need_id.startswith("sha256:")
    assert fallback.need_id != default.need_id


def test_source_eligibility_policy_has_exact_v1_boundaries() -> None:
    # Given: the v1 source eligibility policy
    policy = SourceEligibilityPolicy()

    # When/Then: need classes map exactly and unknown/retracted never qualify
    assert policy.minimum_content(EvidenceNeedKind.BIBLIOGRAPHIC_EXISTENCE) is ContentClass.METADATA_ONLY
    assert policy.minimum_content(EvidenceNeedKind.CONTEXT) is ContentClass.ABSTRACT
    for kind in set(EvidenceNeedKind) - {
        EvidenceNeedKind.BIBLIOGRAPHIC_EXISTENCE,
        EvidenceNeedKind.CONTEXT,
    }:
        assert policy.minimum_content(kind) is ContentClass.FULLTEXT
    assert not policy.is_eligible(
        ContentClass.METADATA_ONLY,
        EvidenceRecordClass(ContentClass.UNKNOWN, retracted=False),
    )
    assert not policy.is_eligible(
        ContentClass.FULLTEXT,
        EvidenceRecordClass(ContentClass.FULLTEXT, retracted=True),
    )
